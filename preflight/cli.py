from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fleet import DEFAULT_FLEET
from .host import capture_host
from .probes import run_probe

DEFAULT_RECORD_DIR = Path.home() / ".local" / "share" / "preflight" / "records"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug_time(ts: str) -> str:
    return ts.replace(":", "").replace("-", "").replace("Z", "Z")


def build_record(timeout: float) -> dict[str, Any]:
    checked_at = utc_now()
    probes = [run_probe(spec, timeout=timeout).to_dict() for spec in DEFAULT_FLEET]
    status = "pass"
    if any(p["status"] == "fail" for p in probes):
        status = "fail"
    elif any(p["status"] == "degraded" for p in probes):
        status = "degraded"
    return {"tool": "preflight", "version": "0.1.0", "checked_at": checked_at, "status": status, "probes": probes, "host": capture_host()}


def write_record(record: dict[str, Any], record_dir: Path) -> Path:
    record_dir.mkdir(parents=True, exist_ok=True)
    path = record_dir / f"{slug_time(record['checked_at'])}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def print_report(record: dict[str, Any], path: Path | None = None) -> None:
    print(f"preflight {record['status'].upper()} {record['checked_at']}")
    for probe in record["probes"]:
        elapsed = f"{probe['elapsed_ms']}ms" if probe.get("elapsed_ms") is not None else "n/a"
        detail = f" — {probe['detail']}" if probe.get("detail") else ""
        print(f"[{probe['status']}] {probe['name']} ({elapsed}){detail}")
    host = record["host"]
    mem = host["memory"]
    print(f"host load={host['load']['load_1']:.2f}/{host['load']['load_5']:.2f}/{host['load']['load_15']:.2f} mem_used={mem['used_kb']//1024}MB/{mem['total_kb']//1024}MB")
    for disk in host["disks"]:
        print(f"disk {disk['mount']} used={disk['used_pct']}% free={disk['free_bytes']//(1024*1024)}MB")
    if path:
        print(f"record: {path}")


def latest_record(record_dir: Path) -> Path | None:
    if not record_dir.exists():
        return None
    records = sorted(record_dir.glob("*.json"))
    return records[-1] if records else None


def cmd_record(args: argparse.Namespace) -> int:
    record = build_record(timeout=args.timeout)
    path = write_record(record, args.record_dir)
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print_report(record, path)
    return 0 if record["status"] == "pass" else 1


def cmd_last(args: argparse.Namespace) -> int:
    path = latest_record(args.record_dir)
    if path is None:
        print(f"no records found in {args.record_dir}")
        return 2
    record = json.loads(path.read_text(encoding="utf-8"))
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print_report(record, path)
    return 0 if record["status"] == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preflight", description="Fleet health recorder")
    parser.add_argument("--record-dir", type=Path, default=DEFAULT_RECORD_DIR)
    parser.add_argument("--timeout", type=float, default=5.0)
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="check fleet and write a timestamped evidence record")
    p_record.add_argument("--json", action="store_true", help="print JSON instead of compact report")
    p_record.add_argument("--timeout", type=float, default=None, help="per-probe timeout in seconds")
    p_record.set_defaults(func=cmd_record)

    p_check = sub.add_parser("check", help="check fleet without changing the interface contract; currently aliases record")
    p_check.add_argument("--json", action="store_true", help="print JSON instead of compact report")
    p_check.add_argument("--timeout", type=float, default=None, help="per-probe timeout in seconds")
    p_check.set_defaults(func=cmd_record)

    p_last = sub.add_parser("last", help="show the most recent record")
    p_last.add_argument("--json", action="store_true", help="print JSON instead of compact report")
    p_last.set_defaults(func=cmd_last)

    args = parser.parse_args(argv)
    if getattr(args, "timeout", None) is None:
        args.timeout = parser.get_default("timeout")
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
