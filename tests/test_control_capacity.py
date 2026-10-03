import unittest

from control.capacity import Pending, Slot, choose_assignment


def _job(task_id: str, size: int, tier: str = "basic", engine: str = "mineru", priority: int = 0) -> Pending:
    return Pending(task_id=task_id, tier=tier, engine=engine, byte_size=size, priority=priority)


class CapacityTests(unittest.TestCase):
    def test_skips_a_large_task_when_a_smaller_one_fits(self) -> None:
        upstreams = [Slot("http://gpu", slots=2, inflight=0, tiers=("basic",))]
        choice = choose_assignment(
            [_job("large", 20), _job("small", 4)],
            upstreams,
            inflight_bytes=0,
            byte_limit=10,
            discovered=True,
        )
        self.assertEqual(choice, ("small", "http://gpu"))

    def test_admits_an_oversized_task_when_the_queue_is_idle(self) -> None:
        upstreams = [Slot("http://gpu", slots=1, inflight=0, tiers=("basic",))]
        choice = choose_assignment(
            [_job("large", 20)],
            upstreams,
            inflight_bytes=0,
            byte_limit=5,
            discovered=True,
        )
        self.assertEqual(choice, ("large", "http://gpu"))

    def test_does_not_send_standard_to_a_cpu_upstream(self) -> None:
        upstreams = [
            Slot("http://cpu", slots=1, inflight=0, tiers=("flash", "basic")),
            Slot("http://gpu", slots=1, inflight=0, tiers=("flash", "basic", "standard", "advanced")),
        ]
        choice = choose_assignment(
            [_job("one", 1, tier="standard"), _job("two", 1, tier="standard")],
            upstreams,
            inflight_bytes=0,
            byte_limit=100,
            discovered=True,
        )
        self.assertEqual(choice, ("one", "http://gpu"))
        busy = [
            Slot("http://cpu", slots=1, inflight=0, tiers=("flash", "basic")),
            Slot("http://gpu", slots=1, inflight=1, tiers=("flash", "basic", "standard", "advanced")),
        ]
        self.assertIsNone(
            choose_assignment([_job("two", 1, tier="standard")], busy, 1, 100, discovered=True)
        )

    def test_higher_priority_is_chosen_before_an_earlier_job(self) -> None:
        upstreams = [Slot("http://gpu", slots=1, inflight=0, tiers=("basic",))]
        choice = choose_assignment(
            [_job("low", 1, priority=0), _job("high", 1, priority=5)],
            upstreams,
            inflight_bytes=0,
            byte_limit=100,
            discovered=True,
        )
        self.assertEqual(choice, ("high", "http://gpu"))

    def test_same_priority_keeps_arrival_order(self) -> None:
        upstreams = [Slot("http://gpu", slots=1, inflight=0, tiers=("basic",))]
        choice = choose_assignment(
            [_job("first", 1, priority=3), _job("second", 1, priority=3)],
            upstreams,
            inflight_bytes=0,
            byte_limit=100,
            discovered=True,
        )
        self.assertEqual(choice, ("first", "http://gpu"))

    def test_lower_priority_small_file_does_not_pass_a_blocked_higher_job(self) -> None:
        upstreams = [Slot("http://gpu", slots=1, inflight=0, tiers=("basic",))]
        choice = choose_assignment(
            [_job("high-large", 20, priority=5), _job("low-small", 4, priority=0)],
            upstreams,
            inflight_bytes=8,
            byte_limit=10,
            discovered=True,
        )
        self.assertIsNone(choice)

    def test_fills_the_upstream_with_fewer_jobs(self) -> None:
        upstreams = [
            Slot("http://a", slots=2, inflight=1, tiers=("basic",)),
            Slot("http://b", slots=2, inflight=0, tiers=("basic",)),
        ]
        choice = choose_assignment([_job("next", 1)], upstreams, 1, 100, discovered=True)
        self.assertEqual(choice, ("next", "http://b"))


if __name__ == "__main__":
    unittest.main()
