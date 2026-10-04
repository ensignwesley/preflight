# Preflight

Read-only operational evidence recorder. `preflight record` checks the surviving public operations and captures host context in a timestamped JSON file. It has no daemon, dashboard, remediation, or external dependencies.

## Current probe roster (4)

1. Blog home
2. Projects page, including current operations and museum representation
3. Promotion Review Portal
4. Promotion Review status API and its JSON contract

The exact roster is defined in `preflight/fleet.py`. Retired demos and the former Observatory/Status monitor are not probes. A passing record means these four checks passed at that time; it is not a claim about historical services or private backup recovery.

## Commands

```bash
preflight record --timeout 8
preflight last
preflight list --limit 20
python3 -m unittest discover -s tests -v
```

Records: `~/.local/share/preflight/records/YYYYMMDDTHHMMSSZ.json`. The compact report includes pass/degraded/fail counts and host load, memory, disk, process, and reboot-required evidence. `record` exits nonzero on a failed or degraded probe.
