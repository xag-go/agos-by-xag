"""scripts/slo.py: the monthly SLO report from `slo_samples` (docs/compliance/sre.md).
Read-only on the database; each SLI judged against its SLO; a minute with no health
sample counts as down."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "slo.py"


def _slo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("slo_report", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["slo_report"] = module
    spec.loader.exec_module(module)
    return module


def _db(path: Path) -> sqlite3.Connection:
    from agos_core.db.connection import open_database

    return open_database(path)


def _add(db: sqlite3.Connection, sli: str, at: str, value: int | None, ok: int = 1) -> None:
    db.execute(
        "INSERT INTO slo_samples (sli, subject, value_ms, ok, at) VALUES (?, '', ?, ?, ?)",
        (sli, value, ok, at),
    )


def test_the_report_judges_each_sli_for_the_month(tmp_path: Path) -> None:
    file = tmp_path / "agos.db"
    db = _db(file)
    for minute in range(10):  # 10 health probes, one failed; 5 minutes with none
        _add(db, "health", f"2026-10-01T00:{minute:02d}:00.000Z", 3, 0 if minute == 4 else 1)
    for ms in (300, 500, 900, 1200):
        _add(db, "page", "2026-10-02T00:00:00.000Z", ms)
    for ms in (1000, 2000, 5000, 7000, 30000):
        _add(db, "first_output", "2026-10-03T00:00:00.000Z", ms)
    _add(db, "automation_delay", "2026-10-04T00:00:00.000Z", 1000, 1)
    _add(db, "automation_delay", "2026-10-04T00:00:00.000Z", 300000, 0)
    _add(db, "page", "2026-11-01T00:00:00.000Z", 99999)  # next month: not counted
    db.close()
    report = _slo().report(file, "2026-10", now="2026-10-01T00:15:00.000Z")
    rows = {r["sli"]: r for r in report["rows"]}
    assert rows["S1 page"]["samples"] == 4
    assert rows["S1 page"]["value"] == 50.0 and rows["S1 page"]["met"] is False  # 95% ≤ 800 ms
    assert rows["S2 first output"]["value"] == 60.0  # 3 of 5 within 6 s
    assert rows["S2 first output"]["met"] is False
    # 15 minutes since the first probe: 9 ok of 15 expected.
    assert rows["S3 availability"]["value"] == 60.0
    assert rows["S4 automation on time"]["value"] == 50.0
    assert report["month"] == "2026-10"


def test_the_script_prints_a_markdown_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tmp_path / "agos.db"
    db = _db(file)
    _add(db, "page", "2026-10-02T00:00:00.000Z", 100)
    db.close()
    slo = _slo()
    assert slo.main(["--db", str(file), "--month", "2026-10"]) == 0
    out = capsys.readouterr().out
    assert "| S1 page |" in out and "no samples" in out  # S2 has none
    assert slo.main(["--db", str(file), "--month", "2026-10", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"][0]["samples"] == 1
    assert slo.main(["--db", str(tmp_path / "none.db")]) == 2
