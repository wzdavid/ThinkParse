"""Reconciler process. The gateway does not start this loop."""

from __future__ import annotations

import logging
import time

from control.config import Settings
from control.factory import build_docling_client, build_mineru_clients, build_plane
from control.reconcile import Reconciler
from control.tiers import TierCatalog


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    clients = build_mineru_clients(settings)
    settings.slot_counts(len(clients))
    plane = build_plane(settings, clients)
    reconciler = Reconciler(
        plane.store,
        plane.objects,
        clients[0],
        max_inflight=settings.max_inflight,
        max_attempts=settings.max_attempts,
        docling=build_docling_client(settings),
        mineru_pool=clients,
        task_timeout_seconds=settings.task_timeout_seconds,
        result_expires_seconds=settings.result_expires_seconds,
        slots=settings.slot_counts(len(clients)),
        inflight_byte_limit=settings.inflight_byte_limit,
        tiers=TierCatalog(list(clients), settings.accepted_tiers),
    )
    while True:
        worked = reconciler.run_once()
        time.sleep(0.05 if worked else settings.poll_interval_seconds)


if __name__ == "__main__":
    main()
