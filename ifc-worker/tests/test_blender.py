import subprocess
from pathlib import Path

import pytest

from worker import blender
from worker.config import WorkerSettings


def settings(path=""):
    return WorkerSettings(be_base_url="http://be", worker_key="k", blender_path=path)


def test_optimize_skipped_without_blender(tmp_path):
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"orig")
    assert blender.optimize_glb(glb, settings()) is False
    assert glb.read_bytes() == b"orig"


def test_optimize_invokes_blender_command(tmp_path, monkeypatch):
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"orig")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"optimized")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(blender.subprocess, "run", fake_run)
    assert blender.optimize_glb(glb, settings("/opt/blender")) is True
    argv = calls[0]
    assert argv[0] == "/opt/blender" and "--background" in argv and "--factory-startup" in argv
    assert any(a.endswith("blender_optimize.py") for a in argv)
    assert glb.read_bytes() == b"optimized"


def test_optimize_failure_raises_and_keeps_file(tmp_path, monkeypatch):
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"orig")
    monkeypatch.setattr(blender.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "boom"))
    with pytest.raises(RuntimeError):
        blender.optimize_glb(glb, settings("/b"))
    assert glb.read_bytes() == b"orig"


def test_optimize_timeout_raises(tmp_path, monkeypatch):
    glb = tmp_path / "a.glb"
    glb.write_bytes(b"orig")

    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    monkeypatch.setattr(blender.subprocess, "run", boom)
    with pytest.raises(RuntimeError):
        blender.optimize_glb(glb, settings("/b"))
