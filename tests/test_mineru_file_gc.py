"""Router source copies expire unless a queued or running job still needs them."""

from __future__ import annotations

import importlib.util
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _load():
    path = Path(__file__).resolve().parents[1] / "docker" / "mineru_file_gc.py"
    spec = importlib.util.spec_from_file_location("mineru_file_gc", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("mineru_file_gc.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gc = _load()


@dataclass
class Route:
    public_id: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Registry:
    def __init__(self) -> None:
        self.routes: dict[str, list[Route]] = {"file": [], "upload": [], "job": []}

    def list(self, kind: str, owner_scope: str | None = None) -> list[Route]:
        del owner_scope
        return list(self.routes[kind])

    def remove(self, kind: str, public_id: str) -> None:
        self.routes[kind] = [route for route in self.routes[kind] if route.public_id != public_id]


class SourceStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.discarded: list[str] = []

    def delete_file(self, file_id: str) -> None:
        self.deleted.append(file_id)

    def discard_upload(self, upload_id: str) -> None:
        self.discarded.append(upload_id)


class RouterSweepTests(unittest.TestCase):
    def test_old_idle_sources_are_removed_and_running_inputs_stay(self) -> None:
        registry = Registry()
        registry.routes["file"] = [
            Route("file-old", "2020-01-01T00:00:00Z"),
            Route("file-live", "2020-01-01T00:00:00Z"),
            Route("file-fresh", "2099-01-01T00:00:00Z"),
        ]
        registry.routes["upload"] = [Route("upload_old", "2020-01-01T00:00:00Z")]
        registry.routes["job"] = [
            Route(
                "job_1",
                "2020-01-01T00:00:00Z",
                metadata={
                    "active_counted": True,
                    "payload": {"status": "running", "files": [{"file_id": "file-live"}]},
                },
            )
        ]
        source = SourceStore()
        removed = gc.sweep_router_sources(registry, source, now=1_800_000_000, older_than=60)
        self.assertEqual(removed, 2)
        self.assertEqual(source.deleted, ["file-old"])
        self.assertEqual(source.discarded, ["upload_old"])
        self.assertEqual([route.public_id for route in registry.routes["file"]], ["file-live", "file-fresh"])

    def test_zero_retention_keeps_every_source(self) -> None:
        registry = Registry()
        registry.routes["file"] = [Route("file-old", "2020-01-01T00:00:00Z")]
        source = SourceStore()
        removed = gc.sweep_router_sources(registry, source, now=1_800_000_000, older_than=0)
        self.assertEqual(removed, 0)
        self.assertEqual(source.deleted, [])


if __name__ == "__main__":
    unittest.main()
