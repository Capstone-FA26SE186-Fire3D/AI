"""Shared helpers for geometry/metadata/process tests."""
from __future__ import annotations

import json
import struct
from datetime import datetime, timezone

from worker.gate_client import ClaimResult


def make_claim(source_hash: str = "a" * 64) -> ClaimResult:
    return ClaimResult(
        code="Claimed", replayed=False, status="Running", attempt_id="att-1", lease_token="tok",
        lease_until=datetime(2030, 1, 1, tzinfo=timezone.utc), receipt_id="r-1",
        output_prefix="jobs/1/att-1/", input_hash="b" * 64, source_key="src/s.ifc", source_hash=source_hash,
    )


def glb_json(data: bytes) -> dict:
    """Parse the JSON chunk of a GLB without any glTF library."""
    magic, version, _length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF" and version == 2
    chunk_len, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20:20 + chunk_len])
