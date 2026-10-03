import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from control.config import Settings
from control.docling import DoclingClient
from control.objects import LocalObjectStore
from control.reconcile import Reconciler
from control.service import ControlPlane
from control.store import MemoryStore


def _settings(tmp: str) -> Settings:
    return Settings(
        database_url="",
        object_dir=Path(tmp),
        mineru_base_url="http://mineru.test",
        mineru_api_key="",
        max_inflight=2,
        max_file_bytes=1024 * 1024,
        free_min_bytes=0,
        max_attempts=3,
        task_timeout_seconds=30,
        legacy_allow_flash=False,
        require_postgres=False,
        poll_interval_seconds=0.01,
        http_timeout_seconds=1,
        docling_base_url="http://docling.test",
    )


class DoclingRouteTests(unittest.TestCase):
    def test_jats_uses_docling_and_keeps_mineru_shape_off_the_document(self) -> None:
        calls: list[str] = []

        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            del headers
            calls.append(f"{method} {path}")
            if path == "/v1/convert/source/async":
                payload = json.loads(body or b"{}")
                self.assertEqual(payload["file_sources"][0]["filename"], "paper.xml")
                self.assertEqual(payload["options"]["to_formats"], ["md", "json"])
                return 200, json.dumps({"task_id": "dl_1", "task_status": "pending"}).encode()
            if path == "/v1/status/poll/dl_1":
                return 200, json.dumps({"task_id": "dl_1", "task_status": "success"}).encode()
            if path == "/v1/result/dl_1":
                return 200, json.dumps(
                    {"document": {"md_content": "# JATS", "json_content": {"texts": [{"text": "JATS"}]}}}
                ).encode()
            return 404, b""

        with TemporaryDirectory() as tmp:
            store = MemoryStore()
            objects = LocalObjectStore(Path(tmp))
            plane = ControlPlane(store, objects, _settings(tmp))
            mineru_called = {"n": 0}

            class IdleMinerU:
                base_url = "http://mineru.test"

                def submit(self, *args, **kwargs):
                    del args, kwargs
                    mineru_called["n"] += 1
                    raise AssertionError("pdf engine must not parse jats")

                def poll(self, job_id: str):
                    del job_id
                    raise AssertionError("unused")

                def fetch(self, poll):
                    del poll
                    raise AssertionError("unused")

                def cancel(self, job_id: str) -> None:
                    del job_id

            docling = DoclingClient("http://docling.test", transport=transport)
            reconciler = Reconciler(
                store,
                objects,
                IdleMinerU(),
                max_inflight=2,
                max_attempts=3,
                docling=docling,
            )
            created = plane.submit("paper.xml", b"<article/>")
            self.assertEqual(created["backend"], "docling")
            reconciler.run_once()
            reconciler.run_once()
            payload = plane.status_payload(created["task_id"])
            assert payload is not None
            self.assertEqual(payload["task"]["status"], "completed")
            self.assertEqual(payload["docling_document"]["texts"][0]["text"], "JATS")
            self.assertEqual(payload["markdown_content"], "# JATS")
            self.assertNotIn("schema", payload["middle_json"])
            self.assertEqual(mineru_called["n"], 0)
            self.assertTrue(any(path.startswith("POST /v1/convert/source/async") for path in calls))


if __name__ == "__main__":
    unittest.main()
