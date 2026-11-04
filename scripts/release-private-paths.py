#!/usr/bin/env python3
"""No private development path in what is published (docs/releases.md).

The maintainer's own setup has folders that mean nothing to anyone else, and say
too much about one machine: the worktrees (~/agos-wt/...), his notes (~/wiki/...),
his helper scripts (~/agos-tools), his server's ssh name (agos-local), the audit
folders (eng-audit/...) and his home folder (/home/<his user>). Docs, ADRs and
compliance files must describe AGOS, not that machine.

    scripts/release-private-paths.py                 docs/ and the top-level *.md at HEAD
    scripts/release-private-paths.py --all           every exported text file at HEAD
    scripts/release-private-paths.py --tree <dir>    a folder (the public export's tree)
    scripts/release-private-paths.py --rev <rev>     another commit

Exit 1 with file:line for each hit. Paths every AGOS install has (/home/agos, the
CI runner's agos-ci users, ~/.hermes, ~/agos-data) are fine. Files marked
`export-ignore` in .gitattributes are never published, so never checked.
Standard library only.
"""

from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Homes every install or CI run has; anything else under /home is someone's own.
_PUBLIC_HOMES = r"(?:agos|agos-ci|agos-ci-test|agent|tester|runner|user|you|me|alice|bob|[a-z])\b"
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a builder worktree (~/agos-wt)", re.compile(r"agos-wt\b")),
    ("the maintainer's notes (~/wiki)", re.compile(r"~/wiki\b|\$HOME/wiki\b")),
    ("the maintainer's helper scripts (~/agos-tools)", re.compile(r"\bagos-tools/")),
    ("the maintainer's ssh host name (agos-local)", re.compile(r"\bagos-local\b")),
    ("a private audit folder (eng-audit/)", re.compile(r"\beng-audit/")),
    ("someone's home folder", re.compile(rf"/home/(?!{_PUBLIC_HOMES}|<)[A-Za-z_][\w.-]*")),
]
DOCS = re.compile(r"^(docs/.*|[^/]+\.md)$")


def _own_words() -> list[tuple[str, re.Pattern[str]]]:
    """This machine's user name, when it is not one every install has."""
    user = getpass.getuser()
    if len(user) < 4 or re.fullmatch(_PUBLIC_HOMES, user):
        return []
    return [(f"this machine's user name ({user})", re.compile(re.escape(user)))]


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _exported(rev: str) -> list[str]:
    names = _git("ls-tree", "-r", "--name-only", rev).splitlines()
    ignored = set()
    if names:
        found = subprocess.run(  # noqa: S603
            ["git", "check-attr", "--stdin", "export-ignore"],  # noqa: S607
            cwd=ROOT,
            input="\n".join(names),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        ignored = {line.split(": ")[0] for line in found.splitlines() if line.endswith(": set")}
    return [name for name in names if name not in ignored]


def scan(files: dict[str, str]) -> list[str]:
    """`path:line: what` for every private path in the given files' text."""
    rules = PATTERNS + _own_words()
    hits = []
    for path, text in sorted(files.items()):
        for number, line in enumerate(text.splitlines(), 1):
            for what, pattern in rules:
                if pattern.search(line):
                    hits.append(f"{path}:{number}: {what}: {line.strip()[:160]}")
                    break  # one hit per line is enough to find it
    return hits


def _read_rev(rev: str, every: bool) -> dict[str, str]:
    files = {}
    for name in _exported(rev):
        if not every and not DOCS.match(name):
            continue
        data = subprocess.run(  # noqa: S603
            ["git", "show", f"{rev}:{name}"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        if b"\0" not in data[:8000]:
            files[name] = data.decode("utf-8", "replace")
    return files


def _read_tree(tree: Path, every: bool) -> dict[str, str]:
    files = {}
    paths = tree.rglob("*") if every else [*tree.glob("*.md"), *(tree / "docs").rglob("*")]
    for path in paths:
        name = path.relative_to(tree).as_posix()
        if not path.is_file() or name.startswith(".git/") or (not every and not DOCS.match(name)):
            continue
        data = path.read_bytes()
        if b"\0" not in data[:8000]:
            files[name] = data.decode("utf-8", "replace")
    return files


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--all", action="store_true", help="every exported text file")
    parser.add_argument("--tree", type=Path, help="check this folder instead of a commit")
    parser.add_argument("--rev", default="HEAD")
    args = parser.parse_args(argv)
    files = _read_tree(args.tree, args.all) if args.tree else _read_rev(args.rev, args.all)
    hits = scan(files)
    for hit in hits:
        print(hit, file=sys.stderr)
    where = str(args.tree) if args.tree else args.rev
    if hits:
        print(f"private paths: {len(hits)} in {len(files)} files of {where}", file=sys.stderr)
        return 1
    print(f"private paths: none in {len(files)} files of {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
