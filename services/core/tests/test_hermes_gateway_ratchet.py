"""The ratchet of the Hermes Gateway (ADR 0024): Hermes calls outside
agos_core/hermes_gateway may only go down, per rule and per file, against
hermes_gateway_baseline.json; and actions/ may not import subprocess or open a
database itself, except the files still in that baseline. A change that removes
calls lowers the baseline in the same change:
`python tests/hermes_gateway_scan.py --update` (from services/core)."""

from __future__ import annotations

import json

import hermes_gateway_scan as scan

ADVICE = "run `python tests/hermes_gateway_scan.py --update` from services/core"


def test_no_new_hermes_call_outside_the_gateway() -> None:
    now, baseline = scan.scan(), scan.load_baseline()
    grown = {
        (rule, rel): (baseline.get(rule, {}).get(rel, 0), count)
        for rule, files in now.items()
        for rel, count in files.items()
        if count > baseline.get(rule, {}).get(rel, 0)
    }
    assert not grown, (
        f"Hermes calls outside agos_core/hermes_gateway grew (baseline, now): {grown}. "
        "Go through hermes_gateway (cli, process, hermes_db) instead."
    )


def test_a_removed_call_is_recorded_in_the_baseline() -> None:
    now, baseline = scan.scan(), scan.load_baseline()
    shrunk = {
        (rule, rel): (count, now.get(rule, {}).get(rel, 0))
        for rule, files in baseline.items()
        for rel, count in files.items()
        if now.get(rule, {}).get(rel, 0) < count
    }
    assert not shrunk, f"fewer calls than the baseline says (baseline, now) {shrunk}: {ADVICE}"


def test_the_baseline_totals_match_its_counts() -> None:
    data = json.loads(scan.BASELINE.read_text())
    assert data["totals"] == scan.totals(data["counts"])


def test_actions_never_import_subprocess_outside_the_baseline() -> None:
    allowed = set(scan.load_baseline()["actions_import"])
    now = set(scan.scan()["actions_import"])
    assert now <= allowed, sorted(now - allowed)


def test_actions_never_open_a_database_outside_the_baseline() -> None:
    allowed = {r for r in scan.load_baseline()["sqlite3_connect"] if r.startswith("actions/")}
    now = {r for r in scan.scan()["sqlite3_connect"] if r.startswith("actions/")}
    assert now <= allowed, sorted(now - allowed)


def test_the_scan_sees_each_kind_of_call() -> None:
    code = "\n".join(
        [
            "import subprocess, sqlite3",
            "from agos_core.hermes_gateway import cli as hermes_cli",
            "hermes_cli.config_writes(engine, ws, [])",  # the gateway: not counted
            "core.engine._hermes(ws, 'kanban', 'list')",
            "engine.walled_cli(key, 'x')",
            "subprocess.run(['hermes'])",
            "sqlite3.connect('file:x?mode=ro', uri=True)",
            "hermes_python(settings)",
            "core.engine.runner.run(['hermes'], timeout=1)",
            "SCRIPT = 'subprocess.run([1])'",  # code in a string is Hermes's to run
        ]
    )
    found = scan.scan_file("actions/x.py", code)
    assert found == {
        "actions_import": 1,
        "engine_cli": 2,
        "subprocess": 1,
        "sqlite3_connect": 1,
        "hermes_python": 1,
        "engine_runner": 1,
    }


def test_the_gateway_and_the_engine_it_wraps_are_not_counted() -> None:
    counted = {rel for files in scan.scan().values() for rel in files}
    assert not {r for r in counted if r.startswith(scan.INSIDE)}
