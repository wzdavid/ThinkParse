"""HTTP client for a MinerU 4.0 api-server or router."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib import error, request

from control.bundle import BundleError, open_result_zip


class UpstreamUnavailable(Exception):
    """MinerU did not answer or returned a retryable failure."""


class UpstreamNotFound(Exception):
    """The upstream job id is gone. The control plane may resubmit."""


class UpstreamRejected(Exception):
    """MinerU refused the request. Resubmitting the same request will not help."""


Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]


@dataclass
class UpstreamPoll:
    status: str
    error_message: str | None = None
    markdown_file_id: str | None = None
    middle_file_id: str | None = None
    zip_file_id: str | None = None
    source_file_id: str | None = None
    job_id: str | None = None

    def engine_file_ids(self) -> list[str]:
        found: list[str] = []
        for item in (self.source_file_id, self.zip_file_id, self.markdown_file_id, self.middle_file_id):
            if item and item not in found:
                found.append(item)
        return found


@dataclass
class NativeArtifacts:
    markdown: str
    middle: dict[str, Any] | None
    content_list: list[Any] | None = None
    document: dict[str, Any] | None = None
    images: dict[str, bytes] = field(default_factory=dict)


class MinerUClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 60,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport

    def health(self) -> bool:
        try:
            status, _ = self._request("GET", "/v1/health", None, {})
        except UpstreamUnavailable:
            return False
        return 200 <= status < 300

    def tiers(self) -> tuple[str, ...] | None:
        try:
            status, payload = self._request("GET", "/v1/tiers", None, {})
        except (UpstreamUnavailable, UpstreamNotFound):
            return None
        if not 200 <= status < 300:
            return None
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return None
        return tuple(str(item["id"]) for item in data if isinstance(item, dict) and item.get("id"))

    def submit(self, data: bytes, filename: str, sha256: str, tier: str, ocr_mode: str) -> str:
        mime = "application/pdf" if filename.lower().endswith(".pdf") else "application/octet-stream"
        created = self._json(
            "POST",
            "/v1/uploads",
            {
                "filename": filename,
                "bytes": len(data),
                "mime_type": mime,
                "purpose": "parse",
                "sha256sum": sha256,
            },
        )
        file_id = _file_id(created)
        if file_id is None:
            upload_id = str(created["id"])
            self._request(
                "PUT",
                f"/v1/uploads/{upload_id}/content",
                data,
                {"Content-Type": "application/octet-stream"},
            )
            completed = self._json("POST", f"/v1/uploads/{upload_id}/complete", {"sha256sum": sha256})
            file_id = _file_id(completed)
        if not file_id:
            raise UpstreamUnavailable("MinerU upload did not return a file id")
        job = self._json(
            "POST",
            "/v1/parse/jobs",
            {
                "files": [{"source": {"type": "file_id", "file_id": file_id}}],
                "tier": tier,
                "ocr_mode": ocr_mode,
                "output_formats": ["zip"],
            },
        )
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise UpstreamUnavailable("MinerU did not return job_id")
        return job_id

    def poll(self, job_id: str) -> UpstreamPoll:
        body = self._json("GET", f"/v1/parse/jobs/{job_id}", None)
        status = str(body.get("status") or "")
        message = None
        markdown_id = None
        middle_id = None
        zip_id = None
        source_id = None
        files = body.get("files") or []
        if isinstance(files, list) and files:
            first = files[0] if isinstance(files[0], dict) else {}
            if isinstance(first.get("file_id"), str):
                source_id = first["file_id"]
            error = first.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            elif isinstance(error, str):
                message = error
            outputs = first.get("output_files") or {}
            if isinstance(outputs, dict):
                markdown_id = _ref_id(outputs.get("markdown"))
                middle_id = _ref_id(outputs.get("middle_json"))
                zip_id = _ref_id(outputs.get("zip"))
        if status == "partial":
            status = "failed"
            message = message or "MinerU job finished partial"
        return UpstreamPoll(
            status=status,
            error_message=message,
            markdown_file_id=markdown_id,
            middle_file_id=middle_id,
            zip_file_id=zip_id,
            source_file_id=source_id,
        )

    def fetch(self, poll: UpstreamPoll) -> NativeArtifacts:
        if not poll.zip_file_id:
            raise UpstreamRejected("MinerU result zip is missing")
        try:
            bundle = open_result_zip(self._download(poll.zip_file_id))
        except BundleError as exc:
            raise UpstreamRejected(str(exc)) from exc
        return NativeArtifacts(markdown=bundle.markdown, middle=bundle.middle, images=dict(bundle.images))

    def release_files(self, file_ids: list[str]) -> None:
        """Drop MinerU scratch files. Missing ids are already gone."""
        for file_id in file_ids:
            if not file_id:
                continue
            try:
                self._request("DELETE", f"/v1/files/{file_id}", None, {})
            except (UpstreamUnavailable, UpstreamNotFound, UpstreamRejected):
                continue

    def cancel(self, job_id: str) -> None:
        try:
            self._request("DELETE", f"/v1/parse/jobs/{job_id}", None, {})
        except UpstreamNotFound:
            return

    def _download(self, file_id: str) -> bytes:
        status, payload = self._request("GET", f"/v1/files/{file_id}/content", None, {})
        if status >= 400:
            raise UpstreamUnavailable(f"failed to download {file_id}: HTTP {status}")
        return payload

    def _json(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        raw = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if raw is not None else {}
        status, payload = self._request(method, path, raw, headers)
        if not payload:
            return {}
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise UpstreamUnavailable(f"MinerU {path} returned a non-object")
        if status in {408, 409, 425, 429}:
            raise UpstreamUnavailable(f"MinerU {path} HTTP {status}: {parsed}")
        if status >= 400:
            raise UpstreamRejected(f"MinerU {path} HTTP {status}: {_error_message(parsed)}")
        return parsed

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None,
        headers: dict[str, str],
    ) -> tuple[int, bytes]:
        sent = dict(headers)
        if self.api_key:
            sent["Authorization"] = f"Bearer {self.api_key}"
        if self._transport is not None:
            status, payload = self._transport(method, path, body, sent)
            if status == 404:
                raise UpstreamNotFound(path)
            if status >= 500:
                raise UpstreamUnavailable(f"MinerU HTTP {status}")
            return status, payload
        req = request.Request(self.base_url + path, data=body, headers=sent, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.status, response.read()
        except error.HTTPError as exc:
            payload = exc.read()
            if exc.code == 404:
                raise UpstreamNotFound(path) from exc
            if exc.code >= 500:
                raise UpstreamUnavailable(f"MinerU HTTP {exc.code}") from exc
            return exc.code, payload
        except error.URLError as exc:
            raise UpstreamUnavailable(str(exc.reason)) from exc


def _error_message(payload: dict[str, Any]) -> str:
    error_obj = payload.get("error")
    if isinstance(error_obj, dict) and error_obj.get("message"):
        return str(error_obj["message"])
    if payload.get("detail"):
        return str(payload["detail"])
    return json.dumps(payload, ensure_ascii=False)[:500]


def _file_id(payload: dict[str, Any]) -> str | None:
    file_obj = payload.get("file")
    if isinstance(file_obj, dict) and isinstance(file_obj.get("id"), str):
        return file_obj["id"]
    if isinstance(payload.get("file_id"), str):
        return payload["file_id"]
    return None


def _ref_id(value: Any) -> str | None:
    if isinstance(value, dict) and isinstance(value.get("file_id"), str):
        return value["file_id"]
    if isinstance(value, str):
        return value
    return None
