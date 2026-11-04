"""The migrations on a copy of real data (scripts/migration_rehearsal.py).

A database made at an older version (from git history, or a local backup copy), with
rows in every table, runs every migration forward: integrity_check, foreign_key_check
and the row counts hold, the result has the same shape as a fresh database, and opening
it again (a restart) or replaying the last migration changes nothing. The rehearsal
never opens a live database: it works on a copy.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agos_core.db import connection
from agos_core.db.migrations import MIGRATIONS

CORE = Path(__file__).resolve().parents[1]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "migration_rehearsal", CORE / "scripts" / "migration_rehearsal.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


rehearsal = _tool()
HALF = len(MIGRATIONS) // 2


def _old(tmp_path: Path, upto: int = HALF) -> Path:
    db_file = tmp_path / "data" / "system" / "agos.db"
    rehearsal.build_old(db_file, MIGRATIONS[:upto])
    return db_file


def _failed(result: object) -> list[str]:
    return [c.name for c in result.checks if not c.ok]  # type: ignore[attr-defined]


def test_an_old_database_with_rows_in_every_table_migrates_forward(tmp_path: Path) -> None:
    db_file = _old(tmp_path)
    with sqlite3.connect(db_file) as db:
        seeded = rehearsal.seed(db)
    # The generic filler reaches nearly every table of that version.
    assert sum(1 for n in seeded.values() if n > 0) >= 0.9 * len(seeded), seeded
    result = rehearsal.rehearse(db_file, label="half")
    assert result.from_version == HALF and result.to_version == len(MIGRATIONS)
    assert _failed(result) == [], [c for c in result.checks if not c.ok]


def test_every_version_in_one_go_migrates_forward(tmp_path: Path) -> None:
    """Every 10th version from the first one: each one's upgrade path still works."""
    for upto in range(1, len(MIGRATIONS), 10):
        db_file = _old(tmp_path / str(upto), upto)
        with sqlite3.connect(db_file) as db:
            rehearsal.seed(db)
        result = rehearsal.rehearse(db_file, label=str(upto))
        assert _failed(result) == [], (upto, [c for c in result.checks if not c.ok])


def test_a_migration_that_loses_rows_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = _old(tmp_path, len(MIGRATIONS))
    with sqlite3.connect(db_file) as db:
        rehearsal.seed(db)
    # A table rebuild that forgot its INSERT ... SELECT: the rows are gone, and no
    # migration deleted them by name.
    forgot = (
        "CREATE TABLE labels_new AS SELECT * FROM labels WHERE 0;\n"
        "DROP TABLE labels;\n"
        "ALTER TABLE labels_new RENAME TO labels;\n"
    )
    monkeypatch.setattr(connection, "MIGRATIONS", (*MIGRATIONS, forgot))
    result = rehearsal.rehearse(db_file, label="loses rows")
    assert "row counts" in _failed(result)
    lost = next(c for c in result.checks if c.name == "row counts").detail
    assert lost.startswith("lost: labels 2 -> 0"), lost


def test_rows_a_cleanup_deletes_with_their_parent_are_told(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = _old(tmp_path, len(MIGRATIONS))
    with sqlite3.connect(db_file) as db:
        rehearsal.seed(db)
    monkeypatch.setattr(connection, "MIGRATIONS", (*MIGRATIONS, "DELETE FROM workspaces;"))
    result = rehearsal.rehearse(db_file, label="cascade")
    counts = next(c for c in result.checks if c.name == "row counts")
    assert counts.ok and "labels 2 -> 0" in counts.detail, counts.detail


def test_a_migration_that_deletes_by_name_is_told_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = _old(tmp_path, len(MIGRATIONS))
    with sqlite3.connect(db_file) as db:
        rehearsal.seed(db)
    monkeypatch.setattr(connection, "MIGRATIONS", (*MIGRATIONS, "DELETE FROM labels;"))
    result = rehearsal.rehearse(db_file, label="clean-up")
    counts = next(c for c in result.checks if c.name == "row counts")
    assert counts.ok and "labels 2 -> 0" in counts.detail


def test_a_broken_link_fails(tmp_path: Path) -> None:
    db_file = _old(tmp_path, len(MIGRATIONS))  # no rebuild runs (it would refuse first)
    with sqlite3.connect(db_file) as db:
        rehearsal.seed(db)
        # A row of a table every later version keeps, pointing at no workspace.
        table = "chat_turns"
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
        row = rehearsal._row(db, table, sql, 7)
        row["workspace_id"] = "no-such-workspace"
        row["chat_id"] = 999_999
        db.execute("PRAGMA foreign_keys = OFF")
        rehearsal._insert(db, table, row)
    result = rehearsal.rehearse(db_file, label="orphan")
    assert "foreign_key_check" in _failed(result)


def test_an_upgrade_path_that_ends_unlike_a_fresh_database_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = _old(tmp_path)
    with sqlite3.connect(db_file) as db:
        rehearsal.seed(db)
        db.execute("ALTER TABLE workspaces ADD COLUMN only_on_old_copies TEXT")
    result = rehearsal.rehearse(db_file, label="drift")
    assert "same shape as a fresh database" in _failed(result)


def test_the_rehearsal_never_opens_a_live_database(tmp_path: Path) -> None:
    for live in (Path("/home/agos/agos-data/system/agos.db"), Path.home() / "agos-data" / "x.db"):
        with pytest.raises(SystemExit, match="live"):
            rehearsal.copy_backup(live, tmp_path / "copy.db")


def test_a_backup_copy_is_read_only_and_copied(tmp_path: Path) -> None:
    source = _old(tmp_path / "backups")
    with sqlite3.connect(source) as db:
        seeded = rehearsal.seed(db)
    before = source.read_bytes()
    target = tmp_path / "work" / "data" / "system" / "agos.db"
    rehearsal.copy_backup(source, target)
    assert source.read_bytes() == before
    result = rehearsal.rehearse(target, label="copy")
    assert _failed(result) == []
    assert all(result.rows_before[t] >= n for t, n in seeded.items())


def test_the_newest_backup_copy_is_found(tmp_path: Path) -> None:
    older = _old(tmp_path / "a")
    newer = _old(tmp_path / "b")
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "agos.db").write_text("not a database")
    import os

    os.utime(older, (1, 1))
    assert rehearsal.newest_backup(tmp_path) == newer


def _shallow() -> bool:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(CORE), "rev-parse", "--is-shallow-repository"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode != 0 or done.stdout.strip() != "false"


@pytest.mark.skipif(_shallow(), reason="needs the git history (not a shallow checkout)")
def test_old_versions_come_from_git_history() -> None:
    found = rehearsal.history(CORE)
    lengths = [n for _, n in found]
    assert lengths == sorted(set(lengths)), "one version per length, oldest first"
    assert lengths[-1] == len(MIGRATIONS)
    sha, n = found[0]
    assert len(rehearsal.migrations_at(sha, CORE)) == n


@pytest.mark.skipif(_shallow(), reason="needs the git history (not a shallow checkout)")
def test_the_command_rehearses_old_versions_and_writes_a_report(tmp_path: Path) -> None:
    import json

    report = tmp_path / "report.json"
    rc = rehearsal.main(["--git", "2", "--work", str(tmp_path / "w"), "--report", str(report)])
    assert rc == 0
    results = json.loads(report.read_text())
    assert len(results) == 2 and all(r["ok"] for r in results)
    assert {c["name"] for c in results[0]["checks"]} >= {
        "integrity_check",
        "foreign_key_check",
        "row counts",
        "same shape as a fresh database",
        "restart changes nothing",
    }


def test_a_shallow_checkout_says_why_it_has_no_old_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The nightly's runner checked out one commit: the rehearsal found no old version and
    # only said "0/0 rehearsals passed".
    monkeypatch.setattr(rehearsal, "history", lambda **_: [])
    monkeypatch.setattr(rehearsal, "is_shallow", lambda repo=CORE: True)
    assert rehearsal.main(["--git", "12", "--work", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "shallow" in out and "fetch-depth: 0" in out


def test_a_shallow_clone_is_told_apart_from_a_full_one(tmp_path: Path) -> None:
    def git(*args: str, cwd: Path = tmp_path) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: S603, S607

    full = tmp_path / "full"
    full.mkdir()
    git("init", "-q", cwd=full)
    for n in range(2):
        (full / "f").write_text(str(n))
        git("add", "f", cwd=full)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", str(n), cwd=full)
    git("clone", "-q", "--depth", "1", f"file://{full}", "shallow")
    assert not rehearsal.is_shallow(full)
    assert rehearsal.is_shallow(tmp_path / "shallow")
