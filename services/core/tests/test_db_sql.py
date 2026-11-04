"""db/sql.py: SQL text only from `?` marks and names out of a constant set; and the CI
junit summary reads pytest's file with a parser that refuses DTDs."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from agos_core.db import sql

REPO = Path(__file__).resolve().parents[3]


def test_marks_fit_an_in_list_and_the_values_stay_parameters() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (id INTEGER, name TEXT)")
    db.executemany("INSERT INTO t VALUES (?, ?)", [(1, "a"), (2, "b'); DROP TABLE t; --")])
    ids = [1, 2]
    query = sql.text("SELECT name FROM t WHERE id IN ({ids}) ORDER BY id", ids=sql.marks(2))
    assert query == "SELECT name FROM t WHERE id IN (?, ?) ORDER BY id"
    assert [r[0] for r in db.execute(query, ids)] == ["a", "b'); DROP TABLE t; --"]
    # No values: `IN ()` (SQLite reads it as an empty list), as before.
    assert sql.marks(0) == ""
    assert (
        db.execute(sql.text("SELECT 1 FROM t WHERE id IN ({m})", m=sql.marks(0))).fetchall() == []
    )
    with pytest.raises(ValueError):
        sql.marks(-1)


def test_a_name_must_be_one_of_the_constant_set() -> None:
    assert sql.name("title", {"title", "name"}) == "title"
    with pytest.raises(ValueError):
        sql.name("title; DROP TABLE t", {"title"})
    with pytest.raises(ValueError):
        sql.name("why", {"title"})
    # Even an allowed entry must look like a name.
    with pytest.raises(ValueError):
        sql.name("a b", {"a b"})


def test_assignments_and_select_lists_check_every_column() -> None:
    cols = frozenset({"status", "error"})
    assert sql.assignments(["status", "error"], cols) == "status = ?, error = ?"
    with pytest.raises(ValueError):
        sql.assignments(["status", "owner"], cols)
    wanted = ("id", "title", "block_kind")
    assert sql.or_null(wanted, {"id", "title"}, wanted) == "id, title, NULL AS block_kind"
    with pytest.raises(ValueError):
        sql.or_null(("id", "x"), {"id"}, ("id",))


def test_a_name_read_from_a_file_is_always_a_quoted_identifier() -> None:
    """A table name from a database file (which another process can write) is quoted,
    any quote inside doubled: it names a table and never runs as SQL."""
    db = sqlite3.connect(":memory:")
    odd = 'x" FROM t; DROP TABLE t; --'
    db.execute(sql.text("CREATE TABLE {t} (id TEXT)", t=sql.quoted("t")))
    db.execute(sql.text("CREATE TABLE {t} (id TEXT)", t=sql.quoted(odd)))
    assert sql.quoted(odd) == '"x"" FROM t; DROP TABLE t; --"'
    assert db.execute(sql.text("SELECT COUNT(*) FROM {t}", t=sql.quoted(odd))).fetchone()[0] == 0
    names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names == {"t", odd}


def test_text_takes_only_pieces_made_here() -> None:
    with pytest.raises(TypeError):
        sql.text("SELECT * FROM t WHERE id IN ({ids})", ids="1) OR (1=1")  # type: ignore[arg-type]
    assert sql.text("SELECT {c} FROM t", c=sql.name("c", {"c"})) == "SELECT c FROM t"


# ---- scripts/ci/junit_summary.py ---------------------------------------------------


def _summary_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "junit_summary", REPO / "scripts/ci/junit_summary.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(path: Path) -> str:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(REPO / "scripts/ci/junit_summary.py"), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def test_junit_summary_reads_pytests_counts(tmp_path: Path) -> None:
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
        'errors="0" failures="1" skipped="3" tests="10" time="12.4"><testcase/></testsuite>'
        "</testsuites>"
    )
    assert _run(junit) == "### Core tests: 10 run, 1 failed, 0 errors, 3 skipped, 12 s"
    assert _run(tmp_path / "gone.xml") == "### Core tests: no gone.xml (pytest did not finish)"


def test_junit_summary_refuses_entities_and_doctypes(tmp_path: Path) -> None:
    bomb = tmp_path / "pytest.xml"
    bomb.write_text(
        '<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
        '<testsuite tests="&b;"/>'
    )
    assert _run(bomb).startswith("### Core tests: pytest.xml not read")
    module = _summary_module()
    with pytest.raises(module._Refused):
        module.suite_attributes(b'<!DOCTYPE t SYSTEM "file:///etc/passwd"><testsuite/>')
    assert module.suite_attributes(b"<testsuites/>") == {}
