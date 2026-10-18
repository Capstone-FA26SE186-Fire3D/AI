import hashlib
import json
import time
from datetime import datetime, timezone

import httpx

from worker.config import WorkerSettings
from worker.gate_client import ClaimResult, GateClient
from worker.runner import JobRunner, OutputFile
from worker.storage import LocalStorage

SRC = b"ISO-10303-21;fake"


def claim(source_hash=None):
    return ClaimResult("OK", False, "Running", "a1", "lt", datetime.now(timezone.utc), "r1",
                       "out/j1/", "i" * 64, "src/model.ifc",
                       source_hash or hashlib.sha256(SRC).hexdigest())


def setup(tmp_path, handler):
    root = tmp_path / "store"
    (root / "src").mkdir(parents=True)
    (root / "src" / "model.ifc").write_bytes(SRC)
    calls = []

    def wrapped(req):
        action = req.url.path.rsplit("/", 1)[1]
        body = json.loads(req.read())
        calls.append((action, body))
        return handler(action, body)

    gate = GateClient("http://be", "k", httpx.Client(transport=httpx.MockTransport(wrapped)))
    return gate, LocalStorage(root), calls, root


def ok_handler(action, body):
    if action == "outputs":
        return httpx.Response(200, json={"artifactId": "art", "outputHash": "oh-" + body["output"]["objectKey"]})
    return httpx.Response(200, json={"code": "OK", "leaseUntil": "2026-10-18T10:00:00Z"})


def process_two(src, out, c):
    files = []
    for n, t in (("a.json", "preview_glb"), ("b.json", "building_metadata")):
        p = out / n
        p.write_text('{"n":"%s"}' % n)
        files.append(OutputFile(p, t, "1", {"k": 1}, "Passed", [], "application/json"))
    return files


def settings():
    return WorkerSettings(be_base_url="http://be", worker_key="k")


def test_runner_registers_outputs_then_completes(tmp_path):
    gate, storage, calls, root = setup(tmp_path, ok_handler)
    JobRunner(gate, storage, settings(), process_two).run("j1", claim())
    actions = [a for a, _ in calls if a != "renew"]
    assert actions == ["outputs", "outputs", "complete"]
    out = [b["output"] for a, b in calls if a == "outputs"]
    assert out[0]["objectKey"] == "out/j1/a.json"
    stored = (root / "out/j1/a.json").read_bytes()
    assert out[0]["sha256Hash"] == hashlib.sha256(stored).hexdigest()
    assert out[0]["sizeBytes"] == len(stored)
    assert out[0]["validatorVersion"].startswith("fet3d-ifc/")
    assert calls[-1][1]["outputHash"] == "oh-out/j1/b.json"


def test_runner_fails_on_source_hash_mismatch(tmp_path):
    gate, storage, calls, _ = setup(tmp_path, ok_handler)
    called = []
    JobRunner(gate, storage, settings(), lambda *a: called.append(1) or []).run("j1", claim("0" * 64))
    assert [a for a, _ in calls] == ["fail"]
    assert calls[0][1]["reason"] == "Source hash mismatch" and not called


def test_runner_fails_on_exception(tmp_path):
    gate, storage, calls, _ = setup(tmp_path, ok_handler)

    def boom(*a):
        raise RuntimeError("x" * 2000)

    JobRunner(gate, storage, settings(), boom).run("j1", claim())
    fail = [b for a, b in calls if a == "fail"][0]
    assert len(fail["reason"]) == 1000


def test_runner_stops_on_stale_attempt(tmp_path):
    def handler(action, body):
        if action == "renew":
            return httpx.Response(409, json={"code": "StaleAttempt"})
        return ok_handler(action, body)

    gate, storage, calls, _ = setup(tmp_path, handler)

    def slow(src, out, c):
        time.sleep(0.5)
        return process_two(src, out, c)

    JobRunner(gate, storage, settings(), slow, renew_interval=0.05).run("j1", claim())
    names = [a for a, _ in calls]
    assert "complete" not in names and "outputs" not in names and "fail" not in names
    assert "renew" in names


def test_runner_fails_on_non_stale_conflict(tmp_path):
    def handler(action, body):
        if action == "complete":
            return httpx.Response(409, json={"code": "OUTPUT_CONFLICT"})
        return ok_handler(action, body)

    gate, storage, calls, _ = setup(tmp_path, handler)
    JobRunner(gate, storage, settings(), process_two).run("j1", claim())
    fails = [b for a, b in calls if a == "fail"]
    assert len(fails) == 1 and "OUTPUT_CONFLICT" in fails[0]["reason"]
