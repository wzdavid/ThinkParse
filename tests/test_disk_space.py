import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from shared.disk_space import (
    GIB,
    DiskPolicy,
    StorageEntry,
    capped_reserve,
    decide,
    entries_to_delete,
)


def _policy(**overrides: object) -> DiskPolicy:
    values = {
        "free_min_bytes": 8 * GIB,
        "free_min_percent": 10.0,
        "free_target_bytes": 16 * GIB,
        "free_target_percent": 20.0,
        "min_age_seconds": 3 * 3600,
        "check_interval_minutes": 1,
    }
    values.update(overrides)
    return DiskPolicy(**values)


class DiskReserveTests(unittest.TestCase):
    def test_large_filesystem_uses_absolute_reserves(self):
        total = 378 * GIB
        self.assertEqual(capped_reserve(total, 8 * GIB, 10), 8 * GIB)
        self.assertEqual(capped_reserve(total, 16 * GIB, 20), 16 * GIB)

    def test_huge_filesystem_does_not_reserve_a_percentage(self):
        total = 100 * 1024 * GIB
        self.assertEqual(capped_reserve(total, 8 * GIB, 10), 8 * GIB)
        decision = decide(total, 44 * 1024 * GIB, _policy())
        self.assertEqual(decision.state, "ok")

    def test_small_filesystem_is_capped_by_percent(self):
        total = 20 * GIB
        self.assertEqual(capped_reserve(total, 8 * GIB, 10), 2 * GIB)
        self.assertEqual(capped_reserve(total, 16 * GIB, 20), 4 * GIB)
        decision = decide(total, 5 * GIB, _policy())
        self.assertEqual(decision.state, "ok")
        tight = decide(total, 3 * GIB, _policy())
        self.assertEqual(tight.state, "reclaim")
        blocked = decide(total, 1 * GIB, _policy())
        self.assertEqual(blocked.state, "reject")

    def test_zero_percent_disables_the_cap(self):
        self.assertEqual(capped_reserve(20 * GIB, 8 * GIB, 0), 8 * GIB)

    def test_reclaim_line_is_never_below_the_refuse_line(self):
        policy = _policy(free_target_bytes=1 * GIB, free_target_percent=0)
        decision = decide(100 * GIB, 2 * GIB, policy)
        self.assertGreaterEqual(
            decision.reclaim_below_bytes, decision.reject_below_bytes
        )
        self.assertEqual(decision.state, "reject")


class EntrySelectionTests(unittest.TestCase):
    def test_keeps_recent_entries_and_deletes_oldest_first(self):
        entries = [
            StorageEntry("recent", 2 * 3600, 10 * GIB),
            StorageEntry("oldest", 30 * 3600, 6 * GIB),
            StorageEntry("older", 10 * 3600, 6 * GIB),
        ]
        chosen = entries_to_delete(entries, free_bytes=9 * GIB, reclaim_below_bytes=16 * GIB, min_age_seconds=3 * 3600)
        self.assertEqual([entry.key for entry in chosen], ["oldest", "older"])

    def test_stops_once_projected_free_space_recovers(self):
        entries = [
            StorageEntry("oldest", 30 * 3600, 8 * GIB),
            StorageEntry("older", 10 * 3600, 8 * GIB),
        ]
        chosen = entries_to_delete(entries, free_bytes=10 * GIB, reclaim_below_bytes=16 * GIB, min_age_seconds=3 * 3600)
        self.assertEqual([entry.key for entry in chosen], ["oldest"])

    def test_does_nothing_when_already_above_target(self):
        entries = [StorageEntry("oldest", 30 * 3600, 8 * GIB)]
        chosen = entries_to_delete(entries, free_bytes=20 * GIB, reclaim_below_bytes=16 * GIB, min_age_seconds=3 * 3600)
        self.assertEqual(chosen, [])


class DiskGuardTests(unittest.TestCase):
    def test_pressure_deletes_old_entries_and_keeps_recent_ones(self):
        import tempfile
        from cleanup.disk_guard import reclaim_directory

        with tempfile.TemporaryDirectory() as raw:
            root = __import__("pathlib").Path(raw)
            old = root / "old-task"
            recent = root / "recent-task"
            old.mkdir()
            recent.mkdir()
            old_ts = (datetime.now() - timedelta(hours=5)).timestamp()
            os.utime(old, (old_ts, old_ts))
            policy = _policy(
                free_min_bytes=10**18,
                free_min_percent=0,
                free_target_bytes=10**18,
                free_target_percent=0,
                min_age_seconds=3 * 3600,
            )
            deleted = reclaim_directory(root, policy)
            self.assertEqual(deleted, 1)
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())

    def test_pressure_does_not_follow_symlinks(self):
        import tempfile
        from cleanup.disk_guard import reclaim_directory

        with tempfile.TemporaryDirectory() as raw:
            root = __import__("pathlib").Path(raw)
            outside = root.parent / f"{root.name}-outside"
            outside.mkdir()
            try:
                marker = outside / "keep"
                marker.write_text("keep", encoding="utf-8")
                link = root / "linked"
                link.symlink_to(outside, target_is_directory=True)
                old_ts = (datetime.now() - timedelta(hours=5)).timestamp()
                os.utime(link, (old_ts, old_ts), follow_symlinks=False)
                policy = _policy(
                    free_min_bytes=10**18,
                    free_min_percent=0,
                    free_target_bytes=10**18,
                    free_target_percent=0,
                    min_age_seconds=3 * 3600,
                )
                deleted = reclaim_directory(root, policy)
                self.assertEqual(deleted, 0)
                self.assertTrue(marker.exists())
                self.assertTrue(link.is_symlink())
            finally:
                marker = outside / "keep"
                if marker.exists():
                    marker.unlink()
                outside.rmdir()


class SchedulerTests(unittest.TestCase):
    def test_schedule_runs_cleanup_and_disk_guard_immediately(self):
        import sys
        from unittest.mock import MagicMock

        sys.modules.setdefault("schedule", MagicMock())
        from cleanup.cleanup_scheduler import CleanupScheduler

        calls = []
        scheduler = CleanupScheduler(cleanup_hours=6, extra_hours=2, temp_max_age_hours=6)
        schedule_mock = MagicMock()

        with (
            patch.object(scheduler, "_run_cleanup", lambda: calls.append("cleanup")),
            patch.object(scheduler, "_run_disk_guard", lambda: calls.append("disk")),
            patch("cleanup.cleanup_scheduler.schedule", schedule_mock),
        ):
            scheduler.install_schedule()

        self.assertEqual(calls, ["disk", "cleanup"])
        schedule_mock.every.assert_called_once_with(6)


class PolicyEnvTests(unittest.TestCase):
    def test_interval_is_at_least_one_minute(self):
        from shared.disk_space import load_policy

        with patch.dict(os.environ, {"DISK_CHECK_INTERVAL_MINUTES": "0"}):
            self.assertEqual(load_policy().check_interval_minutes, 1)

    def test_pressure_age_cannot_undercut_task_time_limit(self):
        from shared.disk_space import load_policy

        with (
            patch("shared.celeryconfig.task_time_limit", 7200),
            patch.dict(os.environ, {"DISK_PRESSURE_MIN_AGE_HOURS": "1"}),
        ):
            self.assertGreaterEqual(load_policy().min_age_seconds, 7200)


if __name__ == "__main__":
    unittest.main()
