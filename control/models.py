"""Control-plane records. Status values are internal; the gateway maps them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


ACCEPTED = "accepted"
DISPATCHING = "dispatching"
RUNNING = "running"
PROJECTING = "projecting"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})
INFLIGHT = frozenset({DISPATCHING, RUNNING, PROJECTING})

PUBLIC_PENDING = "pending"
PUBLIC_PROCESSING = "processing"
PUBLIC_COMPLETED = "completed"
PUBLIC_FAILED = "failed"
PUBLIC_CANCELLED = "cancelled"


def public_status(status: str) -> str:
    if status in {ACCEPTED, DISPATCHING}:
        return PUBLIC_PENDING
    if status in {RUNNING, PROJECTING}:
        return PUBLIC_PROCESSING
    if status == COMPLETED:
        return PUBLIC_COMPLETED
    if status == CANCELLED:
        return PUBLIC_CANCELLED
    return PUBLIC_FAILED


@dataclass
class TaskRecord:
    id: str
    blob_sha256: str
    file_name: str
    legacy_options: dict[str, Any]
    tier: str
    ocr_mode: str
    engine: str
    status: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    attempt: int
    upstream_job_id: str | None
    cancel_requested: bool
    legacy_backend: str
    next_attempt_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)
    upstream_base_url: str = ""
    purged_at: datetime | None = None
    upstream_finished_at: datetime | None = None
    page_count: int | None = None
    batch_id: str | None = None
    priority: int = 0


@dataclass
class ArtifactRecord:
    task_id: str
    kind: str
    storage_key: str
    byte_size: int
    filename: str | None = None


@dataclass
class FileRecord:
    id: str
    filename: str
    byte_size: int
    storage_key: str
    purpose: str
    created_at: datetime
    sha256: str | None = None
    mime_type: str | None = None
    task_id: str | None = None


@dataclass
class UploadRecord:
    id: str
    filename: str
    byte_size: int
    mime_type: str
    status: str
    created_at: datetime
    expires_at: datetime
    sha256: str | None = None
    storage_key: str | None = None
    file_id: str | None = None
