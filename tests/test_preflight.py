import json
import unittest
from pathlib import Path

from preflight.cli import latest_record, slug_time, write_record
from preflight.probes import ProbeResult


class PreflightTests(unittest.TestCase):
    def test_slug_time_is_filename_safe(self):
        self.assertEqual(slug_time("2026-07-22T04:20:00Z"), "20260722T042000Z")

    def test_probe_result_serializes(self):
        result = ProbeResult(name="x", kind="http", status="pass", url="https://example.test", http_status=200, elapsed_ms=12)
        self.assertEqual(result.to_dict()["status"], "pass")

    def test_write_and_find_latest_record(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            record = {
                "checked_at": "2026-07-22T04:20:00Z",
                "status": "pass",
                "probes": [],
                "host": {
                    "load": {"load_1": 0, "load_5": 0, "load_15": 0},
                    "memory": {"used_kb": 0, "total_kb": 0},
                    "disks": [],
                },
            }
            path = write_record(record, tmp_path)
            self.assertEqual(latest_record(tmp_path), path)
            self.assertEqual(json.loads(path.read_text())["checked_at"], record["checked_at"])


if __name__ == "__main__":
    unittest.main()
