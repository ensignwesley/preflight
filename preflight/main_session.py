"""Read-only main-session and scheduled-heartbeat evidence (OpenClaw SQLite)."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .probes import ProbeResult

MAIN_KEY = 'agent:main:main'
HEARTBEAT_ID = '2b16884e-9e1c-4f86-91cf-a58aac5f653f'
ROOT = Path.home() / '.openclaw'
GRACE_MS = 60 * 60 * 1000  # one hour beyond the configured four-hour cadence


def _read(path: Path, sql: str, args: tuple, timeout: float):
    # URI mode=ro refuses to create a missing database or mutate its contents.
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True,
                                 timeout=timeout)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        return conn.execute(sql, args).fetchall()


def main_session_health(timeout: float = 5, *, root: Path = ROOT,
                        now_ms: int | None = None) -> ProbeResult:
    """No model turn is sent. A PASS is metadata + fresh scheduler evidence only."""
    started = time.monotonic()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms

    def result(status, detail):
        return ProbeResult('main-session', 'main-session', status,
                           elapsed_ms=int((time.monotonic() - started) * 1000), detail=detail)

    try:
        nodes = _read(root / 'agents/main/agent/openclaw-agent.sqlite', '''
            SELECT n.current_session_id, n.entry_json, n.entry_valid,
                   n.archived_at, w.session_id AS window_id, w.ended_at
            FROM session_nodes n LEFT JOIN session_windows w
              ON w.session_id = n.current_session_id AND w.session_key = n.session_key
            WHERE n.session_key = ?''', (MAIN_KEY,), timeout)
        if len(nodes) != 1:
            return result('fail', 'main session missing; inspect/reset main through OpenClaw')
        node = nodes[0]
        entry = json.loads(node['entry_json'])
        if not isinstance(entry, dict):
            raise ValueError('entry must be an object')
        recovery = entry.get('mainRestartRecovery', {})
        if isinstance(recovery, dict) and 'tombstone' in recovery:
            return result('fail', 'main session tombstoned during restart recovery; use Resume or /reset through OpenClaw, then verify a successful heartbeat')
        if node['entry_valid'] != 1 or entry.get('sessionId') != node['current_session_id'] or not node['window_id']:
            return result('fail', 'main session entry/window invalid; inspect main lifecycle through OpenClaw')
        if node['archived_at'] is not None or 'archivedAt' in entry or node['ended_at'] is not None:
            return result('fail', 'main session archived/ended; inspect/reset main through OpenClaw')
        if entry.get('initializationPending') or entry.get('providerReview') or 'pendingProjectGitUrl' in entry or 'pendingWorktree' in entry:
            return result('fail', 'main session admission blocked; inspect pending initialization/provider review/workspace in OpenClaw')
        state_db = root / 'state/openclaw.sqlite'
        jobs = _read(state_db, 'SELECT store_key, enabled, job_json, state_json FROM cron_jobs WHERE job_id = ?', (HEARTBEAT_ID,), timeout)
        if len(jobs) != 1:
            return result('fail', 'main heartbeat job missing/ambiguous; inspect scheduler')
        job = jobs[0]
        spec, state = json.loads(job['job_json']), json.loads(job['state_json'])
        schedule = spec['schedule']
        interval = schedule['everyMs']
        if not job['enabled'] or spec.get('enabled') is not True:
            return result('fail', 'main heartbeat disabled; inspect scheduler')
        if spec.get('agentId') != 'main' or spec.get('sessionTarget') != 'main' or spec.get('payload', {}).get('kind') != 'heartbeat' or schedule.get('kind') != 'every' or type(interval) is not int or interval <= 0:
            return result('fail', 'main heartbeat target/cadence changed; inspect scheduler contract')
        receipts = _read(state_db, '''SELECT status, started_at_ms, finished_at_ms
            FROM cron_run_receipts WHERE store_key = ? AND job_id = ?
            ORDER BY started_at_ms DESC LIMIT 1''', (job['store_key'], HEARTBEAT_ID), timeout)
        if not receipts:
            return result('fail', 'main usable; no heartbeat receipt; verify a scheduled heartbeat')
        receipt = receipts[0]
        age = now_ms - receipt['started_at_ms']
        if age < 0:
            return result('fail', 'main usable; heartbeat receipt is future-dated; inspect clock/scheduler')
        if receipt['status'] not in ('ok', 'running') or state.get('lastRunStatus') == 'error':
            why = 'restart recovery rejection' if 'ended during restart recovery' in str(state.get('lastError', '')) else 'scheduler failure'
            return result('fail', f'main usable; last heartbeat unresolved ({why}, receipt={receipt["status"]}); verify a successful scheduled heartbeat before claiming recovery')
        if receipt['status'] == 'running':
            if age > GRACE_MS:
                return result('fail', 'main usable; heartbeat running >1h; inspect stuck run')
            # A running attempt is not recovery proof and cannot hide a prolonged outage.
            successes = _read(state_db, '''SELECT started_at_ms FROM cron_run_receipts
                WHERE store_key = ? AND job_id = ? AND status = 'ok'
                ORDER BY started_at_ms DESC LIMIT 1''', (job['store_key'], HEARTBEAT_ID), timeout)
            if not successes or not 0 <= now_ms - successes[0]['started_at_ms'] <= interval + GRACE_MS:
                return result('fail', 'main usable; heartbeat running but last success stale/missing; await terminal success')
        elif receipt['finished_at_ms'] is None or not receipt['started_at_ms'] <= receipt['finished_at_ms'] <= now_ms:
            return result('fail', 'main usable; heartbeat completion timestamp invalid; inspect scheduler')
        if age > interval + GRACE_MS:
            return result('fail', 'main usable; heartbeat receipt stale (>cadence +1h); inspect scheduler')
        next_run = state.get('nextRunAtMs')
        if type(next_run) is not int:
            return result('fail', 'main usable; heartbeat next-run evidence missing; inspect scheduler')
        if receipt['status'] != 'running' and now_ms > next_run + GRACE_MS:
            return result('fail', 'main usable; heartbeat overdue >1h; inspect scheduler')
        return result('pass', f'main entry/window usable; heartbeat {receipt["status"]}, age={age // 1000}s, cadence={interval // 1000}s (metadata/receipt evidence, not a live turn)')
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        # Never echo database contents, credentials, or arbitrary scheduler errors.
        return result('fail', 'main-session evidence missing/unreadable or schema changed; inspect local OpenClaw SQLite stores')
