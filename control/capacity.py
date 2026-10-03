"""Choose the next task that fits an upstream slot and the in-flight byte budget."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pending:
    task_id: str
    tier: str
    engine: str
    byte_size: int
    priority: int = 0


@dataclass(frozen=True)
class Slot:
    base_url: str
    slots: int
    inflight: int
    tiers: tuple[str, ...] | None


def choose_assignment(
    pending: list[Pending],
    upstreams: list[Slot],
    inflight_bytes: int,
    byte_limit: int,
    *,
    discovered: bool,
    admit_oversized: bool = True,
) -> tuple[str, str] | None:
    """Return ``(task_id, base_url)``. An empty base URL means Docling.

    ``pending`` is ordered by priority descending; equal priorities keep their
    incoming order (creation time, when the store listed them that way). A job
    that fits a slot but not the byte budget blocks every lower priority; a
    smaller job of the same priority may still run. When nothing is in flight
    and ``admit_oversized`` is set, the first placeable job is admitted so one
    large file cannot sit forever.
    """

    pending = _by_priority(pending)
    chosen = _first_fit(pending, upstreams, inflight_bytes, byte_limit, discovered, enforce_bytes=True)
    if chosen is not None or inflight_bytes > 0 or not admit_oversized:
        return chosen
    return _first_fit(pending, upstreams, inflight_bytes, byte_limit, discovered, enforce_bytes=False)


def _first_fit(
    pending: list[Pending],
    upstreams: list[Slot],
    inflight_bytes: int,
    byte_limit: int,
    discovered: bool,
    *,
    enforce_bytes: bool,
) -> tuple[str, str] | None:
    held: int | None = None
    for job in pending:
        if held is not None and job.priority < held:
            continue
        over_budget = enforce_bytes and inflight_bytes + job.byte_size > byte_limit
        if over_budget and _placeable(job, upstreams, discovered):
            held = job.priority
            continue
        if over_budget:
            continue
        if job.engine == "docling":
            return job.task_id, ""
        url = _pick_url(job.tier, upstreams, discovered)
        if url is not None:
            return job.task_id, url
    return None


def byte_hold_priority(
    pending: list[Pending],
    upstreams: list[Slot],
    inflight_bytes: int,
    byte_limit: int,
    *,
    discovered: bool,
) -> int | None:
    """Priority of the first placeable job that does not fit the byte budget.

    Later pages must not admit a lower priority while this job is still waiting.
    """

    for job in _by_priority(pending):
        if not _placeable(job, upstreams, discovered):
            continue
        if inflight_bytes + job.byte_size > byte_limit:
            return job.priority
        return None
    return None


def _placeable(job: Pending, upstreams: list[Slot], discovered: bool) -> bool:
    if job.engine == "docling":
        return True
    return _pick_url(job.tier, upstreams, discovered) is not None


def _by_priority(pending: list[Pending]) -> list[Pending]:
    return sorted(pending, key=lambda job: -job.priority)


def _pick_url(tier: str, upstreams: list[Slot], discovered: bool) -> str | None:
    eligible = [slot for slot in upstreams if slot.inflight < slot.slots and _serves(slot, tier, discovered)]
    if not eligible:
        return None
    chosen = min(eligible, key=lambda slot: (slot.inflight, slot.base_url))
    return chosen.base_url


def _serves(slot: Slot, tier: str, discovered: bool) -> bool:
    if slot.tiers is None:
        return not discovered
    return tier in slot.tiers
