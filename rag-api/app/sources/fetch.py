"""Verified HTTPS fetch of pinned source documents."""
from __future__ import annotations

import hashlib
from urllib.parse import urljoin, urlsplit

import httpx

from app.v2.errors import refuse

_MAX_REDIRECTS = 3


def _safe(uri: str) -> str:
    """URI for messages/logs: no userinfo, query or fragment."""
    try:
        parts = urlsplit(uri)
    except ValueError:
        return "<invalid uri>"
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}"


def _check_https(uri: str) -> None:
    try:
        scheme = urlsplit(uri).scheme.lower()
    except ValueError:
        raise refuse("AI_SOURCE_UNAVAILABLE", "Source URI is invalid") from None
    if scheme != "https":
        raise refuse("AI_SOURCE_UNAVAILABLE", f"Source URI must use https: {_safe(uri)}")


def fetch_document(
    uri: str,
    expected_sha256: str,
    *,
    max_bytes: int,
    timeout: float,
    client: httpx.Client | None = None,
) -> tuple[bytes, str]:
    _check_https(uri)
    owned = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        current = uri
        for hop in range(_MAX_REDIRECTS + 1):
            try:
                request = http.build_request("GET", current)
                response = http.send(request, stream=True, follow_redirects=False)
            except httpx.InvalidURL:
                raise refuse("AI_SOURCE_UNAVAILABLE", f"Source URI is invalid: {_safe(current)}") from None
            except httpx.HTTPError:
                raise refuse("AI_SOURCE_UNAVAILABLE", f"Source fetch failed: {_safe(current)}") from None
            try:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location or hop == _MAX_REDIRECTS:
                        raise refuse("AI_SOURCE_UNAVAILABLE", "Too many or invalid redirects")
                    try:
                        current = urljoin(current, location)
                    except ValueError:
                        raise refuse("AI_SOURCE_UNAVAILABLE", "Invalid redirect location") from None
                    _check_https(current)
                    continue
                if response.status_code != 200:
                    raise refuse("AI_SOURCE_UNAVAILABLE", f"Source returned status {response.status_code}")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise refuse("AI_SOURCE_UNAVAILABLE", "Source exceeds size limit")
                buf = bytearray()
                try:
                    for part in response.iter_bytes():
                        buf.extend(part)
                        if len(buf) > max_bytes:
                            raise refuse("AI_SOURCE_UNAVAILABLE", "Source exceeds size limit")
                except httpx.HTTPError:
                    raise refuse("AI_SOURCE_UNAVAILABLE", f"Source fetch failed: {_safe(current)}") from None
                content_type = response.headers.get("content-type", "")
                data = bytes(buf)
                break
            finally:
                response.close()
        else:  # pragma: no cover
            raise refuse("AI_SOURCE_UNAVAILABLE", "Too many redirects")
    finally:
        if owned:
            http.close()
    if hashlib.sha256(data).hexdigest() != expected_sha256.lower():
        raise refuse("AI_SOURCE_HASH_MISMATCH", "Source content hash does not match the pinned hash")
    return data, content_type
