# preflight

A small read-only fleet health recorder for Wesley's services.

## Design

`preflight record` is a black-box recorder snapshot, not a dashboard and not a daemon. It checks the public fleet, validates key health JSON fields, captures host context, writes durable JSON evidence, prints a compact operator report, and exits with an honest status code.

This is the v0 product because the operator problem is evidence: when something looks wrong, produce a record that says what was checked, what passed, what failed or degraded, and what the host looked like at that moment.

## Usage

```bash
preflight record
preflight record --timeout 8
preflight record --json
preflight last
preflight list
preflight list --limit 20
preflight check
```

`check` currently uses the same recorder path as `record`; the product promise is still a saved evidence file, not an ephemeral ping. Use `list` and `last` to inspect what the recorder has captured. `list --json` emits the same latest-record window as text output, honoring `--limit` for scripts.

Records are written to:

```text
~/.local/share/preflight/records/YYYYMMDDTHHMMSSZ.json
```

## Current fleet probes

- Blog home
- Projects
- Status page
- Status JSON data
- Observatory page
- Observatory JSON API (`all_up: true`)
- Dead Drop health (`ok`, service identity, readable/writable storage)
- DEAD//CHAT health (`ok`, service identity)
- Forth health (`ok`, service identity)
- Lisp page
- Markov page
- Pathfinder page
- Comments health (`ok`, service identity, readable/writable storage)

## Host evidence captured

- Hostname
- Load average
- Memory totals/available/used
- Disk usage for `/` and `/home`
- Top processes by CPU via `ps`

## Exit codes

- `0` — all probes passed
- `1` — one or more probes failed or were degraded
- `2` — command/configuration error, including no saved record for `last`

## Non-goals for v0

- No dashboard
- No daemon
- No remediation
- No alerting
- No privileged writes
- No external dependencies

If `record` proves useful, the next design step is `watch`: reuse this exact record format and write a record on healthy→unhealthy transition.
