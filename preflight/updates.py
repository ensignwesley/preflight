"""Local update evidence. No sudo, apt refresh, upgrades, or service mutations."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

GRACE = 36 * 3600  # permits one nightly upgrade/reboot window, with margin
STATE = Path.home() / '.local/share/preflight/update-health.json'


def command(argv, timeout):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise RuntimeError(f'{argv[0]} exited {result.returncode}: {result.stderr.strip()[:160]}')
    return result.stdout


def log_result(text, now):
    """Only trust a terminal outcome in the most recent real (not dry) run."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if 'Starting unattended upgrades script' in line]
    if not starts:
        return 'unattended log has no run start'
    run = lines[starts[-1]:]
    try:
        stamp = datetime.strptime(run[0][:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 'unattended log timestamp unrecognized'
    if not 0 <= now - stamp <= GRACE:
        return 'last unattended run is stale (>36h) or future-dated'
    if any(re.search(r'\b(ERROR|WARNING)\b|dry.run', line, re.I) for line in run):
        return 'latest unattended run contains errors/warnings or is a dry run'
    if not any('All upgrades installed' in line or
               'No packages found that can be upgraded unattended' in line for line in run):
        return 'latest unattended run lacks terminal success evidence'
    return None


def journal_result(text, now):
    entries = [json.loads(line) for line in text.splitlines() if line.strip()]
    # Service-manager finish/failure records, not default systemctl Result=success.
    outcomes = [e for e in entries if e.get('UNIT') == 'apt-daily-upgrade.service'
                and (e.get('JOB_TYPE') == 'start' or e.get('UNIT_RESULT'))]
    if not outcomes:
        return 'unattended log unreadable; apt-daily-upgrade journal has no accessible outcome'
    last = outcomes[-1]
    age = now - int(last['__REALTIME_TIMESTAMP']) / 1_000_000
    if not 0 <= age <= GRACE:
        return 'last apt-daily-upgrade journal outcome is stale (>36h) or future-dated'
    if last.get('JOB_RESULT') != 'done' and last.get('UNIT_RESULT') != 'success':
        return 'latest apt-daily-upgrade journal outcome is not successful'
    return None


def update_health(timeout=5.0, *, state=STATE, now=None,
                  reboot=Path('/var/run/reboot-required'),
                  apt_stamp=Path('/var/lib/apt/periodic/update-success-stamp'),
                  log=Path('/var/log/unattended-upgrades/unattended-upgrades.log')):
    from .probes import ProbeResult
    started = time.monotonic()
    now = time.time() if now is None else now
    problems = []
    details = []
    try:
        output = command(['apt', 'list', '--upgradable'], timeout)
        packages = sorted(line.strip() for line in output.splitlines() if '/' in line and line.strip())
        previous = json.loads(state.read_text()) if state.exists() else {}
        pending = {pkg: previous.get(pkg, now) for pkg in packages}
        if any(not isinstance(t, (int, float)) or t > now for t in pending.values()):
            raise ValueError('invalid pending-package first-seen evidence')
        stale = [pkg for pkg, first in pending.items() if now - first > GRACE]
        state.parent.mkdir(parents=True, exist_ok=True)
        temporary = state.with_suffix('.tmp')
        temporary.write_text(json.dumps(pending, sort_keys=True) + '\n')
        temporary.replace(state)
        details.append(f'{len(packages)} upgradable ({len(stale)} older than 36h)')
        if stale:
            problems.append('stale upgrades: ' + ', '.join(stale)[:300])
        if not apt_stamp.exists() or not 0 <= now - apt_stamp.stat().st_mtime <= GRACE:
            problems.append('APT successful index refresh missing/stale (>36h)')
        if reboot.exists():
            age = now - reboot.stat().st_mtime
            details.append(f'reboot pending {age / 3600:.1f}h')
            if not 0 <= age <= GRACE:
                problems.append('stale or future-dated reboot-required marker')
        else:
            details.append('no reboot pending')
        try:
            issue = log_result(log.read_text(errors='replace'), now)
            source = 'unattended log'
        except OSError:
            issue = journal_result(command(['journalctl', '-u', 'apt-daily-upgrade',
                                           '--since', '48 hours ago', '-n', '200',
                                           '-o', 'json', '--no-pager', '-q'], timeout), now)
            source = 'apt-daily-upgrade journal'
        if issue:
            problems.append(issue)
        else:
            details.append(f'last run succeeded ({source}, <36h)')
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        problems.append(f'update evidence unavailable: {exc}')
    return ProbeResult(name='os-updates', kind='local', status='degraded' if problems else 'pass',
                       elapsed_ms=int((time.monotonic() - started) * 1000),
                       detail='; '.join(details + problems))
