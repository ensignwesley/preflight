from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class ProbeResult:
    name: str
    kind: str
    status: str
    url: str | None = None
    http_status: int | None = None
    elapsed_ms: int | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_probe(spec: dict[str, Any], timeout: float = 5.0) -> ProbeResult:
    kind = spec.get("kind", "http")
    if kind in {"http", "json"}:
        return http_probe(spec, timeout=timeout)
    return ProbeResult(name=spec.get("name", "unknown"), kind=kind, status="fail", detail=f"unsupported probe kind: {kind}")


def json_path(data: Any, path: str) -> Any:
    """Return a dotted JSON path from nested dictionaries.

    Preflight uses this for small semantic assertions on health endpoints. It is
    intentionally simple: fleet probes only need object fields like ``ok`` or
    ``storage.writable``, not a full JSONPath language.
    """
    value = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def check_json_expectations(data: Any, expectations: dict[str, Any]) -> str | None:
    for path, expected in expectations.items():
        try:
            actual = json_path(data, path)
        except KeyError:
            return f"missing JSON field: {path}"
        if actual != expected:
            return f"JSON field {path}={actual!r}, expected {expected!r}"
    return None


def check_json_freshness(data: Any, freshness: dict[str, Any], now: datetime | None = None) -> str | None:
    """Validate that an ISO-8601 JSON timestamp is recent enough."""
    field = freshness.get("field")
    max_age_seconds = freshness.get("max_age_seconds")
    if not field or max_age_seconds is None:
        return None
    try:
        raw_value = json_path(data, field)
    except KeyError:
        return f"missing freshness field: {field}"
    if not isinstance(raw_value, str):
        return f"freshness field {field} is not a string"
    try:
        timestamp = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        return f"freshness field {field} is not ISO-8601"
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (now - timestamp).total_seconds()
    if age_seconds < 0:
        return f"freshness field {field} is from the future"
    if age_seconds > float(max_age_seconds):
        return f"freshness field {field} is stale ({int(age_seconds)}s > {max_age_seconds}s)"
    return None


def http_probe(spec: dict[str, Any], timeout: float = 5.0) -> ProbeResult:
    name = spec["name"]
    kind = spec.get("kind", "http")
    url = spec["url"]
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": "preflight/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body_bytes = response.read(2_000_000)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            code = response.getcode()
            body = body_bytes.decode("utf-8", errors="replace")
            if not (200 <= code < 300):
                return ProbeResult(name, kind, "fail", url, code, elapsed_ms, f"HTTP {code}")
            if kind == "json":
                try:
                    payload = json.loads(body or "null")
                except json.JSONDecodeError as exc:
                    return ProbeResult(name, kind, "degraded", url, code, elapsed_ms, f"invalid JSON: {exc.msg}")
                detail = check_json_expectations(payload, spec.get("expect_json", {}))
                if detail:
                    return ProbeResult(name, kind, "degraded", url, code, elapsed_ms, detail)
                detail = check_json_freshness(payload, spec.get("expect_fresh", {}))
                if detail:
                    return ProbeResult(name, kind, "degraded", url, code, elapsed_ms, detail)
            expected = spec.get("expect")
            if expected and expected not in body:
                return ProbeResult(name, kind, "degraded", url, code, elapsed_ms, f"missing marker: {expected!r}")
            return ProbeResult(name, kind, "pass", url, code, elapsed_ms)
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(name, kind, "fail", url, exc.code, elapsed_ms, f"HTTP {exc.code}")
    except Exception as exc:  # network and timeout failures should be evidence, not stack traces
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ProbeResult(name, kind, "fail", url, None, elapsed_ms, str(exc))
