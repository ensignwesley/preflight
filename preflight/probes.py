from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
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
                    json.loads(body or "null")
                except json.JSONDecodeError as exc:
                    return ProbeResult(name, kind, "degraded", url, code, elapsed_ms, f"invalid JSON: {exc.msg}")
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
