import json
import os
import unittest
from unittest.mock import patch

from shared import observability


class FakeRedis:
    def __init__(self):
        self.closed = False

    def ping(self):
        return True

    def llen(self, key):
        return {
            "mineru-tasks": 2,
            "mineru-tasks\x06\x163": 1,
        }.get(key, 0)

    def scan_iter(self, match):
        assert match == "thinkparse:worker:*"
        return iter(["thinkparse:worker:gpu-0"])

    def get(self, key):
        assert key == "thinkparse:worker:gpu-0"
        return json.dumps({"worker": "gpu-0", "stage": "idle"})

    def close(self):
        self.closed = True


class FakeInspect:
    def stats(self):
        return {"gpu-0": {"pool": {"max-concurrency": 1}}}

    def active(self):
        return {
            "gpu-0": [
                {
                    "id": "task-1",
                    "name": "mineru.parse_document",
                    "args": ["path", "paper.pdf", "pipeline"],
                    "time_start": 100.0,
                }
            ]
        }

    def reserved(self):
        return {
            "gpu-0": [
                {
                    "id": "task-2",
                    "name": "mineru.parse_document",
                    "args": ["path", "queued.pdf", "pipeline"],
                }
            ]
        }


class FakeControl:
    def inspect(self, timeout):
        assert timeout == 1.0
        return FakeInspect()


class FakeCelery:
    control = FakeControl()


class FakeCancellationRedis:
    def __init__(self, exists=True):
        self.exists_value = exists
        self.closed = False

    def exists(self, key):
        assert key == "thinkparse:cancel:task-1"
        return self.exists_value

    def close(self):
        self.closed = True


class FakeS3Storage:
    storage_type = "s3"

    def health_check(self):
        return {
            "available": True,
            "type": "s3",
            "buckets": {"temp": True, "output": True},
        }


class ObservabilityTests(unittest.TestCase):
    def test_legacy_pagination_request_overrides_environment(self):
        with patch.dict(os.environ, {"MINERU_ENABLE_PAGINATION": "false"}):
            self.assertIs(observability.resolve_legacy_pagination(True), True)
            self.assertIs(observability.resolve_legacy_pagination(False), False)

    def test_legacy_pagination_defaults_to_environment(self):
        with patch.dict(os.environ, {"MINERU_ENABLE_PAGINATION": "true"}):
            self.assertIs(observability.resolve_legacy_pagination(None), True)
        with patch.dict(os.environ, {"MINERU_ENABLE_PAGINATION": "false"}):
            self.assertIs(observability.resolve_legacy_pagination(None), False)

    def test_redis_snapshot_counts_priority_queues(self):
        client = FakeRedis()
        with patch.object(observability, "_redis_client", return_value=client):
            snapshot = observability.collect_redis_snapshot()

        self.assertIs(snapshot["available"], True)
        self.assertEqual(snapshot["queue_depth"], 3)
        self.assertEqual(snapshot["worker_heartbeats"][0]["worker"], "gpu-0")
        self.assertIs(client.closed, True)

    def test_worker_snapshot_reports_active_and_reserved_tasks(self):
        with patch.object(observability.time, "time", return_value=160.0):
            snapshot = observability.collect_worker_snapshot(FakeCelery())

        self.assertIs(snapshot["available"], True)
        self.assertEqual(snapshot["active_count"], 1)
        self.assertEqual(snapshot["reserved_count"], 1)
        self.assertEqual(snapshot["active_tasks"][0]["runtime_seconds"], 60.0)
        self.assertEqual(snapshot["active_tasks"][0]["file_name"], "paper.pdf")
        self.assertEqual(snapshot["reserved_tasks"][0]["file_name"], "queued.pdf")

    def test_gpu_snapshot_includes_runtime_identity_and_metrics(self):
        completed = type(
            "Completed",
            (),
            {"stdout": "0, Example GPU, GPU-example, 555.1, 42, 24576, 8192, 61\n"},
        )()
        with patch.object(observability.subprocess, "run", return_value=completed):
            snapshot = observability.collect_gpu_snapshot()

        self.assertIs(snapshot["available"], True)
        self.assertEqual(snapshot["device_count"], 1)
        self.assertEqual(snapshot["devices"][0]["utilization_percent"], 42)
        self.assertEqual(snapshot["devices"][0]["name"], "Example GPU")
        self.assertEqual(snapshot["devices"][0]["uuid"], "GPU-example")
        self.assertEqual(snapshot["devices"][0]["driver_version"], "555.1")

    def test_watchdog_can_be_disabled_and_detects_overdue_task(self):
        self.assertIs(
            observability.is_task_watchdog_overdue(10.0, 20.0, timeout_seconds=5.0),
            True,
        )
        self.assertIs(
            observability.is_task_watchdog_overdue(10.0, 20.0, timeout_seconds=0),
            False,
        )

    def test_redelivered_task_observes_watchdog_cancellation(self):
        client = FakeCancellationRedis()
        with patch.object(observability, "_redis_client", return_value=client):
            cancelled = observability.is_task_cancellation_requested("task-1")

        self.assertIs(cancelled, True)
        self.assertIs(client.closed, True)

    def test_watchdog_restart_requires_persisted_cancellation(self):
        with patch.object(
            observability,
            "request_task_cancellation",
            side_effect=RuntimeError("redis unavailable"),
        ):
            self.assertIs(observability.prepare_watchdog_restart("task-1"), False)
        with patch.object(observability, "request_task_cancellation"):
            self.assertIs(observability.prepare_watchdog_restart("task-1"), True)

    def test_s3_snapshot_performs_backend_health_check(self):
        with (
            patch.object(observability, "STORAGE_TYPE", "s3"),
            patch.object(observability, "get_storage", return_value=FakeS3Storage()),
        ):
            snapshot = observability.collect_storage_snapshot()

        self.assertIs(snapshot["available"], True)
        self.assertEqual(snapshot["buckets"], {"temp": True, "output": True})


if __name__ == "__main__":
    unittest.main()
