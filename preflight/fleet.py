from __future__ import annotations

DEFAULT_FLEET = [
    {"name": "blog", "kind": "http", "url": "https://wesley.thesisko.com/", "expect": "Reports from the Frontline"},
    {"name": "projects", "kind": "http", "url": "https://wesley.thesisko.com/projects/", "expect": "Projects"},
    {"name": "status", "kind": "http", "url": "https://wesley.thesisko.com/status/", "expect": "Status"},
    {"name": "status-data", "kind": "json", "url": "https://wesley.thesisko.com/status/data.json"},
    {"name": "observatory", "kind": "http", "url": "https://wesley.thesisko.com/observatory/", "expect": "Observatory"},
    {"name": "observatory-api", "kind": "json", "url": "https://wesley.thesisko.com/observatory/api", "expect_json": {"all_up": True}},
    {"name": "dead-drop", "kind": "json", "url": "https://wesley.thesisko.com/drop/health", "expect_json": {"ok": True, "service": "dead-drop", "storage.readable": True, "storage.writable": True}},
    {"name": "dead-chat", "kind": "json", "url": "https://wesley.thesisko.com/chat/health", "expect_json": {"ok": True, "service": "dead-chat"}},
    {"name": "forth", "kind": "json", "url": "https://wesley.thesisko.com/forth/health", "expect_json": {"ok": True, "service": "forth"}},
    {"name": "lisp", "kind": "http", "url": "https://wesley.thesisko.com/lisp/", "expect": "Lisp"},
    {"name": "markov", "kind": "http", "url": "https://wesley.thesisko.com/markov/", "expect": "Markov"},
    {"name": "pathfinder", "kind": "http", "url": "https://wesley.thesisko.com/pathfinder/", "expect": "Pathfinder"},
    {"name": "comments", "kind": "json", "url": "https://wesley.thesisko.com/comments/health", "expect_json": {"ok": True, "service": "comments", "storage.readable": True, "storage.writable": True}},
]
