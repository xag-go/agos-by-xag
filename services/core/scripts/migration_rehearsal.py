"""Rehearse every migration on a copy of real data, before a ship.

    uv run python scripts/migration_rehearsal.py                 # newest backup copy, else git history
    uv run python scripts/migration_rehearsal.py --db COPY.db    # one given copy of an agos.db
    uv run python scripts/migration_rehearsal.py --git all       # every old version in git history
    uv run python scripts/migration_rehearsal.py --report out.json

Where the data comes from, in this order:
  1. `--db FILE`: a copy of an agos.db (a restored backup, never the live file);
  2. the newest `agos.db` copy under ~/agos-roots-test (`--roots DIR`), if there is one;
  3. old versions rebuilt from git history: db/migrations.py as it was at older commits
     (one commit per number of migrations; `--git N` evenly spread, `--git all`), each
     database made with the migrations of THAT commit and given rows in every table.
Then the current migrations run forward on it, and it must pass:
  - the migrations run (none raises), user_version = the number of migrations;
  - PRAGMA integrity_check is ok, PRAGMA foreign_key_check finds nothing;
  - row counts: no table loses a row (a table a migration drops or renames is told);
  - same shape as a fresh database (columns, indexes, triggers, views): the upgrade path
    and a new install end with the same schema;
  - a restart (opening it again) and replaying the last migration change nothing.

The live database is never opened: a path under the live AGOS's data folders is refused,
and a backup is copied (SQLite's backup API, read-only source) before anything runs.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agos_core.db import connection

__all__ = [
    "Check",
    "Rehearsal",
    "build_old",
    "copy_backup",
    "history",
    "main",
    "migrations_at",
    "newest_backup",
    "rehearse",
    "seed",
]

CORE = Path(__file__).resolve().parents[1]
MIGRATIONS_FILE = CORE / "src" / "agos_core" / "db" / "migrations.py"
AT = "2026-01-02T03:04:05+00:00"
# Where a live AGOS keeps its data (the agos account's, and a local install's).
LIVE_DIRS = (Path("/home/agos"), Path.home() / "agos-data")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Rehearsal:
    label: str
    from_version: int
    to_version: int
    rows_before: dict[str, int]
    rows_after: dict[str, int]
    checks: list[Check] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)


# ---- old versions ------------------------------------------------------------------------


def migrations_at(rev: str, repo: Path = CORE) -> tuple[str, ...]:
    """db/migrations.py's MIGRATIONS as it was at commit `rev` (read, never run).

    An entry may be a name imported from a `db/schema_<area>.py` module (a migration
    whose text lives beside the size-frozen list): it is read from that module at the
    same commit."""
    top = _git(repo, "rev-parse", "--show-toplevel").strip()
    rel = MIGRATIONS_FILE.resolve().relative_to(Path(top).resolve()).as_posix()
    text = _git(repo, "show", f"{rev}:{rel}")
    tree = ast.parse(text)
    for node in tree.body:
        target: ast.expr
        value: ast.expr | None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "MIGRATIONS" and value is not None:
            if not isinstance(value, ast.Tuple | ast.List):
                return tuple(str(m) for m in ast.literal_eval(value))
            names = _imported_texts(tree, rev, repo, rel)
            unknown = [e.id for e in value.elts if isinstance(e, ast.Name) and e.id not in names]
            if unknown:
                raise ValueError(f"MIGRATIONS at {rev} names unknown texts: {unknown}")
            return tuple(
                names[e.id] if isinstance(e, ast.Name) else str(ast.literal_eval(e))
                for e in value.elts
            )
    raise ValueError(f"no MIGRATIONS in {rel} at {rev}")


def _imported_texts(tree: ast.Module, rev: str, repo: Path, rel: str) -> dict[str, str]:
    """name -> text of each `from agos_core.db.<module> import NAME` in that version."""
    folder = rel.rsplit("/", 1)[0]
    out: dict[str, str] = {}
    for node in tree.body:
        if not (isinstance(node, ast.ImportFrom) and node.module):
            continue
        if not node.module.startswith("agos_core.db."):
            continue
        source = _git(repo, "show", f"{rev}:{folder}/{node.module.rsplit('.', 1)[1]}.py")
        values = {
            n.targets[0].id: n.value
            for n in ast.parse(source).body
            if isinstance(n, ast.Assign)
            and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)
        }
        for alias in node.names:
            if alias.name in values:
                out[alias.asname or alias.name] = str(ast.literal_eval(values[alias.name]))
    return out


def history(repo: Path = CORE, *, side_branches: bool = False) -> list[tuple[str, int]]:
    """(commit, number of migrations) for each number the file ever had, fewest first;
    per number the newest such commit (a mid-merge commit may have had a broken copy).

    Kept: every commit of the main line (first parents: what was merged and could
    ship), and every other commit whose list is exactly the start of today's. A side
    branch's commit whose list differs held a migration renumbered or rewritten before
    its merge (two branches took the same number): no install ever ran that copy.
    `side_branches` keeps those too (a report, not a gate)."""
    top = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    rel = MIGRATIONS_FILE.resolve().relative_to(top).as_posix()
    main_line = set(_git(top, "log", "--first-parent", "--format=%H", "--", rel).split())
    now = _current()
    seen: dict[int, str] = {}
    for sha in _git(top, "log", "--format=%H", "--reverse", "--", rel).split():
        try:
            old = migrations_at(sha, repo)
        except (ValueError, SyntaxError, subprocess.CalledProcessError):
            continue
        if side_branches or sha in main_line or now[: len(old)] == old:
            seen[len(old)] = sha
    return sorted(((sha, n) for n, sha in seen.items()), key=lambda p: p[1])


def is_shallow(repo: Path = CORE) -> bool:
    """A checkout of only the newest commit(s) (CI's default `actions/checkout`): it
    holds none of the old versions `history` rebuilds."""
    return _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(repo), *args],  # noqa: S607 - the system's git
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _current() -> tuple[str, ...]:
    """The list db/connection.py runs (looked up each time: tests swap it)."""
    found: tuple[str, ...] = vars(connection)["MIGRATIONS"]
    return found


@contextlib.contextmanager
def _migrations(migrations: Sequence[str]) -> Iterator[None]:
    kept = _current()
    vars(connection)["MIGRATIONS"] = tuple(migrations)
    try:
        yield
    finally:
        vars(connection)["MIGRATIONS"] = kept


@contextlib.contextmanager
def _backups_beside(db_file: Path) -> Iterator[None]:
    """Files a migration moves out (db/old_copies.py) stay in the rehearsal's folder."""
    kept = os.environ.get("AGOS_BACKUP_DIR")
    os.environ["AGOS_BACKUP_DIR"] = str(db_file.resolve().parent.parent.parent / "agos-backups")
    try:
        yield
    finally:
        if kept is None:
            os.environ.pop("AGOS_BACKUP_DIR", None)
        else:
            os.environ["AGOS_BACKUP_DIR"] = kept


def build_old(db_file: Path, migrations: Sequence[str]) -> None:
    """A database made by an older AGOS: these migrations only (user_version = len)."""
    with _migrations(migrations), _backups_beside(db_file):
        connection.open_database(db_file).close()


# ---- rows in every table -----------------------------------------------------------------


def _tables(db: sqlite3.Connection) -> list[str]:
    rows = db.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    virtual = {n for n, sql in rows if str(sql or "").upper().startswith("CREATE VIRTUAL")}
    shadow = {
        n for n, _ in rows for v in virtual if n.startswith(v + "_") and n != v
    }  # an FTS table's own storage
    return sorted(n for n, _ in rows if n not in virtual and n not in shadow)


def _fk_order(db: sqlite3.Connection, tables: list[str]) -> list[str]:
    parents = {
        t: {r[2] for r in db.execute(f"PRAGMA foreign_key_list({_q(t)})")} - {t} for t in tables
    }
    done: list[str] = []
    left = list(tables)
    while left:
        ready = [t for t in left if parents[t] <= set(done) or not (parents[t] & set(left))]
        for t in ready or left[:1]:
            done.append(t)
            left.remove(t)
    return done


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _enum(sql: str, column: str) -> list[str]:
    """The values a `CHECK (column IN ('a','b'))` allows."""
    found = re.search(
        rf"\b{re.escape(column)}\b\s+IN\s*\(([^)]*)\)", sql, re.IGNORECASE
    ) or re.search(rf"CHECK\s*\(\s*{re.escape(column)}\s+IN\s*\(([^)]*)\)", sql, re.IGNORECASE)
    if not found:
        return []
    return re.findall(r"'((?:[^']|'')*)'", found.group(1)) or [
        v.strip() for v in found.group(1).split(",") if v.strip()
    ]


_TRIES: tuple[Any, ...] = ("{}", "[]", 0, 1, "x", AT, None)


def _json_columns(sql: str) -> dict[str, str]:
    """Columns whose CREATE line says they hold JSON (`-- JSON ...`): an empty value of
    that shape (later migrations read them with json_extract / json_each)."""
    found: dict[str, str] = {}
    for line in sql.splitlines():
        m = re.match(r"\s*(?:ADD\s+COLUMN\s+)?(\w+)\s+TEXT\b[^-]*--\s*JSON(.*)$", line, re.I)
        if m:
            found[m.group(1)] = "[]" if "[]" in m.group(2) or "list" in m.group(2) else "{}"
    return found


def _row(db: sqlite3.Connection, table: str, sql: str, i: int) -> dict[str, Any] | None:
    cols = db.execute(f"PRAGMA table_info({_q(table)})").fetchall()
    pks = [c for c in cols if c[5]]
    fks = {r[3]: (r[2], r[4]) for r in db.execute(f"PRAGMA foreign_key_list({_q(table)})")}
    values: dict[str, Any] = {}
    json_cols = _json_columns(sql)
    for _, name, kind, notnull, default, pk in cols:
        kind = str(kind or "").upper()
        if pk and len(pks) == 1 and "INT" in kind:
            continue  # the rowid
        if name in fks:
            parent, to = fks[name]
            key = to or "rowid"
            got = db.execute(
                f"SELECT {_q(key)} FROM {_q(parent)} ORDER BY rowid LIMIT 1 OFFSET ?",
                (0,),
            ).fetchone()
            if got is None and notnull:
                return None
            values[name] = got[0] if got else None
            continue
        allowed = _enum(sql, name)
        if allowed:
            values[name] = allowed[i % len(allowed)]
        elif default is not None and not pk:
            continue
        elif name in json_cols:
            values[name] = json_cols[name]
        elif "INT" in kind:
            values[name] = i + 1
        elif "REAL" in kind:
            values[name] = 1.5 + i
        elif "BLOB" in kind:
            values[name] = b"x"
        elif name.endswith("_at"):
            values[name] = AT
        else:
            values[name] = f"{table}-{name}-{i}"
    return values


def _insert(db: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    if values:
        cols = ", ".join(_q(c) for c in values)
        marks = ", ".join("?" for _ in values)
        db.execute(f"INSERT INTO {_q(table)} ({cols}) VALUES ({marks})", tuple(values.values()))
    else:
        db.execute(f"INSERT INTO {_q(table)} DEFAULT VALUES")


def _seed_row(db: sqlite3.Connection, table: str, sql: str, i: int) -> bool:
    values = _row(db, table, sql, i)
    if values is None:
        return False
    for _ in range(4 * len(values) + 4):
        try:
            _insert(db, table, values)
            return True
        except sqlite3.IntegrityError as error:
            # A CHECK names its columns: try the next plain value for each of them.
            said = str(error)
            if "CHECK" not in said and "NOT NULL" not in said:
                return False
            named = [c for c in values if re.search(rf"\b{re.escape(c)}\b", said)] or list(values)
            for column in named:
                now = values[column]
                at = _TRIES.index(now) if now in _TRIES else -1
                values[column] = _TRIES[(at + 1) % len(_TRIES)]
        except sqlite3.OperationalError:
            return False
    return False


def seed(db: sqlite3.Connection, rows: int = 2) -> dict[str, int]:
    """`rows` rows in every table that takes them (parents first); table -> rows put."""
    db.execute("PRAGMA foreign_keys = ON")
    sql_of = dict(db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall())
    put: dict[str, int] = {}
    for table in _fk_order(db, _tables(db)):
        put[table] = sum(_seed_row(db, table, str(sql_of.get(table) or ""), i) for i in range(rows))
    db.commit()
    return put


# ---- the copy and the checks -------------------------------------------------------------


def _live(path: Path) -> bool:
    where = path.expanduser().resolve()
    return any(where == d or d in where.parents for d in (p.resolve() for p in LIVE_DIRS))


def copy_backup(source: Path, target: Path) -> None:
    """A consistent copy of a backup's agos.db (the source is opened read-only)."""
    if _live(source):
        raise SystemExit(f"refusing {source}: that is a live AGOS's data; give a backup copy")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    try:
        with contextlib.closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    finally:
        src.close()


def newest_backup(root: Path) -> Path | None:
    """The newest agos.db copy under `root` (not a Hermes install, not a test rig's roots)."""
    found: list[tuple[float, Path]] = []
    for path in root.rglob("agos*.db") if root.is_dir() else []:
        if {"installs", "roots", "node_modules"} & set(path.parts) or _live(path):
            continue
        try:
            if path.read_bytes()[:16] != b"SQLite format 3\x00":
                continue
            with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'workspaces'"
                ).fetchone():
                    continue
        except (OSError, sqlite3.Error):
            continue
        found.append((path.stat().st_mtime, path))
    return max(found)[1] if found else None


def _counts(db: sqlite3.Connection) -> dict[str, int]:
    return {t: int(db.execute(f"SELECT COUNT(*) FROM {_q(t)}").fetchone()[0]) for t in _tables(db)}


def _shape(db: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        t: sorted(
            (str(c[1]), str(c[2]).upper(), int(c[3]), str(c[4]), int(c[5]))
            for c in db.execute(f"PRAGMA table_info({_q(t)})")
        )
        for t in _tables(db)
    }
    others = db.execute(
        "SELECT type, name, tbl_name FROM sqlite_master"
        " WHERE type IN ('index', 'trigger', 'view') AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {"tables": tables, "others": sorted((str(a), str(b), str(c)) for a, b, c in others)}


def _shape_diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    said: list[str] = []
    for t in sorted(set(old["tables"]) | set(new["tables"])):
        a, b = old["tables"].get(t), new["tables"].get(t)
        if a != b:
            if a is None or b is None:
                said.append(f"table {t}: only on the {'fresh' if a is None else 'upgraded'} one")
            else:
                only = sorted(set(map(tuple, a)) ^ set(map(tuple, b)))
                said.append(f"table {t}: {only[:4]}")
    for item in sorted(set(old["others"]) ^ set(new["others"])):
        side = "upgraded" if item in old["others"] else "fresh"
        said.append(f"{item[0]} {item[1]} on {item[2]}: only on the {side} one")
    return said


def _gone_by_migration(table: str, migrations: Sequence[str]) -> bool:
    pattern = re.compile(
        rf"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?{re.escape(table)}\b"
        rf"|--\s*agos:\s*rename-table\s+{re.escape(table)}\s"
        rf"|ALTER\s+TABLE\s+{re.escape(table)}\s+RENAME\s+TO\b",
        re.IGNORECASE,
    )
    return any(pattern.search(m) for m in migrations)


def _deleted_by_migration(table: str, migrations: Sequence[str]) -> bool:
    """A migration that says `DELETE FROM <table>` meant to (a clean-up)."""
    pattern = re.compile(rf"DELETE\s+FROM\s+{re.escape(table)}\b", re.IGNORECASE)
    return any(pattern.search(m) for m in migrations)


def _parents(db: sqlite3.Connection) -> dict[str, set[str]]:
    return {
        t: {str(r[2]) for r in db.execute(f"PRAGMA foreign_key_list({_q(t)})")} for t in _tables(db)
    }


def _ancestors(table: str, parents: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    todo = [table]
    while todo:
        for parent in parents.get(todo.pop(), set()) - seen:
            seen.add(parent)
            todo.append(parent)
    return seen


def _row_check(
    before: dict[str, int],
    after: dict[str, int],
    ran: Sequence[str],
    parents: dict[str, set[str]],
) -> Check:
    """No table loses rows, unless a migration drops / renames it, deletes from it by
    name, or deletes from (or drops for good) a table it hangs on (ON DELETE CASCADE).
    Rows gone any other way (a rebuild that forgot its INSERT ... SELECT) fail."""
    lost: list[str] = []
    told: list[str] = []
    for table, n in sorted(before.items()):
        if table not in after:
            (told if _gone_by_migration(table, ran) else lost).append(f"{table} (gone)")
        elif after[table] < n:
            change = f"{table} {n} -> {after[table]}"
            up = _ancestors(table, parents)
            # A rebuild drops and recreates a table: its own DROP explains nothing.
            meant = any(_deleted_by_migration(t, ran) for t in {table} | up) or any(
                t not in after and _gone_by_migration(t, ran) for t in up
            )
            (told if meant else lost).append(change)
    detail = "lost: " + "; ".join(lost) if lost else f"{sum(before.values())} rows checked"
    if told:
        detail += "; changed by a migration on purpose: " + ", ".join(told)
    return Check("row counts", not lost, detail)


def _fresh_shape() -> dict[str, Any]:
    db = connection.open_database(":memory:")
    try:
        return _shape(db)
    finally:
        db.close()


def rehearse(db_file: Path, *, label: str) -> Rehearsal:
    """Run every current migration on `db_file` (a copy) and check what it became."""
    started = time.monotonic()
    with contextlib.closing(sqlite3.connect(db_file)) as raw:
        from_version = int(raw.execute("PRAGMA user_version").fetchone()[0])
        before = _counts(raw)
        parents = _parents(raw)
    target = len(_current())
    result = Rehearsal(label, from_version, target, before, {})
    checks = result.checks
    with _backups_beside(db_file):
        try:
            db = connection.open_database(db_file)
        except Exception as error:  # noqa: BLE001 - told as the check's failure
            checks.append(Check("migrations run", False, f"{type(error).__name__}: {error}"))
            result.seconds = time.monotonic() - started
            return result
        try:
            checks.append(Check("migrations run", True, f"{from_version} -> {target}"))
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            checks.append(Check("user_version", version == target, f"{version} (want {target})"))
            integrity = [str(r[0]) for r in db.execute("PRAGMA integrity_check")]
            checks.append(Check("integrity_check", integrity == ["ok"], "; ".join(integrity[:5])))
            broken = [tuple(r) for r in db.execute("PRAGMA foreign_key_check")]
            checks.append(Check("foreign_key_check", not broken, str(broken[:5])))
            after = _counts(db)
            result.rows_after = after
            for table, up in _parents(db).items():
                parents[table] = parents.get(table, set()) | up
            ran = _current()[from_version:]
            checks.append(_row_check(before, after, ran, parents))
            shape = _shape(db)
            drift = _shape_diff(shape, _fresh_shape())
            checks.append(Check("same shape as a fresh database", not drift, "; ".join(drift[:8])))
            # Replaying the last migration (a second run of a new migration) is harmless.
            db.execute(f"PRAGMA user_version = {target - 1}")
            try:
                connection._migrate(db, db_file.resolve().parent.parent)
                replay = _counts(db) == after and _shape(db) == shape
                checks.append(Check("last migration replays", replay, ""))
            except Exception as error:  # noqa: BLE001 - told as the check's failure
                db.execute(f"PRAGMA user_version = {target}")
                checks.append(Check("last migration replays", False, f"{error}"))
        finally:
            db.close()
        again = connection.open_database(db_file)
        try:
            same = (
                int(again.execute("PRAGMA user_version").fetchone()[0]) == target
                and _counts(again) == result.rows_after
            )
            checks.append(Check("restart changes nothing", same, ""))
        finally:
            again.close()
    result.seconds = round(time.monotonic() - started, 2)
    return result


# ---- the command -------------------------------------------------------------------------


def _spread(points: list[tuple[str, int]], want: str) -> list[tuple[str, int]]:
    older = [p for p in points if p[1] < len(_current())]
    if want == "all" or len(older) <= int(want):
        return older
    n = int(want)
    step = (len(older) - 1) / max(n - 1, 1)
    return [older[round(i * step)] for i in range(n)]


def _say(result: Rehearsal) -> None:
    mark = "PASS" if result.ok else "FAIL"
    print(
        f"{mark} {result.label}: v{result.from_version} -> v{result.to_version}, "
        f"{sum(result.rows_before.values())} rows, {result.seconds:.1f}s"
    )
    for check in result.checks:
        if not check.ok:
            print(f"    FAIL {check.name}: {check.detail[:500]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", type=Path, help="a copy of an agos.db (never the live one)")
    parser.add_argument("--roots", type=Path, default=Path.home() / "agos-roots-test")
    parser.add_argument("--git", default="", help="N old versions from git history, or 'all'")
    parser.add_argument(
        "--side-branches",
        action="store_true",
        help="also old versions only a side branch had (renumbered before merge; told only)",
    )
    parser.add_argument("--report", type=Path, help="write the results as JSON here")
    parser.add_argument("--work", type=Path, help="where the copies go (default: a temp dir)")
    args = parser.parse_args(argv)

    work = args.work or Path(tempfile.mkdtemp(prefix="agos-migrations-"))
    results: list[Rehearsal] = []
    source = args.db or (None if args.git else newest_backup(args.roots))
    if source is not None:
        copy = work / "backup" / "data" / "system" / "agos.db"
        copy_backup(source, copy)
        results.append(rehearse(copy, label=f"backup copy {source}"))
    if args.git or source is None:
        versions = _spread(history(side_branches=args.side_branches), args.git or "8")
        if not versions and is_shallow():
            print(
                "no old version found: this git checkout is shallow (only the newest commit)."
                " Clone with the full history (actions/checkout: fetch-depth: 0)."
            )
        elif not versions:
            print(
                "no old version found: the git history holds no older migrations list"
                " (e.g. a one-commit export). Rehearse a backup copy with --db instead."
            )
        for sha, n in versions:
            db_file = work / f"v{n}" / "data" / "system" / "agos.db"
            try:
                build_old(db_file, migrations_at(sha))
            except sqlite3.Error as error:
                # That commit's own list never ran anywhere (it fails on an empty file).
                print(f"skip v{n} ({sha[:8]}): its own migrations fail ({error})")
                continue
            with contextlib.closing(sqlite3.connect(db_file)) as db:
                seed(db)
            results.append(rehearse(db_file, label=f"v{n} ({sha[:8]}, from git history)"))
    for result in results:
        _say(result)
    if args.report:
        args.report.write_text(
            json.dumps([asdict(r) | {"ok": r.ok} for r in results], indent=1, ensure_ascii=False)
            + "\n"
        )
    failed = [r for r in results if not r.ok]
    print(f"{len(results) - len(failed)}/{len(results)} rehearsals passed (copies in {work})")
    return 1 if failed or not results else 0


if __name__ == "__main__":
    sys.exit(main())
