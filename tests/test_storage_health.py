import unittest
from unittest.mock import patch

from shared import storage


class FakeS3FileSystem:
    def __init__(self, existing_buckets):
        self.existing_buckets = set(existing_buckets)
        self.checked = []

    def exists(self, bucket):
        self.checked.append(bucket)
        return bucket in self.existing_buckets


class StorageHealthTests(unittest.TestCase):
    def create_s3_adapter(self, existing_buckets):
        adapter = storage.StorageAdapter.__new__(storage.StorageAdapter)
        adapter.storage_type = "s3"
        adapter._fs = FakeS3FileSystem(existing_buckets)
        return adapter

    def test_s3_health_check_is_read_only_and_checks_both_buckets(self):
        buckets = {storage.S3_BUCKET_TEMP, storage.S3_BUCKET_OUTPUT}
        adapter = self.create_s3_adapter(buckets)

        snapshot = adapter.health_check()

        self.assertIs(snapshot["available"], True)
        self.assertEqual(set(adapter._fs.checked), buckets)

    def test_s3_health_check_reports_missing_bucket(self):
        adapter = self.create_s3_adapter({storage.S3_BUCKET_TEMP})

        snapshot = adapter.health_check()

        self.assertIs(snapshot["available"], False)
        self.assertIs(snapshot["buckets"][storage.S3_BUCKET_OUTPUT], False)

    def test_local_health_check_requires_writable_directories(self):
        adapter = storage.StorageAdapter.__new__(storage.StorageAdapter)
        adapter.storage_type = "local"
        with (
            patch.object(storage.Path, "exists", return_value=True),
            patch.object(storage.os, "access", return_value=True),
        ):
            snapshot = adapter.health_check()

        self.assertIs(snapshot["available"], True)


if __name__ == "__main__":
    unittest.main()
