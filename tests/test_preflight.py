import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from preflight.cli import build_record, format_status_counts, iter_records, latest_record, limited_records, slug_time, status_counts, write_record
from preflight.coverage import coverage_gaps, derive_proxied_locations, parse_observatory_targets, run_coverage_probe
from preflight.fleet import DEFAULT_FLEET
from preflight.host import reboot_required
from preflight.probes import ProbeResult, check_body_markers, check_content_type, check_headers, check_json_array_item_keys, check_json_array_names, check_json_expectations, check_json_freshness, check_json_object_keys, check_latency_threshold, json_path, run_probe


class PreflightTests(unittest.TestCase):
    def test_nginx_include_graph_derives_only_public_proxied_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "conf.d").mkdir()
            (root / "nginx.conf").write_text("http { include conf.d/*.conf; }\n", encoding="utf-8")
            (root / "conf.d" / "site.conf").write_text(
                """
                server {
                    location / { root /srv/www; }
                    location /api { proxy_pass http://127.0.0.1:4100; }
                    location /socket { proxy_pass http://127.0.0.1:4100/ws; }
                    location @fallback { proxy_pass http://127.0.0.1:4998; }
                    location /private { internal; proxy_pass http://127.0.0.1:4999; }
                    # location /commented { proxy_pass http://127.0.0.1:4997; }
                }
                """,
                encoding="utf-8",
            )
            self.assertEqual(
                derive_proxied_locations(root / "nginx.conf", include_root=root),
                [
                    {"location": "/api", "upstream": "http://127.0.0.1:4100"},
                    {"location": "/socket", "upstream": "http://127.0.0.1:4100/ws"},
                ],
            )

    def test_observatory_targets_are_parsed_without_executing_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "checker.py"
            source.write_text(
                "TARGETS = [{'slug': 'api', 'url': 'http://127.0.0.1:4100/health'}]\n"
                "raise RuntimeError('must not execute')\n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_observatory_targets(source),
                [{"slug": "api", "url": "http://127.0.0.1:4100/health"}],
            )

    def test_coverage_matches_backend_endpoint_and_reports_gaps(self):
        locations = [
            {"location": "/api", "upstream": "http://127.0.0.1:4100"},
            {"location": "/socket", "upstream": "http://127.0.0.1:4100/ws"},
            {"location": "/missing", "upstream": "http://127.0.0.1:4200"},
        ]
        targets = [{"slug": "api", "url": "http://127.0.0.1:4100/health"}]
        self.assertEqual(
            coverage_gaps(locations, targets),
            [{"location": "/missing", "upstream": "http://127.0.0.1:4200"}],
        )

    def test_coverage_probe_turns_red_then_green_when_target_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nginx = root / "nginx.conf"
            checker = root / "checker.py"
            nginx.write_text(
                "server { location /throwaway { proxy_pass http://127.0.0.1:4321; } }\n",
                encoding="utf-8",
            )
            checker.write_text("TARGETS = []\n", encoding="utf-8")
            red = run_coverage_probe(nginx, checker, include_root=root)
            self.assertEqual(red.status, "fail")
            self.assertIn("/throwaway", red.detail)

            checker.write_text(
                "TARGETS = [{'slug': 'throwaway', 'url': 'http://127.0.0.1:4321/health'}]\n",
                encoding="utf-8",
            )
            green = run_coverage_probe(nginx, checker, include_root=root)
            self.assertEqual(green.status, "pass")
            self.assertIn("1 proxied location(s) covered", green.detail)

    def test_slug_time_is_filename_safe(self):
        self.assertEqual(slug_time("2026-07-22T04:20:00Z"), "20260722T042000Z")

    def test_status_counts_summarize_probe_outcomes(self):
        record = {"probes": [{"status": "pass"}, {"status": "degraded"}, {"status": "fail"}, {"status": "pass"}]}
        counts = status_counts(record)
        self.assertEqual(counts, {"pass": 2, "degraded": 1, "fail": 1})
        self.assertEqual(format_status_counts(counts), "2 pass, 1 degraded, 1 fail")

    def test_probe_result_serializes(self):
        result = ProbeResult(name="x", kind="http", status="pass", url="https://example.test", http_status=200, elapsed_ms=12)
        self.assertEqual(result.to_dict()["status"], "pass")

    def test_default_fleet_includes_public_app_surfaces(self):
        by_name = {spec["name"]: spec for spec in DEFAULT_FLEET}
        for name in ["dead-drop-ui", "dead-chat-ui", "comments-ui", "promotion-review"]:
            self.assertIn(name, by_name)
            self.assertEqual(by_name[name]["kind"], "http")
        self.assertIn("Secret Message", by_name["dead-drop-ui"]["expect_all"])
        self.assertIn("Callsign", by_name["dead-chat-ui"]["expect_all"])
        self.assertEqual(by_name["dead-chat-ws"]["kind"], "websocket")
        self.assertEqual(by_name["dead-chat-ws"]["url"], "wss://wesley.thesisko.com/chat/ws")
        self.assertEqual(by_name["forth-ws"]["kind"], "websocket")
        self.assertEqual(by_name["forth-ws"]["send_text"], "2 3 + .")
        self.assertEqual(by_name["forth-ws"]["expect_text"], "5  ok")
        self.assertEqual(by_name["comments-ui"]["request_headers"], {"Accept": "text/html"})
        self.assertIn("Public endpoints", by_name["comments-ui"]["expect_all"])

    def test_default_fleet_includes_promotion_review_surface_and_status_api(self):
        by_name = {spec["name"]: spec for spec in DEFAULT_FLEET}
        self.assertIn("promotion-review", by_name)
        self.assertIn("promotion-review-status", by_name)
        self.assertEqual(by_name["promotion-review"]["url"], "https://wesley.thesisko.com/promotion-review/")
        self.assertEqual(by_name["promotion-review-status"]["expect_json"]["service"], "promotion-review")

    def test_default_fleet_covers_command_news_contract_and_rosters(self):
        by_name = {spec["name"]: spec for spec in DEFAULT_FLEET}
        self.assertEqual(
            by_name["command-news-feed"]["expect_array_item_keys"]["keys"],
            ["title", "url", "source", "publishedAt", "fetchedAt"],
        )
        self.assertEqual(len(by_name["command-news-status"]["expect_object_keys"]["keys"]), 18)
        self.assertEqual(by_name["command-news-health"]["expect_json"], {"healthy": True})
        self.assertEqual(by_name["command-news-health"]["url"], "https://wesley.thesisko.com/command-news/health.json")
        self.assertIn("Command News Feed", by_name["status-data"]["expect_array_names"]["names"])
        self.assertIn("command-news", by_name["observatory-api"]["expect_object_keys"]["keys"])

    def test_websocket_probe_rejects_non_websocket_scheme(self):
        result = run_probe({"name": "bad-ws", "kind": "websocket", "url": "https://example.test/ws"})
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.detail, "unsupported websocket scheme: https")

    def test_json_expectations_check_nested_fields(self):
        payload = {"ok": True, "service": "demo", "storage": {"readable": True}}
        self.assertEqual(json_path(payload, "storage.readable"), True)
        self.assertIsNone(check_json_expectations(payload, {"ok": True, "storage.readable": True}))
        self.assertEqual(check_json_expectations(payload, {"service": "other"}), "JSON field service='demo', expected 'other'")
        self.assertEqual(check_json_expectations(payload, {"storage.writable": True}), "missing JSON field: storage.writable")

    def test_body_markers_check_required_public_copy(self):
        body = "Reports from the Frontline with Dead Drop and DEAD//CHAT"
        self.assertIsNone(check_body_markers(body, "Reports", ["Dead Drop", "DEAD//CHAT"]))
        self.assertEqual(check_body_markers(body, "Missing", []), "missing marker: 'Missing'")
        self.assertEqual(check_body_markers(body, None, ["Dead Drop", "Forth REPL"]), "missing marker: 'Forth REPL'")

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

    def test_json_array_names_flags_roster_drift(self):
        rule = {"field": "services", "names": ["Blog", "Dead Drop", "Status"]}
        payload = {"services": [{"name": "Status"}, {"name": "Blog"}, {"name": "Dead Drop"}]}
        self.assertIsNone(check_json_array_names(payload, rule))
        self.assertEqual(
            check_json_array_names({"services": [{"name": "Blog"}, {"name": "Status"}, {"name": "Ghost"}]}, rule),
            "JSON array services names mismatch (missing Dead Drop; extra Ghost)",
        )
        self.assertEqual(check_json_array_names({}, rule), "missing JSON array: services")
        self.assertEqual(check_json_array_names({"services": "Blog"}, rule), "JSON field services is not an array")

    def test_json_object_keys_flags_roster_drift(self):
        rule = {"field": "services", "keys": ["blog", "dead-drop", "status"]}
        payload = {"services": {"status": {}, "blog": {}, "dead-drop": {}}}
        self.assertIsNone(check_json_object_keys(payload, rule))
        self.assertEqual(
            check_json_object_keys({"services": {"blog": {}, "status": {}, "ghost": {}}}, rule),
            "JSON object services names mismatch (missing dead-drop; extra ghost)",
        )
        self.assertEqual(check_json_object_keys({}, rule), "missing JSON object: services")
        self.assertEqual(check_json_object_keys({"services": []}, rule), "JSON field services is not an object")

    def test_json_array_item_keys_enforces_exact_contract(self):
        rule = {"keys": ["title", "url"], "min_items": 1}
        self.assertIsNone(check_json_array_item_keys([{"title": "News", "url": "https://example.test"}], rule))
        self.assertEqual(check_json_array_item_keys({}, rule), "JSON root is not an array")
        self.assertEqual(check_json_array_item_keys([], rule), "JSON root has 0 items, expected at least 1")
        self.assertEqual(
            check_json_array_item_keys([{"title": "News", "extra": True}], rule),
            "JSON root[0] object names mismatch (missing url; extra extra)",
        )

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

    def test_header_expectations_check_security_directives(self):
        headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'self'; object-src 'none'"}
        self.assertIsNone(check_headers(headers, {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "object-src 'none'"}))
        self.assertIsNone(check_headers(headers, {"x-content-type-options": "nosniff"}))
        self.assertEqual(check_headers(headers, {"Referrer-Policy": "no-referrer"}), "missing header: Referrer-Policy")
        self.assertEqual(
            check_headers(headers, {"Content-Security-Policy": "frame-ancestors 'self'"}),
            'header Content-Security-Policy="default-src \'self\'; object-src \'none\'", expected to contain "frame-ancestors \'self\'"',
        )

    def test_reboot_required_reports_marker_file_presence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "reboot-required"
            self.assertFalse(reboot_required(str(marker)))
            marker.write_text("restart required\n", encoding="utf-8")
            self.assertTrue(reboot_required(str(marker)))

    def test_record_includes_reboot_required_signal(self):
        record = build_record(timeout=0.001)
        self.assertIn("reboot_required", record["host"])
        self.assertIsInstance(record["host"]["reboot_required"], bool)

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
