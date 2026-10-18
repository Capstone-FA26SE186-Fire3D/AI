from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    def download(self, key: str, dest: Path, max_bytes: int) -> None: ...

    def upload(self, key: str, src: Path, content_type: str) -> None: ...


def split_key(key: str, default_bucket: str) -> tuple[str, str]:
    if key.startswith("s3://"):
        bucket, _, rest = key[5:].partition("/")
        return bucket, rest
    return default_bucket, key.lstrip("/")


class S3Storage:
    def __init__(self, settings, client=None):
        self._bucket = settings.s3_bucket
        if client is None:
            import boto3
            client = boto3.client("s3", region_name=settings.s3_region or None,
                                  endpoint_url=settings.s3_endpoint_url or None)
        self._s3 = client

    def download(self, key: str, dest: Path, max_bytes: int) -> None:
        bucket, k = split_key(key, self._bucket)
        obj = self._s3.get_object(Bucket=bucket, Key=k)
        if int(obj.get("ContentLength") or 0) > max_bytes:
            raise ValueError("Source exceeds max size")
        total = 0
        with open(dest, "wb") as f:
            for chunk in obj["Body"].iter_chunks(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Source exceeds max size")
                f.write(chunk)

    def upload(self, key: str, src: Path, content_type: str) -> None:
        bucket, k = split_key(key, self._bucket)
        self._s3.upload_file(str(src), bucket, k, ExtraArgs={"ContentType": content_type})


class LocalStorage:
    def __init__(self, root: Path):
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        _, k = split_key(key, "")
        p = (self._root / k).resolve()
        if self._root.resolve() not in p.parents:
            raise ValueError("Invalid key")
        return p

    def download(self, key: str, dest: Path, max_bytes: int) -> None:
        src = self._path(key)
        if src.stat().st_size > max_bytes:
            raise ValueError("Source exceeds max size")
        dest.write_bytes(src.read_bytes())

    def upload(self, key: str, src: Path, content_type: str) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(Path(src).read_bytes())
