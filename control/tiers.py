"""Tiers this deployment can serve, discovered from the configured MinerU services."""

from __future__ import annotations

import time
from typing import Callable, Protocol

ALL_TIERS: tuple[str, ...] = ("flash", "basic", "standard", "advanced")


class TierSource(Protocol):
    def tiers(self) -> tuple[str, ...] | None: ...


class TierCatalog:
    """Unions upstream tiers, then keeps only the operator allow-list.

    A tier is offered when any reachable MinerU reports it. Placement still
    sends a job only to an upstream that reported the tier. When no upstream
    answers, the allow-list is used and the reconciler holds the job.
    """

    def __init__(
        self,
        sources: list[TierSource],
        allowed: tuple[str, ...] = ALL_TIERS,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sources = sources
        self.allowed = tuple(tier for tier in ALL_TIERS if tier in allowed)
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._cached: tuple[str, ...] | None = None
        self._per_source: list[tuple[str, ...] | None] = []
        self._discovered = False
        self._expires = 0.0

    def available(self) -> tuple[str, ...]:
        now = self._clock()
        if self._cached is None or now >= self._expires:
            self._cached, self._discovered = self._discover()
            self._expires = now + self.ttl_seconds
        return self._cached

    def discovered(self) -> bool:
        self.available()
        return self._discovered

    def reported(self) -> list[tuple[str, ...] | None]:
        self.available()
        return list(self._per_source)

    def _discover(self) -> tuple[tuple[str, ...], bool]:
        per_source: list[tuple[str, ...] | None] = []
        union: set[str] = set()
        for source in self.sources:
            tiers = source.tiers()
            if tiers is None:
                per_source.append(None)
                continue
            reported = tuple(tier for tier in ALL_TIERS if tier in tiers)
            per_source.append(reported)
            union.update(reported)
        self._per_source = per_source
        if not union:
            return self.allowed, False
        return tuple(tier for tier in self.allowed if tier in union), True


class StaticTiers:
    def __init__(self, allowed: tuple[str, ...] = ALL_TIERS) -> None:
        self.allowed = tuple(tier for tier in ALL_TIERS if tier in allowed)

    def available(self) -> tuple[str, ...]:
        return self.allowed

    def discovered(self) -> bool:
        return False

    def reported(self) -> list[tuple[str, ...] | None]:
        return []
