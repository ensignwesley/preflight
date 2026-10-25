from __future__ import annotations

# Six public operations plus two local operational probes. Historical demos are not probes.
DEFAULT_FLEET = [
    {"name": "os-updates", "kind": "updates"},
    {"name": "main-session", "kind": "main-session"},
    {"name": "blog", "kind": "http", "url": "https://wesley.thesisko.com/", "expect": "Reports from the Frontline", "max_elapsed_ms": 2000},
    {"name": "projects", "kind": "http", "url": "https://wesley.thesisko.com/projects/", "expect": "Projects", "expect_all": ["Promotion Review", "Preflight", "Project Museum"], "max_elapsed_ms": 2000},
    {"name": "comments-ui", "kind": "http", "url": "https://wesley.thesisko.com/comments/", "request_headers": {"Accept": "text/html"}, "expect": "Comments API", "expect_all": ["Self-hosted blog comment service", "online", "Public endpoints"], "max_elapsed_ms": 2000},
    {"name": "comments", "kind": "json", "url": "https://wesley.thesisko.com/comments/health", "expect_json": {"ok": True, "service": "comments", "storage.readable": True, "storage.writable": True}, "expect_headers": {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}, "max_elapsed_ms": 1000},
    {"name": "promotion-review", "kind": "http", "url": "https://wesley.thesisko.com/promotion-review/", "expect": "Promotion Review Portal", "expect_all": ["Phase 1", "Secure Coms", "Evaluation details"], "max_elapsed_ms": 2000},
    {"name": "promotion-review-status", "kind": "json", "url": "https://wesley.thesisko.com/promotion-review/api/status", "expect_json": {"status": "phase1", "service": "promotion-review", "evaluation.max_score": 50}, "max_elapsed_ms": 1000},
]
