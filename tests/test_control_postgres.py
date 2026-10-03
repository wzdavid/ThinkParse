"""PostgreSQL task store. Skips unless THINKPARSE_TEST_DATABASE_URL is set."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from control.config import Settings
from control.objects import LocalObjectStore
from control.reconcile import Reconciler
from control.service import ControlPlane
from control.store import PostgresStore
from test_control_reconcile import FakeMinerU

URL = os.getenv(
    "THINKPARSE_TEST_DATABASE_URL",
    "postgresql://thinkparse:thinkparse@127.0.0.1:54329/thinkparse",
)


def _postgres_up() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    try:
        with psycopg.connect(URL, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


@unittest.skipUnless(_postgres_up(), "Postgres is not reachable at THINKPARSE_TEST_DATABASE_URL")
class PostgresStoreTests(unittest.TestCase):
    def test_task_survives_a_new_connection(self) -> None:
        with TemporaryDirectory() as tmp:
            settings = Settings(
                database_url=URL,
                object_dir=Path(tmp),
                mineru_base_url="http://mineru.test",
                mineru_api_key="",
                max_inflight=2,
                max_file_bytes=1024 * 1024,
                free_min_bytes=0,
                max_attempts=3,
                task_timeout_seconds=30,
                legacy_allow_flash=False,
                require_postgres=True,
                poll_interval_seconds=0.01,
                http_timeout_seconds=1,
            )
            import psycopg

            with psycopg.connect(URL) as conn:
                conn.execute("DROP TABLE IF EXISTS artifacts, files, uploads, tasks, blobs CASCADE")
                conn.commit()
            store = PostgresStore(URL)
            objects = LocalObjectStore(Path(tmp))
            plane = ControlPlane(store, objects, settings)
            engine = FakeMinerU()
            reconciler = Reconciler(store, objects, engine, max_inflight=2, max_attempts=3)
            created = plane.submit("paper.pdf", b"%PDF-postgres")
            reconciler.run_once()
            reopened = PostgresStore(URL)
            task = reopened.get_task(created["task_id"])
            assert task is not None
            self.assertEqual(task.status, "running")
            self.assertEqual(task.upstream_job_id, "job_1")
            reconciler.store = reopened
            reconciler.run_once()
            payload = ControlPlane(reopened, objects, settings).status_payload(created["task_id"])
            assert payload is not None
            self.assertEqual(payload["task"]["status"], "completed")
            self.assertTrue(payload["content_list"])
            self.assertNotIn("schema", payload["middle_json"])


if __name__ == "__main__":
    unittest.main()
