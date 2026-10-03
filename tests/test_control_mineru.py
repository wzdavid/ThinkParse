import io
import json
import unittest
import zipfile

from control.mineru import MinerUClient, UpstreamNotFound, UpstreamRejected


class MinerUClientTests(unittest.TestCase):
    def test_submit_uploads_then_creates_job(self) -> None:
        calls: list[tuple[str, str, bytes | None]] = []

        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            calls.append((method, path, body))
            self.assertEqual(headers.get("Authorization"), "Bearer secret")
            if method == "POST" and path == "/v1/uploads":
                payload = json.loads(body or b"{}")
                self.assertEqual(payload["sha256sum"], "abc")
                return 200, json.dumps({"id": "upload_1", "status": "pending"}).encode()
            if method == "PUT" and path == "/v1/uploads/upload_1/content":
                self.assertEqual(body, b"%PDF")
                return 200, b""
            if method == "POST" and path == "/v1/uploads/upload_1/complete":
                return 200, json.dumps({"id": "upload_1", "file": {"id": "file_1"}}).encode()
            if method == "POST" and path == "/v1/parse/jobs":
                payload = json.loads(body or b"{}")
                self.assertEqual(payload["tier"], "basic")
                self.assertEqual(payload["ocr_mode"], "auto")
                self.assertEqual(payload["files"][0]["source"]["file_id"], "file_1")
                self.assertEqual(payload["output_formats"], ["zip"])
                return 202, json.dumps({"job_id": "job_1", "status": "queued"}).encode()
            if method == "GET" and path == "/v1/parse/jobs/job_1":
                return 200, json.dumps(
                    {
                        "job_id": "job_1",
                        "status": "completed",
                        "files": [
                            {
                                "file_id": "file_src",
                                "status": "completed",
                                "output_files": {"zip": {"file_id": "file_zip"}},
                            }
                        ],
                    }
                ).encode()
            if method == "GET" and path == "/v1/files/file_zip/content":
                return 200, _zip(b"# title\n\n![](images/fig1.jpg)\n", {"pages": []}, {"fig1.jpg": b"img"})
            return 500, b""

        client = MinerUClient("http://mineru.test", api_key="secret", transport=transport)
        job_id = client.submit(b"%PDF", "paper.pdf", "abc", "basic", "auto")
        self.assertEqual(job_id, "job_1")
        poll = client.poll(job_id)
        self.assertEqual(poll.source_file_id, "file_src")
        self.assertEqual(poll.engine_file_ids(), ["file_src", "file_zip"])
        native = client.fetch(poll)
        self.assertIn("# title", native.markdown)
        self.assertEqual(native.middle, {"pages": []})
        self.assertEqual(native.images["fig1.jpg"], b"img")
        self.assertIn(("PUT", "/v1/uploads/upload_1/content", b"%PDF"), calls)

    def test_instant_upload_skips_put(self) -> None:
        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            del headers
            if path == "/v1/uploads":
                return 200, json.dumps({"id": "upload_1", "status": "completed", "file": {"id": "file_9"}}).encode()
            if path == "/v1/parse/jobs":
                return 202, json.dumps({"job_id": "job_9"}).encode()
            if method == "PUT":
                raise AssertionError("put should not run when the upload is already complete")
            return 500, b""

        client = MinerUClient("http://mineru.test", transport=transport)
        self.assertEqual(client.submit(b"pdf", "a.pdf", "ff", "basic", "ocr"), "job_9")

    def test_release_files_deletes_ids_and_ignores_missing(self) -> None:
        calls: list[str] = []

        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            del body, headers
            calls.append(f"{method} {path}")
            if path.endswith("file_zip"):
                return 404, b""
            return 200, b"{}"

        client = MinerUClient("http://mineru.test", transport=transport)
        client.release_files(["file_src", "", "file_zip"])
        self.assertEqual(calls, ["DELETE /v1/files/file_src", "DELETE /v1/files/file_zip"])

    def test_missing_job_is_not_found(self) -> None:
        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            del method, path, body, headers
            return 404, json.dumps({"error": {"code": "job_not_found"}}).encode()

        client = MinerUClient("http://mineru.test", transport=transport)
        with self.assertRaises(UpstreamNotFound):
            client.poll("job_missing")

    def test_completed_job_without_zip_is_rejected(self) -> None:
        def transport(method: str, path: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
            del method, body, headers
            if path == "/v1/parse/jobs/job_1":
                return 200, json.dumps({"status": "completed", "files": [{"output_files": {}}]}).encode()
            return 500, b""

        client = MinerUClient("http://mineru.test", transport=transport)
        with self.assertRaises(UpstreamRejected):
            client.fetch(client.poll("job_1"))


def _zip(markdown: bytes, middle: dict, images: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("markdown.md", markdown)
        archive.writestr("middle_json.json", json.dumps(middle))
        for name, data in images.items():
            archive.writestr(f"images/{name}", data)
    return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
