from __future__ import annotations

import ast
import glob
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .probes import ProbeResult

DEFAULT_NGINX_CONFIG = Path("/etc/nginx/nginx.conf")
DEFAULT_OBSERVATORY_TARGETS = Path("/home/jarvis/observatory/checker.py")


@dataclass(frozen=True)
class Directive:
    name: str
    args: tuple[str, ...]
    children: tuple["Directive", ...] = ()


def _tokens(text: str) -> list[str]:
    """Tokenize the nginx syntax needed for directives, blocks, and includes."""
    tokens: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escaped = False
    in_comment = False

    def flush() -> None:
        if current:
            tokens.append("".join(current))
            current.clear()

    for char in text:
        if in_comment:
            if char == "\n":
                in_comment = False
            continue
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                current.append(char)
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "#":
            flush()
            in_comment = True
        elif char.isspace():
            flush()
        elif char in "{};":
            flush()
            tokens.append(char)
        else:
            current.append(char)
    if quote:
        raise ValueError("unterminated quoted string in nginx configuration")
    if escaped:
        current.append("\\")
    flush()
    return tokens


def _parse_directives(tokens: list[str], start: int = 0, nested: bool = False) -> tuple[list[Directive], int]:
    directives: list[Directive] = []
    words: list[str] = []
    index = start
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token == ";":
            if not words:
                continue
            directives.append(Directive(words[0], tuple(words[1:])))
            words = []
        elif token == "{":
            if not words:
                raise ValueError("nginx block has no directive name")
            children, index = _parse_directives(tokens, index, nested=True)
            directives.append(Directive(words[0], tuple(words[1:]), tuple(children)))
            words = []
        elif token == "}":
            if words:
                raise ValueError("nginx directive is missing ';' before '}'")
            if not nested:
                raise ValueError("unexpected '}' in nginx configuration")
            return directives, index
        else:
            words.append(token)
    if nested:
        raise ValueError("unterminated nginx block")
    if words:
        raise ValueError("nginx directive is missing ';' at end of file")
    return directives, index


def parse_nginx(text: str) -> list[Directive]:
    directives, _ = _parse_directives(_tokens(text))
    return directives


def _walk(directives: list[Directive] | tuple[Directive, ...]):
    for directive in directives:
        yield directive
        yield from _walk(directive.children)


def load_nginx_include_graph(entry: Path, include_root: Path | None = None) -> list[tuple[Path, list[Directive]]]:
    """Load an nginx entry point and every recursively referenced include once."""
    entry = entry.resolve()
    include_root = (include_root or entry.parent).resolve()
    loaded: list[tuple[Path, list[Directive]]] = []
    seen: set[Path] = set()

    def visit(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        directives = parse_nginx(resolved.read_text(encoding="utf-8"))
        loaded.append((resolved, directives))
        for directive in _walk(directives):
            if directive.name != "include" or not directive.args:
                continue
            pattern = directive.args[0]
            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = include_root / candidate
            for match in sorted(glob.glob(str(candidate))):
                matched = Path(match)
                if matched.is_file():
                    visit(matched)

    visit(entry)
    return loaded


def derive_proxied_locations(entry: Path, include_root: Path | None = None) -> list[dict[str, str]]:
    """Return public location blocks that directly proxy to an upstream service."""
    locations: set[tuple[str, str]] = set()
    for source, directives in load_nginx_include_graph(entry, include_root=include_root):
        for directive in _walk(directives):
            if directive.name != "location" or not directive.args:
                continue
            location = directive.args[-1]
            # Named and explicitly internal locations are implementation details, not public services.
            if location.startswith("@") or any(child.name == "internal" for child in directive.children):
                continue
            proxies = [child.args[0] for child in directive.children if child.name == "proxy_pass" and child.args]
            for upstream in proxies:
                locations.add((location, upstream))
    return [
        {"location": location, "upstream": upstream}
        for location, upstream in sorted(locations)
    ]


def parse_observatory_targets(path: Path) -> list[dict[str, str]]:
    """Read the literal TARGETS assignment without importing or executing checker.py."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else ([node.target.id] if isinstance(node.target, ast.Name) else [])
            if "TARGETS" not in names:
                continue
            value = ast.literal_eval(node.value)
            if not isinstance(value, list):
                raise ValueError("Observatory TARGETS must be a list")
            targets: list[dict[str, str]] = []
            for item in value:
                if not isinstance(item, dict) or not isinstance(item.get("slug"), str) or not isinstance(item.get("url"), str):
                    raise ValueError("each Observatory target must have string slug and url fields")
                targets.append({"slug": item["slug"], "url": item["url"]})
            return targets
    raise ValueError("Observatory source has no literal TARGETS assignment")


def _endpoint(url: str) -> tuple[str, int] | None:
    parsed = urlsplit(url)
    if not parsed.hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if parsed.scheme in ("https", "wss") else 80 if parsed.scheme in ("http", "ws") else None
    return (parsed.hostname, port) if port is not None else None


def coverage_gaps(locations: list[dict[str, str]], targets: list[dict[str, str]]) -> list[dict[str, str]]:
    """A target covers every public location served by the same backend endpoint."""
    target_endpoints = {_endpoint(target["url"]) for target in targets}
    target_endpoints.discard(None)
    return [location for location in locations if _endpoint(location["upstream"]) not in target_endpoints]


def run_coverage_probe(
    nginx_config: Path = DEFAULT_NGINX_CONFIG,
    observatory_targets: Path = DEFAULT_OBSERVATORY_TARGETS,
    include_root: Path | None = None,
) -> ProbeResult:
    try:
        locations = derive_proxied_locations(nginx_config, include_root=include_root)
        targets = parse_observatory_targets(observatory_targets)
        gaps = coverage_gaps(locations, targets)
    except (OSError, SyntaxError, ValueError) as exc:
        return ProbeResult(
            name="observatory-coverage",
            kind="config",
            status="fail",
            url=str(nginx_config),
            detail=f"coverage configuration error: {exc}",
        )

    if gaps:
        missing = ", ".join(f"{item['location']} -> {item['upstream']}" for item in gaps)
        return ProbeResult(
            name="observatory-coverage",
            kind="config",
            status="fail",
            url=str(nginx_config),
            detail=f"{len(gaps)} proxied location(s) lack Observatory targets: {missing}",
        )
    return ProbeResult(
        name="observatory-coverage",
        kind="config",
        status="pass",
        url=str(nginx_config),
        detail=f"{len(locations)} proxied location(s) covered by {len(targets)} Observatory target(s)",
    )
