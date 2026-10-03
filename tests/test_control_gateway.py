import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from control.config import Settings
from control.gateway import create_app
from control.mineru import MinerUClient
from control.objects import LocalObjectStore
from control.service import ControlPlane
from control.store import MemoryStore


class GatewayTests(unittest.TestCase):
    def test_submit_and_health(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = Settings(
                database_url="",
                object_dir=Path(tmp),
                mineru_base_url="http://mineru.test",
                mineru_api_key="",
                max_inflight=2,
                max_file_bytes=128,
                free_min_bytes=0,
                max_attempts=3,
                task_timeout_seconds=0,
                legacy_allow_flash=False,
                require_postgres=False,
                poll_interval_seconds=1,
                http_timeout_seconds=1,
            )
            plane = ControlPlane(MemoryStore(), LocalObjectStore(Path(tmp)), settings)
            engine = MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))
            client = TestClient(create_app(plane, engine))

            live = client.get("/api/v1/health/live")
            self.assertEqual(live.status_code, 200)
            self.assertEqual(live.json()["status"], "alive")

            ready = client.get("/api/v1/health/ready")
            self.assertEqual(ready.status_code, 200)
            self.assertTrue(ready.json()["components"]["mineru"])

            submitted = client.post(
                "/api/v1/tasks/submit",
                files={"file": ("paper.pdf", b"%PDF-1.4", "application/pdf")},
                data={"backend": "pipeline", "formula_enable": "true", "f_dump_content_list": "true"},
            )
            self.assertEqual(submitted.status_code, 200)
            body = submitted.json()
            self.assertTrue(body["task_id"])
            self.assertEqual(body["status"], "pending")
            self.assertEqual(body["backend"], "pipeline")

            status = client.get(f"/api/v1/tasks/{body['task_id']}")
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["task"]["status"], "pending")
            self.assertEqual(client.get("/api/v1/tasks/missing").status_code, 404)

            stats = client.get("/api/v1/queue/stats")
            self.assertEqual(stats.json()["stats"]["pending"], 1)

            huge = client.post(
                "/api/v1/tasks/submit",
                files={"file": ("big.pdf", b"x" * 200, "application/pdf")},
            )
            self.assertEqual(huge.status_code, 413)

            rejected = client.post(
                "/api/v1/tasks/submit",
                files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
                data={"backend": "advanced"},
            )
            self.assertEqual(rejected.status_code, 400)

            waiting = client.post(
                "/file_parse",
                files=[("files", ("paper.pdf", b"%PDF", "application/pdf"))],
            )
            self.assertEqual(waiting.status_code, 504)


if __name__ == "__main__":
    unittest.main()
