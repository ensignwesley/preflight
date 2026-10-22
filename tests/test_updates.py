import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from preflight.updates import GRACE, journal_result, log_result, update_health


class UpdateTests(unittest.TestCase):
    def test_latest_incomplete_or_failed_run_cannot_reuse_older_success(self):
        old = '2026-10-22 01:00:00 INFO Starting unattended upgrades script\n2026-10-22 01:01:00 INFO All upgrades installed\n'
        new = '2026-10-22 02:00:00 INFO Starting unattended upgrades script\n'
        now = 1792638000  # 2026-10-22 03:00 UTC
        self.assertIsNone(log_result(old, now))
        self.assertIn('lacks terminal', log_result(old + new, now))
        self.assertIn('errors', log_result(old + new + '2026-10-22 02:01:00 ERROR broken dpkg\n', now))
        self.assertIn('stale', log_result(old, now + GRACE))

    def test_journal_requires_real_fresh_success(self):
        self.assertIn('no accessible', journal_result('', 1000))
        event = {'UNIT': 'apt-daily-upgrade.service', 'JOB_TYPE': 'start', 'JOB_RESULT': 'done', '__REALTIME_TIMESTAMP': '1000000000'}
        self.assertIsNone(journal_result(json.dumps(event), 1001))
        event['JOB_RESULT'] = 'failed'
        self.assertIn('not successful', journal_result(json.dumps(event), 1001))

    def test_backlog_and_reboot_age_survive_repeated_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, reboot, stamp, log = [root / n for n in ('state', 'reboot', 'stamp', 'log')]
            stamp.touch()
            reboot.touch()
            now = 1792638000
            os.utime(stamp, (now, now))
            os.utime(reboot, (now, now))
            log.write_text('2026-10-22 02:00:00 INFO Starting unattended upgrades script\n2026-10-22 02:01:00 INFO All upgrades installed\n')
            with patch('preflight.updates.command', return_value='Listing...\npkg/noble 2 amd64 [upgradable from: 1]\n'):
                first = update_health(state=state, now=now, reboot=reboot, apt_stamp=stamp, log=log)
                self.assertEqual(first.status, 'pass', first.detail)
                later = update_health(state=state, now=now + GRACE + 1, reboot=reboot, apt_stamp=stamp, log=log)
                self.assertEqual(later.status, 'degraded')
                self.assertIn('stale upgrades', later.detail)
                self.assertIn('stale or future-dated reboot', later.detail)
                self.assertIn('index refresh', later.detail)
            with patch('preflight.updates.command', return_value='Listing...\n'):
                update_health(state=state, now=now, reboot=reboot, apt_stamp=stamp, log=log)
                self.assertEqual(json.loads(state.read_text()), {})

    def test_unreadable_log_and_empty_journal_are_degraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stamp = root / 'stamp'
            stamp.touch()
            with patch('preflight.updates.command', side_effect=['Listing...\n', '']):
                result = update_health(state=root / 'state', reboot=root / 'no-reboot', apt_stamp=stamp, log=root / 'missing')
            self.assertEqual(result.status, 'degraded')
            self.assertIn('no accessible outcome', result.detail)
