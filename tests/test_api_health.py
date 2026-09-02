import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

from api import app as app_module


def _components(workers_available=True):
    return {
        "redis": {"available": True, "queue_depth": 0},
        "storage": {"available": True, "type": "local"},
        "workers": {
            "available": workers_available,
            "count": 1 if workers_available else 0,
            "active_tasks": [],
        },
    }


class ApiHealthTests(unittest.TestCase):
    def test_readiness_dependency_probe_is_bounded(self):
        def available_redis():
            return {"available": True}

        def slow_storage():
            time.sleep(0.05)
            return {"available": True, "type": "s3"}

        def available_worker(_celery_app):
            return {"available": True, "count": 1}

        with (
            patch.dict(os.environ, {"HEALTH_DEPENDENCY_TIMEOUT_SECONDS": "0.01"}),
            patch.object(app_module, "collect_redis_snapshot", available_redis),
            patch.object(app_module, "collect_storage_snapshot", slow_storage),
            patch.object(app_module, "collect_worker_snapshot", available_worker),
        ):
            ready, components = asyncio.run(app_module.collect_readiness())

        self.assertIs(ready, False)
        self.assertIs(components["storage"]["available"], False)
        self.assertIn("timed out", components["storage"]["error"])

    def test_readiness_returns_503_when_worker_is_unavailable(self):
        async def fake_readiness():
            return False, _components(workers_available=False)

        with patch.object(app_module, "collect_readiness", fake_readiness):
            response = asyncio.run(app_module.readiness_check())

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.body)["status"], "not_ready")

    def test_legacy_health_preserves_worker_shape(self):
        async def fake_readiness():
            return True, _components()

        with patch.object(app_module, "collect_readiness", fake_readiness):
            response = asyncio.run(app_module.health_check())
        payload = json.loads(response.body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(payload["workers"], {"active": 1, "available": True})

    def test_readiness_summary_does_not_expose_runtime_identifiers(self):
        components = _components()
        components["redis"]["worker_heartbeats"] = [
            {
                "worker": "private-worker-name",
                "task_id": "private-task-id",
                "file_name": "private-file.pdf",
                "gpu": {
                    "devices": [
                        {
                            "index": 0,
                            "utilization_percent": 50,
                            "memory_total_mb": 100,
                            "memory_used_mb": 25,
                            "temperature_c": 60,
                        }
                    ]
                },
            }
        ]
        summary = app_module.summarize_health_components(components)
        serialized = json.dumps(summary)

        self.assertNotIn("private-worker-name", serialized)
        self.assertNotIn("private-task-id", serialized)
        self.assertNotIn("private-file.pdf", serialized)
        self.assertEqual(summary["gpu"]["max_utilization_percent"], 50)

    def test_deep_health_exposes_runtime_diagnostics(self):
        components = _components()
        components["redis"]["worker_heartbeats"] = [
            {
                "worker": "worker-1",
                "task_id": "task-1",
                "file_name": "paper.pdf",
                "gpu": {
                    "devices": [
                        {
                            "index": 0,
                            "name": "Example GPU",
                            "uuid": "GPU-example",
                            "driver_version": "555.1",
                            "utilization_percent": 50,
                            "memory_total_mb": 100,
                            "memory_used_mb": 25,
                            "temperature_c": 60,
                        }
                    ]
                },
            }
        ]
        components["workers"]["active_tasks"] = [
            {
                "task_id": "task-1",
                "worker": "worker-1",
                "file_name": "paper.pdf",
                "runtime_seconds": 10,
            }
        ]

        async def fake_readiness():
            return True, components

        with patch.object(app_module, "collect_readiness", fake_readiness):
            response = asyncio.run(app_module.deep_health_check())
        payload = json.loads(response.body)
        serialized = json.dumps(payload)

        self.assertIn("Example GPU", serialized)
        self.assertIn("GPU-example", serialized)
        self.assertIn("worker-1", serialized)
        self.assertIn("task-1", serialized)
        self.assertIn("paper.pdf", serialized)

    def test_cancel_reports_request_instead_of_false_completion(self):
        calls = []

        async def fake_to_thread(function, *args, **kwargs):
            calls.append((function, args, kwargs))

        with patch.object(app_module.asyncio, "to_thread", fake_to_thread):
            payload = asyncio.run(app_module.cancel_task("task-1"))

        self.assertEqual(payload["status"], "cancel_requested")
        self.assertIs(calls[0][0], app_module.request_task_cancellation)
        self.assertEqual(calls[0][1], ("task-1",))
        self.assertEqual(calls[1][1], ("task-1",))
        self.assertEqual(calls[1][2], {"terminate": False})

    def test_successful_celery_result_preserves_cancelled_semantics(self):
        class CancelledResult:
            status = "SUCCESS"
            result = {
                "status": "cancelled",
                "file_name": "paper.pdf",
                "completed_at": "2026-09-02T00:00:00+00:00",
                "error_message": "Parsing cancelled",
            }
            retries = 0

            def successful(self):
                return True

            def failed(self):
                return False

        with patch.object(app_module, "AsyncResult", return_value=CancelledResult()):
            payload = app_module.build_task_status_response("task-1")

        self.assertEqual(payload["task"]["status"], "cancelled")
        self.assertEqual(payload["task"]["error_message"], "Parsing cancelled")


if __name__ == "__main__":
    unittest.main()
