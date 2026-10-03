"""Release MinerU 4.0.10 scratch blobs.

The PyPI 4.0.10 file store drops the file id and leaves the bytes. This hooks
the parser module when a newer MinerU has not already marked ``releases_blobs``.
The router keeps its own copy of each upload; that copy is swept the same way.
Set MINERU_FILE_RETENTION_SECONDS to delete files that clients never release.
"""

from __future__ import annotations

import asyncio
import importlib.machinery
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator


def _retention_seconds() -> int:
    raw = os.getenv("MINERU_FILE_RETENTION_SECONDS")
    if raw is None or not raw.strip():
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _pinned(app_state: Any) -> set[str]:
    jobs = getattr(app_state, "job_store", None)
    if jobs is None:
        return set()
    active = getattr(jobs, "active_file_ids", None)
    if callable(active):
        found = active()
        if isinstance(found, set):
            return found
    pinned: set[str] = set()
    for rec in getattr(jobs, "_jobs", {}).values():
        if getattr(rec, "status", "") not in {"queued", "running"}:
            continue
        for item in getattr(rec, "files", []) or []:
            file_id = getattr(item, "file_id", None)
            if isinstance(file_id, str) and file_id:
                pinned.add(file_id)
    return pinned


def _apply(module: Any) -> None:
    file_store = module.FileStore
    if getattr(file_store, "releases_blobs", False):
        return
    original_delete = file_store.delete_file

    def delete_file(self: Any, file_id: str) -> None:
        rec = self._files.get(file_id)
        original_delete(self, file_id)
        sha = None if rec is None else rec.sha256sum
        if not sha or any(item.sha256sum == sha for item in self._files.values()):
            return
        self._blob_abs(sha).unlink(missing_ok=True)

    def purge_expired(self: Any, *, older_than: int, pinned: set[str]) -> int:
        if older_than <= 0:
            return 0
        now = int(time.time())
        doomed = [
            rec.id
            for rec in list(self._files.values())
            if rec.id not in pinned and now - rec.created_at >= older_than
        ]
        for file_id in doomed:
            self.delete_file(file_id)
        return len(doomed)

    file_store.delete_file = delete_file
    if not hasattr(file_store, "purge_expired"):
        file_store.purge_expired = purge_expired
    file_store.releases_blobs = True

    original_create = module.create_app

    def create_app(*args: Any, **kwargs: Any) -> Any:
        app = original_create(*args, **kwargs)
        previous = app.router.lifespan_context

        @asynccontextmanager
        async def wrapped(application: Any) -> AsyncIterator[None]:
            async with previous(application):
                seconds = _retention_seconds()
                task = None
                if seconds > 0:
                    task = asyncio.create_task(_purge(application, seconds), name="mineru-file-retention")
                try:
                    yield
                finally:
                    if task is not None:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

        app.router.lifespan_context = wrapped
        return app

    module.create_app = create_app


async def _purge(application: Any, older_than: int) -> None:
    interval = min(60, older_than)
    while True:
        await asyncio.sleep(interval)
        store = application.state.file_store
        store.purge_expired(older_than=older_than, pinned=_pinned(application.state))


_ACTIVE_JOB = {"queued", "running", "pending"}


def _route_age_seconds(created_at: object, now: float) -> float | None:
    if not isinstance(created_at, str):
        return None
    try:
        parsed = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return now - parsed.timestamp()


def _pinned_router_files(registry: Any) -> set[str]:
    pinned: set[str] = set()
    for job in registry.list("job"):
        payload = job.metadata.get("payload")
        status = payload.get("status") if isinstance(payload, dict) else None
        if not job.metadata.get("active_counted") and status not in _ACTIVE_JOB:
            continue
        aliases = job.metadata.get("input_aliases")
        if isinstance(aliases, dict):
            for value in aliases.values():
                if isinstance(value, str) and value:
                    pinned.add(value)
        files = payload.get("files") if isinstance(payload, dict) else None
        if isinstance(files, list):
            for item in files:
                file_id = item.get("file_id") if isinstance(item, dict) else None
                if isinstance(file_id, str) and file_id:
                    pinned.add(file_id)
    return pinned


def sweep_router_sources(registry: Any, source_store: Any, *, now: float, older_than: int) -> int:
    """Drop Router source copies that no queued or running job still needs."""
    if older_than <= 0:
        return 0
    pinned = _pinned_router_files(registry)
    removed = 0
    for route in registry.list("file"):
        age = _route_age_seconds(route.created_at, now)
        if route.public_id in pinned or age is None or age < older_than:
            continue
        source_store.delete_file(route.public_id)
        registry.remove("file", route.public_id)
        removed += 1
    for route in registry.list("upload"):
        age = _route_age_seconds(route.created_at, now)
        if age is None or age < older_than:
            continue
        source_store.discard_upload(route.public_id)
        registry.remove("upload", route.public_id)
        removed += 1
    return removed


def _apply_router(module: Any) -> None:
    if getattr(module, "sweeps_source_files", False):
        return
    original_create = module.create_app

    def create_app(*args: Any, **kwargs: Any) -> Any:
        app = original_create(*args, **kwargs)
        previous = app.router.lifespan_context

        @asynccontextmanager
        async def wrapped(application: Any) -> AsyncIterator[None]:
            async with previous(application):
                seconds = _retention_seconds()
                task = None
                if seconds > 0:
                    task = asyncio.create_task(_purge_router(application, seconds), name="mineru-router-file-retention")
                try:
                    yield
                finally:
                    if task is not None:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

        app.router.lifespan_context = wrapped
        return app

    module.create_app = create_app
    module.sweeps_source_files = True


async def _purge_router(application: Any, older_than: int) -> None:
    interval = min(60, older_than)
    while True:
        await asyncio.sleep(interval)
        sweep_router_sources(
            application.state.registry,
            application.state.source_store,
            now=time.time(),
            older_than=older_than,
        )


class _Finder:
    def __init__(self, fullname: str, apply: Any) -> None:
        self.fullname = fullname
        self.apply = apply

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname != self.fullname:
            return None
        if self in sys.meta_path:
            sys.meta_path.remove(self)
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        original = spec.loader.exec_module

        def exec_module(module: Any) -> None:
            original(module)
            self.apply(module)

        spec.loader.exec_module = exec_module
        return spec


sys.meta_path.insert(0, _Finder("mineru.parser.api_server", _apply))
sys.meta_path.insert(0, _Finder("mineru.kit.router.app", _apply_router))
