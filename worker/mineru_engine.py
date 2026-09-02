"""Cancellable persistent MinerU engine process.

The Celery Worker uses a threads pool, which cannot terminate a running
function. MinerU therefore runs in a dedicated, persistent process: models are
reused between tasks, while cancellation or timeout can terminate only the
engine process and leave the Celery Worker available.
"""
from __future__ import annotations

import atexit
import multiprocessing
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable


class MinerUEngineError(RuntimeError):
    pass


class MinerUEngineCancelled(MinerUEngineError):
    pass


class MinerUEngineTimeout(MinerUEngineError):
    pass


def _engine_loop(request_queue: Any, response_queue: Any) -> None:
    """Run inside the isolated process and reuse MinerU models across jobs."""
    from mineru.cli.common import do_parse, read_fn
    from mineru.utils.model_utils import clean_memory

    while True:
        request = request_queue.get()
        if request is None:
            return

        request_id = request["request_id"]
        pdf_bytes = None
        try:
            file_path = Path(request["file_path"])
            options = request["options"]
            pdf_bytes = read_fn(str(file_path))
            do_parse(
                output_dir=request["output_path"],
                pdf_file_names=[Path(request["file_name"]).stem],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[options.get("lang", "ch")],
                backend=request["backend"],
                parse_method=options.get("method", "auto"),
                formula_enable=options.get("formula_enable", True),
                table_enable=options.get("table_enable", True),
                f_dump_content_list=True,
                f_dump_middle_json=True,
            )
            response_queue.put({"request_id": request_id, "success": True})
        except BaseException as exc:
            response_queue.put(
                {
                    "request_id": request_id,
                    "success": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        finally:
            try:
                clean_memory()
            except Exception:
                pass
            if pdf_bytes is not None:
                del pdf_bytes


class MinerUEngineProcess:
    """Serialize parse calls through one reusable, killable engine process."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 0.5,
        process_context: Any = None,
    ):
        self.poll_interval_seconds = poll_interval_seconds
        self._context = process_context or multiprocessing.get_context("spawn")
        self._process: Any = None
        self._request_queue: Any = None
        self._response_queue: Any = None
        self._lock = threading.Lock()
        self._generation = 0
        atexit.register(self.close)

    def parse(
        self,
        *,
        file_path: Path,
        file_name: str,
        backend: str,
        options: dict[str, Any],
        output_path: Path,
        timeout_seconds: float,
        is_cancel_requested: Callable[[], bool],
        on_state_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        with self._lock:
            self._ensure_started()
            self._notify_state(on_state_change)
            request_id = uuid.uuid4().hex
            self._request_queue.put(
                {
                    "request_id": request_id,
                    "file_path": str(file_path),
                    "file_name": file_name,
                    "backend": backend,
                    "options": options,
                    "output_path": str(output_path),
                }
            )
            deadline = time.monotonic() + timeout_seconds

            while True:
                if is_cancel_requested():
                    self._stop_engine()
                    self._notify_state(on_state_change)
                    raise MinerUEngineCancelled(f"Parsing cancelled: {file_name}")
                if time.monotonic() >= deadline:
                    self._stop_engine()
                    self._notify_state(on_state_change)
                    raise MinerUEngineTimeout(
                        f"MinerU engine timeout after {timeout_seconds:.0f}s: {file_name}"
                    )
                if not self._process.is_alive():
                    exit_code = self._process.exitcode
                    self._stop_engine()
                    self._notify_state(on_state_change)
                    raise MinerUEngineError(
                        f"MinerU engine exited unexpectedly with code {exit_code}: {file_name}"
                    )

                try:
                    response = self._response_queue.get(timeout=self.poll_interval_seconds)
                except queue.Empty:
                    continue
                if response.get("request_id") != request_id:
                    continue
                if response.get("success"):
                    self._notify_state(on_state_change)
                    return
                self._stop_engine()
                self._notify_state(on_state_change)
                raise MinerUEngineError(
                    f"{response.get('error', 'Unknown MinerU error')}\n"
                    f"{response.get('traceback', '')}"
                )

    def close(self) -> None:
        with self._lock:
            self._stop_engine(graceful=True)

    def force_stop(self) -> None:
        """Stop the engine without waiting for a potentially stuck parse lock."""
        self._stop_engine()

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._stop_engine()
        self._request_queue = self._context.Queue()
        self._response_queue = self._context.Queue()
        self._process = self._context.Process(
            target=_engine_loop,
            args=(self._request_queue, self._response_queue),
            name="thinkparse-mineru-engine",
            daemon=False,
        )
        self._process.start()
        self._generation += 1

    def _notify_state(
        self,
        callback: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        if callback is None:
            return
        process = self._process
        callback(
            {
                "alive": bool(process is not None and process.is_alive()),
                "pid": getattr(process, "pid", None),
                "generation": self._generation,
                "restart_count": max(0, self._generation - 1),
            }
        )

    def _stop_engine(self, graceful: bool = False) -> None:
        process = self._process
        if process is None:
            return
        if graceful and process.is_alive() and self._request_queue is not None:
            self._request_queue.put(None)
            process.join(timeout=5)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=5)
        for process_queue in (self._request_queue, self._response_queue):
            if process_queue is None:
                continue
            try:
                process_queue.close()
                process_queue.join_thread()
            except (AttributeError, OSError, ValueError):
                pass
        self._process = None
        self._request_queue = None
        self._response_queue = None


mineru_engine = MinerUEngineProcess()
