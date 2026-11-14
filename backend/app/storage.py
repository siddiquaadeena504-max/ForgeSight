"""Object storage abstraction: local filesystem for development, any S3-compatible store in production.
Objects are never served publicly: the API hands out short-lived HMAC-signed URLs."""
from __future__ import annotations

import hashlib
import hmac
import time
from functools import lru_cache
from pathlib import Path

from .config import get_settings


class Storage:
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage(Storage):
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("Invalid storage key")
        return p

    def put(self, key, data, content_type="application/octet-stream"):
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, key):
        return self._path(key).read_bytes()

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)

    def exists(self, key):
        return self._path(key).exists()


class S3Storage(Storage):
    def __init__(self, bucket, endpoint_url, region, access_key, secret_key):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        try:
            self.client.head_bucket(Bucket=bucket)
        except Exception:
            self.client.create_bucket(Bucket=bucket)

    def put(self, key, data, content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, ServerSideEncryption="AES256")

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(s.s3_bucket, s.s3_endpoint_url, s.s3_region, s.s3_access_key, s.s3_secret_key)
    return LocalStorage(s.storage_dir)


def _sig(key: str, exp: int) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def signed_url(key: str | None) -> str | None:
    if not key:
        return None
    # bucket expiry to 10 minutes so URLs stay cacheable by the browser
    exp = (int(time.time()) // 600 + 1) * 600 + get_settings().file_url_ttl_seconds
    return f"/api/files/{key}?exp={exp}&sig={_sig(key, exp)}"


def verify_signature(key: str, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(sig, _sig(key, exp))
