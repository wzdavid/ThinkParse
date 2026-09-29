"""Filesystem headroom for local parse data.

The defaults are absolute free-space reserves, capped to a percentage of the
filesystem so a small disk is not asked to keep more free space than it has.
They are not sized for any one server. Age-based retention (RESULT_EXPIRES)
still decides when results expire; this module only keeps the process from
filling the disk and stopping Redis.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from shared.storage import OUTPUT_DIR, STORAGE_TYPE, TEMP_DIR

GIB = 1024 ** 3

# Refuse new work when free space is below this, unless the cap percentage
# is smaller (small disks).
DEFAULT_FREE_MIN_BYTES = 8 * GIB
DEFAULT_FREE_MIN_PERCENT = 10.0
# Start deleting the oldest eligible data before the refuse line.
DEFAULT_FREE_TARGET_BYTES = 16 * GIB
DEFAULT_FREE_TARGET_PERCENT = 20.0
# Stay above TASK_TIME_LIMIT (2h) so an in-flight parse is not removed.
DEFAULT_PRESSURE_MIN_AGE_HOURS = 3.0
DEFAULT_CHECK_INTERVAL_MINUTES = 1


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class DiskPolicy:
    free_min_bytes: int
    free_min_percent: float
    free_target_bytes: int
    free_target_percent: float
    min_age_seconds: float
    check_interval_minutes: int


@dataclass(frozen=True)
class DiskDecision:
    state: str
    free_bytes: int
    total_bytes: int
    used_percent: float
    reject_below_bytes: int
    reclaim_below_bytes: int


@dataclass(frozen=True)
class StorageEntry:
    key: str
    age_seconds: float
    size_bytes: int


class StorageCapacityExceeded(Exception):
    """Raised when free space is below the reclaim watermark."""

    def __init__(self, decision: DiskDecision):
        self.decision = decision
        free_gib = decision.free_bytes / GIB
        target_gib = decision.reclaim_below_bytes / GIB
        super().__init__(
            "Insufficient storage: "
            f"{free_gib:.1f} GiB free; new work waits until {target_gib:.1f} GiB is free. "
            "ThinkParse is deleting the oldest results to recover space."
        )


def load_policy() -> DiskPolicy:
    """Read watermarks from the environment on each call."""
    from shared.celeryconfig import task_time_limit

    minutes = _env_int("DISK_CHECK_INTERVAL_MINUTES", DEFAULT_CHECK_INTERVAL_MINUTES)
    configured_age = _env_float(
        "DISK_PRESSURE_MIN_AGE_HOURS", DEFAULT_PRESSURE_MIN_AGE_HOURS
    )
    if configured_age < 0:
        configured_age = DEFAULT_PRESSURE_MIN_AGE_HOURS
    # Never delete a directory that can still belong to a running parse.
    min_age_seconds = max(configured_age * 3600, float(task_time_limit))
    return DiskPolicy(
        free_min_bytes=_env_int("DISK_FREE_MIN_BYTES", DEFAULT_FREE_MIN_BYTES),
        free_min_percent=_env_float("DISK_FREE_MIN_PERCENT", DEFAULT_FREE_MIN_PERCENT),
        free_target_bytes=_env_int("DISK_FREE_TARGET_BYTES", DEFAULT_FREE_TARGET_BYTES),
        free_target_percent=_env_float(
            "DISK_FREE_TARGET_PERCENT", DEFAULT_FREE_TARGET_PERCENT
        ),
        min_age_seconds=min_age_seconds,
        check_interval_minutes=max(1, minutes),
    )


def capped_reserve(total_bytes: int, absolute_bytes: int, percent: float) -> int:
    """Absolute reserve, limited to ``percent`` of ``total_bytes``.

    A non-positive percent disables the cap and returns the absolute reserve.
    """
    absolute = max(0, absolute_bytes)
    if total_bytes <= 0 or percent <= 0:
        return absolute
    by_percent = int(total_bytes * percent / 100)
    return min(absolute, by_percent)


def decide(total_bytes: int, free_bytes: int, policy: DiskPolicy | None = None) -> DiskDecision:
    """Classify free space as ok, reclaim, or reject."""
    active = policy or load_policy()
    total = max(0, total_bytes)
    free = max(0, free_bytes)
    used = max(0, total - free)
    used_percent = (used * 100 / total) if total else 0.0
    reject_below = capped_reserve(total, active.free_min_bytes, active.free_min_percent)
    reclaim_below = capped_reserve(
        total, active.free_target_bytes, active.free_target_percent
    )
    if reclaim_below < reject_below:
        reclaim_below = reject_below
    if free < reject_below:
        state = "reject"
    elif free < reclaim_below:
        state = "reclaim"
    else:
        state = "ok"
    return DiskDecision(
        state=state,
        free_bytes=free,
        total_bytes=total,
        used_percent=round(used_percent, 2),
        reject_below_bytes=reject_below,
        reclaim_below_bytes=reclaim_below,
    )


def entries_to_delete(
    entries: list[StorageEntry],
    free_bytes: int,
    reclaim_below_bytes: int,
    min_age_seconds: float,
) -> list[StorageEntry]:
    """Oldest entries past ``min_age_seconds`` until projected free space recovers."""
    if free_bytes >= reclaim_below_bytes:
        return []
    eligible = [entry for entry in entries if entry.age_seconds >= min_age_seconds]
    eligible.sort(key=lambda entry: entry.age_seconds, reverse=True)
    chosen: list[StorageEntry] = []
    projected = free_bytes
    for entry in eligible:
        if projected >= reclaim_below_bytes:
            break
        chosen.append(entry)
        projected += max(0, entry.size_bytes)
    return chosen


def monitored_paths() -> list[Path]:
    """Directories whose filesystem can stop ThinkParse if it fills up."""
    paths = [Path(TEMP_DIR)]
    if STORAGE_TYPE == "local":
        paths.append(Path(OUTPUT_DIR))
    else:
        paths.append(Path(tempfile.gettempdir()))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def worst_decision(policy: DiskPolicy | None = None) -> DiskDecision | None:
    """Most severe decision across monitored paths. None when nothing is measurable."""
    active = policy or load_policy()
    decisions: list[DiskDecision] = []
    for path in monitored_paths():
        if not path.exists():
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        decisions.append(decide(usage.total, usage.free, active))
    if not decisions:
        return None
    rank = {"ok": 0, "reclaim": 1, "reject": 2}
    return max(decisions, key=lambda item: rank[item.state])


def raise_if_storage_full(policy: DiskPolicy | None = None) -> None:
    """Stop new work once free space is under the reclaim line, not only at the floor.

    In-flight parses can still finish in the reserve. Waiting until the refuse
    line lets those writes consume the last free bytes and stop Redis.
    """
    decision = worst_decision(policy)
    if decision is not None and decision.state != "ok":
        raise StorageCapacityExceeded(decision)
