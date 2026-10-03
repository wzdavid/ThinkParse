"""Local directory object store. Keys are relative POSIX paths."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


class CapacityExceeded(Exception):
    """Free space is below the configured reserve."""


class ObjectStore:
    def put(self, key: str, data: bytes) -> None:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_prefix(self, prefix: str) -> None:
        raise NotImplementedError

    def ensure_capacity(self, incoming: int, min_free: int) -> None:
        raise NotImplementedError


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if key.startswith("/") or ".." in key.split("/"):
            raise ValueError(f"invalid object key: {key}")
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        path = self.root / key
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self.root / key
        if path.is_file():
            path.unlink()

    def delete_prefix(self, prefix: str) -> None:
        root = self.root / _prefix(prefix)
        if not root.is_dir():
            return
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        root.rmdir()

    def ensure_capacity(self, incoming: int, min_free: int) -> None:
        free = shutil.disk_usage(self.root).free
        if free - incoming < min_free:
            raise CapacityExceeded(
                f"object store free space {free} bytes is below reserve {min_free}"
            )


class S3ObjectStore(ObjectStore):
    """S3-compatible store. Capacity is enforced by the bucket, not local free space."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3 object storage; install control/requirements.txt") from exc
        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        last_error: Exception | None = None
        for _ in range(30):
            try:
                existing = {item["Name"] for item in self._client.list_buckets().get("Buckets", [])}
                if bucket not in existing:
                    self._client.create_bucket(Bucket=bucket)
                return
            except Exception as exc:
                last_error = exc
                time.sleep(1)
        raise RuntimeError(f"object store {endpoint} is not ready") from last_error

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix: str) -> None:
        prefix = _prefix(prefix)
        token: str | None = None
        while True:
            kwargs: dict[str, object] = {"Bucket": self.bucket, "Prefix": prefix}
            if token is not None:
                kwargs["ContinuationToken"] = token
            page = self._client.list_objects_v2(**kwargs)
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            for offset in range(0, len(keys), 1000):
                chunk = keys[offset : offset + 1000]
                if chunk:
                    self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": chunk})
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")

    def ensure_capacity(self, incoming: int, min_free: int) -> None:
        del incoming, min_free


def _prefix(prefix: str) -> str:
    if not prefix or prefix.startswith("/") or ".." in prefix.split("/"):
        raise ValueError(f"invalid object prefix: {prefix}")
    return prefix if prefix.endswith("/") else prefix + "/"
