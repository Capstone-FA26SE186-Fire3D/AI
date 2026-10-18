import httpx
import pytest

from worker.gate_client import GateClient, GateError

CLAIM = {
    "code": "OK", "replayed": False, "status": "Running", "attemptId": "a1",
    "leaseToken": "lt", "leaseUntil": "2026-10-18T10:00:00.1234567Z", "receiptId": "r1",
    "outputPrefix": "out/j1/", "inputHash": "i" * 64, "sourceKey": "s3://b/k",
    "sourceHash": "h" * 64, "scenarioVersionId": "sv",
}


def make(handler):
    return GateClient("http://be", "key", httpx.Client(transport=httpx.MockTransport(handler)))


def test_claim_parses_root_or_result():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers["X-Worker-Key"]
        seen["body"] = req.read()
        return httpx.Response(200, json=CLAIM)

    c = make(handler).claim("j1", "ev", "p" * 64, "i" * 64, "tc")
    assert seen["url"] == "http://be/internal/processing/jobs/j1/claim"
    assert seen["key"] == "key"
    assert b'"toolchainVersion"' in seen["body"] and b'"inputHash"' in seen["body"]
    assert c.attempt_id == "a1" and c.output_prefix == "out/j1/" and not c.replayed
    assert c.lease_until.year == 2026

    wrapped = make(lambda r: httpx.Response(200, json={"result": CLAIM})).claim("j1", "e", "p", "i", "t")
    assert wrapped.lease_token == "lt" and wrapped.source_hash == "h" * 64


def test_gate_error_maps_code():
    def handler(req):
        return httpx.Response(409, json={"code": "StaleAttempt", "status": 409},
                              headers={"content-type": "application/problem+json"})

    with pytest.raises(GateError) as e:
        make(handler).renew("j1", "a1", "lt")
    assert e.value.status == 409 and e.value.code == "StaleAttempt"

    with pytest.raises(GateError) as e:
        make(lambda r: httpx.Response(502, text="bad gateway")).fail("j1", "a", "l", "x")
    assert e.value.status == 502
