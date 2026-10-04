import configparser
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKER = ROOT / "docker"
ENTRYPOINT = DOCKER / "entrypoint-allinone.sh"
SUPERVISOR_CONF = DOCKER / "supervisord.allinone.conf"


class AllInOneDeployTests(unittest.TestCase):
    def test_entrypoint_forces_loopback_redis(self):
        text = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('REDIS_URL="redis://127.0.0.1:6379/0"', text)
        self.assertIn("supervisord", text)
        # Use PATH supervisord (pip >=4.2.5); hardcoding Debian's binary breaks on 3.12.
        self.assertRegex(text, r"(?m)^exec supervisord ")
        self.assertNotRegex(text, r"(?m)^exec /usr/bin/supervisord ")

    def test_entrypoint_is_valid_shell(self):
        result = subprocess.run(
            ["sh", "-n", str(ENTRYPOINT)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supervisor_runs_all_four_roles(self):
        parser = configparser.ConfigParser()
        read = parser.read(SUPERVISOR_CONF)
        self.assertEqual(read, [str(SUPERVISOR_CONF)])
        self.assertTrue(parser.getboolean("supervisord", "nodaemon"))
        for program in ("redis", "api", "worker", "cleanup"):
            section = f"program:{program}"
            self.assertIn(section, parser.sections(), section)
            self.assertTrue(parser.getboolean(section, "autorestart"))
        self.assertIn("127.0.0.1", parser.get("program:redis", "command"))
        self.assertIn("api/app.py", parser.get("program:api", "command"))
        self.assertIn("worker/tasks.py", parser.get("program:worker", "command"))
        self.assertTrue(parser.getboolean("program:worker", "stopasgroup"))
        self.assertTrue(parser.getboolean("program:worker", "killasgroup"))

    def test_dockerfiles_and_compose_exist(self):
        gpu = (DOCKER / "Dockerfile.allinone").read_text(encoding="utf-8")
        cpu = (DOCKER / "Dockerfile.allinone.cpu").read_text(encoding="utf-8")
        compose = (DOCKER / "docker-compose.allinone.yml").read_text(encoding="utf-8")
        self.assertIn("FROM mineru-vllm:latest", gpu)
        self.assertIn("entrypoint-allinone.sh", gpu)
        self.assertIn("EXPOSE 8000", gpu)
        self.assertIn("FROM python:3.12-slim", cpu)
        self.assertIn("redis-server", cpu)
        # pip supervisor>=4.2.5 is required on Python 3.12; apt 4.2.1 is not.
        self.assertIn('"supervisor>=4.2.5"', gpu)
        self.assertIn('"supervisor>=4.2.5"', cpu)
        self.assertNotRegex(gpu, r"(?m)^\s*supervisor\s*\\?\s*$")
        self.assertNotRegex(cpu, r"(?m)^\s*supervisor\s*\\?\s*$")
        self.assertIn("profiles: [\"allinone-gpu\"]", compose)
        self.assertIn("profiles: [\"allinone-cpu\"]", compose)
        self.assertIn("mineru-allinone:latest", compose)


if __name__ == "__main__":
    unittest.main()
