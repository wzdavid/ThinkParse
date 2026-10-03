"""HTTP client for an external docling-serve process."""

from __future__ import annotations

import base64
import json
from typing import Any

from control.mineru import (
    NativeArtifacts,
    Transport,
    UpstreamNotFound,
    UpstreamPoll,
    UpstreamRejected,
    UpstreamUnavailable,
)


class DoclingClient:
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
            status, _ = self._request("GET", "/health", None, {})
        except UpstreamUnavailable:
            return False
        return 200 <= status < 300

    def submit(self, data: bytes, filename: str, sha256: str, tier: str, ocr_mode: str) -> str:
        del sha256, tier, ocr_mode
        created = self._json(
            "POST",
            "/v1/convert/source/async",
            {
                "file_sources": [
                    {"base64_string": base64.b64encode(data).decode("ascii"), "filename": filename}
                ],
                "options": {"to_formats": ["md", "json"]},
            },
        )
        task_id = created.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise UpstreamUnavailable("docling-serve did not return task_id")
        return task_id

    def poll(self, job_id: str) -> UpstreamPoll:
        body = self._json("GET", f"/v1/status/poll/{job_id}", None)
        raw = str(body.get("task_status") or "")
        mapped = {"pending": "queued", "started": "running", "success": "completed", "failure": "failed"}.get(raw, raw)
        message = None
        meta = body.get("task_meta")
        if isinstance(meta, dict):
            message = str(meta.get("error") or "") or None
        return UpstreamPoll(status=mapped, error_message=message, job_id=job_id)

    def fetch(self, poll: UpstreamPoll) -> NativeArtifacts:
        if not poll.job_id:
            raise UpstreamUnavailable("docling poll is missing job_id")
        body = self._json("GET", f"/v1/result/{poll.job_id}", None)
        document = body.get("document") if isinstance(body.get("document"), dict) else body
        if not isinstance(document, dict):
            raise UpstreamUnavailable("docling result is not an object")
        markdown = document.get("md_content") if isinstance(document.get("md_content"), str) else ""
        json_content = document.get("json_content")
        if not isinstance(json_content, dict):
            json_content = document if document.get("texts") or document.get("body") else None
        if not isinstance(json_content, dict):
            raise UpstreamUnavailable("docling result has no json_content")
        return NativeArtifacts(markdown=markdown, middle=None, document=json_content)

    def cancel(self, job_id: str) -> None:
        del job_id

    def _json(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        raw = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"} if raw is not None else {}
        status, payload = self._request(method, path, raw, headers)
        if status in {408, 409, 425, 429}:
            raise UpstreamUnavailable(f"docling {path} HTTP {status}")
        if status >= 400:
            raise UpstreamRejected(f"docling {path} HTTP {status}")
        if not payload:
            return {}
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise UpstreamUnavailable(f"docling {path} returned a non-object")
        return parsed

    def _request(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
        sent = dict(headers)
        if self.api_key:
            sent["X-Api-Key"] = self.api_key
        if self._transport is not None:
            status, payload = self._transport(method, path, body, sent)
            if status == 404:
                raise UpstreamNotFound(path)
            if status >= 500:
                raise UpstreamUnavailable(f"docling HTTP {status}")
            return status, payload
        from urllib import error, request

        req = request.Request(self.base_url + path, data=body, headers=sent, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.status, response.read()
        except error.HTTPError as exc:
            if exc.code == 404:
                raise UpstreamNotFound(path) from exc
            if exc.code >= 500:
                raise UpstreamUnavailable(f"docling HTTP {exc.code}") from exc
            return exc.code, exc.read()
        except error.URLError as exc:
            raise UpstreamUnavailable(str(exc.reason)) from exc
