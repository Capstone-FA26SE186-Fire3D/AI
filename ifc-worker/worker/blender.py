"""Optional Blender pass: adds a second, non-overlapping lightmap UV set to every mesh of the preview GLB."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from worker.config import WorkerSettings

log = logging.getLogger("ifc-worker")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "blender_optimize.py"


def optimize_glb(glb: Path, settings: WorkerSettings, timeout: int = 900) -> bool:
    if not settings.blender_path:
        return False
    glb = Path(glb)
    fd, tmp_name = tempfile.mkstemp(suffix=".glb", dir=glb.parent)
    os.close(fd)
    out = Path(tmp_name)
    try:
        argv = [settings.blender_path, "--background", "--factory-startup", "--python", str(SCRIPT),
                "--", str(glb), str(out)]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Blender timed out after {timeout}s") from exc
        except OSError as exc:
            raise RuntimeError(f"Blender could not be started: {exc}") from exc
        if proc.returncode != 0:
            raise RuntimeError(f"Blender exited with {proc.returncode}: {(proc.stderr or '')[-500:]}")
        if not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("Blender produced no output")
        out.replace(glb)
        log.info("Blender lightmap UV pass applied to %s", glb.name)
        return True
    finally:
        if out.exists():
            out.unlink()
