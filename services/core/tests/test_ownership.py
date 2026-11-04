"""The ownership registry (agos_core/db/ownership/) is complete and true.

1. Every table, view and column the migrations leave is registered, and nothing
   registered is gone.
2. Every app_settings key the code (or a migration) names is registered, and every
   registered key is still named somewhere.
3. Every entry has a reason, every MOVE_ONCE says where the thing lives in Hermes
   now, and something deletes every MOVE_ONCE key.
4. A `moving` mark (another branch changes the entry) holds only while the number
   of migrations is the one it was set at: a merge that adds migrations fails here
   until the entry is checked again.
"""

from __future__ import annotations

import re

import ownership_scan as scan

from agos_core.db import ownership
from agos_core.db.migrations import MIGRATIONS
from agos_core.db.ownership import CODE, FILES, HERMES_FILES, KEYS, MOVE_ONCE, TABLES, Owned


def _entries() -> list[tuple[str, Owned]]:
    out: list[tuple[str, Owned]] = []
    for name, table in TABLES.items():
        out.append((name, table.owned))
        out += [(f"{name}.{c}", o) for c, o in table.columns.items()]
    out += [(f"app_settings[{k}]", o) for k, o in KEYS.items()]
    out += [(f"file[{k}]", o) for k, o in FILES.items()]
    out += [
        (f"hermes file[{k}]", Owned(ownership.AGOS_ONLY, "Hermes's", h))
        for k, h in HERMES_FILES.items()
    ]
    return out


def test_every_table_and_column_is_registered_and_none_is_gone() -> None:
    schema = scan.schema()
    unregistered = [t for t in schema if t not in TABLES]
    gone = [t for t in TABLES if t not in schema]
    for table, columns in schema.items():
        known = TABLES.get(table)
        if known is None:
            continue
        unregistered += [f"{table}.{c}" for c in columns if c not in known.columns]
        gone += [f"{table}.{c}" for c in known.columns if c not in columns]
    assert not unregistered, (
        "not in agos_core/db/ownership/ (say whose it is and why): " + ", ".join(unregistered)
    )
    assert not gone, "in agos_core/db/ownership/ but no longer in the schema: " + ", ".join(gone)


def test_views_are_marked_as_views() -> None:
    import sqlite3

    from agos_core.db import hermes_text
    from agos_core.db.connection import _migrate

    db = sqlite3.connect(":memory:")
    hermes_text.install(db)
    _migrate(db)
    views = {str(r[0]) for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
    assert views == {name for name, t in TABLES.items() if t.view}


def test_every_app_settings_key_is_registered_and_none_is_gone() -> None:
    uses = scan.key_uses()
    unreadable = [u.where for u in uses if u.key is None]
    assert not unreadable, (
        "an app_settings key the guard can't read (use a literal or a module constant): "
        + ", ".join(unreadable)
    )
    named = {str(u.key) for u in uses} | scan.migration_keys()
    unregistered = sorted(named - set(KEYS))
    gone = sorted(set(KEYS) - named)
    assert not unregistered, "app_settings keys not in agos_core/db/ownership/ KEYS: " + ", ".join(
        unregistered
    )
    assert not gone, "registered app_settings keys nothing uses any more: " + ", ".join(gone)


def test_every_reason_is_written() -> None:
    empty = [name for name, o in _entries() if not o.why.strip()]
    assert not empty, "empty reasons: " + ", ".join(empty)
    kinds = {o.kind for _, o in _entries()}
    assert kinds <= {ownership.AGOS_ONLY, ownership.MOVE_ONCE}
    nowhere = [n for n, o in _entries() if o.kind == MOVE_ONCE and not o.hermes.strip()]
    assert not nowhere, "MOVE_ONCE without the place it lives in Hermes now: " + ", ".join(nowhere)
    evidence = [n for n, o in _entries() if o.hermes and not o.hermes.strip()]
    assert not evidence


def test_every_move_once_key_is_deleted_by_something() -> None:
    deleted = scan.deleted_keys()
    kept = [k for k, o in KEYS.items() if o.kind == MOVE_ONCE and k not in deleted]
    assert not kept, "MOVE_ONCE keys nothing deletes: " + ", ".join(kept)


def test_moving_marks_are_checked_again_after_a_merge() -> None:
    stale = [
        f"{name} ({o.moving[0]}, set at {o.moving[1]} migrations)"
        for name, o in _entries()
        if o.moving is not None and o.moving[1] != len(MIGRATIONS)
    ]
    assert not stale, (
        "migrations changed since these were marked as moving in another branch: check "
        "each entry against the merged code, then remove its mark: " + ", ".join(stale)
    )


def test_the_hermes_evidence_points_at_real_files() -> None:
    """Every `H: <path>` given as evidence is a file in the Hermes checkout (skipped
    without one): a Hermes update that moves it shows here."""
    import os
    import re
    from pathlib import Path

    import pytest

    checkout = Path(
        os.environ.get("AGOS_HERMES_SOURCE") or Path.home() / ".hermes" / "hermes-agent"
    )
    if not (checkout / "hermes_cli").is_dir():
        pytest.skip("no Hermes checkout")
    missing = [
        f"{name}: {path}"
        for name, o in _entries()
        for part in re.findall(r"H:\s*([^;]*)", o.hermes)
        for path in re.findall(r"([\w./-]+\.(?:py|md))", part)
        if "/" in path and not (checkout / path).is_file()
    ]
    assert not missing, "evidence paths not in Hermes: " + ", ".join(missing)


def test_the_scan_finds_every_way_a_key_is_named(tmp_path: object) -> None:
    """The guard itself: literal, constant, prefix + id, .format, f-string, helper,
    SQL literal and SQL parameter are all read; an unreadable key is reported."""
    import ast

    code = """
HELD = "digest.held."
WRITTEN = "playbooks.written.{}"
def _key(ws):
    return f"office.{ws}"
def a(db, ws, row):
    get_setting(db, "usage", {})
    set_setting(db, HELD + ws, [])
    get_setting(db, WRITTEN.format(ws), None)
    get_setting(db, _key(ws), None)
    db.execute("DELETE FROM app_settings WHERE key LIKE 'hermes.model.%'")
    db.execute("DELETE FROM app_settings WHERE key = ?", (HELD + ws,))
    get_setting(db, row.lookup(), None)
"""
    tree = ast.parse(code)
    resolver = scan._Resolver({"x.py": tree})
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    found = []
    local = scan._locals(tree)
    for c in calls:
        name = getattr(c.func, "id", "")
        if name in ("get_setting", "set_setting"):
            got = resolver.key(c.args[1], "x.py", local)
            found.append(scan._norm(got) if got else None)
    assert found == ["usage", "digest.held.*", "playbooks.written.*", "office.*", None]


def test_every_file_outside_the_database_is_registered_and_none_is_gone() -> None:
    """The files AGOS keeps outside agos.db (origins.json, owner-rules.json, the
    General ledger, .deliveries logs, the Kanban asks' allowed file, automation .md
    files, the scripts it writes into Hermes's scripts folder, the gateway drop-in,
    backup zips…) are in the registry like the tables: a new file the code names fails
    here until it says whose it is, so a copy of Hermes data can't hide in a file.
    The scan never reads the db/ownership/ package (nor its files part, files.py),
    so an entry nothing names fails too."""
    named = scan.file_names()
    assert not any(where & scan.REGISTRY_MODULES for where in named.values())
    groups = {"FILES": set(FILES), "HERMES_FILES": set(HERMES_FILES), "CODE": set(CODE)}
    for a, b in [("FILES", "HERMES_FILES"), ("FILES", "CODE"), ("HERMES_FILES", "CODE")]:
        both = sorted(groups[a] & groups[b])
        assert not both, f"in {a} and {b} at once: " + ", ".join(both)
    known = set().union(*groups.values())
    unregistered = sorted(n for n in named if n not in known)
    assert not unregistered, (
        "files the code names that agos_core/db/ownership/ FILES / HERMES_FILES / CODE "
        "lacks (say whose it is and why): "
        + ", ".join(f"{n} ({', '.join(sorted(named[n]))})" for n in unregistered)
    )
    gone = sorted(n for n in known if n not in named)
    assert not gone, "registered files nothing names any more: " + ", ".join(gone)
    nowhere = [n for n, h in HERMES_FILES.items() if not h.strip().startswith("H:")]
    assert not nowhere, "Hermes files without where Hermes keeps them: " + ", ".join(nowhere)
    for name, where in CODE.items():  # AGOS's own module: it is there
        if not where.startswith("H:"):
            assert (scan.SRC / where.split()[0]).is_file(), name
    # No bare wildcard: "{}.json" would accept any future f"{x}.json".
    loose = [n for n in known if re.fullmatch(r"\{\}\.(json|md|py|ya?ml|txt|db|zip|conf|log)", n)]
    assert not loose, "wildcard file names (make them exact): " + ", ".join(loose)


def test_the_none_is_gone_check_can_fail(monkeypatch: object) -> None:
    """A registered name only the registry mentions is reported as gone."""
    import pytest

    mp = pytest.MonkeyPatch()
    try:
        mp.setitem(FILES, "never-named-anywhere.json", Owned(ownership.AGOS_ONLY, "x"))
        named = scan.file_names()
        assert [n for n in FILES if n not in named] == ["never-named-anywhere.json"]
    finally:
        mp.undo()


def test_the_file_guard_catches_a_new_file(monkeypatch: object) -> None:
    """The guard itself: a new literal or f-string file name is found."""
    import ast

    import pytest

    mp = pytest.MonkeyPatch()
    try:
        code = (
            'P = "agos-x-"\nA = "models-copy.json"\nB = f"{x}.cache.json"\nC = ".json"\n'
            'D = "*/SKILL.md"\nE = f"{P}{n}.py"\nF = "agos-runtime.conf"\nG = "a.zip"\n'
            'H = "icon.svg"\n'
        )
        mp.setattr(scan, "_modules", lambda skip_migrations=True: {"x.py": ast.parse(code)})
        assert set(scan.file_names()) == {
            "models-copy.json",
            "{}.cache.json",
            "agos-x-{}.py",
            "agos-runtime.conf",
            "a.zip",
            "icon.svg",
        }
    finally:
        mp.undo()


def test_every_wildcard_key_says_what_its_id_is() -> None:
    """Purge and the start sweep are registry-driven (db/workspaces._purge_keys,
    db/orphan_keys.sweep): a `*` key without its id kind would outlive its
    workspace — the leftover this rule exists to prevent."""
    from agos_core.db.ownership import KEYS, WILDCARD_IDS

    assert set(WILDCARD_IDS) == {k for k in KEYS if k.endswith("*")}
    assert set(WILDCARD_IDS.values()) <= {"workspace", "chat", "global"}
