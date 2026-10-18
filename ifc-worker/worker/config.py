from __future__ import annotations

import re
import subprocess
from functools import lru_cache

import ifcopenshell
from pydantic_settings import BaseSettings, SettingsConfigDict

from worker import __version__


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    be_base_url: str
    worker_key: str
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""
    blender_path: str = ""
    max_source_bytes: int = 524_288_000
    environment: str = "development"
    # Jobs run at once; further deliveries get 503 WORKER_BUSY before claiming (dispatcher redelivers).
    max_concurrent_jobs: int = 1


@lru_cache(maxsize=8)
def _blender_version(path: str) -> str:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"Blender\s+(\d+)\.(\d+)", out)
    return f"{m.group(1)}.{m.group(2)}" if m else ""


def toolchain_version(settings: WorkerSettings) -> str:
    version = f"fet3d-ifc/{__version__}+ifcopenshell-{ifcopenshell.version}"
    if settings.blender_path:
        blender = _blender_version(settings.blender_path)
        if blender:
            version += f"+blender-{blender}"
    return version


if __name__ == "__main__":
    print(toolchain_version(WorkerSettings()))
