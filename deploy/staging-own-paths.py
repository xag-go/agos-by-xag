#!/usr/bin/env python3
"""A staging copy's Hermes roots, restored from live's backup, still name live's data
folder, live's roots (agos-<id>), live's sandbox networks and live's egress proxy.
This rewrites them to staging's own, as LITERAL text (no sed: a path holding '#',
'&' or '.' is just text here), in every root's and member's

- config.yaml and profile.yaml,
- cron/jobs.json (a job's workdir),
- Kanban boards (kanban.db and boards/*/kanban.db: every text cell, e.g. a card's
  workspace folder),

and then checks that none of them still names live's data folder. Stdlib only.
agos-staging.sh runs it after the import, before any staging Hermes starts; the
staging core re-syncs every sandbox at start too (defense in depth).

    staging-own-paths.py fix   <roots> <live data> <staging data> <live prefix> <staging prefix> <egress>
    staging-own-paths.py check <roots> <live data>

`check` prints each file that still names <live data> and exits 1 when any does.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

TEXT_NAMES = {"config.yaml", "profile.yaml"}
SKIP_DIRS = {"installs", "sessions", "logs", "cache", "node_modules", ".git", "sandboxes"}


def _files(roots: Path) -> Iterator[Path]:
    for here, dirs, names in os.walk(roots):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not Path(here, d).is_symlink()]
        for name in names:
            path = Path(here, name)
            if path.is_symlink():
                continue
            if (
                name in TEXT_NAMES
                or (name == "jobs.json" and path.parent.name == "cron")
                or name == "kanban.db"
            ):
                yield path


def rewriter(
    live: str, stg: str, live_prefix: str, prefix: str, egress: str
) -> Callable[[str], str]:
    live, stg = live.rstrip("/"), stg.rstrip("/")
    end = r"(?=$|[/\"'\s,\]}:])"
    steps = [
        # live's root folders are staging's own names under staging's data
        (re.compile(re.escape(f"{live}/hermes/{live_prefix}")), f"{stg}/hermes/{prefix}"),
        (re.compile(re.escape(live) + end), stg),
        (re.compile(re.escape(f"agos-net-{live_prefix}")), f"agos-net-{prefix}"),
        (re.compile(re.escape("http://agos-egress:")), f"http://{egress}:"),
    ]

    def own(text: str) -> str:
        for pattern, repl in steps:
            text = pattern.sub(repl.replace("\\", "\\\\"), text)
        return text

    return own


def _tables(conn: sqlite3.Connection) -> list[tuple[str, list[str]]]:
    out = []
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
        if table.startswith("sqlite_"):
            continue
        cols = [
            str(r[1])
            for r in conn.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34) * 2)}")')
            if str(r[2]).upper() in ("", "TEXT") or "CHAR" in str(r[2]).upper()
        ]
        if cols:
            out.append((table, cols))
    return out


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def fix_db(path: Path, own: Callable[[str], str], needles: list[str]) -> int:
    conn = sqlite3.connect(path)
    changed = 0
    try:
        conn.create_function("agos_own", 1, lambda v: own(v) if isinstance(v, str) else v)
        for table, cols in _tables(conn):
            for col in cols:
                where = " OR ".join(f"instr({_q(col)}, ?) > 0" for _ in needles)
                cur = conn.execute(
                    f"UPDATE {_q(table)} SET {_q(col)} = agos_own({_q(col)}) WHERE {where}",  # quoted names
                    needles,
                )
                changed += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return changed


def db_names(path: Path, live: str) -> bool:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table, cols in _tables(conn):
            for col in cols:
                row = conn.execute(
                    f"SELECT 1 FROM {_q(table)} WHERE instr({_q(col)}, ?) > 0 LIMIT 1",  # quoted names
                    (live,),
                ).fetchone()
                if row:
                    return True
    finally:
        conn.close()
    return False


def fix(roots: Path, live: str, stg: str, live_prefix: str, prefix: str, egress: str) -> int:
    own = rewriter(live, stg, live_prefix, prefix, egress)
    needles = [live.rstrip("/"), f"agos-net-{live_prefix}", "http://agos-egress:"]
    changed = 0
    for path in _files(roots):
        if path.name == "kanban.db":
            changed += fix_db(path, own, needles)
            continue
        text = path.read_text(encoding="utf-8", errors="surrogateescape")
        new = own(text)
        if new != text:
            path.write_text(new, encoding="utf-8", errors="surrogateescape")
            changed += 1
    return changed


def check(roots: Path, live: str) -> list[Path]:
    live = live.rstrip("/")
    found = []
    for path in _files(roots):
        if path.name == "kanban.db":
            if db_names(path, live):
                found.append(path)
        elif live in path.read_text(encoding="utf-8", errors="surrogateescape"):
            found.append(path)
    return found


def main(argv: list[str]) -> int:
    if len(argv) == 7 and argv[0] == "fix":
        n = fix(Path(argv[1]), *argv[2:])
        print(f"staging roots: {n} place(s) now name staging's own data")
        return 0
    if len(argv) == 3 and argv[0] == "check":
        left = check(Path(argv[1]), argv[2])
        for path in left:
            print(f"still names live's data: {path}")
        return 1 if left else 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
