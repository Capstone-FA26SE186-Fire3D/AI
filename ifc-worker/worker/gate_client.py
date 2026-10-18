from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


class GateError(Exception):
    def __init__(self, status: int, code: str = "", message: str = ""):
        super().__init__(f"gate error {status} {code} {message}".strip())
        self.status = status
        self.code = code


@dataclass
class ClaimResult:
    code: str
    replayed: bool
    status: str
    attempt_id: str
    lease_token: str
    lease_until: datetime
    receipt_id: str
    output_prefix: str
    input_hash: str
    source_key: str
    source_hash: str


def parse_dt(value) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _unwrap(body):
    if not isinstance(body, dict):
        return {}
    if isinstance(body.get("result"), dict):
        merged = dict(body["result"])
        for k, v in body.items():
            merged.setdefault(k, v)
        return merged
    return body


class GateClient:
    def __init__(self, base_url: str, worker_key: str, http: httpx.Client):
        self._base = base_url.rstrip("/")
        self._key = worker_key
        self._http = http

    def _post(self, job_id: str, action: str, body: dict) -> dict:
        try:
            res = self._http.post(f"{self._base}/internal/processing/jobs/{job_id}/{action}",
                                  json=body, headers={"X-Worker-Key": self._key})
        except httpx.HTTPError as exc:
            raise GateError(503, "GateUnreachable", str(exc)) from exc
        try:
            data = res.json()
        except ValueError:
            data = {}
        data = _unwrap(data)
        if res.status_code >= 400:
            raise GateError(res.status_code, str(data.get("code") or ""),
                            str(data.get("detail") or data.get("title") or ""))
        return data

    def claim(self, job_id, event_key, payload_hash, input_hash, toolchain_version) -> ClaimResult:
        d = self._post(job_id, "claim", {"eventKey": event_key, "payloadHash": payload_hash,
                                         "inputHash": input_hash, "toolchainVersion": toolchain_version})
        try:
            return ClaimResult(
                code=str(d.get("code", "OK")), replayed=bool(d.get("replayed", False)),
                status=str(d.get("status", "")), attempt_id=str(d["attemptId"]),
                lease_token=str(d["leaseToken"]), lease_until=parse_dt(d["leaseUntil"]),
                receipt_id=str(d["receiptId"]), output_prefix=str(d.get("outputPrefix") or ""),
                input_hash=str(d.get("inputHash") or input_hash), source_key=str(d.get("sourceKey") or ""),
                source_hash=str(d.get("sourceHash") or ""))
        except (KeyError, ValueError) as exc:
            raise GateError(502, "InvalidGateResponse", f"claim response: {exc}") from exc

    def renew(self, job_id, attempt_id, lease_token) -> datetime:
        d = self._post(job_id, "renew", {"attemptId": attempt_id, "leaseToken": lease_token})
        return parse_dt(d["leaseUntil"])

    def register_output(self, job_id, attempt_id, lease_token, output: dict) -> dict:
        return self._post(job_id, "outputs", {"attemptId": attempt_id, "leaseToken": lease_token,
                                              "output": output})

    def complete(self, job_id, attempt_id, lease_token, output_hash) -> dict:
        return self._post(job_id, "complete", {"attemptId": attempt_id, "leaseToken": lease_token,
                                               "outputHash": output_hash})

    def fail(self, job_id, attempt_id, lease_token, reason: str) -> dict:
        return self._post(job_id, "fail", {"attemptId": attempt_id, "leaseToken": lease_token,
                                           "reason": reason[:1000] or "Processing failed"})
