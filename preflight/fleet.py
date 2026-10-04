from __future__ import annotations

# Public, continuously consumed operations only. Historical demos are not probes.
DEFAULT_FLEET = [
    {"name": "blog", "kind": "http", "url": "https://wesley.thesisko.com/", "expect": "Reports from the Frontline", "max_elapsed_ms": 2000},
    {"name": "projects", "kind": "http", "url": "https://wesley.thesisko.com/projects/", "expect": "Projects", "expect_all": ["Promotion Review", "Preflight", "Project Museum"], "max_elapsed_ms": 2000},
    {"name": "promotion-review", "kind": "http", "url": "https://wesley.thesisko.com/promotion-review/", "expect": "Promotion Review Portal", "expect_all": ["Phase 1", "Secure Coms", "Evaluation details"], "max_elapsed_ms": 2000},
    {"name": "promotion-review-status", "kind": "json", "url": "https://wesley.thesisko.com/promotion-review/api/status", "expect_json": {"status": "phase1", "service": "promotion-review", "evaluation.max_score": 50}, "max_elapsed_ms": 1000},
]
