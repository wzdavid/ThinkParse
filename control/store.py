"""Task stores. Tests use memory. Production uses PostgreSQL."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from control.models import (
    CANCELLED,
    COMPLETED,
    FAILED,
    INFLIGHT,
    ArtifactRecord,
    FileRecord,
    TaskRecord,
    UploadRecord,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStore:
    def ping(self) -> bool:
        raise NotImplementedError

    def put_blob(self, sha256: str, byte_size: int, storage_key: str) -> None:
        raise NotImplementedError

    def blob_key(self, sha256: str) -> str | None:
        raise NotImplementedError

    def create_task(self, task: TaskRecord) -> None:
        raise NotImplementedError

    def get_task(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    def update_task(self, task: TaskRecord) -> None:
        raise NotImplementedError

    def inflight_count(self) -> int:
        raise NotImplementedError

    def claim_cancelled(self) -> TaskRecord | None:
        raise NotImplementedError

    def claim_id(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    def list_pending(self, limit: int, now: datetime | None = None, offset: int = 0) -> list[tuple[TaskRecord, int]]:
        raise NotImplementedError

    def blob_size(self, sha256: str) -> int:
        raise NotImplementedError

    def list_inflight(self) -> list[TaskRecord]:
        raise NotImplementedError

    def counts(self) -> dict[str, int]:
        raise NotImplementedError

    def list_tasks(self, statuses: set[str] | None, limit: int) -> list[TaskRecord]:
        raise NotImplementedError

    def tasks_for_batch(self, batch_id: str) -> list[TaskRecord]:
        raise NotImplementedError

    def set_meta(self, key: str, value: str) -> None:
        raise NotImplementedError

    def get_meta(self, key: str) -> tuple[str, datetime] | None:
        raise NotImplementedError

    def operations_snapshot(self, since: datetime) -> dict[str, Any]:
        raise NotImplementedError

    def add_artifact(self, artifact: ArtifactRecord) -> None:
        raise NotImplementedError

    def artifacts(self, task_id: str) -> list[ArtifactRecord]:
        raise NotImplementedError

    def replace_artifacts(self, task_id: str, artifacts: list[ArtifactRecord]) -> None:
        raise NotImplementedError

    def delete_task_files(self, task_id: str) -> None:
        raise NotImplementedError

    def delete_files_with_key(self, storage_key: str) -> None:
        raise NotImplementedError

    def release_blob(self, sha256: str) -> str | None:
        raise NotImplementedError

    def list_unreferenced_blobs(self, before: datetime, limit: int) -> list[tuple[str, str]]:
        raise NotImplementedError

    def list_expired_uploads(self, before: datetime, limit: int) -> list[UploadRecord]:
        raise NotImplementedError


class MemoryStore(TaskStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._blobs: dict[str, tuple[str, int, datetime]] = {}
        self._tasks: dict[str, TaskRecord] = {}
        self._artifacts: dict[str, list[ArtifactRecord]] = {}
        self._files: dict[str, FileRecord] = {}
        self._uploads: dict[str, UploadRecord] = {}
        self._meta: dict[str, tuple[str, datetime]] = {}

    def ping(self) -> bool:
        return True

    def put_blob(self, sha256: str, byte_size: int, storage_key: str) -> None:
        with self._lock:
            current = self._blobs.get(sha256)
            if current is None or not current[0]:
                self._blobs[sha256] = (storage_key, byte_size, utcnow())

    def blob_key(self, sha256: str) -> str | None:
        with self._lock:
            item = self._blobs.get(sha256)
            if item is None or not item[0]:
                return None
            return item[0]

    def blob_size(self, sha256: str) -> int:
        with self._lock:
            item = self._blobs.get(sha256)
            if item is None or not item[0]:
                return 0
            return item[1]

    def create_task(self, task: TaskRecord) -> None:
        with self._lock:
            self._tasks[task.id] = task

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(self, task: TaskRecord) -> None:
        with self._lock:
            self._tasks[task.id] = task

    def inflight_count(self) -> int:
        with self._lock:
            return sum(1 for task in self._tasks.values() if task.status in INFLIGHT and task.upstream_job_id)

    def claim_cancelled(self) -> TaskRecord | None:
        with self._lock:
            ordered = sorted(self._tasks.values(), key=lambda item: item.created_at)
            for task in ordered:
                if task.cancel_requested and task.status in {"accepted", "dispatching"} and not task.upstream_job_id:
                    task.status = "dispatching"
                    return task
            return None

    def claim_id(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.upstream_job_id or task.status not in {"accepted", "dispatching"}:
                return None
            task.status = "dispatching"
            return task

    def list_pending(self, limit: int, now: datetime | None = None, offset: int = 0) -> list[tuple[TaskRecord, int]]:
        now = now or utcnow()
        with self._lock:
            rows = [
                task
                for task in self._tasks.values()
                if task.status in {"accepted", "dispatching"}
                and not task.upstream_job_id
                and not task.cancel_requested
                and (task.next_attempt_at is None or task.next_attempt_at <= now)
            ]
            rows.sort(key=lambda item: (-item.priority, item.created_at))
            page = rows[offset : offset + limit]
            return [(task, self._blob_size_unlocked(task.blob_sha256)) for task in page]

    def _blob_size_unlocked(self, sha256: str) -> int:
        item = self._blobs.get(sha256)
        return 0 if item is None else item[1]

    def list_inflight(self) -> list[TaskRecord]:
        with self._lock:
            return [
                task
                for task in self._tasks.values()
                if task.upstream_job_id and task.status in {"running", "projecting", "dispatching"}
            ]

    def counts(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for task in self._tasks.values():
                counts[task.status] = counts.get(task.status, 0) + 1
            return counts

    def list_tasks(self, statuses: set[str] | None, limit: int) -> list[TaskRecord]:
        with self._lock:
            rows = list(self._tasks.values())
        if statuses is not None:
            rows = [task for task in rows if task.status in statuses]
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return rows[:limit]

    def tasks_for_batch(self, batch_id: str) -> list[TaskRecord]:
        with self._lock:
            rows = [task for task in self._tasks.values() if task.batch_id == batch_id]
        rows.sort(key=lambda item: item.created_at)
        return rows

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._meta[key] = (value, utcnow())

    def get_meta(self, key: str) -> tuple[str, datetime] | None:
        with self._lock:
            return self._meta.get(key)

    def operations_snapshot(self, since: datetime) -> dict[str, Any]:
        with self._lock:
            tasks = list(self._tasks.values())
            sizes = {sha: item[1] for sha, item in self._blobs.items()}
        return _summarize(tasks, sizes, since)

    def add_artifact(self, artifact: ArtifactRecord) -> None:
        with self._lock:
            self._artifacts.setdefault(artifact.task_id, []).append(artifact)

    def artifacts(self, task_id: str) -> list[ArtifactRecord]:
        with self._lock:
            return list(self._artifacts.get(task_id, []))

    def replace_artifacts(self, task_id: str, artifacts: list[ArtifactRecord]) -> None:
        with self._lock:
            self._artifacts[task_id] = list(artifacts)

    def put_upload(self, upload: UploadRecord) -> None:
        with self._lock:
            self._uploads[upload.id] = upload

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._lock:
            return self._uploads.get(upload_id)

    def put_file(self, record: FileRecord) -> None:
        with self._lock:
            self._files[record.id] = record

    def get_file(self, file_id: str) -> FileRecord | None:
        with self._lock:
            return self._files.get(file_id)

    def files_for_task(self, task_id: str) -> list[FileRecord]:
        with self._lock:
            return [item for item in self._files.values() if item.task_id == task_id]

    def list_expired(self, before: datetime, limit: int) -> list[TaskRecord]:
        with self._lock:
            rows = [
                task
                for task in self._tasks.values()
                if task.status in {COMPLETED, FAILED, CANCELLED}
                and task.purged_at is None
                and task.completed_at is not None
                and task.completed_at < before
            ]
        rows.sort(key=lambda item: item.completed_at or item.created_at)
        return rows[:limit]

    def delete_task_files(self, task_id: str) -> None:
        with self._lock:
            self._files = {key: item for key, item in self._files.items() if item.task_id != task_id}

    def delete_files_with_key(self, storage_key: str) -> None:
        with self._lock:
            self._files = {key: item for key, item in self._files.items() if item.storage_key != storage_key}

    def release_blob(self, sha256: str) -> str | None:
        with self._lock:
            if any(task.blob_sha256 == sha256 and task.purged_at is None for task in self._tasks.values()):
                return None
            item = self._blobs.get(sha256)
            if item is None or not item[0]:
                return None
            created = item[2] if len(item) > 2 else utcnow()
            self._blobs[sha256] = ("", item[1], created)
            return item[0]

    def list_unreferenced_blobs(self, before: datetime, limit: int) -> list[tuple[str, str]]:
        with self._lock:
            rows: list[tuple[datetime, str, str]] = []
            for sha256, item in self._blobs.items():
                if not item[0]:
                    continue
                created = item[2] if len(item) > 2 else utcnow()
                if created >= before:
                    continue
                if any(task.blob_sha256 == sha256 and task.purged_at is None for task in self._tasks.values()):
                    continue
                rows.append((created, sha256, item[0]))
        rows.sort(key=lambda item: item[0])
        return [(sha256, key) for _, sha256, key in rows[:limit]]

    def list_expired_uploads(self, before: datetime, limit: int) -> list[UploadRecord]:
        with self._lock:
            rows = [
                upload
                for upload in self._uploads.values()
                if upload.status == "pending" and upload.expires_at < before
            ]
        rows.sort(key=lambda item: item.expires_at)
        return rows[:limit]


def _priority_value(column: object, options: dict[str, Any]) -> int:
    if isinstance(column, int) and not isinstance(column, bool):
        return column
    raw = options.get("priority", 0)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return 0


def _row_to_task(row: dict[str, Any]) -> TaskRecord:
    warnings = row.get("warnings") or []
    if isinstance(warnings, str):
        warnings = json.loads(warnings)
    options = row.get("legacy_options") or {}
    if isinstance(options, str):
        options = json.loads(options)
    return TaskRecord(
        id=row["id"],
        blob_sha256=row["blob_sha256"],
        file_name=row["file_name"],
        legacy_options=options,
        tier=row["tier"],
        ocr_mode=row["ocr_mode"],
        engine=row["engine"],
        status=row["status"],
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        attempt=row["attempt"],
        upstream_job_id=row.get("upstream_job_id"),
        cancel_requested=bool(row["cancel_requested"]),
        legacy_backend=row["legacy_backend"],
        next_attempt_at=row.get("next_attempt_at"),
        warnings=list(warnings),
        upstream_base_url=row.get("upstream_base_url") or "",
        purged_at=row.get("purged_at"),
        upstream_finished_at=row.get("upstream_finished_at"),
        page_count=row.get("page_count"),
        batch_id=row.get("batch_id"),
        priority=_priority_value(row.get("priority"), options),
    )


class PostgresStore(TaskStore):
    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("psycopg is required for THINKPARSE_DATABASE_URL; install control/requirements.txt") from exc
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._url = database_url
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self._connect() as conn:
            for statement in schema.split(";"):
                sql = statement.strip()
                if sql:
                    conn.execute(sql)
            conn.commit()

    def _connect(self):
        return self._psycopg.connect(self._url, row_factory=self._dict_row)

    def ping(self) -> bool:
        with self._connect() as conn:
            conn.execute("SELECT 1")
            return True

    def put_blob(self, sha256: str, byte_size: int, storage_key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO blobs (sha256, byte_size, storage_key, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (sha256) DO UPDATE
                SET byte_size = EXCLUDED.byte_size,
                    storage_key = EXCLUDED.storage_key,
                    created_at = EXCLUDED.created_at
                WHERE blobs.storage_key = ''
                """,
                (sha256, byte_size, storage_key, utcnow()),
            )
            conn.commit()

    def blob_key(self, sha256: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT storage_key FROM blobs WHERE sha256 = %s", (sha256,)).fetchone()
            if row is None or not row["storage_key"]:
                return None
            return row["storage_key"]

    def create_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, blob_sha256, file_name, legacy_options, tier, ocr_mode, engine,
                    status, error_message, created_at, started_at, completed_at, attempt,
                    upstream_job_id, cancel_requested, legacy_backend, next_attempt_at, warnings,
                    upstream_base_url, purged_at, upstream_finished_at, page_count, batch_id, priority
                ) VALUES (
                    %s, %s, %s, %s::jsonb, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s::jsonb,
                    %s, %s, %s, %s, %s, %s
                )
                """,
                _task_params(task),
            )
            conn.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
            return None if row is None else _row_to_task(row)

    def update_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks SET
                    blob_sha256 = %s,
                    file_name = %s,
                    legacy_options = %s::jsonb,
                    tier = %s,
                    ocr_mode = %s,
                    engine = %s,
                    status = %s,
                    error_message = %s,
                    created_at = %s,
                    started_at = %s,
                    completed_at = %s,
                    attempt = %s,
                    upstream_job_id = %s,
                    cancel_requested = %s,
                    legacy_backend = %s,
                    next_attempt_at = %s,
                    warnings = %s::jsonb,
                    upstream_base_url = %s,
                    purged_at = %s,
                    upstream_finished_at = %s,
                    page_count = %s,
                    batch_id = %s,
                    priority = %s
                WHERE id = %s
                """,
                (
                    task.blob_sha256,
                    task.file_name,
                    json.dumps(task.legacy_options),
                    task.tier,
                    task.ocr_mode,
                    task.engine,
                    task.status,
                    task.error_message,
                    task.created_at,
                    task.started_at,
                    task.completed_at,
                    task.attempt,
                    task.upstream_job_id,
                    task.cancel_requested,
                    task.legacy_backend,
                    task.next_attempt_at,
                    json.dumps(task.warnings),
                    task.upstream_base_url,
                    task.purged_at,
                    task.upstream_finished_at,
                    task.page_count,
                    task.batch_id,
                    task.priority,
                    task.id,
                ),
            )
            conn.commit()

    def inflight_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM tasks
                WHERE upstream_job_id IS NOT NULL
                  AND status IN ('dispatching', 'running', 'projecting')
                """
            ).fetchone()
            return int(row["n"])

    def blob_size(self, sha256: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT byte_size FROM blobs WHERE sha256 = %s AND storage_key <> ''",
                (sha256,),
            ).fetchone()
            return 0 if row is None else int(row["byte_size"])

    def claim_cancelled(self) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE tasks SET status = 'dispatching'
                WHERE id = (
                    SELECT id FROM tasks
                    WHERE cancel_requested = TRUE
                      AND status IN ('accepted', 'dispatching')
                      AND upstream_job_id IS NULL
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                RETURNING *
                """
            ).fetchone()
            conn.commit()
            return None if row is None else _row_to_task(row)

    def claim_id(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                UPDATE tasks SET status = 'dispatching'
                WHERE id = %s
                  AND status IN ('accepted', 'dispatching')
                  AND upstream_job_id IS NULL
                RETURNING *
                """,
                (task_id,),
            ).fetchone()
            conn.commit()
            return None if row is None else _row_to_task(row)

    def list_pending(self, limit: int, now: datetime | None = None, offset: int = 0) -> list[tuple[TaskRecord, int]]:
        now = now or utcnow()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tasks.*, COALESCE(blobs.byte_size, 0) AS blob_byte_size
                FROM tasks
                LEFT JOIN blobs ON blobs.sha256 = tasks.blob_sha256
                WHERE tasks.status IN ('accepted', 'dispatching')
                  AND tasks.upstream_job_id IS NULL
                  AND tasks.cancel_requested = FALSE
                  AND (tasks.next_attempt_at IS NULL OR tasks.next_attempt_at <= %s)
                ORDER BY tasks.priority DESC, tasks.created_at
                LIMIT %s OFFSET %s
                """,
                (now, limit, offset),
            ).fetchall()
            return [(_row_to_task(row), int(row["blob_byte_size"])) for row in rows]

    def list_inflight(self) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE upstream_job_id IS NOT NULL
                  AND status IN ('dispatching', 'running', 'projecting')
                ORDER BY created_at
                """
            ).fetchall()
            return [_row_to_task(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status").fetchall()
            return {row["status"]: int(row["n"]) for row in rows}

    def list_tasks(self, statuses: set[str] | None, limit: int) -> list[TaskRecord]:
        with self._connect() as conn:
            if statuses:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE status = ANY(%s) ORDER BY created_at DESC LIMIT %s",
                    (list(statuses), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                ).fetchall()
            return [_row_to_task(row) for row in rows]

    def tasks_for_batch(self, batch_id: str) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE batch_id = %s ORDER BY created_at",
                (batch_id,),
            ).fetchall()
            return [_row_to_task(row) for row in rows]

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO control_meta (key, value, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (key, value, utcnow()),
            )
            conn.commit()

    def get_meta(self, key: str) -> tuple[str, datetime] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value, updated_at FROM control_meta WHERE key = %s", (key,)).fetchone()
            if row is None:
                return None
            return row["value"], row["updated_at"]

    def operations_snapshot(self, since: datetime) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tasks.*, COALESCE(blobs.byte_size, 0) AS blob_byte_size
                FROM tasks
                LEFT JOIN blobs ON blobs.sha256 = tasks.blob_sha256
                """
            ).fetchall()
        tasks = [_row_to_task(row) for row in rows]
        sizes = {row["blob_sha256"]: int(row["blob_byte_size"]) for row in rows}
        return _summarize(tasks, sizes, since)

    def add_artifact(self, artifact: ArtifactRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (task_id, kind, storage_key, byte_size, filename)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (artifact.task_id, artifact.kind, artifact.storage_key, artifact.byte_size, artifact.filename),
            )
            conn.commit()

    def artifacts(self, task_id: str) -> list[ArtifactRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id, kind, storage_key, byte_size, filename FROM artifacts WHERE task_id = %s",
                (task_id,),
            ).fetchall()
            return [
                ArtifactRecord(
                    task_id=row["task_id"],
                    kind=row["kind"],
                    storage_key=row["storage_key"],
                    byte_size=row["byte_size"],
                    filename=row["filename"],
                )
                for row in rows
            ]

    def replace_artifacts(self, task_id: str, artifacts: list[ArtifactRecord]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE task_id = %s", (task_id,))
            for artifact in artifacts:
                conn.execute(
                    """
                    INSERT INTO artifacts (task_id, kind, storage_key, byte_size, filename)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (artifact.task_id, artifact.kind, artifact.storage_key, artifact.byte_size, artifact.filename),
                )
            conn.commit()

    def put_upload(self, upload: UploadRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO uploads (
                    id, filename, byte_size, mime_type, sha256, status, storage_key, file_id, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    storage_key = EXCLUDED.storage_key,
                    file_id = EXCLUDED.file_id,
                    sha256 = EXCLUDED.sha256
                """,
                (
                    upload.id,
                    upload.filename,
                    upload.byte_size,
                    upload.mime_type,
                    upload.sha256,
                    upload.status,
                    upload.storage_key,
                    upload.file_id,
                    upload.created_at,
                    upload.expires_at,
                ),
            )
            conn.commit()

    def get_upload(self, upload_id: str) -> UploadRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM uploads WHERE id = %s", (upload_id,)).fetchone()
            if row is None:
                return None
            return UploadRecord(
                id=row["id"],
                filename=row["filename"],
                byte_size=row["byte_size"],
                mime_type=row["mime_type"],
                status=row["status"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                sha256=row.get("sha256"),
                storage_key=row.get("storage_key"),
                file_id=row.get("file_id"),
            )

    def put_file(self, record: FileRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO files (
                    id, filename, byte_size, storage_key, purpose, created_at, sha256, mime_type, task_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    record.id,
                    record.filename,
                    record.byte_size,
                    record.storage_key,
                    record.purpose,
                    record.created_at,
                    record.sha256,
                    record.mime_type,
                    record.task_id,
                ),
            )
            conn.commit()

    def get_file(self, file_id: str) -> FileRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE id = %s", (file_id,)).fetchone()
            if row is None:
                return None
            return _row_to_file(row)

    def files_for_task(self, task_id: str) -> list[FileRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM files WHERE task_id = %s", (task_id,)).fetchall()
            return [_row_to_file(row) for row in rows]

    def list_expired(self, before: datetime, limit: int) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN ('completed', 'failed', 'cancelled')
                  AND purged_at IS NULL AND completed_at < %s
                ORDER BY completed_at
                LIMIT %s
                """,
                (before, limit),
            ).fetchall()
            return [_row_to_task(row) for row in rows]

    def delete_task_files(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM files WHERE task_id = %s", (task_id,))
            conn.commit()

    def delete_files_with_key(self, storage_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM files WHERE storage_key = %s", (storage_key,))
            conn.commit()

    def release_blob(self, sha256: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                WITH doomed AS (
                    SELECT sha256, storage_key FROM blobs
                    WHERE sha256 = %s AND storage_key <> ''
                      AND NOT EXISTS (
                        SELECT 1 FROM tasks
                        WHERE tasks.blob_sha256 = blobs.sha256 AND purged_at IS NULL
                      )
                )
                UPDATE blobs
                SET storage_key = ''
                FROM doomed
                WHERE blobs.sha256 = doomed.sha256
                RETURNING doomed.storage_key AS storage_key
                """,
                (sha256,),
            ).fetchone()
            conn.commit()
            if row is None or not row["storage_key"]:
                return None
            return row["storage_key"]

    def list_unreferenced_blobs(self, before: datetime, limit: int) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sha256, storage_key FROM blobs
                WHERE storage_key <> '' AND created_at < %s
                  AND NOT EXISTS (
                    SELECT 1 FROM tasks
                    WHERE tasks.blob_sha256 = blobs.sha256 AND purged_at IS NULL
                  )
                ORDER BY created_at
                LIMIT %s
                """,
                (before, limit),
            ).fetchall()
            return [(row["sha256"], row["storage_key"]) for row in rows]

    def list_expired_uploads(self, before: datetime, limit: int) -> list[UploadRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM uploads
                WHERE status = 'pending' AND expires_at < %s
                ORDER BY expires_at
                LIMIT %s
                """,
                (before, limit),
            ).fetchall()
            return [_row_to_upload(row) for row in rows]


def _summarize(tasks: list[TaskRecord], sizes: dict[str, int], since: datetime) -> dict[str, Any]:
    counts: dict[str, int] = {}
    inflight_by_url: dict[str, int] = {}
    inflight_bytes_by_url: dict[str, int] = {}
    inflight_bytes = 0
    oldest: datetime | None = None
    completed_in_window = 0
    failed_in_window = 0
    pages_in_window = 0
    by_tier: dict[str, dict[str, int]] = {}
    failure_counts: dict[str, int] = {}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
        tier_row = by_tier.setdefault(task.tier, {"queued": 0, "running": 0, "failed_in_window": 0})
        if task.status in {"accepted", "dispatching"} and not task.upstream_job_id:
            tier_row["queued"] += 1
            if oldest is None or task.created_at < oldest:
                oldest = task.created_at
        if task.status in INFLIGHT and task.upstream_job_id:
            tier_row["running"] += 1
            url = task.upstream_base_url or ""
            size = sizes.get(task.blob_sha256, 0)
            inflight_by_url[url] = inflight_by_url.get(url, 0) + 1
            inflight_bytes_by_url[url] = inflight_bytes_by_url.get(url, 0) + size
            inflight_bytes += size
        in_window = task.completed_at is not None and task.completed_at >= since
        if task.status == COMPLETED and in_window:
            completed_in_window += 1
            pages_in_window += task.page_count or 0
        if task.status == "failed" and in_window:
            failed_in_window += 1
            tier_row["failed_in_window"] += 1
            if task.error_message:
                reason = task.error_message[:160]
                failure_counts[reason] = failure_counts.get(reason, 0) + 1
    failures = sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    return {
        "counts": counts,
        "inflight_bytes": inflight_bytes,
        "inflight_by_url": inflight_by_url,
        "inflight_bytes_by_url": inflight_bytes_by_url,
        "oldest_queued_at": oldest,
        "completed_in_window": completed_in_window,
        "failed_in_window": failed_in_window,
        "pages_in_window": pages_in_window,
        "by_tier": {
            tier: row
            for tier, row in by_tier.items()
            if row["queued"] or row["running"] or row["failed_in_window"]
        },
        "failures": [{"reason": reason, "count": count} for reason, count in failures],
    }


def _row_to_upload(row: dict[str, Any]) -> UploadRecord:
    return UploadRecord(
        id=row["id"],
        filename=row["filename"],
        byte_size=row["byte_size"],
        mime_type=row["mime_type"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        sha256=row.get("sha256"),
        storage_key=row.get("storage_key"),
        file_id=row.get("file_id"),
    )


def _row_to_file(row: dict[str, Any]) -> FileRecord:
    return FileRecord(
        id=row["id"],
        filename=row["filename"],
        byte_size=row["byte_size"],
        storage_key=row["storage_key"],
        purpose=row["purpose"],
        created_at=row["created_at"],
        sha256=row.get("sha256"),
        mime_type=row.get("mime_type"),
        task_id=row.get("task_id"),
    )


def _task_params(task: TaskRecord) -> tuple[Any, ...]:
    return (
        task.id,
        task.blob_sha256,
        task.file_name,
        json.dumps(task.legacy_options),
        task.tier,
        task.ocr_mode,
        task.engine,
        task.status,
        task.error_message,
        task.created_at,
        task.started_at,
        task.completed_at,
        task.attempt,
        task.upstream_job_id,
        task.cancel_requested,
        task.legacy_backend,
        task.next_attempt_at,
        json.dumps(task.warnings),
        task.upstream_base_url,
        task.purged_at,
        task.upstream_finished_at,
        task.page_count,
        task.batch_id,
        task.priority,
    )
