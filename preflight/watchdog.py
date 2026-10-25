"""Independent timer entry point; transition-only Secure Coms alerts, no remediation."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .main_session import main_session_health

STATE_DIR = Path.home() / '.local/share/preflight/main-watchdog'
CREDENTIALS = Path.home() / 'promotion-portal/instance/credentials.generated.json'
ENDPOINT = 'http://127.0.0.1:3010/promotion-review/api/messages'


def send_alert(body: str) -> int:
    token = json.loads(CREDENTIALS.read_text())['wesley']['api_token']
    request = urllib.request.Request(ENDPOINT, method='POST',
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps({'recipient': 'captain', 'body': body}).encode())
    with urllib.request.urlopen(request, timeout=8) as response:
        receipt = json.load(response)
        if response.status != 201 or receipt.get('status') != 'stored' or type(receipt.get('id')) is not int:
            raise RuntimeError('Secure Coms did not confirm storage')
        return receipt['id']


def _save(path: Path, data: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(data, out, indent=2)
            out.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def check(*, state_dir: Path = STATE_DIR, probe=main_session_health, notify=send_alert) -> int:
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state_dir / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = state_dir / 'state.json'
        try:
            old = json.loads(path.read_text())
        except (OSError, ValueError):
            old = {}
        if not isinstance(old, dict):
            old = {}
        result = probe(timeout=5)
        failed = result.status != 'pass'
        checked = datetime.now(timezone.utc).isoformat()
        state = {'checked_at': checked, 'probe': result.to_dict(),
                 'alerted_failure': bool(old.get('alerted_failure'))}
        for key in ('last_alert_at', 'last_alert_id'):
            if key in old:
                state[key] = old[key]
        # Do not send a cold-start healthy notice or a notice for every changed error.
        transition = failed != state['alerted_failure']
        delivery_failed = False
        if transition:
            label = 'FAILURE' if failed else 'RECOVERY'
            body = f'Independent main-session watchdog {label} at {checked}: {result.detail}. Read-only evidence; no Gateway/session changes made.'
            try:
                receipt_id = notify(body)
                if type(receipt_id) is int:
                    state['last_alert_id'] = receipt_id
                state['alerted_failure'] = failed
                state['last_alert_at'] = checked
            except Exception:
                # Keep transition pending for retry; never print exception/token/response.
                state['notification_error'] = 'Secure Coms delivery failed; retry next timer tick'
                delivery_failed = True
        _save(path, state)
        print(f'main-session watchdog {result.status.upper()}: {result.detail}')
        if delivery_failed:
            print(state['notification_error'])
        return 1 if failed or delivery_failed else 0


if __name__ == '__main__':
    raise SystemExit(check())
