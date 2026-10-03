"""Wire the store and object directory from the environment."""

from __future__ import annotations

from control.config import Settings
from control.docling import DoclingClient
from control.mineru import MinerUClient
from control.objects import LocalObjectStore, ObjectStore, S3ObjectStore
from control.service import ControlPlane
from control.store import MemoryStore, PostgresStore, TaskStore
from control.tiers import TierCatalog


def open_store(settings: Settings) -> TaskStore:
    if settings.database_url:
        return PostgresStore(settings.database_url)
    if settings.require_postgres:
        raise RuntimeError("THINKPARSE_DATABASE_URL is required when THINKPARSE_REQUIRE_POSTGRES is set")
    return MemoryStore()


def open_objects(settings: Settings) -> ObjectStore:
    if settings.s3_endpoint:
        return S3ObjectStore(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key,
            settings.s3_bucket,
        )
    settings.object_dir.mkdir(parents=True, exist_ok=True)
    return LocalObjectStore(settings.object_dir)


def build_plane(settings: Settings, clients: list[MinerUClient] | None = None) -> ControlPlane:
    tiers = None if clients is None else TierCatalog(list(clients), settings.accepted_tiers)
    return ControlPlane(open_store(settings), open_objects(settings), settings, tiers)


def build_mineru_clients(settings: Settings) -> list[MinerUClient]:
    urls = settings.mineru_base_urls or (settings.mineru_base_url,)
    return [
        MinerUClient(url, api_key=settings.mineru_api_key, timeout=settings.http_timeout_seconds)
        for url in urls
    ]


def build_docling_client(settings: Settings) -> DoclingClient | None:
    if not settings.docling_base_url:
        return None
    return DoclingClient(settings.docling_base_url, timeout=settings.http_timeout_seconds)
