import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from control.config import Settings
from control.gateway import create_app
from control.mineru import MinerUClient
from control.objects import LocalObjectStore
from control.reconcile import Reconciler
from control.service import ControlPlane
from control.store import MemoryStore
from control.tiers import TierCatalog
from test_control_reconcile import FakeMinerU


def _settings(
    tmp: str,
    api_key: str = "",
    accepted_tiers: tuple[str, ...] = ("flash", "basic", "standard", "advanced"),
) -> Settings:
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
        api_key=api_key,
        accepted_tiers=accepted_tiers,
    )


class NativeApiTests(unittest.TestCase):
    def test_upload_job_and_file_content_stay_separate(self) -> None:
        with TemporaryDirectory() as tmp:
            store = MemoryStore()
            objects = LocalObjectStore(Path(tmp))
            plane = ControlPlane(store, objects, _settings(tmp))
            engine = FakeMinerU()
            reconciler = Reconciler(store, objects, engine, max_inflight=2, max_attempts=3)
            client = TestClient(create_app(plane, MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))))
            payload = b"%PDF-native"
            created = client.post(
                "/api/v2/uploads",
                json={
                    "filename": "paper.pdf",
                    "bytes": len(payload),
                    "mime_type": "application/pdf",
                    "purpose": "parse",
                },
            )
            self.assertEqual(created.status_code, 200)
            upload_id = created.json()["id"]
            self.assertEqual(created.json()["status"], "pending")
            put = client.put(f"/api/v2/uploads/{upload_id}/content", content=payload)
            self.assertEqual(put.status_code, 200)
            done = client.post(f"/api/v2/uploads/{upload_id}/complete", json={})
            self.assertEqual(done.status_code, 200)
            file_id = done.json()["file"]["id"]
            job = client.post(
                "/api/v2/jobs",
                json={"files": [{"source": {"type": "file_id", "file_id": file_id}}], "tier": "basic", "ocr_mode": "auto"},
            )
            self.assertEqual(job.status_code, 202)
            body = job.json()
            self.assertNotIn("markdown_content", body)
            self.assertEqual(body["status"], "queued")
            reconciler.run_once()
            reconciler.run_once()
            status = client.get(f"/api/v2/jobs/{body['job_id']}")
            self.assertEqual(status.status_code, 200)
            finished = status.json()
            self.assertEqual(finished["status"], "completed")
            self.assertNotIn("markdown", json.dumps(finished["files"][0].get("error")))
            markdown_id = finished["files"][0]["output_files"]["markdown"]["file_id"]
            downloaded = client.get(f"/api/v2/files/{markdown_id}/content")
            self.assertEqual(downloaded.status_code, 200)
            self.assertIn("Hello", downloaded.text)
            image_id = finished["files"][0]["output_files"]["images"][0]["file_id"]
            image = client.get(f"/api/v2/files/{image_id}/content")
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content, b"img-bytes")
            self.assertNotIn("data:image", json.dumps(finished))
            legacy = client.get(f"/api/v1/tasks/{body['job_id']}")
            self.assertIn("content_list", legacy.json())
            self.assertNotIn("schema", legacy.json()["middle_json"])
            self.assertNotIn("docling_document", legacy.json())

    def test_api_key_gates_native_routes_only(self) -> None:
        with TemporaryDirectory() as tmp:
            plane = ControlPlane(MemoryStore(), LocalObjectStore(Path(tmp)), _settings(tmp, api_key="secret"))
            client = TestClient(create_app(plane, MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))))
            denied = client.post(
                "/api/v2/uploads",
                json={"filename": "a.pdf", "bytes": 1, "mime_type": "application/pdf"},
            )
            self.assertEqual(denied.status_code, 401)
            allowed = client.post(
                "/api/v2/uploads",
                json={"filename": "a.pdf", "bytes": 4, "mime_type": "application/pdf"},
                headers={"Authorization": "Bearer secret"},
            )
            self.assertEqual(allowed.status_code, 200)
            legacy = client.post(
                "/api/v1/tasks/submit",
                files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
            )
            self.assertEqual(legacy.status_code, 200)
            self.assertEqual(client.post("/v1/uploads", json={}).status_code, 404)

    def test_tiers_come_from_the_running_engine(self) -> None:
        with TemporaryDirectory() as tmp:
            cpu_engine = _TierSource(("flash", "basic"))
            plane = ControlPlane(
                MemoryStore(),
                LocalObjectStore(Path(tmp)),
                _settings(tmp),
                TierCatalog([cpu_engine]),
            )
            client = TestClient(create_app(plane, MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))))
            listed = client.get("/api/v2/tiers")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["id"] for item in listed.json()["data"]], ["flash", "basic"])
            self.assertTrue(listed.json()["discovered"])
            rejected = client.post(
                "/api/v1/tasks/submit",
                data={"tier": "standard"},
                files={"file": ("paper.pdf", b"%PDF", "application/pdf")},
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertIn("not available", rejected.json()["detail"])

    def test_job_accepts_top_level_file_id_and_is_listed(self) -> None:
        with TemporaryDirectory() as tmp:
            plane = ControlPlane(MemoryStore(), LocalObjectStore(Path(tmp)), _settings(tmp))
            client = TestClient(create_app(plane, MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))))
            payload = b"%PDF-list"
            created = client.post(
                "/api/v2/uploads",
                json={"filename": "paper.pdf", "bytes": len(payload), "mime_type": "application/pdf"},
            ).json()
            self.assertEqual(client.get(f"/api/v2/uploads/{created['id']}").json()["status"], "pending")
            client.put(f"/api/v2/uploads/{created['id']}/content", content=payload)
            file_id = client.post(f"/api/v2/uploads/{created['id']}/complete", json={}).json()["file"]["id"]
            job = client.post("/api/v2/jobs", json={"file_id": file_id, "tier": "basic"})
            self.assertEqual(job.status_code, 202)
            listed = client.get("/api/v2/jobs", params={"status": "queued"}).json()
            self.assertEqual([item["job_id"] for item in listed["data"]], [job.json()["job_id"]])
            self.assertEqual(client.get("/api/v2/jobs", params={"status": "completed"}).json()["data"], [])

    def test_v2_health_reports_every_upstream(self) -> None:
        with TemporaryDirectory() as tmp:
            plane = ControlPlane(MemoryStore(), LocalObjectStore(Path(tmp)), _settings(tmp))
            down = MinerUClient("http://down.test", transport=lambda *args: (503, b"{}"))
            up = MinerUClient("http://up.test", transport=lambda *args: (200, b'{"status":"ok"}'))
            client = TestClient(create_app(plane, down, engines=[down, up]))
            health = client.get("/api/v2/health")
            self.assertEqual(health.status_code, 200)
            upstreams = health.json()["components"]["mineru_upstreams"]
            self.assertEqual([item["healthy"] for item in upstreams], [False, True])
            only_down = TestClient(create_app(plane, down, engines=[down]))
            self.assertEqual(only_down.get("/api/v2/health").status_code, 503)

    def test_batch_counts_and_cancel_leave_completed_jobs(self) -> None:
        with TemporaryDirectory() as tmp:
            store = MemoryStore()
            objects = LocalObjectStore(Path(tmp))
            plane = ControlPlane(store, objects, _settings(tmp))
            engine = FakeMinerU()
            reconciler = Reconciler(store, objects, engine, max_inflight=4, max_attempts=3)
            client = TestClient(create_app(plane, MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))))
            ids = []
            for index in range(20):
                created = plane.submit(f"{index}.pdf", b"%PDF", tier="basic", batch_id="batch-a")
                ids.append(created["task_id"])
            summary = client.get("/api/v2/batches/batch-a").json()
            self.assertEqual(
                summary["queued"] + summary["running"] + summary["completed"] + summary["failed"] + summary["canceled"],
                20,
            )
            self.assertEqual(summary["total"], 20)
            reconciler.run_once()
            reconciler.run_once()
            done = plane.batch_summary("batch-a")
            assert done is not None
            self.assertEqual(done["completed"], 1)
            removed = client.delete("/api/v2/batches/batch-a")
            self.assertEqual(removed.status_code, 200)
            self.assertEqual(removed.json()["canceled"], 19)
            reconciler.run_once()
            kept = plane.native_job(ids[0])
            assert kept is not None
            self.assertEqual(kept["status"], "completed")
            failed = client.get("/api/v2/batches/batch-a/jobs", params={"status": "canceled"})
            self.assertEqual(len(failed.json()["data"]), 19)
            self.assertEqual(client.post("/api/v2/jobs", json={"file_id": "missing", "batch_id": "bad id"}).status_code, 400)

    def test_stats_reports_the_queue_and_slots(self) -> None:
        with TemporaryDirectory() as tmp:
            plane = ControlPlane(MemoryStore(), LocalObjectStore(Path(tmp)), _settings(tmp))
            engine = MinerUClient("http://mineru.test", transport=lambda *args: (200, b"{}"))
            client = TestClient(create_app(plane, engine, engines=[engine]))
            plane.submit("paper.pdf", b"%PDF")
            stats = client.get("/api/v2/stats").json()
            self.assertEqual(stats["queue"]["accepted"], 1)
            self.assertEqual(stats["slots"]["total"], 2)
            self.assertEqual(stats["inflight_byte_limit"], 1 << 30)
            self.assertGreaterEqual(stats["oldest_queued_seconds"], 0)
            self.assertEqual(client.get("/api/v1/queue/stats").json()["stats"]["pending"], 1)


class _TierSource:
    def __init__(self, tiers: tuple[str, ...] | None) -> None:
        self._tiers = tiers

    def tiers(self) -> tuple[str, ...] | None:
        return self._tiers


class TierCatalogTests(unittest.TestCase):
    def test_offers_the_union_of_reachable_upstreams(self) -> None:
        catalog = TierCatalog(
            [_TierSource(("flash", "basic", "standard", "advanced")), _TierSource(("flash", "basic")), _TierSource(None)],
        )
        self.assertEqual(catalog.available(), ("flash", "basic", "standard", "advanced"))
        self.assertEqual(
            catalog.reported(),
            [("flash", "basic", "standard", "advanced"), ("flash", "basic"), None],
        )
        self.assertTrue(catalog.discovered())

    def test_operator_allow_list_narrows_discovered_tiers(self) -> None:
        catalog = TierCatalog([_TierSource(("flash", "basic", "standard", "advanced"))], allowed=("basic", "standard"))
        self.assertEqual(catalog.available(), ("basic", "standard"))

    def test_falls_back_to_allow_list_when_no_upstream_answers(self) -> None:
        catalog = TierCatalog([_TierSource(None)], allowed=("flash", "basic"))
        self.assertEqual(catalog.available(), ("flash", "basic"))
        self.assertFalse(catalog.discovered())

    def test_caches_until_ttl_expires(self) -> None:
        now = [0.0]
        source = _TierSource(("basic",))
        catalog = TierCatalog([source], ttl_seconds=10, clock=lambda: now[0])
        self.assertEqual(catalog.available(), ("basic",))
        source._tiers = ("flash", "basic")
        self.assertEqual(catalog.available(), ("basic",))
        now[0] = 11
        self.assertEqual(catalog.available(), ("flash", "basic"))

    def test_mineru_client_reads_tier_list(self) -> None:
        body = b'{"object":"list","data":[{"id":"flash"},{"id":"basic"}]}'
        client = MinerUClient("http://mineru.test", transport=lambda *args: (200, body))
        self.assertEqual(client.tiers(), ("flash", "basic"))
        broken = MinerUClient("http://mineru.test", transport=lambda *args: (500, b"{}"))
        self.assertIsNone(broken.tiers())


if __name__ == "__main__":
    unittest.main()
