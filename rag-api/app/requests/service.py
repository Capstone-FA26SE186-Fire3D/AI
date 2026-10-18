"""Durable BE request lifecycle: dedup, processing, reconcile lookup and recovery (spec A6)."""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.answering.pipeline import PipelineDeps, run_pipeline
from app.answering.usage import context_budget
from app.requests.store import RequestRecord, RequestStore
from app.sources.resolver import SourceResolver
from app.v2.errors import AdapterRefusal
from app.v2.schemas import ROUTES, AdapterRequest, AdapterResponse

log = logging.getLogger(__name__)

TERMINAL_RECOMMENDATION = "Không thể hoàn tất yêu cầu sau nhiều lần thử; cần kiểm tra lại nguồn."

_USAGE_SUM_FIELDS = ("provider_units", "input_tokens", "output_tokens")


def error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _refusal(exc: AdapterRefusal) -> tuple[int, dict]:
    return exc.status_code, error(exc.code, exc.message)


def _unavailable() -> tuple[int, dict]:
    return 503, error("AI_TEMPORARILY_UNAVAILABLE", "AI service is temporarily unavailable")


def _outcome_unknown() -> tuple[int, dict]:
    return 500, error("AI_OUTCOME_UNKNOWN", "Outcome unknown; reconcile with GET /v2/requests/{request_id}")


def _in_progress() -> tuple[int, dict]:
    return 409, error("AI_REQUEST_IN_PROGRESS", "Request is already being processed")


def _sum_usage(previous: dict | None, current: dict) -> dict:
    total = dict(current)
    if isinstance(previous, dict):
        for key in _USAGE_SUM_FIELDS:
            prev = previous.get(key)
            if isinstance(prev, (int, float)) and not isinstance(prev, bool):
                total[key] = int(total.get(key, 0)) + int(prev)
    return total


class RequestService:
    def __init__(self, store: RequestStore, resolver: SourceResolver, deps: PipelineDeps) -> None:
        self.store = store
        self.resolver = resolver
        self.deps = deps
        self._locks: dict[str, list] = {}  # request_id -> [lock, holders]
        self._locks_guard = threading.Lock()

    @contextmanager
    def _request_lock(self, request_id: str):
        """Non-blocking in-process per-request_id lock; yields False when another submit holds it.
        It only narrows races inside one process; correctness across processes comes from the
        store's primary key."""
        with self._locks_guard:
            entry = self._locks.setdefault(request_id, [threading.Lock(), 0])
            entry[1] += 1
        acquired = entry[0].acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                entry[0].release()
            with self._locks_guard:
                entry[1] -= 1
                if entry[1] == 0:
                    self._locks.pop(request_id, None)

    # ---- validation before anything is persisted -------------------------------------------

    def _precheck(self, route_key: str, req: AdapterRequest) -> tuple[int, dict] | None:
        spec = ROUTES.get(route_key)
        if spec is None:
            return 404, error("AI_ROUTE_MISMATCH", f"Unknown route {route_key}")
        if (req.audience, req.operation, req.response_type) != (spec.audience, spec.operation, spec.response_type):
            return 422, error(
                "AI_ROUTE_MISMATCH",
                f"Route {route_key} expects audience={spec.audience}, operation={spec.operation}, "
                f"response_type={spec.response_type}",
            )
        if spec.organization_id_null and req.organization_id is not None:
            return 422, error("AI_ROUTE_MISMATCH", f"Route {route_key} requires organization_id to be null")
        if spec.requires_bim and req.bim is None:
            # Checked here (before INSERT) so the pipeline never refuses this after mark_processing.
            return 422, error("AI_REVISION_NOT_PINNED", "ScenarioDraft requires a pinned BIM revision")
        try:
            context_budget(req.limits, self.deps.settings.max_output_tokens)
        except AdapterRefusal as exc:
            return _refusal(exc)
        return None

    def _dedup(self, rec: RequestRecord, input_hash: str) -> tuple[int, dict]:
        if rec.input_hash != input_hash:
            return 409, error("AI_REQUEST_CONFLICT", "request_id was already used with a different input")
        if rec.status == "Completed" and rec.response is not None:
            return 200, rec.response
        return _in_progress()

    def _completed_or_unknown(self, request_id: str) -> tuple[int, dict]:
        """complete() lost the race: return what the other worker stored."""
        rec = self.store.get(request_id)
        if rec is not None and rec.status == "Completed" and rec.response is not None:
            return 200, rec.response
        return _outcome_unknown()

    # ---- POST ------------------------------------------------------------------------------

    def submit(self, route_key: str, req: AdapterRequest) -> tuple[int, dict]:
        rejected = self._precheck(route_key, req)
        if rejected:
            return rejected
        with self._request_lock(req.request_id) as acquired:
            if not acquired:
                return _in_progress()
            return self._submit_locked(req)

    def _submit_locked(self, req: AdapterRequest) -> tuple[int, dict]:
        rid = req.request_id
        try:
            existing = self.store.get(rid)
            if existing is not None:
                return self._dedup(existing, req.input_hash)
            payload = req.model_dump(mode="json", by_alias=True)
            if not self.store.insert_received(rid, req.operation, req.audience, req.input_hash, payload):
                existing = self.store.get(rid)  # lost the PK race
                if existing is None:
                    return _in_progress()
                return self._dedup(existing, req.input_hash)
        except Exception:
            log.exception("request store unavailable", extra={"request_id": rid})
            return _unavailable()

        # Row is ours and Received: no provider side-effect yet, so failures delete it.
        try:
            prepared = self.resolver.prepare(req.sources)
            if not self.store.mark_processing(rid):
                # Purged/changed underneath us; nothing was sent to a provider.
                log.warning("mark_processing lost the row", extra={"request_id": rid})
                return _unavailable()
        except AdapterRefusal as exc:
            self._safe_delete(rid)
            return _refusal(exc)
        except Exception:
            log.exception("pre-processing failure", extra={"request_id": rid})
            self._safe_delete(rid)
            return _unavailable()

        # Processing is committed: from here a provider call may have happened.
        try:
            response = run_pipeline(req, prepared, self.deps)
        except AdapterRefusal as exc:
            # Every AdapterRefusal raised by run_pipeline happens before provider.generate
            # (quota-unit / BIM-pin checks; both are also pre-checked before INSERT), so no
            # provider side-effect exists: delete the row and return the refusal instead of
            # leaving a Processing row behind a definitive 4xx.
            self._safe_delete(rid)
            return _refusal(exc)
        except Exception:
            log.exception("pipeline failure after processing", extra={"request_id": rid})
            return _outcome_unknown()

        try:
            body = response.model_dump(mode="json")
            if not self.store.complete(rid, body, body["usage"]):
                return self._completed_or_unknown(rid)
        except Exception:
            log.exception("complete failed", extra={"request_id": rid})
            return _outcome_unknown()
        return 200, body

    def _safe_delete(self, request_id: str) -> None:
        try:
            self.store.delete(request_id)
        except Exception:
            log.exception("delete failed", extra={"request_id": request_id})

    # ---- GET lookup ------------------------------------------------------------------------

    def lookup(self, request_id: str) -> tuple[int, dict]:
        rec = self.store.get(request_id)
        if rec is None:
            return 404, error("AI_REQUEST_NOT_FOUND", "Request not found")
        if rec.status == "Completed" and rec.response is not None:
            return 200, rec.response
        return 202, {"request_id": rec.request_id, "status": "Processing"}

    # ---- recovery --------------------------------------------------------------------------

    def recover_once(self, now: datetime) -> int:
        """Purge stale Received rows, then re-run stale Processing rows. Returns rows completed."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        cutoff = now - timedelta(seconds=self.deps.settings.request_stale_seconds)
        purged = self.store.purge_stale_received(cutoff)
        if purged:
            log.info("purged %d stale Received requests", purged)
        completed = 0
        seen: set[str] = set()
        while True:
            # Exclude rows already handled in this pass so a failing row is neither re-run
            # nor re-claimed (which would burn an extra attempt) within the same pass.
            rec = self.store.claim_stale(cutoff, exclude=seen)
            if rec is None:
                break
            seen.add(rec.request_id)
            if self._recover_one(rec):
                completed += 1
        return completed

    def _recover_one(self, rec: RequestRecord) -> bool:
        cap = self.deps.settings.recovery_max_attempts
        if rec.attempts > cap:
            # Never delete: a 404 would make BE refund although a provider call may have happened.
            return self._complete_terminal(rec, "AI_RECOVERY_ATTEMPTS_EXHAUSTED")
        try:
            req = AdapterRequest.model_validate(rec.payload)
            prepared = self.resolver.prepare(req.sources)
            response: AdapterResponse = run_pipeline(req, prepared, self.deps)
            body = response.model_dump(mode="json")
            total = _sum_usage(rec.usage_total, body["usage"])
            body["usage"] = total
            if not self.store.complete(rec.request_id, body, total):
                log.info("recovered request already completed elsewhere", extra={"request_id": rec.request_id})
                return False
        except Exception as exc:
            code = exc.code if isinstance(exc, AdapterRefusal) else "AI_RECOVERY_FAILED"
            log.exception("recovery attempt failed (%s)", code, extra={"request_id": rec.request_id})
            if rec.attempts >= cap:
                return self._complete_terminal(rec, code)
            # Left Processing; the next pass retries once it is stale again.
            return False
        log.info("recovered stale request", extra={"request_id": rec.request_id})
        return True

    def _complete_terminal(self, rec: RequestRecord, reason_code: str) -> bool:
        """Close a row that cannot be recovered with a terminal InsufficientEvidence answer."""
        payload = rec.payload if isinstance(rec.payload, dict) else {}
        response_type = payload.get("response_type")
        if response_type not in ("KnowledgeAnswer", "ScenarioDraft"):
            response_type = "KnowledgeAnswer"
        zero = {"provider_units": 0, "input_tokens": 0, "output_tokens": 0, "model_version": "none"}
        usage = _sum_usage(rec.usage_total, zero)
        if isinstance(rec.usage_total, dict) and isinstance(rec.usage_total.get("model_version"), str):
            usage["model_version"] = rec.usage_total["model_version"]
        body = AdapterResponse(
            request_id=rec.request_id, response_type=response_type, status="InsufficientEvidence",
            recommendation=TERMINAL_RECOMMENDATION, scenario_draft=None, bim_anchors=[], citations=[],
            rule_results=[], confidence="low", assumptions=[],
            limitations=[f"Không hoàn tất sau {rec.attempts} lần thử (mã {reason_code})."],
            usage=usage,
        ).model_dump(mode="json")
        try:
            done = self.store.complete(rec.request_id, body, body["usage"])
        except Exception:
            log.exception("terminal completion failed", extra={"request_id": rec.request_id})
            return False
        if done:
            log.warning("request closed as InsufficientEvidence after %d attempts (%s)", rec.attempts, reason_code,
                        extra={"request_id": rec.request_id})
        return done
