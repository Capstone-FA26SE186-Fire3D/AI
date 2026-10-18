from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from worker.config import toolchain_version
from worker.gate_client import ClaimResult, GateClient, GateError

log = logging.getLogger("ifc-worker")


@dataclass
class OutputFile:
    path: Path
    artifact_type: str
    schema_version: str
    metadata: dict = field(default_factory=dict)
    outcome: Literal["Passed", "Failed"] = "Passed"
    issues: list[dict] = field(default_factory=list)
    content_type: str = "application/octet-stream"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_stale(exc: GateError, renew: bool = False) -> bool:
    if "stale" in exc.code.lower():
        return True
    return renew and exc.status == 409


class _Stale(Exception):
    pass


class JobRunner:
    def __init__(self, gate: GateClient, storage, settings,
                 process: Callable[[Path, Path, ClaimResult], list[OutputFile]],
                 renew_interval: float = 20.0):
        self._gate = gate
        self._storage = storage
        self._settings = settings
        self._process = process
        self._interval = renew_interval

    def run(self, job_id: str, claim: ClaimResult) -> None:
        stop = threading.Event()
        stale = threading.Event()

        def renew_loop():
            while not stop.wait(self._interval):
                try:
                    self._gate.renew(job_id, claim.attempt_id, claim.lease_token)
                except GateError as exc:
                    if _is_stale(exc, renew=True):
                        stale.set()
                        return
                    log.warning("renew failed: %s", exc)
                except Exception:  # noqa: BLE001
                    log.exception("renew failed")

        thread = threading.Thread(target=renew_loop, daemon=True)
        thread.start()
        try:
            self._execute(job_id, claim, stale)
        except _Stale:
            log.warning("job %s: lease lost, aborting", job_id)
        except GateError as exc:
            if _is_stale(exc):
                log.warning("job %s: lease lost (%s)", job_id, exc)
            else:
                self._safe_fail(job_id, claim, str(exc), stale)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", job_id)
            self._safe_fail(job_id, claim, f"{type(exc).__name__}: {exc}", stale)
        finally:
            stop.set()
            thread.join(timeout=5)

    def _safe_fail(self, job_id, claim, reason, stale):
        if stale.is_set():
            return
        try:
            self._gate.fail(job_id, claim.attempt_id, claim.lease_token, reason[:1000])
        except Exception:  # noqa: BLE001
            log.exception("fail call failed")

    def _execute(self, job_id: str, claim: ClaimResult, stale: threading.Event) -> None:
        def check():
            if stale.is_set():
                raise _Stale()

        toolchain = toolchain_version(self._settings)
        with tempfile.TemporaryDirectory(prefix="ifcjob-") as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "source.ifc"
            out_dir = tmp_path / "out"
            out_dir.mkdir()
            self._storage.download(claim.source_key, src, self._settings.max_source_bytes)
            check()
            if sha256_file(src) != claim.source_hash.lower():
                self._safe_fail(job_id, claim, "Source hash mismatch", stale)
                return
            outputs = self._process(src, out_dir, claim)
            check()
            last_hash = None
            for o in outputs:
                key = claim.output_prefix + o.path.name
                self._storage.upload(key, o.path, o.content_type)
                check()
                res = self._gate.register_output(job_id, claim.attempt_id, claim.lease_token, {
                    "artifactType": o.artifact_type, "objectKey": key,
                    "sha256Hash": sha256_file(o.path), "sizeBytes": o.path.stat().st_size,
                    "schemaVersion": o.schema_version, "metadata": o.metadata,
                    "validatorVersion": toolchain, "outcome": o.outcome, "issues": o.issues})
                last_hash = res["outputHash"]
                check()
            if last_hash is None:
                raise RuntimeError("Processing produced no outputs")
            self._gate.complete(job_id, claim.attempt_id, claim.lease_token, last_hash)
