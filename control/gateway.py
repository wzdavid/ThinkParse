"""Legacy HTTP gateway. It does not run the reconciler loop."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from control import __version__
from control.config import Settings
from control.factory import build_mineru_clients, build_plane
from control.mineru import MinerUClient
from control.options import RequestRejected
from control.service import ControlPlane
from control.store import utcnow


def create_app(
    plane: ControlPlane,
    engine: MinerUClient,
    reconciler_error: str | None = None,
    engines: list[MinerUClient] | None = None,
) -> FastAPI:
    app = FastAPI(title="ThinkParse", version=__version__)
    pool = engines or [engine]
    app.state.plane = plane
    app.state.engine = engine
    app.state.reconciler_error = reconciler_error
    _register_native(app, plane)

    @app.post("/api/v1/tasks/submit")
    async def submit_task(
        file: UploadFile = File(...),
        backend: str = Form("pipeline"),
        lang: str = Form("ch"),
        method: str = Form("auto"),
        formula_enable: str = Form("true"),
        table_enable: str = Form("true"),
        priority: int = Form(0),
        enable_pagination: str | None = Form(None),
        f_dump_content_list: str | None = Form(None),
        tier: str | None = Form(None),
    ):
        del enable_pagination, f_dump_content_list
        data = await _read_limited(file, plane.settings.max_file_bytes)
        try:
            return plane.submit(
                file.filename or "document.pdf",
                data,
                backend=backend,
                method=method,
                lang=lang,
                formula_enable=formula_enable,
                table_enable=table_enable,
                tier=tier,
                priority=priority,
            )
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @app.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        payload = plane.status_payload(task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="task not found")
        return payload

    @app.delete("/api/v1/tasks/{task_id}")
    async def cancel_task(task_id: str):
        payload = plane.cancel(task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="task not found")
        return payload

    @app.post("/file_parse")
    async def file_parse(
        files: list[UploadFile] = File(...),
        backend: str = Form("pipeline"),
        parse_method: str = Form("auto"),
        lang_list: str = Form("ch"),
        formula_enable: str = Form("true"),
        table_enable: str = Form("true"),
    ):
        file = files[0]
        data = await _read_limited(file, plane.settings.max_file_bytes)
        try:
            submitted = plane.submit(
                file.filename or "document.pdf",
                data,
                backend=backend,
                method=parse_method,
                lang=lang_list.split(",")[0],
                formula_enable=formula_enable,
                table_enable=table_enable,
            )
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        deadline = time.monotonic() + plane.settings.task_timeout_seconds
        while time.monotonic() < deadline:
            payload = plane.status_payload(submitted["task_id"])
            if payload and payload["task"]["status"] in {"completed", "failed", "cancelled"}:
                return payload
            await asyncio.sleep(0.2)
        return JSONResponse(
            status_code=504,
            content={"success": False, "task_id": submitted["task_id"], "error": "timed out waiting for the reconciler"},
        )

    @app.get("/api/v1/queue/stats")
    async def queue_stats():
        return plane.queue_stats()

    @app.get("/api/v1/queue/tasks")
    async def queue_tasks(
        status: str | None = Query(None),
        limit: int = Query(100, le=1000),
    ):
        return plane.queue_tasks(status, limit)

    @app.get("/api/v1/health/live")
    async def live():
        return _health("alive", True)

    @app.get("/api/v1/health")
    async def health():
        ready, components = _ready(plane, pool)
        return JSONResponse(status_code=200 if ready else 503, content=_health("ready" if ready else "not_ready", ready, components))

    @app.get("/api/v1/health/ready")
    async def ready():
        ready_ok, components = _ready(plane, pool)
        return JSONResponse(
            status_code=200 if ready_ok else 503,
            content=_health("ready" if ready_ok else "not_ready", ready_ok, components),
        )

    @app.get("/api/v1/health/deep")
    async def deep():
        ready_ok, components = _ready(plane, pool)
        components.update(_deep_components(plane, pool, app.state.reconciler_error))
        return _health("ready" if ready_ok else "not_ready", ready_ok, components)

    @app.get("/api/v2/stats")
    async def stats(request: Request, window_seconds: int = Query(900, ge=1, le=3600)):
        _require_key(plane, request)
        return plane.fleet_stats(window_seconds, _upstream_views(plane, pool))

    @app.get("/api/v2/batches/{batch_id}")
    async def get_batch(batch_id: str, request: Request):
        _require_key(plane, request)
        payload = plane.batch_summary(batch_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return payload

    @app.get("/api/v2/batches/{batch_id}/jobs")
    async def batch_jobs(
        batch_id: str,
        request: Request,
        status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ):
        _require_key(plane, request)
        payload = plane.batch_jobs(batch_id, status, limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return payload

    @app.delete("/api/v2/batches/{batch_id}")
    async def delete_batch(batch_id: str, request: Request):
        _require_key(plane, request)
        payload = plane.cancel_batch(batch_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return payload

    @app.get("/api/v2/health")
    async def health_v2():
        ready_ok, components = _ready(plane, pool)
        components.update(_deep_components(plane, pool, app.state.reconciler_error))
        return JSONResponse(
            status_code=200 if ready_ok else 503,
            content={
                "status": "ok" if ready_ok else "unavailable",
                "version": __version__,
                "components": components,
            },
        )

    return app


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1 << 20)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail=f"File too large. Maximum size: {limit / (1024 * 1024):.0f}MB")
        chunks.append(chunk)
    return b"".join(chunks)


def _ready(plane: ControlPlane, pool: list[MinerUClient]) -> tuple[bool, dict[str, object]]:
    store_ok = False
    try:
        store_ok = plane.store.ping()
    except Exception:
        store_ok = False
    object_ok = True
    try:
        plane.objects.ensure_capacity(0, 0)
    except Exception:
        object_ok = False
    mineru_ok = any(client.health() for client in pool)
    components = {"task_store": store_ok, "object_store": object_ok, "mineru": mineru_ok}
    return store_ok and object_ok and mineru_ok, components


def _deep_components(plane: ControlPlane, pool: list[MinerUClient], reconciler_error: str | None) -> dict[str, object]:
    failed = plane.store.list_tasks({"failed"}, 1)
    return {
        "mineru_upstreams": [{"healthy": client.health()} for client in pool],
        "tiers": list(plane.tiers.available()),
        "tiers_discovered": plane.tiers.discovered(),
        "inflight": plane.store.inflight_count(),
        "max_inflight": plane.settings.max_inflight,
        "last_error": failed[0].error_message if failed else reconciler_error,
    }


def _upstream_views(plane: ControlPlane, pool: list[MinerUClient]) -> list[dict[str, object]]:
    slots = plane.settings.slot_counts(len(pool))
    reported = plane.tiers.reported()
    views: list[dict[str, object]] = []
    for index, client in enumerate(pool):
        tiers = reported[index] if index < len(reported) and reported[index] is not None else plane.tiers.available()
        views.append(
            {
                "base_url": client.base_url,
                "healthy": client.health(),
                "tiers": list(tiers),
                "slots": slots[index],
            }
        )
    return views


def _health(status: str, success: bool, components: dict[str, object] | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "success": success,
        "status": status,
        "service": "ThinkParse API Server",
        "version": __version__,
        "timestamp": utcnow().isoformat(),
    }
    if components is not None:
        body["components"] = components
    return body


def _register_native(app: FastAPI, plane: ControlPlane) -> None:
    @app.get("/api/v2/tiers")
    async def tiers(request: Request):
        _require_key(plane, request)
        offered = plane.tiers.available()
        return {
            "object": "list",
            "discovered": plane.tiers.discovered(),
            "data": [{"id": tier} for tier in offered],
        }

    @app.post("/api/v2/uploads")
    async def create_upload(request: Request):
        _require_key(plane, request)
        body = await request.json()
        try:
            upload = plane.create_upload(
                str(body["filename"]),
                int(body["bytes"]),
                str(body["mime_type"]),
                body.get("sha256sum"),
            )
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return _upload_body(upload)

    @app.get("/api/v2/uploads/{upload_id}")
    async def get_upload(upload_id: str, request: Request):
        _require_key(plane, request)
        upload = plane.store.get_upload(upload_id)
        if upload is None:
            raise HTTPException(status_code=404, detail="upload not found")
        return _upload_body(upload)

    @app.put("/api/v2/uploads/{upload_id}/content")
    async def upload_content(upload_id: str, request: Request):
        _require_key(plane, request)
        try:
            plane.write_upload(upload_id, await request.body())
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return Response(status_code=200)

    @app.post("/api/v2/uploads/{upload_id}/complete")
    async def complete_upload(upload_id: str, request: Request):
        _require_key(plane, request)
        raw = await request.body()
        sha = None
        if raw:
            sha = json.loads(raw).get("sha256sum")
        try:
            upload = plane.complete_upload(upload_id, sha)
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return _upload_body(upload)

    @app.post("/api/v2/jobs", status_code=202)
    async def create_job(request: Request):
        _require_key(plane, request)
        body = await request.json()
        try:
            file_id = body.get("file_id")
            if not file_id:
                source = body["files"][0]["source"]
                if source.get("type") != "file_id":
                    raise RequestRejected(400, "only file_id sources are accepted")
                file_id = source["file_id"]
            payload = plane.create_native_job(
                str(file_id),
                body.get("tier"),
                str(body.get("ocr_mode") or "auto"),
                None if body.get("batch_id") is None else str(body.get("batch_id")),
                _priority_field(body.get("priority", 0)),
            )
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise HTTPException(status_code=400, detail="invalid job request") from exc
        return payload

    @app.get("/api/v2/jobs")
    async def list_jobs(
        request: Request,
        status: str | None = Query(None),
        limit: int = Query(50, ge=1, le=500),
    ):
        _require_key(plane, request)
        return plane.native_jobs(status, limit)

    @app.get("/api/v2/jobs/{job_id}")
    async def get_job(job_id: str, request: Request):
        _require_key(plane, request)
        payload = plane.native_job(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="job not found")
        return payload

    @app.delete("/api/v2/jobs/{job_id}")
    async def delete_job(job_id: str, request: Request):
        _require_key(plane, request)
        payload = plane.cancel(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {"job_id": job_id, "status": "canceled"}

    @app.get("/api/v2/files/{file_id}")
    async def file_metadata(file_id: str, request: Request):
        _require_key(plane, request)
        record = plane.store.get_file(file_id)
        if record is None:
            raise HTTPException(status_code=404, detail="file not found")
        return {
            "id": record.id,
            "object": "file",
            "filename": record.filename,
            "bytes": record.byte_size,
            "mime_type": record.mime_type,
            "purpose": record.purpose,
            "sha256sum": record.sha256,
        }

    @app.get("/api/v2/files/{file_id}/content")
    async def file_content(file_id: str, request: Request):
        _require_key(plane, request)
        try:
            data, mime = plane.read_file(file_id)
        except RequestRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return Response(content=data, media_type=mime)


def _priority_field(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RequestRejected(400, "priority must be an integer from 0 to 9")
    return value


def _require_key(plane: ControlPlane, request: Request) -> None:
    expected = plane.settings.api_key
    if not expected:
        return
    if request.headers.get("authorization") != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid api key")


def _upload_body(upload) -> dict[str, object]:
    body: dict[str, object] = {
        "id": upload.id,
        "object": "upload",
        "bytes": upload.byte_size,
        "filename": upload.filename,
        "mime_type": upload.mime_type,
        "status": upload.status,
        "sha256sum": upload.sha256,
    }
    if upload.file_id:
        body["file"] = {"id": upload.file_id}
    else:
        body["upload_url"] = f"/api/v2/uploads/{upload.id}/content"
    return body


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    clients = build_mineru_clients(settings)
    settings.slot_counts(len(clients))
    plane = build_plane(settings, clients)
    app = create_app(plane, clients[0], engines=clients)
    uvicorn.run(app, host="0.0.0.0", port=int(__import__("os").getenv("API_PORT", "8000")))


if __name__ == "__main__":
    main()
