# Preflight

Read-only operational evidence recorder. `preflight record` checks the surviving public operations and captures host context in a timestamped JSON file. It has no dashboard, remediation, or external Python dependencies. An independent user timer checks main-session health and sends transition-only Secure Coms alerts.

## Current probe roster (8: six public, two local)

1. Blog home
2. Projects page, including current operations and museum representation
3. Comments API HTML surface
4. Comments health and writable storage contract
5. Promotion Review Portal
6. Promotion Review status API and its JSON contract
7. Local OS update health: pending package versions first seen over 36h ago, reboot marker over 36h old, APT index refresh over 36h old, and latest unattended run outcome/freshness.

8. Local main-session validity/admission and heartbeat outcome/freshness (see below).

The exact roster is defined in `preflight/fleet.py`. Retired demos and the former Observatory/Status monitor are not probes. A passing record means these eight checks passed at that time; it is not a claim about historical services or private backup recovery. The blog's public-surface checker separately verifies the embedded Comments widget on a post.

## Commands

```bash
preflight record --timeout 8
preflight last
preflight list --limit 20
python3 -m unittest discover -s tests -v
```

Records: `~/.local/share/preflight/records/YYYYMMDDTHHMMSSZ.json`. The compact report includes pass/degraded/fail counts and host load, memory, disk, process, and reboot-required evidence. `record` exits nonzero on a failed or degraded probe.

OS evidence: `apt list --upgradable`, `/var/run/reboot-required`, the successful APT refresh stamp, and the latest unattended-upgrades log run (fallback: apt-daily-upgrade journal). Missing/unreadable, failed, stale or incomplete run evidence is degraded, never green. The 36h grace covers one nightly 03:30 upgrade / 04:30 reboot window. First-seen package/version observations persist privately in `~/.local/share/preflight/update-health.json`; this measures observed backlog age, not release age. Losing that state resets the grace period. No sudo or package/service changes occur.


## Main-session probe and independent watchdog

`main-session` reads the canonical agent SQLite `session_nodes`/current `session_windows` and scheduler SQLite `cron_jobs`/`cron_run_receipts` using read-only connections. It fails on the owner admission guard `mainRestartRecovery.tombstone` (including a null value), invalid/missing/archived main, admission pauses, disabled/misdirected/missing heartbeat job, failed/interrupted/skipped receipt, missing or future-dated evidence, or stale/overdue heartbeat. A closed run window (`session_windows.ended_at`) is normal between turns on 10.5 and is not a failure; liveness comes from the scheduled receipts. It uses the configured `everyMs` cadence plus a one-hour allowance (currently 4h + 1h); a running receipt may last at most one hour and needs recent terminal success. A reset alone does not erase the last heartbeat failure: recovery requires a successful scheduled receipt. Schema/read failures fail closed with an actionable diagnostic; raw entries and scheduler error strings are not printed.

A PASS means usable metadata plus fresh scheduler receipts, **not** a new live model-turn test. Normal turns do not substitute for heartbeat execution. No model call, session reset, Gateway restart, or database write is performed by this probe.

The independent `preflight-main-watchdog.timer` invokes only this local probe every 15 minutes (also two minutes after user-manager startup), so a dead main session is not its own sole monitor. The oneshot service stores its latest probe/result privately in `~/.local/share/preflight/main-watchdog/state.json`, logs a concise diagnostic to the user journal, and posts one failure and one recovery transition to Captain through the local authenticated Portal API. It reads the existing Portal credential at send time, never stores/prints the token, retries failed delivery next tick, suppresses repeated failure notices, and locks against concurrent invocations. Portal or user-manager failure remains an external dependency: an undelivered alert is retained locally and journaled; this is not off-host monitoring. User lingering is required for checks when logged out.

Install (recoverable user units, no root):

```bash
mkdir -p ~/.config/systemd/user
ln -s /home/jarvis/preflight/systemd/preflight-main-watchdog.service ~/.config/systemd/user/
ln -s /home/jarvis/preflight/systemd/preflight-main-watchdog.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now preflight-main-watchdog.timer
systemctl --user start preflight-main-watchdog.service
systemctl --user status preflight-main-watchdog.timer
journalctl --user -u preflight-main-watchdog.service -n 20 --no-pager
```

A failed service exit is intentional when the probe or alert fails; the timer continues checking. Disable with `systemctl --user disable --now preflight-main-watchdog.timer`. The timer is independent of OpenClaw's scheduler and does not modify it. Full `preflight record --timeout 8` still records all eight probes; the timer's local result is separate and does not purport to check public services or OS maintenance.
