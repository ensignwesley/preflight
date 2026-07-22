from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace").strip()


def loadavg() -> dict[str, float]:
    one, five, fifteen, *_ = _read("/proc/loadavg").split()
    return {"load_1": float(one), "load_5": float(five), "load_15": float(fifteen)}


def memory() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in _read("/proc/meminfo").splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"total_kb": total, "available_kb": available, "used_kb": max(total - available, 0)}


def disks() -> list[dict[str, Any]]:
    mounts = []
    seen = set()
    for mount in ("/", "/home"):
        if mount in seen or not Path(mount).exists():
            continue
        seen.add(mount)
        usage = shutil.disk_usage(mount)
        mounts.append({
            "mount": mount,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_pct": round((usage.used / usage.total) * 100, 2) if usage.total else None,
        })
    return mounts


def top_processes(limit: int = 8) -> list[dict[str, Any]]:
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid,pcpu,pmem,rss,comm,args", "--sort=-pcpu"],
            text=True,
            timeout=3,
        )
    except Exception as exc:
        return [{"error": str(exc)}]
    rows = []
    for line in out.splitlines()[1 : limit + 1]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, cpu, mem, rss, comm, args = parts
        rows.append({"pid": int(pid), "cpu_pct": float(cpu), "mem_pct": float(mem), "rss_kb": int(rss), "comm": comm, "args": args[:240]})
    return rows


def capture_host() -> dict[str, Any]:
    return {
        "hostname": os.uname().nodename,
        "load": loadavg(),
        "memory": memory(),
        "disks": disks(),
        "top_processes": top_processes(),
    }
