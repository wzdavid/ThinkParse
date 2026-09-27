import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docker" / "render-gpu-workers.py"
GPU_UP = ROOT / "docker" / "gpu-up.sh"


class RenderGpuWorkersTests(unittest.TestCase):
    def render(self, gpu_count: str, workers_per_gpu: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(SCRIPT),
                "--gpu-count",
                gpu_count,
                "--workers-per-gpu",
                workers_per_gpu,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_two_gpus_four_workers_pin_index_zero(self):
        result = self.render("2", "4")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout
        self.assertEqual(text.count("container_name:"), 8)
        self.assertEqual(text.count("CUDA_VISIBLE_DEVICES=0"), 8)
        self.assertNotIn("CUDA_VISIBLE_DEVICES=1", text)
        self.assertEqual(text.count('device_ids: ["0"]'), 4)
        self.assertEqual(text.count('device_ids: ["1"]'), 4)
        self.assertIn("container_name: mineru-worker-gpu-0-0", text)
        self.assertIn("WORKER_NAME=mineru-gpu-1-3", text)
        self.assertEqual(text.count('profiles: ["mineru-multi-gpu"]'), 8)
        self.assertIn("WORKER_CONCURRENCY=${GPU_WORKER_CONCURRENCY:-1}", text)
        self.assertRegex(text, r"(?m)^    container_name: mineru-worker-gpu-0-0$")
        self.assertNotRegex(text, r"(?m)^    container_name: mineru-worker-gpu-0$")

    def test_cleanup_matches_container_name_exactly(self):
        script = GPU_UP.read_text(encoding="utf-8")
        self.assertIn("container_name: ${name}$", script)
        self.assertIn("docker compose config --quiet", script)

    def test_rejects_zero_and_over_cap(self):
        zero = self.render("0", "1")
        self.assertNotEqual(zero.returncode, 0)
        huge = self.render("2", "33")
        self.assertNotEqual(huge.returncode, 0)

    def test_gpu_up_shell_syntax(self):
        result = subprocess.run(
            ["sh", "-n", str(GPU_UP)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
