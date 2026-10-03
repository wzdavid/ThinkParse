"""Environment configuration for the 2.0 gateway and reconciler."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    object_dir: Path
    mineru_base_url: str
    mineru_api_key: str
    max_inflight: int
    max_file_bytes: int
    free_min_bytes: int
    max_attempts: int
    task_timeout_seconds: int
    legacy_allow_flash: bool
    require_postgres: bool
    poll_interval_seconds: float
    http_timeout_seconds: float
    mineru_base_urls: tuple[str, ...] = ()
    docling_base_url: str = ""
    api_key: str = ""
    result_expires_seconds: int = 24 * 3600
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "thinkparse"
    accepted_tiers: tuple[str, ...] = ("flash", "basic", "standard", "advanced")
    slots: tuple[int, ...] = ()
    inflight_byte_limit: int = 1 << 30

    def slot_counts(self, upstreams: int) -> tuple[int, ...]:
        if upstreams <= 0:
            return ()
        if not self.slots:
            return tuple(self.max_inflight for _ in range(upstreams))
        if len(self.slots) == 1:
            return tuple(self.slots[0] for _ in range(upstreams))
        if len(self.slots) != upstreams:
            raise ValueError(f"THINKPARSE_SLOTS has {len(self.slots)} values for {upstreams} MinerU URLs")
        return self.slots

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("THINKPARSE_DATABASE_URL", "").strip(),
            object_dir=Path(os.getenv("THINKPARSE_OBJECT_DIR", "data")),
            mineru_base_url=os.getenv("MINERU_BASE_URL", "http://127.0.0.1:8001").rstrip("/"),
            mineru_api_key=os.getenv("MINERU_API_KEY", "").strip(),
            max_inflight=_env_int("THINKPARSE_MAX_INFLIGHT", 4),
            max_file_bytes=_env_int("MAX_FILE_SIZE", 100 * 1024 * 1024),
            free_min_bytes=_env_int("THINKPARSE_FREE_MIN_BYTES", 8 * 1024**3),
            max_attempts=_env_int("THINKPARSE_MAX_ATTEMPTS", 5),
            task_timeout_seconds=_env_int("THINKPARSE_TASK_TIMEOUT_SECONDS", 7200),
            legacy_allow_flash=_env_bool("LEGACY_ALLOW_FLASH", False),
            require_postgres=_env_bool("THINKPARSE_REQUIRE_POSTGRES", False),
            poll_interval_seconds=float(os.getenv("THINKPARSE_POLL_INTERVAL", "1.0")),
            http_timeout_seconds=float(os.getenv("THINKPARSE_HTTP_TIMEOUT", "60")),
            mineru_base_urls=_mineru_urls(),
            docling_base_url=os.getenv("DOCLING_BASE_URL", "").strip().rstrip("/"),
            api_key=os.getenv("THINKPARSE_API_KEY", "").strip(),
            result_expires_seconds=_env_int("RESULT_EXPIRES_SECONDS", 24 * 3600),
            s3_endpoint=os.getenv("THINKPARSE_S3_ENDPOINT", "").strip().rstrip("/"),
            s3_access_key=os.getenv("THINKPARSE_S3_ACCESS_KEY", "").strip(),
            s3_secret_key=os.getenv("THINKPARSE_S3_SECRET_KEY", "").strip(),
            s3_bucket=os.getenv("THINKPARSE_S3_BUCKET", "thinkparse").strip() or "thinkparse",
            accepted_tiers=_accepted_tiers(),
            slots=_parse_slots(),
            inflight_byte_limit=_env_int("THINKPARSE_INFLIGHT_BYTE_LIMIT", 1 << 30),
        )


_ALL_TIERS = ("flash", "basic", "standard", "advanced")


def _accepted_tiers() -> tuple[str, ...]:
    raw = os.getenv("THINKPARSE_ACCEPTED_TIERS", "").strip()
    if not raw:
        return _ALL_TIERS
    tiers = {part.strip().lower() for part in raw.split(",") if part.strip()}
    accepted = tuple(tier for tier in _ALL_TIERS if tier in tiers)
    if not accepted:
        raise ValueError(f"THINKPARSE_ACCEPTED_TIERS has no known tier: {raw!r}")
    return accepted


def _parse_slots() -> tuple[int, ...]:
    raw = os.getenv("THINKPARSE_SLOTS", "").strip()
    if not raw:
        return ()
    slots = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not slots or any(slot <= 0 for slot in slots):
        raise ValueError(f"THINKPARSE_SLOTS must be positive integers: {raw!r}")
    return slots


def _mineru_urls() -> tuple[str, ...]:
    raw = os.getenv("MINERU_BASE_URLS", "").strip()
    if raw:
        return tuple(part.strip().rstrip("/") for part in raw.split(",") if part.strip())
    return (os.getenv("MINERU_BASE_URL", "http://127.0.0.1:8001").strip().rstrip("/"),)
