"""Delete the oldest local parse data when free space falls under the watermark."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from shared.disk_space import GIB, DiskPolicy, decide, load_policy
from shared.storage import OUTPUT_DIR, STORAGE_TYPE, TEMP_DIR


def _contained_child(root: Path, child: Path) -> bool:
    """True for a real direct child of ``root``. Symlinks are never deleted."""
    if child.is_symlink():
        print(f"  [Skip symlink] {child.name}")
        return False
    try:
        root_resolved = root.resolve()
        child_resolved = child.resolve()
        child_resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        print(f"  [Skip outside root] {child.name}")
        return False
    if child_resolved.parent != root_resolved:
        print(f"  [Skip outside root] {child.name}")
        return False
    return True


def _eligible_children(root: Path, cutoff_ts: float) -> list[tuple[float, Path]]:
    children: list[tuple[float, Path]] = []
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        print(f"  [Error] Cannot list {root}: {exc}")
        return children
    for child in entries:
        try:
            modified = child.stat().st_mtime
        except OSError as exc:
            print(f"  [Error] Cannot access {child.name}: {exc}")
            continue
        if modified <= cutoff_ts and _contained_child(root, child):
            children.append((modified, child))
    children.sort()
    return children


def reclaim_directory(root: Path, policy: DiskPolicy, now: datetime | None = None) -> int:
    """Delete oldest entries in ``root`` until free space is back at the target.

    Entries newer than ``policy.min_age_seconds`` are left in place so an
    in-flight parse is not removed. Returns the number of entries deleted.
    """
    if not root.exists():
        return 0
    moment = now or datetime.now()
    cutoff = moment.timestamp() - policy.min_age_seconds
    try:
        usage = shutil.disk_usage(root)
    except OSError as exc:
        print(f"  [Error] Cannot read disk usage for {root}: {exc}")
        return 0
    decision = decide(usage.total, usage.free, policy)
    if decision.state == "ok":
        return 0

    print(
        f"Disk pressure on {root}: {usage.free / GIB:.1f} GiB free, "
        f"target {decision.reclaim_below_bytes / GIB:.1f} GiB, "
        f"refuse below {decision.reject_below_bytes / GIB:.1f} GiB"
    )
    deleted = 0
    for _modified, child in _eligible_children(root, cutoff):
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            break
        if usage.free >= decide(usage.total, usage.free, policy).reclaim_below_bytes:
            break
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            deleted += 1
            print(f"  [Disk pressure deleted] {child.name}")
        except OSError as exc:
            print(f"  [Delete failed] {child.name}: {exc}")
    if deleted == 0:
        print(
            f"  No entries older than {policy.min_age_seconds / 3600:.1f}h "
            f"to delete under {root}"
        )
    return deleted


def reclaim_under_pressure(policy: DiskPolicy | None = None) -> int:
    """Reclaim ThinkParse output (local storage) and temp directories only."""
    active = policy or load_policy()
    roots: list[Path] = []
    if STORAGE_TYPE == "local":
        roots.append(Path(OUTPUT_DIR))
    roots.append(Path(TEMP_DIR))
    deleted = 0
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deleted += reclaim_directory(root, active)
    return deleted
