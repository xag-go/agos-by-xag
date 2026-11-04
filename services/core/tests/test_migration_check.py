"""The expand/contract check (scripts/migration_check.py, docs/operations.md "Schema
changes"): every migration since 140 only adds; a removal needs its own contract step."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from agos_core.db.migrations import MIGRATIONS

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migration_check.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _with(*extra: str) -> tuple[tuple[str, ...], int]:
    return (*MIGRATIONS, *extra), len(MIGRATIONS) + 1


def test_the_shipped_migrations_are_additive() -> None:
    assert _script().check() == []


def test_a_dropped_column_or_table_is_refused() -> None:
    check = _script().check
    added = "CREATE TABLE probe (id INTEGER PRIMARY KEY, a TEXT, b TEXT) STRICT;"
    migrations, first = _with(added, "ALTER TABLE probe DROP COLUMN b;", "DROP TABLE probe;")
    problems = check(migrations, first)
    assert problems == [
        f"migration {first + 1} removes probe.b with no '-- agos: contract probe.b' step",
        f"migration {first + 2} removes probe with no '-- agos: contract probe' step",
    ]


def test_a_rename_is_a_removal_too() -> None:
    added = "CREATE TABLE probe (id INTEGER PRIMARY KEY, a TEXT) STRICT;"
    migrations, first = _with(added, "ALTER TABLE probe RENAME COLUMN a TO c;")
    assert _script().check(migrations, first) == [
        f"migration {first + 1} removes probe.a with no '-- agos: contract probe.a' step"
    ]


def test_a_named_contract_step_and_a_full_rebuild_pass() -> None:
    added = "CREATE TABLE probe (id INTEGER PRIMARY KEY, a TEXT, b TEXT) STRICT;"
    rebuild = """
  CREATE TABLE probe_new (id INTEGER PRIMARY KEY, a TEXT, b TEXT, c TEXT) STRICT;
  INSERT INTO probe_new (id, a, b) SELECT id, a, b FROM probe;
  DROP TABLE probe;
  ALTER TABLE probe_new RENAME TO probe;
  """
    contract = "  -- agos: contract probe.b\n  ALTER TABLE probe DROP COLUMN b;\n"
    migrations, first = _with(added, rebuild, contract)
    assert _script().check(migrations, first) == []
