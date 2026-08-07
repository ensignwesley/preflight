from __future__ import annotations

DEFAULT_FLEET = [
    {"name": "blog", "kind": "http", "url": "https://wesley.thesisko.com/", "expect": "Reports from the Frontline", "max_elapsed_ms": 2000},
    {"name": "projects", "kind": "http", "url": "https://wesley.thesisko.com/projects/", "expect": "Projects", "max_elapsed_ms": 2000},
    {"name": "status", "kind": "http", "url": "https://wesley.thesisko.com/status/", "expect": "Status", "max_elapsed_ms": 2000},
    {"name": "status-data", "kind": "json", "url": "https://wesley.thesisko.com/status/data.json", "expect_fresh": {"field": "generated_at", "max_age_seconds": 900}, "max_elapsed_ms": 1000},
    {"name": "observatory", "kind": "http", "url": "https://wesley.thesisko.com/observatory/", "expect": "Observatory", "max_elapsed_ms": 2000},
    {"name": "observatory-api", "kind": "json", "url": "https://wesley.thesisko.com/observatory/api", "expect_json": {"all_up": True}, "max_elapsed_ms": 1000},
    {"name": "dead-drop", "kind": "json", "url": "https://wesley.thesisko.com/drop/health", "expect_json": {"ok": True, "service": "dead-drop", "storage.readable": True, "storage.writable": True}, "max_elapsed_ms": 1000},
    {"name": "dead-chat", "kind": "json", "url": "https://wesley.thesisko.com/chat/health", "expect_json": {"ok": True, "service": "dead-chat"}, "max_elapsed_ms": 1000},
    {"name": "forth", "kind": "json", "url": "https://wesley.thesisko.com/forth/health", "expect_json": {"ok": True, "service": "forth"}, "max_elapsed_ms": 1000},
    {"name": "lisp", "kind": "http", "url": "https://wesley.thesisko.com/lisp/", "expect": "Lisp", "max_elapsed_ms": 2000},
    {"name": "markov", "kind": "http", "url": "https://wesley.thesisko.com/markov/", "expect": "Markov", "max_elapsed_ms": 2000},
    {"name": "pathfinder", "kind": "http", "url": "https://wesley.thesisko.com/pathfinder/", "expect": "Pathfinder", "max_elapsed_ms": 2000},
    {"name": "comments", "kind": "json", "url": "https://wesley.thesisko.com/comments/health", "expect_json": {"ok": True, "service": "comments", "storage.readable": True, "storage.writable": True}, "max_elapsed_ms": 1000},
]
