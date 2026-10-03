import json
import unittest
from datetime import timedelta
from pathlib import Path

from control.config import Settings
from control.mineru import NativeArtifacts, UpstreamNotFound, UpstreamPoll, UpstreamRejected, UpstreamUnavailable
from control.objects import LocalObjectStore
from control.reconcile import Reconciler
from control.service import ControlPlane
from control.store import MemoryStore, utcnow
from control.tiers import TierCatalog

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_projection" / "middle.json").read_text(encoding="utf-8")
)


def settings(tmp: str) -> Settings:
    return Settings(
        database_url="",
        object_dir=Path(tmp),
        mineru_base_url="http://mineru.test",
        mineru_api_key="",
        max_inflight=1,
        max_file_bytes=1024 * 1024,
        free_min_bytes=0,
        max_attempts=3,
        task_timeout_seconds=5,
        legacy_allow_flash=False,
        require_postgres=False,
        poll_interval_seconds=0.01,
        http_timeout_seconds=1,
    )


class FakeMinerU:
    def __init__(self) -> None:
        self.jobs: dict[str, str] = {}
        self.submitted = 0
        self.markdown = "Hello ![](images/fig1.jpg)"
        self.images = {"fig1.jpg": b"img-bytes"}
        self.cancelled: list[str] = []
        self.released: list[str] = []
        self.forget = False
        self.down = False
        self.hold = False
        self.reject = ""
        self.base_url = ""
        self.tier_names: tuple[str, ...] | None = None

    def tiers(self) -> tuple[str, ...] | None:
        return self.tier_names

    def health(self) -> bool:
        return not self.down

    def submit(self, data: bytes, filename: str, sha256: str, tier: str, ocr_mode: str) -> str:
        del data, filename, sha256, ocr_mode
        if self.down:
            raise UpstreamUnavailable("down")
        if self.reject:
            raise UpstreamRejected(self.reject)
        self.submitted += 1
        job_id = f"job_{self.submitted}"
        self.jobs[job_id] = tier
        return job_id

    def poll(self, job_id: str) -> UpstreamPoll:
        if self.forget or job_id not in self.jobs:
            raise UpstreamNotFound(job_id)
        status = "queued" if self.hold else "completed"
        return UpstreamPoll(
            status=status,
            markdown_file_id="md",
            middle_file_id="mid",
            zip_file_id="file_zip",
            source_file_id="file_src",
        )

    def fetch(self, poll: UpstreamPoll) -> NativeArtifacts:
        del poll
        return NativeArtifacts(
            markdown=self.markdown,
            middle=FIXTURE,
            images=dict(self.images),
        )

    def release_files(self, file_ids: list[str]) -> None:
        self.released.extend(file_ids)

    def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        self.jobs.pop(job_id, None)


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(self.id().replace(".", "_"))
        self.store = MemoryStore()
        self.objects = LocalObjectStore(self.tmp)
        self.engine = FakeMinerU()
        self.plane = ControlPlane(self.store, self.objects, settings(str(self.tmp)))
        self.reconciler = Reconciler(
            self.store,
            self.objects,
            self.engine,
            max_inflight=1,
            max_attempts=3,
        )

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_submit_projects_legacy_payload(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF-1.4")
        self.assertEqual(created["status"], "pending")
        self.assertEqual(created["backend"], "pipeline")
        self.reconciler.run_once()
        self.reconciler.run_once()
        payload = self.plane.status_payload(created["task_id"])
        assert payload is not None
        self.assertEqual(payload["task"]["status"], "completed")
        self.assertEqual(payload["task"]["error_message"], None)
        self.assertIn("Hello", payload["markdown_content"])
        self.assertNotIn("data:image", payload["markdown_content"])
        self.assertEqual(payload["data"]["content"], payload["markdown_content"])
        self.assertEqual(self.engine.released, ["file_src", "file_zip", "md", "mid"])
        self.assertNotIn("schema", payload["middle_json"])
        self.assertTrue(payload["middle_json"]["pdf_info"][0]["discarded_blocks"])
        self.assertTrue(any(item["type"] == "equation" for item in payload["content_list"]))
        image = payload["images"][0]
        self.assertEqual(image["filename"], "fig1.jpg")
        self.assertEqual(image["data_url"], "data:image/jpeg;base64,aW1nLWJ5dGVz")
        self.assertEqual(payload["data"]["images"], payload["images"])
        native = [item for item in self.store.artifacts(created["task_id"]) if item.kind == "middle_native"]
        self.assertEqual(len(native), 1)
        stored = json.loads(self.objects.get(native[0].storage_key))
        self.assertEqual(stored["schema"], "docvortex.middle")

    def test_embedded_data_image_fails_projection(self) -> None:
        self.engine.markdown = "Hello ![](data:image/png;base64,QQQ)"
        self.engine.images = {}
        created = self.plane.submit("paper.pdf", b"%PDF-1.4")
        self.reconciler.run_once()
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        self.assertEqual(task.status, "failed")
        self.assertIn("data:image", task.error_message or "")

    def test_upstream_loss_resubmits_same_task_id(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        self.engine.forget = True
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        self.assertEqual(task.status, "accepted")
        self.assertIsNone(task.upstream_job_id)
        self.assertGreaterEqual(task.attempt, 1)
        task.next_attempt_at = utcnow()
        self.store.update_task(task)
        self.engine.forget = False
        self.reconciler.run_once()
        self.reconciler.run_once()
        payload = self.plane.status_payload(created["task_id"])
        assert payload is not None
        self.assertEqual(payload["task"]["status"], "completed")
        self.assertEqual(payload["task"]["task_id"], created["task_id"])
        self.assertEqual(self.engine.submitted, 2)

    def test_upstream_rejection_fails_without_retry(self) -> None:
        self.engine.reject = "tier standard is not served"
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        self.assertEqual(task.status, "failed")
        self.assertIn("not served", task.error_message or "")
        self.assertEqual(self.engine.submitted, 0)

    def test_higher_priority_is_dispatched_before_an_earlier_job(self) -> None:
        self.engine.hold = True
        low = self.plane.submit("low.pdf", b"low", priority=0)
        high = self.plane.submit("high.pdf", b"high", priority=5)
        self.reconciler.run_once()
        self.assertEqual(self.engine.submitted, 1)
        high_row = self.store.get_task(high["task_id"])
        low_row = self.store.get_task(low["task_id"])
        assert high_row is not None and low_row is not None
        self.assertEqual(high_row.status, "running")
        self.assertEqual(low_row.status, "accepted")

    def test_a_running_task_is_not_preempted_by_a_higher_priority(self) -> None:
        self.engine.hold = True
        low = self.plane.submit("low.pdf", b"low", priority=0)
        self.reconciler.run_once()
        high = self.plane.submit("high.pdf", b"high", priority=9)
        self.reconciler.run_once()
        low_row = self.store.get_task(low["task_id"])
        high_row = self.store.get_task(high["task_id"])
        assert low_row is not None and high_row is not None
        self.assertEqual(low_row.status, "running")
        self.assertEqual(high_row.status, "accepted")
        self.assertEqual(self.engine.submitted, 1)

    def test_inflight_limit_holds_the_second_task(self) -> None:
        self.engine.hold = True
        first = self.plane.submit("a.pdf", b"a")
        second = self.plane.submit("b.pdf", b"b")
        self.reconciler.run_once()
        self.reconciler.run_once()
        self.assertEqual(self.engine.submitted, 1)
        second_row = self.store.get_task(second["task_id"])
        assert second_row is not None
        self.assertEqual(second_row.status, "accepted")
        self.engine.hold = False
        self.reconciler.run_once()
        self.reconciler.run_once()
        first_payload = self.plane.status_payload(first["task_id"])
        assert first_payload is not None
        self.assertEqual(first_payload["task"]["status"], "completed")

    def test_cancel_running_task(self) -> None:
        self.engine.hold = True
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        self.plane.cancel(created["task_id"])
        self.reconciler.run_once()
        payload = self.plane.status_payload(created["task_id"])
        assert payload is not None
        self.assertEqual(payload["task"]["status"], "cancelled")
        self.assertEqual(self.engine.cancelled, ["job_1"])

    def test_unknown_backend_and_unregistered_formats(self) -> None:
        from control.options import RequestRejected

        with self.assertRaises(RequestRejected) as ctx:
            self.plane.submit("paper.pdf", b"%PDF", backend="vlm-vllm-engine")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(RequestRejected) as advanced:
            self.plane.submit("paper.pdf", b"%PDF", tier="advanced")
        self.assertEqual(advanced.exception.status_code, 400)
        with self.assertRaises(RequestRejected) as flash:
            self.plane.submit("paper.pdf", b"%PDF", tier="flash")
        self.assertIn("LEGACY_ALLOW_FLASH", str(flash.exception))
        with self.assertRaises(RequestRejected) as docling:
            self.plane.submit("paper.xml", b"<article/>")
        self.assertIn("Docling", str(docling.exception))

    def test_two_mineru_urls_share_inflight_work(self) -> None:
        first = FakeMinerU()
        second = FakeMinerU()
        first.base_url = "http://gpu0"
        second.base_url = "http://gpu1"
        first.hold = True
        second.hold = True
        reconciler = Reconciler(
            self.store,
            self.objects,
            first,
            max_inflight=2,
            max_attempts=3,
            mineru_pool=[first, second],
        )
        self.plane.submit("a.pdf", b"a")
        self.plane.submit("b.pdf", b"b")
        reconciler.run_once()
        reconciler.run_once()
        self.assertEqual(first.submitted, 1)
        self.assertEqual(second.submitted, 1)

    def test_timeout_fails_a_held_task(self) -> None:
        self.engine.hold = True
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.task_timeout_seconds = 1
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        task.started_at = utcnow() - timedelta(seconds=5)
        self.store.update_task(task)
        self.reconciler.run_once()
        payload = self.plane.status_payload(created["task_id"])
        assert payload is not None
        self.assertEqual(payload["task"]["status"], "failed")
        self.assertIn("timed out", payload["task"]["error_message"])

    def test_expired_results_drop_artifact_bytes(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        task.completed_at = utcnow() - timedelta(seconds=10)
        self.store.update_task(task)
        self.reconciler.result_expires_seconds = 1
        self.reconciler.run_once()
        payload = self.plane.status_payload(created["task_id"])
        assert payload is not None
        self.assertEqual(payload["task"]["error_message"], "result expired")
        self.assertEqual(payload["content_list"], [])
        self.assertEqual([path for path in self.tmp.rglob("*") if path.is_file()], [])

    def test_shared_source_stays_until_every_task_expires(self) -> None:
        first = self.plane.submit("one.pdf", b"%PDF-shared")
        second = self.plane.submit("two.pdf", b"%PDF-shared")
        self.reconciler.run_once()
        self.reconciler.run_once()
        self.reconciler.run_once()
        self.reconciler.run_once()
        older = self.store.get_task(first["task_id"])
        newer = self.store.get_task(second["task_id"])
        assert older is not None and newer is not None
        older.completed_at = utcnow() - timedelta(seconds=10)
        self.store.update_task(older)
        self.reconciler.result_expires_seconds = 1
        self.reconciler.run_once()
        self.assertIsNotNone(self.store.blob_key(older.blob_sha256))
        newer.completed_at = utcnow() - timedelta(seconds=10)
        self.store.update_task(newer)
        self.reconciler.run_once()
        self.assertIsNone(self.store.blob_key(older.blob_sha256))
        self.assertEqual([path for path in self.tmp.rglob("*") if path.is_file()], [])

    def test_abandoned_upload_is_removed(self) -> None:
        upload = self.plane.create_upload("a.pdf", 4, "application/pdf", None)
        self.plane.write_upload(upload.id, b"%PDF")
        upload.expires_at = utcnow() - timedelta(seconds=1)
        self.store.put_upload(upload)
        self.reconciler.run_once()
        stored = self.store.get_upload(upload.id)
        assert stored is not None
        self.assertEqual(stored.status, "expired")
        self.assertIsNone(stored.storage_key)
        self.assertEqual([path for path in self.tmp.rglob("*") if path.is_file()], [])

    def test_slots_are_per_upstream(self) -> None:
        first = FakeMinerU()
        second = FakeMinerU()
        first.base_url = "http://gpu0"
        second.base_url = "http://gpu1"
        first.hold = True
        second.hold = True
        reconciler = Reconciler(
            self.store,
            self.objects,
            first,
            max_inflight=4,
            max_attempts=3,
            mineru_pool=[first, second],
            slots=(2, 2),
        )
        created = [self.plane.submit(f"{index}.pdf", b"x") for index in range(5)]
        for _ in range(5):
            reconciler.run_once()
        self.assertEqual(first.submitted, 2)
        self.assertEqual(second.submitted, 2)
        waiting = [self.store.get_task(item["task_id"]) for item in created]
        self.assertEqual(sum(1 for task in waiting if task is not None and task.status == "accepted"), 1)

    def test_byte_budget_skips_a_large_task_for_a_smaller_one(self) -> None:
        self.reconciler.inflight_byte_limit = 10
        large = self.plane.submit("large.pdf", b"x" * 20)
        small = self.plane.submit("small.pdf", b"tiny")
        self.reconciler.run_once()
        self.assertEqual(self.engine.submitted, 1)
        large_row = self.store.get_task(large["task_id"])
        small_row = self.store.get_task(small["task_id"])
        assert large_row is not None and small_row is not None
        self.assertEqual(large_row.status, "accepted")
        self.assertEqual(small_row.status, "running")

    def test_oversized_task_runs_when_nothing_else_is_in_flight(self) -> None:
        self.reconciler.inflight_byte_limit = 5
        created = self.plane.submit("large.pdf", b"x" * 20)
        self.reconciler.run_once()
        row = self.store.get_task(created["task_id"])
        assert row is not None
        self.assertEqual(row.status, "running")

    def test_a_later_page_is_still_eligible(self) -> None:
        cpu = FakeMinerU()
        gpu = FakeMinerU()
        cpu.base_url = "http://cpu"
        gpu.base_url = "http://gpu"
        cpu.tier_names = ("flash", "basic")
        gpu.tier_names = ("flash", "basic", "standard", "advanced")
        cpu.hold = True
        catalog = TierCatalog([cpu, gpu])
        reconciler = Reconciler(
            self.store,
            self.objects,
            cpu,
            max_inflight=4,
            max_attempts=3,
            mineru_pool=[cpu, gpu],
            slots=(1, 0),
            tiers=catalog,
        )
        for index in range(200):
            self.plane.submit(f"s{index}.pdf", b"s", tier="standard")
        basic = self.plane.submit("basic.pdf", b"b", tier="basic")
        reconciler.run_once()
        self.assertEqual(cpu.submitted, 1)
        self.assertEqual(gpu.submitted, 0)
        started = self.store.get_task(basic["task_id"])
        assert started is not None
        self.assertEqual(started.status, "running")

    def test_standard_stays_off_the_cpu_upstream(self) -> None:
        cpu = FakeMinerU()
        gpu = FakeMinerU()
        cpu.base_url = "http://cpu"
        gpu.base_url = "http://gpu"
        cpu.tier_names = ("flash", "basic")
        gpu.tier_names = ("flash", "basic", "standard", "advanced")
        cpu.hold = True
        gpu.hold = True
        catalog = TierCatalog([cpu, gpu])
        reconciler = Reconciler(
            self.store,
            self.objects,
            cpu,
            max_inflight=4,
            max_attempts=3,
            mineru_pool=[cpu, gpu],
            slots=(1, 1),
            tiers=catalog,
        )
        first = self.plane.submit("one.pdf", b"a", tier="standard")
        second = self.plane.submit("two.pdf", b"b", tier="standard")
        reconciler.run_once()
        reconciler.run_once()
        self.assertEqual(cpu.submitted, 0)
        self.assertEqual(gpu.submitted, 1)
        waiting = self.store.get_task(second["task_id"])
        assert waiting is not None
        self.assertEqual(waiting.status, "accepted")
        started = self.store.get_task(first["task_id"])
        assert started is not None
        self.assertEqual(started.upstream_base_url, "http://gpu")

    def test_transition_log_omits_document_text(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF")
        with self.assertLogs("thinkparse.reconcile", level="INFO") as captured:
            self.reconciler.run_once()
            self.reconciler.run_once()
        text = "\n".join(captured.output)
        self.assertIn(created["task_id"], text)
        self.assertNotIn("Hello", text)
        finished = self.store.get_task(created["task_id"])
        assert finished is not None
        self.assertEqual(finished.status, "completed")
        self.assertIsNotNone(finished.page_count)
        self.assertIsNotNone(finished.upstream_finished_at)
        job = self.plane.native_job(created["task_id"])
        assert job is not None
        self.assertGreaterEqual(job["timing"]["queue_ms"], 0)
        self.assertGreaterEqual(job["timing"]["parse_ms"], 0)
        self.assertGreaterEqual(job["timing"]["project_ms"], 0)
        self.assertEqual(job["pages"], finished.page_count)

    def test_cancel_releases_mineru_scratch(self) -> None:
        self.engine.hold = True
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        task.cancel_requested = True
        self.store.update_task(task)
        self.reconciler.run_once()
        self.assertEqual(self.engine.cancelled, ["job_1"])
        self.assertEqual(self.engine.released, ["file_src", "file_zip", "md", "mid"])

    def test_upload_without_a_task_drops_the_blob_after_an_hour(self) -> None:
        upload = self.plane.create_upload("a.pdf", 4, "application/pdf", None)
        self.plane.write_upload(upload.id, b"%PDF")
        completed = self.plane.complete_upload(upload.id, None)
        assert completed.sha256 is not None
        key, size, _created = self.store._blobs[completed.sha256]
        self.store._blobs[completed.sha256] = (key, size, utcnow() - timedelta(hours=2))
        self.reconciler.run_once()
        self.assertIsNone(self.store.blob_key(completed.sha256))
        self.assertEqual([path for path in self.tmp.rglob("*") if path.is_file()], [])

    def test_fresh_upload_without_a_task_keeps_the_blob(self) -> None:
        upload = self.plane.create_upload("a.pdf", 4, "application/pdf", None)
        self.plane.write_upload(upload.id, b"%PDF")
        completed = self.plane.complete_upload(upload.id, None)
        self.reconciler.run_once()
        assert completed.sha256 is not None
        self.assertIsNotNone(self.store.blob_key(completed.sha256))

    def test_old_blob_stays_while_a_task_references_it(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF")
        task = self.store.get_task(created["task_id"])
        assert task is not None
        key, size, _created = self.store._blobs[task.blob_sha256]
        self.store._blobs[task.blob_sha256] = (key, size, utcnow() - timedelta(hours=2))
        self.reconciler.run_once()
        self.assertIsNotNone(self.store.blob_key(task.blob_sha256))

    def test_purge_removes_orphan_objects_under_the_task(self) -> None:
        created = self.plane.submit("paper.pdf", b"%PDF")
        self.reconciler.run_once()
        self.reconciler.run_once()
        task = self.store.get_task(created["task_id"])
        assert task is not None
        self.objects.put(f"artifacts/{task.id}/stray.bin", b"orphan")
        task.completed_at = utcnow() - timedelta(seconds=10)
        self.store.update_task(task)
        self.reconciler.result_expires_seconds = 1
        self.reconciler.run_once()
        self.assertEqual([path for path in self.tmp.rglob("*") if path.is_file()], [])


if __name__ == "__main__":
    unittest.main()
