import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from preflight.cli import iter_records, latest_record, limited_records, slug_time, write_record
from preflight.probes import ProbeResult, check_content_type, check_json_expectations, check_json_freshness, check_latency_threshold, json_path


class PreflightTests(unittest.TestCase):
    def test_slug_time_is_filename_safe(self):
        self.assertEqual(slug_time("2026-07-22T04:20:00Z"), "20260722T042000Z")

    def test_probe_result_serializes(self):
        result = ProbeResult(name="x", kind="http", status="pass", url="https://example.test", http_status=200, elapsed_ms=12)
        self.assertEqual(result.to_dict()["status"], "pass")

    def test_json_expectations_check_nested_fields(self):
        payload = {"ok": True, "service": "demo", "storage": {"readable": True}}
        self.assertEqual(json_path(payload, "storage.readable"), True)
        self.assertIsNone(check_json_expectations(payload, {"ok": True, "storage.readable": True}))
        self.assertEqual(check_json_expectations(payload, {"service": "other"}), "JSON field service='demo', expected 'other'")
        self.assertEqual(check_json_expectations(payload, {"storage.writable": True}), "missing JSON field: storage.writable")

    def test_json_freshness_flags_stale_status_data(self):
        now = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
        fresh = {"generated_at": "2026-08-01T08:50:00+00:00"}
        stale = {"generated_at": "2026-08-01T08:44:59+00:00"}
        rule = {"field": "generated_at", "max_age_seconds": 900}
        self.assertIsNone(check_json_freshness(fresh, rule, now=now))
        self.assertEqual(
            check_json_freshness(stale, rule, now=now),
            "freshness field generated_at is stale (901s > 900s)",
        )
        self.assertEqual(check_json_freshness({}, rule, now=now), "missing freshness field: generated_at")

    def test_latency_threshold_flags_slow_probe(self):
        self.assertIsNone(check_latency_threshold(999, 1000))
        self.assertEqual(check_latency_threshold(1001, 1000), "elapsed 1001ms exceeds 1000ms budget")
        self.assertIsNone(check_latency_threshold(5000, None))
        self.assertIsNone(check_latency_threshold(5000, "not-a-number"))

    def test_content_type_check_ignores_parameters(self):
        self.assertIsNone(check_content_type("application/json; charset=utf-8", "application/json"))
        self.assertEqual(check_content_type("text/html", "application/json"), "content-type text/html, expected application/json")
        self.assertEqual(check_content_type(None, "application/json"), "content-type missing, expected application/json")
        self.assertIsNone(check_content_type("text/html", None))

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
            self.assertEqual(iter_records(tmp_path), [path])
            self.assertEqual(json.loads(path.read_text())["checked_at"], record["checked_at"])

    def test_iter_records_missing_dir_is_empty(self):
        self.assertEqual(iter_records(Path("/tmp/preflight-missing-test-dir-should-not-exist")), [])

    def test_limited_records_returns_newest_records(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            records = []
            for minute in range(3):
                record = {
                    "checked_at": f"2026-07-22T04:2{minute}:00Z",
                    "status": "pass",
                    "probes": [],
                    "host": {
                        "load": {"load_1": 0, "load_5": 0, "load_15": 0},
                        "memory": {"used_kb": 0, "total_kb": 0},
                        "disks": [],
                    },
                }
                records.append(write_record(record, tmp_path))
            self.assertEqual(limited_records(tmp_path, 2), records[-2:])
            self.assertEqual(limited_records(tmp_path, 0), records[-1:])


if __name__ == "__main__":
    unittest.main()
