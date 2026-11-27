"""Storage adapter checks: real local files and a scripted S3 client, no network."""

from types import SimpleNamespace

import pytest

from worker.storage import LocalStorage, S3Storage, split_key


def test_split_key_preserves_explicit_bucket_and_strips_local_leading_slash():
    assert split_key("s3://models/path/model.ifc", "default") == ("models", "path/model.ifc")
    assert split_key("/path/model.ifc", "default") == ("default", "path/model.ifc")


class Body:
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def iter_chunks(self, size):
        assert size == 1024 * 1024
        yield from self.chunks

    def close(self):
        self.closed = True


class S3:
    def __init__(self, body, size):
        self.body = body
        self.size = size
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"Body": self.body, "ContentLength": self.size}

    def upload_file(self, *args, **kwargs):
        self.calls.append(("upload", args, kwargs))


def storage(client):
    return S3Storage(SimpleNamespace(s3_bucket="default"), client=client)


def test_s3_download_streams_and_closes_body_on_success(tmp_path):
    body = Body([b"one", b"two"])
    client = S3(body, 6)
    destination = tmp_path / "source.ifc"
    storage(client).download("s3://bucket/sub/source.ifc", destination, 6)
    assert destination.read_bytes() == b"onetwo"
    assert client.calls == [("get", {"Bucket": "bucket", "Key": "sub/source.ifc"})]
    assert body.closed


@pytest.mark.parametrize("chunks,declared,max_bytes", [
    ([b"abc"], 3, 2),
    ([b"abc", b"def"], 0, 5),
])
def test_s3_rejects_header_or_stream_over_limit_and_closes(tmp_path, chunks, declared, max_bytes):
    body = Body(chunks)
    with pytest.raises(ValueError, match="max size"):
        storage(S3(body, declared)).download("source.ifc", tmp_path / "source.ifc", max_bytes)
    assert body.closed


def test_s3_read_error_closes_body(tmp_path):
    class Broken(Body):
        def iter_chunks(self, size):
            yield b"first"
            raise OSError("read failed")

    body = Broken([])
    with pytest.raises(OSError, match="read failed"):
        storage(S3(body, 0)).download("source.ifc", tmp_path / "source.ifc", 99)
    assert body.closed


def test_s3_upload_uses_bucket_key_and_content_type(tmp_path):
    source = tmp_path / "report.json"
    source.write_text("{}")
    client = S3(Body([]), 0)
    storage(client).upload("s3://artifacts/out/report.json", source, "application/json")
    assert client.calls == [("upload", (str(source), "artifacts", "out/report.json"), {"ExtraArgs": {"ContentType": "application/json"}})]


def test_local_storage_upload_download_and_size_boundary(tmp_path):
    root = tmp_path / "store"
    store = LocalStorage(root)
    source = tmp_path / "source"
    source.write_bytes(b"ifc")
    store.upload("sub/file.ifc", source, "ignored")
    assert (root / "sub/file.ifc").read_bytes() == b"ifc"
    with pytest.raises(ValueError, match="max size"):
        store.download("sub/file.ifc", tmp_path / "too-small", 2)
    destination = tmp_path / "download"
    store.download("sub/file.ifc", destination, 3)
    assert destination.read_bytes() == b"ifc"


def test_local_storage_blocks_parent_escape_and_does_not_touch_outside_file(tmp_path):
    root = tmp_path / "store"
    store = LocalStorage(root)
    source = tmp_path / "source"
    source.write_bytes(b"safe")
    outside = tmp_path / "outside"
    outside.write_bytes(b"original")
    with pytest.raises(ValueError, match="Invalid key"):
        store.upload("../outside", source, "ignored")
    assert outside.read_bytes() == b"original"
    with pytest.raises(ValueError, match="Invalid key"):
        store.download("../outside", tmp_path / "copy", 100)


def test_local_storage_rejects_symlink_escape(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this host")
    source = tmp_path / "source"
    source.write_bytes(b"safe")
    with pytest.raises(ValueError, match="Invalid key"):
        LocalStorage(root).upload("link/file", source, "ignored")
    assert not (outside / "file").exists()
