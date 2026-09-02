import os
import subprocess
import sys
import unittest


class CeleryConfigTests(unittest.TestCase):
    def import_config(self, **overrides):
        environment = os.environ.copy()
        environment.update(overrides)
        return subprocess.run(
            [sys.executable, "-c", "import shared.celeryconfig"],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_valid_timeout_order_is_accepted(self):
        result = self.import_config(
            TASK_TIME_LIMIT="7200",
            MINERU_ENGINE_TIMEOUT_SECONDS="7200",
            WORKER_WATCHDOG_TIMEOUT_SECONDS="7500",
            BROKER_VISIBILITY_TIMEOUT_SECONDS="9000",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_watchdog_must_exceed_engine_timeout(self):
        result = self.import_config(
            MINERU_ENGINE_TIMEOUT_SECONDS="7200",
            WORKER_WATCHDOG_TIMEOUT_SECONDS="7200",
            BROKER_VISIBILITY_TIMEOUT_SECONDS="9000",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WORKER_WATCHDOG_TIMEOUT_SECONDS", result.stderr)

    def test_visibility_must_exceed_watchdog_timeout(self):
        result = self.import_config(
            MINERU_ENGINE_TIMEOUT_SECONDS="7200",
            WORKER_WATCHDOG_TIMEOUT_SECONDS="7500",
            BROKER_VISIBILITY_TIMEOUT_SECONDS="7500",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BROKER_VISIBILITY_TIMEOUT_SECONDS", result.stderr)

    def test_result_expiry_must_outlive_task_redelivery(self):
        result = self.import_config(
            MINERU_ENGINE_TIMEOUT_SECONDS="7200",
            WORKER_WATCHDOG_TIMEOUT_SECONDS="7500",
            BROKER_VISIBILITY_TIMEOUT_SECONDS="9000",
            RESULT_EXPIRES="9000",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESULT_EXPIRES", result.stderr)


if __name__ == "__main__":
    unittest.main()
