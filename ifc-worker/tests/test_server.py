import threading
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from worker.config import WorkerSettings
from worker.gate_client import ClaimResult, GateError
from worker.server import create_worker_app

H = "a" * 64
RID = "11111111-1111-4111-8111-111111111111"
RECEIPT = "22222222-2222-4222-8222-222222222222"
BODY = {"code": "OK", "eventKey": "ev1", "payloadHash": H,
        "payload": {"job_id": RID, "revision_id": RID, "source_key": "k", "input_hash": H},
        "leaseToken": "x", "attempt": 1}
KEY = {"X-Worker-Key": "secret"}


def settings():
    return WorkerSettings(be_base_url="http://be", worker_key="secret")


def claim_result(replayed=False):
    return ClaimResult("OK", replayed, "Running", "a1", "lt", datetime.now(timezone.utc),
                       RECEIPT, "out/", H, "k", H)


class FakeGate:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def claim(self, *a):
        self.calls.append(a)
        if self.error:
            raise self.error
        return self.result


class Runner:
    def __init__(self):
        self.ran = threading.Event()
        self.args = None

    def run(self, job_id, claim):
        self.args = (job_id, claim)
        self.ran.set()


def build(gate, runner):
    return TestClient(create_worker_app(settings(), lambda: runner, gate=gate))


def test_delivery_requires_worker_key():
    c = build(FakeGate(claim_result()), Runner())
    assert c.post("/deliveries", json=BODY).status_code == 401
    assert c.post("/deliveries", json=BODY, headers={"X-Worker-Key": "bad"}).status_code == 401
    assert c.get("/health").status_code == 200


def test_delivery_acks_and_runs():
    r, g = Runner(), FakeGate(claim_result())
    c = build(g, r)
    res = c.post("/deliveries", json=BODY, headers=KEY)
    assert res.status_code == 200
    assert res.json() == {"eventKey": "ev1", "payloadHash": H, "receiptId": RECEIPT}
    assert r.ran.wait(2)
    assert r.args[0] == RID
    assert g.calls[0][0] == RID and g.calls[0][3] == H


def test_delivery_acks_and_starts_runner_once_on_replay():
    r = Runner()
    c = build(FakeGate(claim_result(replayed=True)), r)
    res = c.post("/deliveries", json=BODY, headers=KEY)
    assert res.status_code == 200 and res.json()["eventKey"] == "ev1"
    assert not r.ran.wait(0.3)


def test_delivery_bad_shape_400_and_gate_error_passthrough():
    c = build(FakeGate(error=GateError(503, "Unavailable")), Runner())
    assert c.post("/deliveries", json=dict(BODY, payloadHash="zz"), headers=KEY).status_code == 400
    assert c.post("/deliveries", content=b"not json", headers=KEY).status_code == 400
    res = c.post("/deliveries", json=BODY, headers=KEY)
    assert res.status_code == 503 and res.json()["code"] == "Unavailable"


def test_invalid_receipt_id_is_502():
    bad = claim_result()
    bad.receipt_id = "nope"
    r = Runner()
    res = build(FakeGate(bad), r).post("/deliveries", json=BODY, headers=KEY)
    assert res.status_code == 502 and res.json()["code"] == "GATE_REPLY_INVALID"
    assert not r.ran.wait(0.2)
