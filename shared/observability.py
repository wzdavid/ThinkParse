"""Runtime health and observability helpers for ThinkParse."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from redis import Redis

from shared import celeryconfig
from shared.disk_space import decide, load_policy
from shared.storage import OUTPUT_DIR, STORAGE_TYPE, TEMP_DIR, get_storage

WORKER_HEARTBEAT_PREFIX = "thinkparse:worker:"
CANCEL_REQUEST_PREFIX = "thinkparse:cancel:"
WORKER_HEARTBEAT_SECONDS = float(os.getenv("WORKER_HEARTBEAT_SECONDS", "15"))
WORKER_HEARTBEAT_TTL_SECONDS = max(int(WORKER_HEARTBEAT_SECONDS * 3), 30)
GPU_METRICS_INTERVAL_SECONDS = float(os.getenv("GPU_METRICS_INTERVAL_SECONDS", "30"))
WORKER_WATCHDOG_TIMEOUT_SECONDS = celeryconfig.worker_watchdog_timeout


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_legacy_pagination(requested: bool | None) -> bool:
    """Resolve request override against the deployment default."""
    if requested is not None:
        return requested
    return os.getenv("MINERU_ENABLE_PAGINATION", "false").lower() == "true"


def request_task_cancellation(task_id: str) -> None:
    client = _redis_client()
    try:
        client.setex(
            f"{CANCEL_REQUEST_PREFIX}{task_id}",
            celeryconfig.result_expires,
            utc_now_iso(),
        )
    finally:
        client.close()


def is_task_cancellation_requested(task_id: str) -> bool:
    probe = TaskCancellationProbe(task_id)
    try:
        return probe.is_requested()
    finally:
        probe.close()


def prepare_watchdog_restart(task_id: str) -> bool:
    """Persist cancellation before exiting so a redelivered task terminates."""
    try:
        request_task_cancellation(task_id)
    except Exception:
        return False
    return True


class TaskCancellationProbe:
    """Efficiently poll one cancellation key during a long parse."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._client: Redis | None = None

    def is_requested(self) -> bool:
        try:
            if self._client is None:
                self._client = _redis_client()
            return bool(self._client.exists(f"{CANCEL_REQUEST_PREFIX}{self.task_id}"))
        except Exception:
            self.close()
            return False

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def _redis_client() -> Redis:
    return Redis.from_url(
        celeryconfig.broker_url,
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
    )


def collect_redis_snapshot() -> dict[str, Any]:
    """Return Redis connectivity and the actual Celery queue depth."""
    client = _redis_client()
    started = time.monotonic()
    try:
        client.ping()
        queue_keys = [celeryconfig.MINERU_QUEUE]
        queue_keys.extend(
            f"{celeryconfig.MINERU_QUEUE}\x06\x16{priority}" for priority in (3, 6, 9)
        )
        queue_depth = sum(int(client.llen(key)) for key in queue_keys)
        worker_states = []
        for key in client.scan_iter(match=f"{WORKER_HEARTBEAT_PREFIX}*"):
            value = client.get(key)
            if not value:
                continue
            try:
                worker_states.append(json.loads(value))
            except json.JSONDecodeError:
                continue
        return {
            "available": True,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "queue": celeryconfig.MINERU_QUEUE,
            "queue_depth": queue_depth,
            "worker_heartbeats": worker_states,
        }
    finally:
        client.close()


def collect_worker_snapshot(celery_app: Any, timeout: float = 1.0) -> dict[str, Any]:
    """Inspect Celery workers with bounded blocking calls."""
    inspect = celery_app.control.inspect(timeout=timeout)
    stats = inspect.stats() or {}
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}
    now = time.time()
    active_tasks = []
    for worker_name, tasks in active.items():
        for task in tasks:
            started_at = task.get("time_start")
            args = task.get("args")
            active_tasks.append(
                {
                    "task_id": task.get("id"),
                    "worker": worker_name,
                    "name": task.get("name"),
                    "file_name": (
                        args[1] if isinstance(args, (list, tuple)) and len(args) > 1 else None
                    ),
                    "backend": (
                        args[2] if isinstance(args, (list, tuple)) and len(args) > 2 else None
                    ),
                    "started_at": started_at,
                    "runtime_seconds": (
                        round(max(0.0, now - float(started_at)), 1)
                        if isinstance(started_at, (int, float))
                        else None
                    ),
                }
            )
    reserved_tasks = []
    for worker_name, tasks in reserved.items():
        for task in tasks:
            args = task.get("args")
            reserved_tasks.append(
                {
                    "task_id": task.get("id"),
                    "worker": worker_name,
                    "name": task.get("name"),
                    "file_name": (
                        args[1] if isinstance(args, (list, tuple)) and len(args) > 1 else None
                    ),
                    "backend": (
                        args[2] if isinstance(args, (list, tuple)) and len(args) > 2 else None
                    ),
                }
            )
    return {
        "available": bool(stats),
        "count": len(stats),
        "names": sorted(stats),
        "active_count": sum(len(tasks) for tasks in active.values()),
        "reserved_count": sum(len(tasks) for tasks in reserved.values()),
        "active_tasks": active_tasks,
        "reserved_tasks": reserved_tasks,
    }


def _path_capacity(raw_path: str, policy: Any) -> dict[str, Any]:
    path = Path(raw_path)
    usage = shutil.disk_usage(path)
    decision = decide(usage.total, usage.free, policy)
    return {
        "path": str(path),
        "writable": os.access(path, os.W_OK),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "used_percent": decision.used_percent,
        "state": decision.state,
        "reject_below_bytes": decision.reject_below_bytes,
        "reclaim_below_bytes": decision.reclaim_below_bytes,
    }


def collect_storage_snapshot() -> dict[str, Any]:
    """Check storage initialization and local capacity without writing data."""
    storage = get_storage()
    snapshot: dict[str, Any] = {
        "available": True,
        "type": storage.storage_type,
    }
    policy = load_policy()
    if STORAGE_TYPE != "local":
        snapshot = storage.health_check()
        try:
            temp_capacity = _path_capacity(tempfile.gettempdir(), policy)
        except OSError:
            temp_capacity = None
        if temp_capacity is not None:
            snapshot["paths"] = {"temp": temp_capacity}
            if temp_capacity["state"] != "ok":
                snapshot["available"] = False
        return snapshot

    paths = {}
    for name, raw_path in (("temp", TEMP_DIR), ("output", OUTPUT_DIR)):
        paths[name] = _path_capacity(raw_path, policy)
        if not paths[name]["writable"] or paths[name]["state"] != "ok":
            snapshot["available"] = False
    snapshot["paths"] = paths
    return snapshot


def collect_gpu_snapshot() -> dict[str, Any]:
    """Collect GPU identity and utilization metrics when nvidia-smi is available."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                (
                    "--query-gpu=index,name,uuid,driver_version,utilization.gpu,"
                    "memory.total,memory.used,temperature.gpu"
                ),
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return {"available": False, "devices": []}

    devices = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 8:
            continue
        try:
            devices.append(
                {
                    "index": int(values[0]),
                    "name": values[1],
                    "uuid": values[2],
                    "driver_version": values[3],
                    "utilization_percent": int(values[4]),
                    "memory_total_mb": int(values[5]),
                    "memory_used_mb": int(values[6]),
                    "temperature_c": int(values[7]),
                }
            )
        except ValueError:
            continue
    return {"available": bool(devices), "device_count": len(devices), "devices": devices}


def is_task_watchdog_overdue(
    task_started_monotonic: float | None,
    now_monotonic: float,
    timeout_seconds: float = WORKER_WATCHDOG_TIMEOUT_SECONDS,
) -> bool:
    return (
        timeout_seconds > 0
        and task_started_monotonic is not None
        and now_monotonic - task_started_monotonic > timeout_seconds
    )


class WorkerHeartbeat:
    """Publish Worker and active-task state to Redis from a daemon thread."""

    def __init__(
        self,
        worker_name: str,
        on_watchdog_timeout: Callable[[], None] | None = None,
    ):
        self.worker_name = worker_name
        self._on_watchdog_timeout = on_watchdog_timeout
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "worker": worker_name,
            "stage": "starting",
            "task_id": None,
            "file_name": None,
            "task_started_at": None,
        }
        self._started = False
        self._gpu_snapshot: dict[str, Any] = {"available": False, "devices": []}
        self._last_gpu_sample = 0.0
        self._task_started_monotonic: float | None = None

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        thread = threading.Thread(
            target=self._run,
            name="thinkparse-worker-heartbeat",
            daemon=True,
        )
        thread.start()

    def set_task(self, task_id: str, file_name: str) -> None:
        with self._lock:
            self._task_started_monotonic = time.monotonic()
            self._state.update(
                {
                    "stage": "processing",
                    "task_id": task_id,
                    "file_name": file_name,
                    "task_started_at": utc_now_iso(),
                }
            )

    def set_metadata(self, **metadata: Any) -> None:
        with self._lock:
            self._state.update(metadata)

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self._state["stage"] = stage

    def clear_task(self) -> None:
        with self._lock:
            self._task_started_monotonic = None
            self._state.update(
                {
                    "stage": "idle",
                    "task_id": None,
                    "file_name": None,
                    "task_started_at": None,
                }
            )

    def _run(self) -> None:
        while True:
            try:
                with self._lock:
                    payload = dict(self._state)
                    task_started_monotonic = self._task_started_monotonic
                now = time.monotonic()
                if is_task_watchdog_overdue(task_started_monotonic, now):
                    task_id = payload.get("task_id")
                    if not task_id or not prepare_watchdog_restart(task_id):
                        print(
                            "Worker watchdog could not persist cancellation; "
                            "restart deferred to avoid a task redelivery loop.",
                            flush=True,
                        )
                        time.sleep(WORKER_HEARTBEAT_SECONDS)
                        continue
                    print(
                        "Worker watchdog detected an overdue task; exiting for supervisor restart.",
                        flush=True,
                    )
                    if self._on_watchdog_timeout is not None:
                        try:
                            self._on_watchdog_timeout()
                        except Exception:
                            pass
                    os._exit(70)
                if now - self._last_gpu_sample >= GPU_METRICS_INTERVAL_SECONDS:
                    self._gpu_snapshot = collect_gpu_snapshot()
                    self._last_gpu_sample = now
                payload["gpu"] = self._gpu_snapshot
                payload["heartbeat_at"] = utc_now_iso()
                payload["pid"] = os.getpid()
                client = _redis_client()
                try:
                    client.setex(
                        f"{WORKER_HEARTBEAT_PREFIX}{self.worker_name}",
                        WORKER_HEARTBEAT_TTL_SECONDS,
                        json.dumps(payload, ensure_ascii=False),
                    )
                finally:
                    client.close()
            except Exception:
                # A Redis outage must not stop document parsing.
                pass
            time.sleep(WORKER_HEARTBEAT_SECONDS)
