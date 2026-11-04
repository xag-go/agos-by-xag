#!/usr/bin/env python3
"""Check the docs: every relative link and every repository path they name exists.

    python3 scripts/check-docs.py          # exit 0 = all good, 1 = broken references

What it checks, in every tracked Markdown file (git ls-files, plus new files not yet added):

1. Relative links, [text](path) and [text](path#anchor): the file or folder exists,
   and the #anchor is a heading of the target Markdown file (GitHub's anchor rules).
   Links to the web (http, https, mailto) are not fetched.
2. Repository paths written in backticks, such as `deploy/agos` or
   `engine/hermes_contract.py:30`: the path exists. A path is tried from the
   repository root, then from the core's package (services/core/src/agos_core),
   the core (services/core) and the web (apps/web, apps/web/src). Only paths that
   start with a folder of this repository are checked, so Hermes's own paths
   (`gateway/run.py`, `hermes_cli/...`) and placeholders (`<data>/...`, `*`) are
   left alone.

Not checked for paths (only for links): the decision records in docs/adr, the
compliance reviews in docs/compliance and the CHANGELOG. They are history (a
review is of one commit) and name files as they were when they were written, or
files a review asks for that do not exist yet.
Product content shipped to workspaces (the team catalog) is skipped entirely.

Standard library only.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_FILES = ("services/core/src/agos_core/catalog/",)
HISTORY = ("docs/adr/", "docs/compliance/", "CHANGELOG.md")

# The first folder of a path that belongs to this repository. A path in backticks
# is checked only when it starts with one of these.
REPO_HEADS = {
    ".github",
    "apps",
    "deploy",
    "docker",
    "docs",
    "packages",
    "scripts",
    "services",
    # inside services/core/src/agos_core
    "actions",
    "api",
    "background",
    "db",
    "domain",
    "engine",
    "hermes_plugin",
    "security",
    "storage",
    # inside services/core
    "tests",
    # inside apps/web/src
    "features",
}
BASES = (
    "",
    "services/core/src/agos_core/",
    "services/core/",
    "apps/web/",
    "apps/web/src/",
)

# [text](target), ![alt](target), and the <target> form for targets with spaces or ")".
LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\)")
HTML_SRC = re.compile(r"""<(?:img|a)\b[^>]*?(?:src|href)=["']([^"']+)["']""", re.I)
CODE_SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^(```|~~~)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def tracked_markdown() -> list[str]:  # git from PATH, read-only
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(f for f in out if not f.startswith(SKIP_FILES))


def slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, inline markup dropped, punctuation
    removed (letters, digits, spaces, '-' and '_' stay), spaces become '-'."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text).replace("*", "").strip().lower()
    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "-_ " or cat[0] in "LN":
            kept.append(ch)
    return "".join(kept).replace(" ", "-")


def prose_lines(text: str) -> list[tuple[int, str]]:
    """The lines outside fenced code blocks, with their numbers."""
    lines, fenced = [], False
    for n, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.lstrip()):
            fenced = not fenced
            continue
        if not fenced:
            lines.append((n, line))
    return lines


_anchors: dict[Path, set[str]] = {}


def anchors(path: Path) -> set[str]:
    if path not in _anchors:
        seen: dict[str, int] = {}
        found: set[str] = set()
        for _, line in prose_lines(path.read_text(encoding="utf-8")):
            m = HEADING.match(line)
            if not m:
                continue
            base = slug(m.group(2))
            n = seen.get(base, 0)
            seen[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
        for m in re.finditer(r"""<a\s+(?:name|id)=["']([^"']+)["']""", path.read_text("utf-8")):
            found.add(m.group(1))
        _anchors[path] = found
    return _anchors[path]


def check_link(source: Path, target: str) -> str | None:
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("//"):
        return None  # http, https, mailto…: not fetched
    target = target.split("?", 1)[0]
    file_part, _, anchor = target.partition("#")
    dest = source if not file_part else (source.parent / file_part).resolve()
    if not file_part and not anchor:
        return None
    try:
        dest.relative_to(ROOT)
    except ValueError:
        return f"link leaves the repository: {target}"
    if not dest.exists():
        return f"missing link target: {target}"
    if anchor and dest.suffix == ".md" and anchor not in anchors(dest):
        return f"missing anchor #{anchor} in {dest.relative_to(ROOT)}"
    return None


def repo_path(token: str) -> str | None:
    """The path a backticked token names in this repository, or None when the
    token is not a repository path (a command, a placeholder, Hermes's path)."""
    token = token.strip().rstrip(".,;:)")
    if " " in token or not re.fullmatch(r"[\w./@\[\]()+-]+(:\d+(-\d+)?(,\d+)*)?", token):
        return None
    token = re.sub(r":\d[\d,\-]*$", "", token)
    if "/" not in token or (
        token.startswith(("/", "~", ".", "$")) and not token.startswith(".github/")
    ):
        return None
    head = token.split("/", 1)[0]
    if head not in REPO_HEADS:
        return None
    return token.rstrip("/")


def check_path(token: str) -> str | None:
    path = repo_path(token)
    if path is None:
        return None
    for base in BASES:
        if (ROOT / (base + path)).exists():
            return None
    return f"missing path: `{path}`"


def main() -> int:
    problems: list[str] = []
    files = tracked_markdown()
    for rel in files:
        source = (ROOT / rel).resolve()
        if not source.exists():
            continue  # deleted in the work tree, not yet in git
        text = source.read_text(encoding="utf-8")
        history = rel.startswith(HISTORY)
        for n, line in prose_lines(text):
            for m in LINK.finditer(line):
                target = m.group(1) or m.group(2)
                if target and (msg := check_link(source, target)):
                    problems.append(f"{rel}:{n}: {msg}")
            for m in HTML_SRC.finditer(line):
                if msg := check_link(source, m.group(1)):
                    problems.append(f"{rel}:{n}: {msg}")
            if history:
                continue
            for m in CODE_SPAN.finditer(line):
                if msg := check_path(m.group(1)):
                    problems.append(f"{rel}:{n}: {msg}")
    for p in problems:
        print(p)
    print(f"check-docs: {len(files)} files, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
