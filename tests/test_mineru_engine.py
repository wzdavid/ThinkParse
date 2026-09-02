import unittest
from pathlib import Path

from worker.mineru_engine import (
    MinerUEngineCancelled,
    MinerUEngineProcess,
    MinerUEngineTimeout,
)


class FakeRequestQueue:
    def __init__(self):
        self.last = None
        self.closed = False

    def put(self, value):
        self.last = value

    def close(self):
        self.closed = True

    def join_thread(self):
        return None


class FakeResponseQueue:
    def __init__(self, request_queue):
        self.request_queue = request_queue
        self.closed = False

    def get(self, timeout):
        return {
            "request_id": self.request_queue.last["request_id"],
            "success": True,
        }

    def close(self):
        self.closed = True

    def join_thread(self):
        return None


class FakeProcess:
    def __init__(self):
        self.pid = 12345
        self.alive = False
        self.exitcode = None
        self.terminated = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.terminated = True
        self.alive = False
        self.exitcode = -15

    def join(self, timeout):
        return None


class FakeContext:
    def __init__(self):
        self.request_queue = FakeRequestQueue()
        self.response_queue = FakeResponseQueue(self.request_queue)
        self.queue_calls = 0
        self.processes = []

    def Queue(self):
        self.queue_calls += 1
        return self.request_queue if self.queue_calls % 2 == 1 else self.response_queue

    def Process(self, **kwargs):
        process = FakeProcess()
        self.processes.append(process)
        return process


class MinerUEngineProcessTests(unittest.TestCase):
    def create_engine(self):
        context = FakeContext()
        engine = MinerUEngineProcess(process_context=context)
        self.addCleanup(engine.close)
        return engine, context

    def parse(self, engine, cancellation, timeout=10, on_state_change=None):
        engine.parse(
            file_path=Path("/tmp/input.pdf"),
            file_name="input.pdf",
            backend="pipeline",
            options={},
            output_path=Path("/tmp/output"),
            timeout_seconds=timeout,
            is_cancel_requested=cancellation,
            on_state_change=on_state_change,
        )

    def test_success_reuses_engine_process(self):
        engine, context = self.create_engine()

        self.parse(engine, lambda: False)
        self.parse(engine, lambda: False)

        self.assertEqual(len(context.processes), 1)
        self.assertTrue(context.processes[0].is_alive())

    def test_cancellation_terminates_engine(self):
        engine, context = self.create_engine()

        with self.assertRaises(MinerUEngineCancelled):
            self.parse(engine, lambda: True)

        self.assertTrue(context.processes[0].terminated)
        self.assertTrue(context.request_queue.closed)
        self.assertTrue(context.response_queue.closed)

    def test_timeout_terminates_engine(self):
        engine, context = self.create_engine()

        with self.assertRaises(MinerUEngineTimeout):
            self.parse(engine, lambda: False, timeout=0)

        self.assertTrue(context.processes[0].terminated)

    def test_next_task_restarts_engine_after_cancellation(self):
        engine, context = self.create_engine()

        with self.assertRaises(MinerUEngineCancelled):
            self.parse(engine, lambda: True)
        self.parse(engine, lambda: False)

        self.assertEqual(len(context.processes), 2)
        self.assertTrue(context.processes[1].is_alive())

    def test_state_reports_engine_identity_and_restart_count(self):
        engine, _ = self.create_engine()
        states = []

        with self.assertRaises(MinerUEngineCancelled):
            self.parse(engine, lambda: True, on_state_change=states.append)
        self.parse(engine, lambda: False, on_state_change=states.append)

        self.assertEqual(states[-1]["restart_count"], 1)
        self.assertIs(states[-1]["alive"], True)
        self.assertEqual(states[-1]["pid"], 12345)


if __name__ == "__main__":
    unittest.main()
