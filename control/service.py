"""Submit and read legacy task records."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from control.config import Settings
from control.models import (
    ACCEPTED,
    CANCELLED,
    COMPLETED,
    DISPATCHING,
    FAILED,
    PROJECTING,
    RUNNING,
    ArtifactRecord,
    FileRecord,
    TaskRecord,
    UploadRecord,
    public_status,
)
from control.objects import CapacityExceeded, ObjectStore
from control.options import ParseOptions, RequestRejected, resolve_options
from control.store import TaskStore, utcnow
from control.tiers import StaticTiers, TierCatalog


class ControlPlane:
    def __init__(
        self,
        store: TaskStore,
        objects: ObjectStore,
        settings: Settings,
        tiers: TierCatalog | StaticTiers | None = None,
    ) -> None:
        self.store = store
        self.objects = objects
        self.settings = settings
        self.tiers = tiers or StaticTiers(settings.accepted_tiers)

    def submit(
        self,
        filename: str,
        data: bytes,
        *,
        backend: str | None = None,
        method: str | None = None,
        lang: str | None = None,
        formula_enable: object = None,
        table_enable: object = None,
        tier: str | None = None,
        priority: int = 0,
        allow_native_tiers: bool = False,
        batch_id: str | None = None,
    ) -> dict[str, Any]:
        batch = _parse_batch_id(batch_id)
        if len(data) > self.settings.max_file_bytes:
            limit = self.settings.max_file_bytes / (1024 * 1024)
            raise RequestRejected(413, f"File too large. Maximum size: {limit:.0f}MB")
        try:
            self.objects.ensure_capacity(len(data), self.settings.free_min_bytes)
        except CapacityExceeded as exc:
            raise RequestRejected(507, str(exc)) from exc
        options = resolve_options(
            filename=filename,
            backend=backend,
            method=method,
            lang=lang,
            formula_enable=formula_enable,
            table_enable=table_enable,
            tier=tier,
            legacy_allow_flash=self.settings.legacy_allow_flash,
            docling_enabled=bool(self.settings.docling_base_url),
            allow_native_tiers=allow_native_tiers,
            accepted_tiers=self.tiers.available(),
        )
        sha = hashlib.sha256(data).hexdigest()
        key = f"blobs/{sha}"
        if self.store.blob_key(sha) is None:
            self.objects.put(key, data)
            self.store.put_blob(sha, len(data), key)
        task = TaskRecord(
            id=str(uuid.uuid4()),
            blob_sha256=sha,
            file_name=filename,
            legacy_options=_options_dict(options, priority),
            tier=options.tier,
            ocr_mode=options.ocr_mode,
            engine=options.engine,
            status=ACCEPTED,
            error_message=None,
            created_at=utcnow(),
            started_at=None,
            completed_at=None,
            attempt=0,
            upstream_job_id=None,
            cancel_requested=False,
            legacy_backend=options.legacy_backend,
            warnings=list(options.warnings),
            batch_id=batch,
            priority=normalize_priority(priority),
        )
        self.store.create_task(task)
        return {
            "success": True,
            "task_id": task.id,
            "status": "pending",
            "message": "Task submitted successfully",
            "file_name": filename,
            "created_at": task.created_at.isoformat(),
            "backend": task.legacy_backend,
            "priority": task.priority,
        }

    def status_payload(self, task_id: str) -> dict[str, Any] | None:
        task = self.store.get_task(task_id)
        if task is None:
            return None
        body: dict[str, Any] = {
            "success": True,
            "task": {
                "task_id": task.id,
                "status": public_status(task.status),
                "created_at": task.created_at.isoformat(),
                "started_at": None if task.started_at is None else task.started_at.isoformat(),
                "completed_at": None if task.completed_at is None else task.completed_at.isoformat(),
                "file_name": task.file_name,
                "backend": task.legacy_backend,
                "result_path": None,
                "error_message": task.error_message,
                "retry_count": task.attempt,
            },
            "timestamp": utcnow().isoformat(),
        }
        if task.status != COMPLETED:
            return body
        if task.purged_at is not None:
            body["task"]["error_message"] = "result expired"
            body["markdown_content"] = ""
            body["content_list"] = []
            body["middle_json"] = {"pdf_info": []}
            body["images"] = []
            body["data"] = {"content": "", "content_list": [], "images": []}
            return body
        artifacts = self.store.artifacts(task.id)
        markdown = _text_artifact(self.objects, artifacts, "markdown")
        content_list = _json_artifact(self.objects, artifacts, "content_list_v1")
        middle = _json_artifact(self.objects, artifacts, "middle_pdf_info")
        if not isinstance(content_list, list) or not isinstance(middle, dict):
            body["task"]["status"] = "failed"
            body["task"]["error_message"] = "completed task is missing legacy artifacts"
            return body
        images = _legacy_images(self.objects, artifacts)
        body["markdown_content"] = markdown
        body["content_list"] = content_list
        body["middle_json"] = middle
        body["images"] = images
        body["data"] = {"content": markdown, "content_list": content_list, "images": images}
        document = _json_artifact(self.objects, artifacts, "docling_document")
        if isinstance(document, dict):
            body["docling_document"] = document
        return body

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        task = self.store.get_task(task_id)
        if task is None:
            return None
        if task.status != COMPLETED:
            task.cancel_requested = True
            if task.status in {ACCEPTED, DISPATCHING} and not task.upstream_job_id:
                task.status = CANCELLED
                task.completed_at = utcnow()
            self.store.update_task(task)
        return {
            "success": True,
            "status": "cancel_requested",
            "message": f"Cancellation requested for task {task_id}.",
            "task_id": task_id,
            "timestamp": utcnow().isoformat(),
        }

    def queue_stats(self) -> dict[str, Any]:
        counts = self.store.counts()
        pending = counts.get(ACCEPTED, 0) + counts.get(DISPATCHING, 0)
        processing = counts.get(RUNNING, 0) + counts.get(PROJECTING, 0)
        return {
            "success": True,
            "stats": {
                "pending": pending,
                "queued": counts.get(ACCEPTED, 0),
                "reserved": counts.get(DISPATCHING, 0),
                "processing": processing,
                "completed": counts.get(COMPLETED, 0),
                "failed": counts.get(FAILED, 0),
                "cancelled": counts.get(CANCELLED, 0),
                "total_active": processing,
                "total_scheduled": pending,
            },
            "workers": {"active_workers": 0, "total_workers": 0},
            "timestamp": utcnow().isoformat(),
            "note": "Counts come from the ThinkParse task store.",
        }

    def queue_tasks(self, status: str | None, limit: int) -> dict[str, Any]:
        wanted = _statuses_for_filter(status)
        rows = self.store.list_tasks(wanted, limit)
        tasks = [
            {
                "task_id": task.id,
                "status": public_status(task.status),
                "file_name": task.file_name,
                "backend": task.legacy_backend,
                "created_at": task.created_at.isoformat(),
                "started_at": None if task.started_at is None else task.started_at.isoformat(),
                "priority": task.priority,
            }
            for task in rows
        ]
        return {
            "success": True,
            "tasks": tasks,
            "count": len(tasks),
            "limit": limit,
            "status_filter": status,
            "timestamp": utcnow().isoformat(),
        }

    def create_upload(self, filename: str, byte_size: int, mime_type: str, sha256: str | None) -> UploadRecord:
        if byte_size > self.settings.max_file_bytes:
            raise RequestRejected(413, "upload exceeds the size limit")
        if sha256 and self.store.blob_key(sha256):
            existing = self._file_for_blob(sha256, filename, byte_size, mime_type)
            upload = UploadRecord(
                id="upload_" + secrets.token_hex(8),
                filename=filename,
                byte_size=byte_size,
                mime_type=mime_type,
                status="completed",
                created_at=utcnow(),
                expires_at=utcnow(),
                sha256=sha256,
                storage_key=self.store.blob_key(sha256),
                file_id=existing.id,
            )
            self.store.put_upload(upload)
            return upload
        upload_id = "upload_" + secrets.token_hex(8)
        upload = UploadRecord(
            id=upload_id,
            filename=filename,
            byte_size=byte_size,
            mime_type=mime_type,
            status="pending",
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(hours=1),
            sha256=sha256,
            storage_key=f"uploads/{upload_id}",
            file_id=None,
        )
        self.store.put_upload(upload)
        return upload

    def write_upload(self, upload_id: str, data: bytes) -> None:
        upload = self.store.get_upload(upload_id)
        if upload is None:
            raise RequestRejected(404, "upload not found")
        if upload.status != "pending":
            raise RequestRejected(409, "upload is not pending")
        if len(data) != upload.byte_size:
            raise RequestRejected(400, "upload byte count does not match")
        if upload.storage_key is None:
            raise RequestRejected(409, "upload has no storage key")
        self.objects.put(upload.storage_key, data)

    def complete_upload(self, upload_id: str, sha256: str | None) -> UploadRecord:
        upload = self.store.get_upload(upload_id)
        if upload is None:
            raise RequestRejected(404, "upload not found")
        if upload.status == "completed" and upload.file_id:
            return upload
        if upload.storage_key is None:
            raise RequestRejected(409, "upload has no content")
        try:
            data = self.objects.get(upload.storage_key)
        except OSError as exc:
            raise RequestRejected(400, "upload content is missing") from exc
        digest = hashlib.sha256(data).hexdigest()
        if sha256 and sha256 != digest:
            raise RequestRejected(400, "sha256sum does not match the uploaded bytes")
        staging = upload.storage_key
        key = f"blobs/{digest}"
        if self.store.blob_key(digest) is None:
            self.objects.put(key, data)
            self.store.put_blob(digest, len(data), key)
        if staging and staging.startswith("uploads/") and staging != key:
            self.objects.delete(staging)
        record = self._file_for_blob(digest, upload.filename, len(data), upload.mime_type)
        upload.status = "completed"
        upload.sha256 = digest
        upload.file_id = record.id
        upload.storage_key = key
        self.store.put_upload(upload)
        return upload

    def create_native_job(
        self,
        file_id: str,
        tier: str | None,
        ocr_mode: str,
        batch_id: str | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        _parse_batch_id(batch_id)
        record = self.store.get_file(file_id)
        if record is None or not record.storage_key:
            raise RequestRejected(404, "file not found")
        data = self.objects.get(record.storage_key)
        created = self.submit(
            record.filename,
            data,
            method=ocr_mode,
            tier=tier,
            allow_native_tiers=True,
            batch_id=batch_id,
            priority=priority,
        )
        task = self.store.get_task(created["task_id"])
        if task is None:
            raise RequestRejected(500, "task disappeared after submit")
        return self.native_job(task.id) or {}

    def native_jobs(self, status: str | None, limit: int) -> dict[str, Any]:
        wanted = _statuses_for_native_filter(status)
        rows = self.store.list_tasks(wanted, limit)
        jobs = [self.native_job(task.id) for task in rows]
        return {"object": "list", "data": [job for job in jobs if job is not None]}

    def native_job(self, task_id: str) -> dict[str, Any] | None:
        task = self.store.get_task(task_id)
        if task is None:
            return None
        mapped = {
            "pending": "queued",
            "processing": "running",
            "completed": "completed",
            "failed": "failed",
            "cancelled": "canceled",
        }[public_status(task.status)]
        outputs: dict[str, Any] = {}
        image_files: list[dict[str, Any]] = []
        if task.status == COMPLETED:
            for record in self.store.files_for_task(task.id):
                if record.purpose == "image":
                    image_files.append(
                        {"file_id": record.id, "filename": record.filename, "bytes": record.byte_size}
                    )
                elif record.purpose in {"markdown", "middle_json", "docling_document"}:
                    outputs[record.purpose] = {"file_id": record.id, "bytes": record.byte_size}
            if image_files:
                outputs["images"] = image_files
        file_status = {"queued": "queued", "running": "running", "completed": "completed", "failed": "failed", "canceled": "failed"}[
            mapped
        ]
        return {
            "job_id": task.id,
            "status": mapped,
            "created_at": task.created_at.isoformat(),
            "tier": task.tier,
            "attempt": task.attempt,
            "pages": task.page_count,
            "batch_id": task.batch_id,
            "priority": task.priority,
            "timing": {
                "queue_ms": _millis(task.created_at, task.started_at),
                "parse_ms": _millis(task.started_at, task.upstream_finished_at),
                "project_ms": _millis(task.upstream_finished_at, task.completed_at),
            },
            "files": [
                {
                    "name": task.file_name,
                    "status": file_status,
                    "output_files": outputs or None,
                    "error": None if not task.error_message else {"message": task.error_message},
                }
            ],
            "links": {"self": f"/api/v2/jobs/{task.id}", "cancel": f"/api/v2/jobs/{task.id}"},
        }

    def fleet_stats(self, window_seconds: int, views: list[dict[str, Any]]) -> dict[str, Any]:
        since = utcnow() - timedelta(seconds=window_seconds)
        snap = self.store.operations_snapshot(since)
        counts = snap["counts"]
        upstreams: list[dict[str, Any]] = []
        used = 0
        total = 0
        for view in views:
            url = str(view["base_url"])
            inflight = int(snap["inflight_by_url"].get(url, 0))
            slots = int(view["slots"])
            used += inflight
            total += slots
            upstreams.append(
                {
                    "healthy": bool(view["healthy"]),
                    "tiers": list(view["tiers"]),
                    "inflight": inflight,
                    "slots": slots,
                    "inflight_bytes": int(snap["inflight_bytes_by_url"].get(url, 0)),
                }
            )
        oldest = snap["oldest_queued_at"]
        heartbeat = self.store.get_meta("reconciler_heartbeat")
        age = None if heartbeat is None else max(0, int((utcnow() - heartbeat[1]).total_seconds()))
        return {
            "object": "stats",
            "queue": {
                "accepted": counts.get(ACCEPTED, 0),
                "dispatching": counts.get(DISPATCHING, 0),
                "running": counts.get(RUNNING, 0),
                "projecting": counts.get(PROJECTING, 0),
            },
            "slots": {"used": used, "total": total},
            "inflight_bytes": snap["inflight_bytes"],
            "inflight_byte_limit": self.settings.inflight_byte_limit,
            "oldest_queued_seconds": None if oldest is None else max(0, int((utcnow() - oldest).total_seconds())),
            "window_seconds": window_seconds,
            "completed_in_window": snap["completed_in_window"],
            "failed_in_window": snap["failed_in_window"],
            "pages_in_window": snap["pages_in_window"],
            "by_tier": snap["by_tier"],
            "upstreams": upstreams,
            "failures": snap["failures"],
            "reconciler_heartbeat_age_seconds": age,
        }

    def batch_summary(self, batch_id: str) -> dict[str, Any] | None:
        rows = self.store.tasks_for_batch(batch_id)
        if not rows:
            return None
        queued = running = completed = failed = canceled = 0
        oldest: datetime | None = None
        pages = 0
        for task in rows:
            public = public_status(task.status)
            if public == "pending":
                queued += 1
                if oldest is None or task.created_at < oldest:
                    oldest = task.created_at
            elif public == "processing":
                running += 1
            elif public == "completed":
                completed += 1
                pages += task.page_count or 0
            elif public == "failed":
                failed += 1
            else:
                canceled += 1
        return {
            "batch_id": batch_id,
            "total": len(rows),
            "queued": queued,
            "running": running,
            "completed": completed,
            "failed": failed,
            "canceled": canceled,
            "oldest_queued_seconds": None if oldest is None else max(0, int((utcnow() - oldest).total_seconds())),
            "pages_completed": pages,
        }

    def batch_jobs(self, batch_id: str, status: str | None, limit: int) -> dict[str, Any] | None:
        rows = self.store.tasks_for_batch(batch_id)
        if not rows:
            return None
        wanted = _statuses_for_native_filter(status)
        if wanted is not None:
            rows = [task for task in rows if task.status in wanted]
        jobs = [self.native_job(task.id) for task in rows[:limit]]
        return {"object": "list", "data": [job for job in jobs if job is not None]}

    def cancel_batch(self, batch_id: str) -> dict[str, Any] | None:
        rows = self.store.tasks_for_batch(batch_id)
        if not rows:
            return None
        canceled = 0
        for task in rows:
            if task.status in {COMPLETED, FAILED, CANCELLED}:
                continue
            self.cancel(task.id)
            canceled += 1
        return {"batch_id": batch_id, "canceled": canceled}

    def read_file(self, file_id: str) -> tuple[bytes, str]:
        record = self.store.get_file(file_id)
        if record is None:
            raise RequestRejected(404, "file not found")
        return self.objects.get(record.storage_key), record.mime_type or "application/octet-stream"

    def _file_for_blob(self, sha256: str, filename: str, byte_size: int, mime_type: str) -> FileRecord:
        existing_key = self.store.blob_key(sha256)
        record = FileRecord(
            id="file_" + secrets.token_hex(8),
            filename=filename,
            byte_size=byte_size,
            storage_key=existing_key or f"blobs/{sha256}",
            purpose="parse",
            created_at=utcnow(),
            sha256=sha256,
            mime_type=mime_type,
            task_id=None,
        )
        self.store.put_file(record)
        return record


_BATCH_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _parse_batch_id(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if _BATCH_ID.fullmatch(value) is None:
        raise RequestRejected(400, "batch_id must be 1-64 characters of letters, digits, hyphen, or underscore")
    return value


def _millis(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def normalize_priority(priority: int) -> int:
    if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0 or priority > 9:
        raise RequestRejected(400, "priority must be an integer from 0 to 9")
    return priority


def _options_dict(options: ParseOptions, priority: int) -> dict[str, Any]:
    return {
        "lang": options.lang,
        "formula_enable": options.formula_enable,
        "table_enable": options.table_enable,
        "priority": priority,
        "warnings": list(options.warnings),
    }


def _statuses_for_filter(status: str | None) -> set[str] | None:
    if status in {None, ""}:
        return None
    if status == "pending":
        return {ACCEPTED, DISPATCHING}
    if status == "processing":
        return {RUNNING, PROJECTING}
    if status == "completed":
        return {COMPLETED}
    if status == "failed":
        return {FAILED}
    if status == "cancelled":
        return {CANCELLED}
    return set()


def _statuses_for_native_filter(status: str | None) -> set[str] | None:
    native_to_public = {"queued": "pending", "running": "processing", "canceled": "cancelled"}
    return _statuses_for_filter(native_to_public.get(status or "", status))


def _artifact(artifacts: list[ArtifactRecord], kind: str) -> ArtifactRecord | None:
    for item in artifacts:
        if item.kind == kind and item.storage_key:
            return item
    return None


def _legacy_images(objects: ObjectStore, artifacts: list[ArtifactRecord]) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    for item in artifacts:
        if item.kind != "image" or not item.filename or not item.storage_key:
            continue
        data = objects.get(item.storage_key)
        mime = _image_mime(item.filename)
        images.append(
            {
                "filename": item.filename,
                "mime_type": mime,
                "size_bytes": len(data),
                "data_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
            }
        )
    return images


def _image_mime(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".gif"):
        return "image/gif"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


def _text_artifact(objects: ObjectStore, artifacts: list[ArtifactRecord], kind: str) -> str:
    item = _artifact(artifacts, kind)
    if item is None:
        return ""
    return objects.get(item.storage_key).decode("utf-8")


def _json_artifact(objects: ObjectStore, artifacts: list[ArtifactRecord], kind: str) -> Any:
    item = _artifact(artifacts, kind)
    if item is None:
        return None
    return json.loads(objects.get(item.storage_key).decode("utf-8"))
