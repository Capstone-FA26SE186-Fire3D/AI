import hashlib

import httpx
import pytest

from app.sources.fetch import fetch_document
from app.v2.errors import AdapterRefusal

BODY = b"hello world"
SHA = hashlib.sha256(BODY).hexdigest()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok(request):
    return httpx.Response(200, content=BODY, headers={"content-type": "text/plain"})


def test_hash_ok():
    data, ctype = fetch_document("https://x.test/a", SHA.upper(), max_bytes=1000, timeout=5, client=_client(_ok))
    assert data == BODY and ctype == "text/plain"


def test_hash_mismatch_code():
    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", "0" * 64, max_bytes=1000, timeout=5, client=_client(_ok))
    assert e.value.code == "AI_SOURCE_HASH_MISMATCH"


def test_http_scheme_refused():
    with pytest.raises(AdapterRefusal) as e:
        fetch_document("http://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(_ok))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_redirect_to_http_refused():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://evil.test/a?token=secret"})

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(handler))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"
    assert "secret" not in e.value.message


def test_https_redirect_followed_and_limited():
    def handler(request):
        if request.url.path == "/a":
            return httpx.Response(301, headers={"location": "/b"})
        return _ok(request)

    data, _ = fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(handler))
    assert data == BODY

    def loop(request):
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(loop))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_oversize_stops():
    pulled = {"n": 0}

    def gen():
        for _ in range(21):
            pulled["n"] += 1
            yield b"x" * (1024 * 1024)

    def handler(request):
        return httpx.Response(200, content=gen())

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=20 * 1024 * 1024, timeout=5, client=_client(handler))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_oversize_aborts_early():
    pulled = {"n": 0}

    def gen():
        for _ in range(100):
            pulled["n"] += 1
            yield b"x" * 1024

    def handler(request):
        return httpx.Response(200, content=gen())

    with pytest.raises(AdapterRefusal):
        fetch_document("https://x.test/a", SHA, max_bytes=5 * 1024, timeout=5, client=_client(handler))
    assert pulled["n"] < 100


def test_404_unavailable():
    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5,
                       client=_client(lambda r: httpx.Response(404)))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_network_error_unavailable():
    def boom(request):
        raise httpx.ConnectError("down")

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(boom))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_invalid_location_is_unavailable():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://[bad"})

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/a", SHA, max_bytes=1000, timeout=5, client=_client(handler))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_invalid_uri_is_unavailable():
    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://[bad/a", SHA, max_bytes=1000, timeout=5, client=_client(_ok))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"


def test_error_message_strips_userinfo():
    def boom(request):
        raise httpx.ConnectError("down")

    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://user:pa55@x.test/a?sig=s3cret", SHA, max_bytes=1000, timeout=5, client=_client(boom))
    assert "pa55" not in e.value.message and "user" not in e.value.message and "s3cret" not in e.value.message
    assert "x.test/a" in e.value.message


def test_httpx_invalid_url_is_unavailable():
    with pytest.raises(AdapterRefusal) as e:
        fetch_document("https://x.test/\x00a", SHA, max_bytes=1000, timeout=5, client=_client(_ok))
    assert e.value.code == "AI_SOURCE_UNAVAILABLE"
