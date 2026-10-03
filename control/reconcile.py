"""Drive accepted tasks through MinerU or Docling and the legacy projector."""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Protocol

from control.capacity import Pending, Slot, byte_hold_priority, choose_assignment
from control.mineru import NativeArtifacts, UpstreamNotFound, UpstreamPoll, UpstreamRejected, UpstreamUnavailable
from control.tiers import TierCatalog
from control.models import (
    CANCELLED,
    COMPLETED,
    FAILED,
    PROJECTING,
    RUNNING,
    ArtifactRecord,
    FileRecord,
    TaskRecord,
)
from control.objects import ObjectStore
from control.project import ProjectionError, project_docling, project_mineru
from control.store import TaskStore, utcnow

log = logging.getLogger("thinkparse.reconcile")


class ParseEngine(Protocol):
    def submit(self, data: bytes, filename: str, sha256: str, tier: str, ocr_mode: str) -> str: ...

    def poll(self, job_id: str) -> UpstreamPoll: ...

    def fetch(self, poll: UpstreamPoll) -> NativeArtifacts: ...

    def cancel(self, job_id: str) -> None: ...


class Reconciler:
    def __init__(
        self,
        store: TaskStore,
        objects: ObjectStore,
        engine: ParseEngine,
        *,
        max_inflight: int,
        max_attempts: int,
        docling: ParseEngine | None = None,
        mineru_pool: list[ParseEngine] | None = None,
        task_timeout_seconds: int = 0,
        result_expires_seconds: int = 0,
        slots: tuple[int, ...] | None = None,
        inflight_byte_limit: int = 1 << 30,
        tiers: TierCatalog | None = None,
    ) -> None:
        self.store = store
        self.objects = objects
        self.engine = engine
        self.docling = docling
        self.mineru_pool = mineru_pool or [engine]
        self.max_inflight = max_inflight
        self.max_attempts = max_attempts
        self.task_timeout_seconds = task_timeout_seconds
        self.result_expires_seconds = result_expires_seconds
        self.slots = slots if slots is not None else tuple(max_inflight for _ in self.mineru_pool)
        self.inflight_byte_limit = inflight_byte_limit
        self.tiers = tiers
        self.last_projection_error: str | None = None

    def run_once(self) -> bool:
        self.store.set_meta("reconciler_heartbeat", utcnow().isoformat())
        self.purge_expired()
        worked = False
        for task in self.store.list_inflight():
            self._progress(task)
            worked = True
        claimed = self._claim()
        if claimed is None:
            return worked
        self._dispatch(claimed)
        return True

    def purge_expired(self) -> None:
        self._purge_uploads()
        self._purge_unreferenced_blobs()
        if self.result_expires_seconds <= 0:
            return
        cutoff = utcnow() - timedelta(seconds=self.result_expires_seconds)
        for task in self.store.list_expired(cutoff, 20):
            self.objects.delete_prefix(f"artifacts/{task.id}/")
            self.store.delete_task_files(task.id)
            self.store.replace_artifacts(task.id, [])
            task.purged_at = utcnow()
            self.store.update_task(task)
            released = self.store.release_blob(task.blob_sha256)
            if released:
                self.objects.delete(released)
                self.store.delete_files_with_key(released)

    def _purge_unreferenced_blobs(self) -> None:
        cutoff = utcnow() - timedelta(hours=1)
        for sha256, _key in self.store.list_unreferenced_blobs(cutoff, 20):
            released = self.store.release_blob(sha256)
            if released:
                self.objects.delete(released)
                self.store.delete_files_with_key(released)

    def _purge_uploads(self) -> None:
        for upload in self.store.list_expired_uploads(utcnow(), 20):
            if upload.storage_key and upload.storage_key.startswith("uploads/"):
                self.objects.delete(upload.storage_key)
            upload.status = "expired"
            upload.storage_key = None
            self.store.put_upload(upload)

    def _release_engine_files(self, client: ParseEngine, poll: UpstreamPoll) -> None:
        release = getattr(client, "release_files", None)
        if release is None:
            return
        try:
            release(poll.engine_file_ids())
        except (UpstreamUnavailable, UpstreamNotFound, UpstreamRejected):
            log.info("upstream scratch files were not released")

    def _discard_native(self, task: TaskRecord) -> None:
        key = f"artifacts/{task.id}/native.json"
        raw: object = None
        try:
            raw = json.loads(self.objects.get(key))
        except (OSError, json.JSONDecodeError, ValueError):
            raw = None
        if isinstance(raw, dict):
            stored = raw.get("image_keys")
            if isinstance(stored, dict):
                for image_key in stored.values():
                    if isinstance(image_key, str) and image_key:
                        self.objects.delete(image_key)
        self.objects.delete(key)

    def _claim(self) -> TaskRecord | None:
        cancelled = self.store.claim_cancelled()
        if cancelled is not None:
            return cancelled
        inflight = self.store.list_inflight()
        counts: dict[str, int] = {}
        inflight_bytes = 0
        for running in inflight:
            url = running.upstream_base_url or ""
            counts[url] = counts.get(url, 0) + 1
            inflight_bytes += self.store.blob_size(running.blob_sha256)
        slots = self._slot_states(counts)
        discovered = self._tiers_discovered()
        offset = 0
        fallback: tuple[str, str] | None = None
        hold: int | None = None
        while True:
            pending_rows = self.store.list_pending(200, offset=offset)
            if not pending_rows:
                break
            pending = [_pending(task, size) for task, size in pending_rows]
            if hold is not None:
                pending = [job for job in pending if job.priority == hold]
                if not pending:
                    break
            choice = choose_assignment(
                pending,
                slots,
                inflight_bytes,
                self.inflight_byte_limit,
                discovered=discovered,
                admit_oversized=False,
            )
            if choice is not None:
                return self.store.claim_id(choice[0])
            if fallback is None and inflight_bytes == 0:
                fallback = choose_assignment(
                    pending,
                    slots,
                    inflight_bytes,
                    self.inflight_byte_limit,
                    discovered=discovered,
                    admit_oversized=True,
                )
            detected = byte_hold_priority(
                pending,
                slots,
                inflight_bytes,
                self.inflight_byte_limit,
                discovered=discovered,
            )
            if detected is not None:
                hold = detected
            elif hold is not None:
                break
            offset += len(pending_rows)
            if len(pending_rows) < 200:
                break
        if fallback is None:
            return None
        return self.store.claim_id(fallback[0])

    def _slot_states(self, counts: dict[str, int]) -> list[Slot]:
        reported: list[tuple[str, ...] | None] = []
        if self.tiers is not None:
            reported = self.tiers.reported()
        states: list[Slot] = []
        for index, client in enumerate(self.mineru_pool):
            url = getattr(client, "base_url", "")
            limit = self.slots[index] if index < len(self.slots) else self.max_inflight
            tiers = reported[index] if index < len(reported) else None
            states.append(Slot(base_url=url, slots=limit, inflight=counts.get(url, 0), tiers=tiers))
        return states

    def _tiers_discovered(self) -> bool:
        return False if self.tiers is None else self.tiers.discovered()

    def _dispatch(self, task: TaskRecord) -> None:
        if task.cancel_requested:
            self._cancel(task)
            return
        blob_key = self.store.blob_key(task.blob_sha256)
        if blob_key is None:
            self._fail(task, "source blob is missing")
            return
        try:
            selected = self._select(task)
            if selected is None:
                before = task.status
                task.status = "accepted"
                self.store.update_task(task)
                self._log(task, before)
                return
            client, base = selected
            data = self.objects.get(blob_key)
            job_id = client.submit(data, task.file_name, task.blob_sha256, task.tier, task.ocr_mode)
        except UpstreamRejected as exc:
            self._fail(task, f"upstream rejected the job: {exc}")
            return
        except UpstreamUnavailable as exc:
            self._retry(task, f"upstream unavailable: {exc}")
            return
        before = task.status
        task.upstream_job_id = job_id
        task.upstream_base_url = base
        task.status = RUNNING
        task.started_at = task.started_at or utcnow()
        task.error_message = None
        self.store.update_task(task)
        self._log(task, before)

    def _progress(self, task: TaskRecord) -> None:
        if task.cancel_requested:
            self._cancel(task)
            return
        if self._timed_out(task):
            self._cancel(task)
            current = self.store.get_task(task.id) or task
            if current.status != CANCELLED:
                self._fail(current, "task timed out")
            else:
                current.status = FAILED
                current.error_message = "task timed out"
                current.completed_at = utcnow()
                self.store.update_task(current)
            return
        if task.status == PROJECTING:
            cached = self._load_cache(task)
            if cached is not None:
                self._project_native(task, cached)
                return
        if not task.upstream_job_id:
            return
        try:
            client, _base = self._select(task)
            poll = client.poll(task.upstream_job_id)
        except UpstreamNotFound:
            self._retry(task, "upstream restarted and dropped the job id")
            return
        except UpstreamRejected as exc:
            self._fail(task, f"upstream rejected the poll: {exc}")
            return
        except UpstreamUnavailable as exc:
            self._retry(task, f"upstream unavailable: {exc}")
            return
        if poll.status in {"queued", "running", "pending"}:
            if task.status != RUNNING:
                before = task.status
                task.status = RUNNING
                self.store.update_task(task)
                self._log(task, before)
            return
        if poll.status in {"completed", "success"}:
            self._finish_parse(task, poll)
            return
        if poll.status in {"canceled", "cancelled"}:
            before = task.status
            task.status = CANCELLED
            task.completed_at = utcnow()
            task.error_message = None
            self.store.update_task(task)
            self._log(task, before)
            self._release_engine_files(client, poll)
            return
        self._fail(task, poll.error_message or f"upstream status {poll.status}")
        self._release_engine_files(client, poll)

    def _finish_parse(self, task: TaskRecord, poll: UpstreamPoll) -> None:
        client: ParseEngine | None = None
        try:
            client, _base = self._select(task)
            native = client.fetch(poll)
        except UpstreamNotFound:
            self._retry(task, "upstream restarted while artifacts were downloading")
            return
        except UpstreamRejected as exc:
            self._fail(task, f"upstream rejected the download: {exc}")
            if client is not None:
                self._release_engine_files(client, poll)
            return
        except UpstreamUnavailable as exc:
            self._retry(task, f"upstream unavailable: {exc}")
            return
        self._store_cache(task, native)
        self._release_engine_files(client, poll)
        before = task.status
        task.upstream_finished_at = task.upstream_finished_at or utcnow()
        task.status = PROJECTING
        self.store.update_task(task)
        self._log(task, before)
        self._project_native(task, native)

    def _project_native(self, task: TaskRecord, native: NativeArtifacts) -> None:
        try:
            if task.engine == "docling":
                projection = project_docling(markdown=native.markdown, document=native.document)
            else:
                projection = project_mineru(
                    markdown=native.markdown,
                    middle=native.middle,
                    content_list=native.content_list,
                )
                missing = [name for name in projection.image_names if name not in native.images]
                if missing:
                    raise ProjectionError("result is missing image bytes: " + ", ".join(missing))
        except (ProjectionError, json.JSONDecodeError, UnicodeError, ValueError) as exc:
            self.last_projection_error = str(exc)
            self._fail(task, f"projection failed: {exc}")
            return
        self._write_projection(task, projection, native.images)
        before = task.status
        pages = projection.middle_pdf_info.get("pdf_info") if isinstance(projection.middle_pdf_info, dict) else None
        if isinstance(pages, list):
            task.page_count = len(pages)
        task.status = COMPLETED
        task.completed_at = utcnow()
        task.error_message = None
        self.store.update_task(task)
        self._log(task, before)

    def _store_cache(self, task: TaskRecord, native: NativeArtifacts) -> None:
        image_keys: dict[str, str] = {}
        for name, data in native.images.items():
            key = f"artifacts/{task.id}/source-images/{name}"
            self.objects.put(key, data)
            image_keys[name] = key
        payload = {
            "markdown": native.markdown,
            "middle": native.middle,
            "content_list": native.content_list,
            "document": native.document,
            "image_keys": image_keys,
        }
        self.objects.put(
            f"artifacts/{task.id}/native.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )

    def _load_cache(self, task: TaskRecord) -> NativeArtifacts | None:
        try:
            raw = json.loads(self.objects.get(f"artifacts/{task.id}/native.json"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        if not isinstance(raw, dict):
            return None
        images: dict[str, bytes] = {}
        stored = raw.get("image_keys")
        if isinstance(stored, dict):
            for name, key in stored.items():
                if isinstance(name, str) and isinstance(key, str):
                    try:
                        images[name] = self.objects.get(key)
                    except OSError:
                        return None
        return NativeArtifacts(
            markdown=raw.get("markdown") or "",
            middle=raw.get("middle") if isinstance(raw.get("middle"), dict) else None,
            content_list=raw.get("content_list") if isinstance(raw.get("content_list"), list) else None,
            document=raw.get("document") if isinstance(raw.get("document"), dict) else None,
            images=images,
        )

    def _write_projection(self, task: TaskRecord, projection, images: dict[str, bytes]) -> None:
        artifacts: list[ArtifactRecord] = []
        markdown_bytes = projection.markdown.encode("utf-8")
        artifacts.append(self._put_bytes(task, "markdown", "result.md", markdown_bytes))
        self._register_output(task, "markdown", "result.md", f"artifacts/{task.id}/result.md", markdown_bytes)
        content_bytes = json.dumps(projection.content_list, ensure_ascii=False).encode("utf-8")
        artifacts.append(self._put_bytes(task, "content_list_v1", "content_list.json", content_bytes))
        middle_bytes = json.dumps(projection.middle_pdf_info, ensure_ascii=False).encode("utf-8")
        artifacts.append(self._put_bytes(task, "middle_pdf_info", "middle.json", middle_bytes))
        self._register_output(task, "middle_json", "middle.json", f"artifacts/{task.id}/middle.json", middle_bytes)
        if projection.native_middle is not None:
            artifacts.append(
                self._put_bytes(
                    task,
                    "middle_native",
                    "middle_native.json",
                    json.dumps(projection.native_middle, ensure_ascii=False).encode("utf-8"),
                )
            )
        if projection.docling_document is not None:
            document_bytes = json.dumps(projection.docling_document, ensure_ascii=False).encode("utf-8")
            artifacts.append(self._put_bytes(task, "docling_document", "docling_document.json", document_bytes))
            self._register_output(
                task,
                "docling_document",
                "docling_document.json",
                f"artifacts/{task.id}/docling_document.json",
                document_bytes,
            )
        for name in sorted(images):
            data = images[name]
            key = f"artifacts/{task.id}/images/{name}"
            self.objects.put(key, data)
            artifacts.append(
                ArtifactRecord(task_id=task.id, kind="image", storage_key=key, byte_size=len(data), filename=name)
            )
            self._register_output(task, "image", name, key, data)
        self.store.replace_artifacts(task.id, artifacts)

    def _register_output(self, task: TaskRecord, purpose: str, filename: str, key: str, data: bytes) -> None:
        self.store.put_file(
            FileRecord(
                id="file_" + secrets.token_hex(8),
                filename=filename,
                byte_size=len(data),
                storage_key=key,
                purpose=purpose,
                created_at=utcnow(),
                sha256=None,
                mime_type=_mime_type(filename),
                task_id=task.id,
            )
        )

    def _put_bytes(self, task: TaskRecord, kind: str, filename: str, data: bytes) -> ArtifactRecord:
        key = f"artifacts/{task.id}/{filename}"
        self.objects.put(key, data)
        return ArtifactRecord(task_id=task.id, kind=kind, storage_key=key, byte_size=len(data), filename=filename)

    def _select(self, task: TaskRecord) -> tuple[ParseEngine, str] | None:
        if task.engine == "docling":
            if self.docling is None:
                raise UpstreamUnavailable("Docling route is not configured")
            return self.docling, getattr(self.docling, "base_url", "docling")
        if task.upstream_base_url:
            for client in self.mineru_pool:
                if getattr(client, "base_url", "") == task.upstream_base_url:
                    return client, task.upstream_base_url
            raise UpstreamUnavailable("pinned MinerU is not in the configured pool")
        counts: dict[str, int] = {}
        for running in self.store.list_inflight():
            if running.id == task.id:
                continue
            url = running.upstream_base_url or ""
            counts[url] = counts.get(url, 0) + 1
        choice = choose_assignment(
            [_pending(task, self.store.blob_size(task.blob_sha256))],
            self._slot_states(counts),
            sum(self.store.blob_size(running.blob_sha256) for running in self.store.list_inflight() if running.id != task.id),
            self.inflight_byte_limit,
            discovered=self._tiers_discovered(),
        )
        if choice is None:
            return None
        for client in self.mineru_pool:
            if getattr(client, "base_url", "") == choice[1]:
                return client, choice[1]
        return None

    def _timed_out(self, task: TaskRecord) -> bool:
        if self.task_timeout_seconds <= 0 or task.started_at is None:
            return False
        if task.status not in {RUNNING, PROJECTING, "dispatching"}:
            return False
        return (utcnow() - task.started_at).total_seconds() > self.task_timeout_seconds

    def _cancel(self, task: TaskRecord) -> None:
        if task.upstream_job_id:
            client: ParseEngine | None = None
            poll: UpstreamPoll | None = None
            try:
                selected = self._select(task)
                if selected is None:
                    raise UpstreamUnavailable("pinned MinerU is not in the configured pool")
                client, _base = selected
                try:
                    poll = client.poll(task.upstream_job_id)
                except (UpstreamUnavailable, UpstreamNotFound, UpstreamRejected):
                    poll = None
                client.cancel(task.upstream_job_id)
            except UpstreamUnavailable:
                return
            except UpstreamRejected:
                pass
            if client is not None and poll is not None:
                self._release_engine_files(client, poll)
        before = task.status
        task.status = CANCELLED
        task.completed_at = utcnow()
        task.upstream_job_id = None
        task.error_message = None
        self.store.update_task(task)
        self._log(task, before)

    def _retry(self, task: TaskRecord, message: str) -> None:
        if task.cancel_requested:
            self._cancel(task)
            return
        task.attempt += 1
        task.upstream_job_id = None
        task.upstream_base_url = ""
        task.error_message = message
        if task.attempt >= self.max_attempts:
            self._fail(task, message)
            return
        delay = min(60, 2**task.attempt)
        before = task.status
        task.status = "accepted"
        task.next_attempt_at = utcnow() + timedelta(seconds=delay)
        self.store.update_task(task)
        self._log(task, before)

    def _fail(self, task: TaskRecord, message: str) -> None:
        self._discard_native(task)
        before = task.status
        task.status = FAILED
        task.error_message = message
        task.completed_at = utcnow()
        task.upstream_job_id = None
        self.store.update_task(task)
        self._log(task, before)

    def _log(self, task: TaskRecord, before: str) -> None:
        if task.status == before:
            return
        elapsed = _segment_ms(task)
        line = json.dumps(
            {
                "task_id": task.id,
                "batch_id": task.batch_id,
                "from": before,
                "to": task.status,
                "attempt": task.attempt,
                "tier": task.tier,
                "upstream": self._upstream_index(task),
                "elapsed_ms": elapsed,
                "error": None if not task.error_message else task.error_message[:200],
            },
            ensure_ascii=False,
        )
        log.info("%s", line)

    def _upstream_index(self, task: TaskRecord) -> int | None:
        if not task.upstream_base_url:
            return None
        for index, client in enumerate(self.mineru_pool):
            if getattr(client, "base_url", "") == task.upstream_base_url:
                return index
        return None


def _mime_type(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".md"):
        return "text/markdown"
    return "application/octet-stream"


def _pending(task: TaskRecord, size: int) -> Pending:
    return Pending(task.id, task.tier, task.engine, size, task.priority)


def _segment_ms(task: TaskRecord) -> int | None:
    if task.status == RUNNING:
        return _millis(task.created_at, task.started_at)
    if task.status == PROJECTING:
        return _millis(task.started_at, task.upstream_finished_at)
    if task.status == COMPLETED:
        return _millis(task.upstream_finished_at, task.completed_at)
    start = task.started_at or task.created_at
    return _millis(start, task.completed_at or utcnow())


def _millis(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))
