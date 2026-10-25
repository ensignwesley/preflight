import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from preflight.main_session import HEARTBEAT_ID, GRACE_MS, main_session_health
from preflight.probes import ProbeResult
from preflight.watchdog import check, send_alert

NOW = 1792905600000
INTERVAL = 14400000


class MainSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.agent = self.root / 'agents/main/agent/openclaw-agent.sqlite'
        self.state = self.root / 'state/openclaw.sqlite'
        self.agent.parent.mkdir(parents=True)
        self.state.parent.mkdir(parents=True)
        self.entry = {'sessionId': 'live'}
        with sqlite3.connect(self.agent) as c:
            c.executescript('''CREATE TABLE session_nodes (session_key TEXT, current_session_id TEXT, entry_json TEXT, entry_valid INTEGER, archived_at INTEGER);
                CREATE TABLE session_windows (session_id TEXT, session_key TEXT, ended_at INTEGER);''')
            c.execute('INSERT INTO session_nodes VALUES (?, ?, ?, 1, NULL)', ('agent:main:main', 'live', json.dumps(self.entry)))
            c.execute('INSERT INTO session_windows VALUES (?, ?, NULL)', ('live', 'agent:main:main'))
        self.spec = {'enabled': True, 'agentId': 'main', 'sessionTarget': 'main', 'payload': {'kind': 'heartbeat'}, 'schedule': {'kind': 'every', 'everyMs': INTERVAL}}
        self.scheduler = {'lastRunStatus': 'ok', 'nextRunAtMs': NOW + INTERVAL}
        with sqlite3.connect(self.state) as c:
            c.executescript('''CREATE TABLE cron_jobs (store_key TEXT, job_id TEXT, enabled INTEGER, job_json TEXT, state_json TEXT);
                CREATE TABLE cron_run_receipts (store_key TEXT, job_id TEXT, status TEXT, started_at_ms INTEGER, finished_at_ms INTEGER);''')
            c.execute('INSERT INTO cron_jobs VALUES (?, ?, 1, ?, ?)', ('store', HEARTBEAT_ID, json.dumps(self.spec), json.dumps(self.scheduler)))
            c.execute('INSERT INTO cron_run_receipts VALUES (?, ?, ?, ?, ?)', ('store', HEARTBEAT_ID, 'ok', NOW - 60000, NOW - 30000))

    def health(self):
        return main_session_health(root=self.root, now_ms=NOW)

    def entry_update(self):
        with sqlite3.connect(self.agent) as c:
            c.execute('UPDATE session_nodes SET entry_json=?', (json.dumps(self.entry),))

    def scheduler_update(self):
        with sqlite3.connect(self.state) as c:
            c.execute('UPDATE cron_jobs SET job_json=?, state_json=?', (json.dumps(self.spec), json.dumps(self.scheduler)))

    def test_healthy_is_read_only_metadata_and_receipts(self):
        before = (self.agent.read_bytes(), self.state.read_bytes())
        result = self.health()
        self.assertEqual(result.status, 'pass')
        self.assertIn('not a live turn', result.detail)
        self.assertEqual(before, (self.agent.read_bytes(), self.state.read_bytes()))

    def test_exact_restart_tombstone_fails_even_with_recent_success(self):
        self.entry['mainRestartRecovery'] = {'tombstone': {'reason': 'restart'}}
        self.entry_update()
        self.assertEqual(self.health().status, 'fail')
        self.assertIn('tombstoned', self.health().detail)

    def test_null_tombstone_matches_owner_admission_guard(self):
        self.entry['mainRestartRecovery'] = {'tombstone': None}
        self.entry_update()
        self.assertIn('tombstoned', self.health().detail)

    def test_reset_does_not_erase_last_failed_heartbeat(self):
        self.scheduler.update(lastRunStatus='error', lastError='Session ended during restart recovery')
        self.scheduler_update()
        with sqlite3.connect(self.state) as c:
            c.execute("UPDATE cron_run_receipts SET status='error'")
        result = self.health()
        self.assertEqual(result.status, 'fail')
        self.assertIn('main usable', result.detail)
        self.assertIn('restart recovery rejection', result.detail)

    def test_failed_receipt_cannot_be_hidden_by_green_scheduler_state(self):
        with sqlite3.connect(self.state) as c:
            c.execute("UPDATE cron_run_receipts SET status='interrupted'")
        self.assertEqual(self.health().status, 'fail')

    def test_missing_invalid_or_ended_main_fails(self):
        statements = ('UPDATE session_nodes SET entry_valid=0', 'UPDATE session_nodes SET current_session_id="missing"', 'UPDATE session_windows SET ended_at=1')
        for statement in statements:
            with self.subTest(statement=statement):
                with sqlite3.connect(self.agent) as c:
                    c.execute(statement)
                self.assertEqual(self.health().status, 'fail')
                with sqlite3.connect(self.agent) as c:
                    c.execute('UPDATE session_nodes SET entry_valid=1, current_session_id="live"')
                    c.execute('UPDATE session_windows SET ended_at=NULL')
        with sqlite3.connect(self.agent) as c:
            c.execute('DELETE FROM session_nodes')
        self.assertEqual(self.health().status, 'fail')

    def test_missing_db_is_failure_and_not_created(self):
        self.agent.unlink()
        self.assertEqual(self.health().status, 'fail')
        self.assertFalse(self.agent.exists())

    def test_stale_success_fails(self):
        with sqlite3.connect(self.state) as c:
            c.execute('UPDATE cron_run_receipts SET started_at_ms=?', (NOW - INTERVAL - GRACE_MS - 1,))
        self.assertIn('stale', self.health().detail)

    def test_overdue_disabled_changed_or_missing_job_fails(self):
        self.scheduler['nextRunAtMs'] = NOW - GRACE_MS - 1
        self.scheduler_update()
        self.assertIn('overdue', self.health().detail)
        self.scheduler['nextRunAtMs'] = NOW + INTERVAL
        self.spec['enabled'] = False
        self.scheduler_update()
        self.assertIn('disabled', self.health().detail)
        self.spec['enabled'] = True
        self.spec['sessionTarget'] = 'other'
        self.scheduler_update()
        self.assertIn('changed', self.health().detail)
        with sqlite3.connect(self.state) as c:
            c.execute('DELETE FROM cron_jobs')
        self.assertIn('missing', self.health().detail)

    def test_future_or_stuck_receipt_fails(self):
        with sqlite3.connect(self.state) as c:
            c.execute('UPDATE cron_run_receipts SET started_at_ms=?', (NOW + 1,))
        self.assertIn('future', self.health().detail)
        with sqlite3.connect(self.state) as c:
            c.execute('UPDATE cron_run_receipts SET status="running", started_at_ms=?', (NOW - GRACE_MS - 1,))
        self.assertIn('running >1h', self.health().detail)

    def test_recent_running_attempt_without_success_is_not_green(self):
        with sqlite3.connect(self.state) as c:
            c.execute('UPDATE cron_run_receipts SET status="running", finished_at_ms=NULL')
        self.assertIn('last success stale/missing', self.health().detail)

    def test_arbitrary_error_is_not_echoed(self):
        self.scheduler.update(lastRunStatus='error', lastError='SECRET')
        self.scheduler_update()
        self.assertNotIn('SECRET', self.health().detail)


class WatchdogTests(unittest.TestCase):
    def test_failure_repeat_recovery_and_retry_without_real_alerts(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'state'
            probe, notify = Mock(), Mock()
            probe.return_value = ProbeResult('main-session', 'main-session', 'pass', detail='healthy')
            self.assertEqual(check(state_dir=directory, probe=probe, notify=notify), 0)
            notify.assert_not_called()
            probe.return_value = ProbeResult('main-session', 'main-session', 'fail', detail='tombstoned')
            self.assertEqual(check(state_dir=directory, probe=probe, notify=notify), 1)
            self.assertIn('FAILURE', notify.call_args.args[0])
            check(state_dir=directory, probe=probe, notify=notify)
            self.assertEqual(notify.call_count, 1)
            probe.return_value = ProbeResult('main-session', 'main-session', 'pass', detail='healthy')
            notify.side_effect = RuntimeError('SECRET')
            self.assertEqual(check(state_dir=directory, probe=probe, notify=notify), 1)
            self.assertNotIn('SECRET', (directory / 'state.json').read_text())
            self.assertTrue(json.loads((directory / 'state.json').read_text())['alerted_failure'])
            notify.side_effect = None
            self.assertEqual(check(state_dir=directory, probe=probe, notify=notify), 0)
            self.assertIn('RECOVERY', notify.call_args.args[0])
            self.assertFalse(json.loads((directory / 'state.json').read_text())['alerted_failure'])
            check(state_dir=directory, probe=probe, notify=notify)
            self.assertEqual(notify.call_count, 3)


class AlertReceiptTests(unittest.TestCase):
    def test_only_created_stored_receipt_is_success(self):
        for status, payload, accepted in ((201, {'status': 'stored', 'id': 300}, True),
                                          (200, {'status': 'stored', 'id': 300}, False),
                                          (201, {'status': 'ok', 'id': 300}, False),
                                          (201, {'status': 'stored'}, False)):
            response = io.BytesIO(json.dumps(payload).encode())
            response.status = status
            with self.subTest(status=status, payload=payload), patch('preflight.watchdog.CREDENTIALS') as credentials, patch('preflight.watchdog.urllib.request.urlopen', return_value=response) as client:
                credentials.read_text.return_value = json.dumps({'wesley': {'api_token': 'test-only'}})
                if accepted:
                    self.assertEqual(send_alert('probe failure'), 300)
                    request = client.call_args.args[0]
                    self.assertEqual(json.loads(request.data), {'recipient': 'captain', 'body': 'probe failure'})
                    self.assertEqual(request.get_header('Authorization'), 'Bearer test-only')
                else:
                    with self.assertRaises(RuntimeError):
                        send_alert('probe failure')
