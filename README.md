# preflight

A small read-only fleet health recorder for Wesley's services.

## Design

`preflight record` is a black-box recorder snapshot, not a dashboard and not a daemon. It checks the public fleet, validates key health JSON fields and exact service rosters where they matter, verifies JSON response media types, checks required security headers, checks required human-visible page markers, verifies selected WebSocket upgrade paths, records response content type/byte size, flags probes that exceed conservative latency budgets, captures host context, writes durable JSON evidence, prints a compact operator report, and exits with an honest status code.

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

`check` currently uses the same recorder path as `record`; the product promise is still a saved evidence file, not an ephemeral ping. Use `list` and `last` to inspect what the recorder has captured. Compact reports include pass/degraded/fail probe counts in the header so an operator can see severity at a glance before reading individual probe lines. `list --json` emits the same latest-record window as text output, honoring `--limit` for scripts.

Records are written to:

```text
~/.local/share/preflight/records/YYYYMMDDTHHMMSSZ.json
```

## Current fleet probes

- Blog home
- Projects
- Status page
- Status JSON data (`all_up: true`, exact ten-service roster, and `generated_at` no more than 15 minutes old)
- Observatory page
- Observatory JSON API (`all_up: true`, exact service-key roster, and `generated_at` no more than 15 minutes old)
- Dead Drop public app page (`DEAD DROP`, message box, auto-destruct control, encryption CTA) and health (`ok`, service identity, readable/writable storage, security headers)
- DEAD//CHAT public app page (callsign gate, connection CTA, message input), health (`ok`, service identity, security headers), and WebSocket upgrade path
- Forth health (`ok`, service identity, security headers) and WebSocket upgrade path
- Lisp page
- Markov page
- Pathfinder page
- Comments public API page (`Comments API`, online status, endpoint copy) and health (`ok`, service identity, readable/writable storage, security headers)
- Promotion Review portal page (Phase 1 / Secure Coms / evaluation-details visible markers)
- Promotion Review status API (`phase1`, service identity, evaluation max-score contract)

All JSON fleet probes must return `application/json` and every HTTP probe records its response content type and byte count. JSON media-type drift marks the record degraded before body parsing so HTML error pages cannot masquerade as healthy JSON. Status JSON has to name the expected monitored services exactly, and Observatory JSON has to expose the expected service-key roster with a fresh `generated_at`, so stale, truncated, or quietly changed fleet inventories cannot hide behind a green aggregate flag. Security-sensitive health endpoints also prove that required headers such as `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and relevant CSP directives are still present. Public HTML probes can require multiple page markers too; the home, Projects, Dead Drop, DEAD//CHAT, Comments API, and Promotion Review pages now prove that visible fleet/project/audit surfaces still name the expected services, controls, deliverables, or access-state copy instead of only matching one generic title. Probes can send small per-target request headers, used where an endpoint content-negotiates between API JSON and the human HTML surface. HTML entities are decoded before marker checks so probes validate the same visible copy a browser would render, not only the raw source bytes. All fleet probes also carry conservative latency budgets: 2 seconds for public HTML pages and 1 second for JSON health/data endpoints. A budget breach marks the record degraded rather than failed. WebSocket probes perform a real RFC 6455 handshake against the public `wss://` endpoint so reverse-proxy upgrade regressions cannot hide behind a green HTTP health route.

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
