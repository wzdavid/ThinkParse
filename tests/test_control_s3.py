"""MinIO object store. Skips unless the local test bucket answers."""

import unittest
from pathlib import Path

from control.config import Settings
from control.factory import open_objects
from control.objects import S3ObjectStore


def _minio_up() -> bool:
    try:
        store = S3ObjectStore(
            "http://127.0.0.1:19000",
            "thinkparse",
            "thinkparse-secret",
            "thinkparse-test",
        )
        store.put("health", b"ok")
        return store.get("health") == b"ok"
    except Exception:
        return False


@unittest.skipUnless(_minio_up(), "MinIO is not reachable on 127.0.0.1:19000")
class S3StoreTests(unittest.TestCase):
    def test_factory_round_trip(self) -> None:
        settings = Settings(
            database_url="",
            object_dir=Path("/tmp/thinkparse-unused"),
            mineru_base_url="http://mineru.test",
            mineru_api_key="",
            max_inflight=1,
            max_file_bytes=100,
            free_min_bytes=0,
            max_attempts=1,
            task_timeout_seconds=1,
            legacy_allow_flash=False,
            require_postgres=False,
            poll_interval_seconds=1,
            http_timeout_seconds=1,
            s3_endpoint="http://127.0.0.1:19000",
            s3_access_key="thinkparse",
            s3_secret_key="thinkparse-secret",
            s3_bucket="thinkparse-test",
        )
        store = open_objects(settings)
        store.put("blobs/abc", b"pdf-bytes")
        self.assertEqual(store.get("blobs/abc"), b"pdf-bytes")
        store.delete("blobs/abc")
        with self.assertRaises(Exception):
            store.get("blobs/abc")


if __name__ == "__main__":
    unittest.main()
