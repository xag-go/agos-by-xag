"""Typed config's ratchet: reads of the process environment outside
agos_core/config.py may only go down, per file, against environ_baseline.json. A
change that removes reads lowers the baseline in the same change:
`python tests/environ_scan.py --update` (from services/core)."""

from __future__ import annotations

import json

import environ_scan as scan

ADVICE = "run `python tests/environ_scan.py --update` from services/core"


def test_no_new_environment_read_outside_config() -> None:
    now, baseline = scan.scan(), scan.load_baseline()
    grown = {rel: (baseline.get(rel, 0), n) for rel, n in now.items() if n > baseline.get(rel, 0)}
    assert not grown, (
        f"os.environ / os.getenv outside config.py grew (baseline, now): {grown}. "
        "Add the setting to Settings (agos_core/config.py) and pass it in instead."
    )


def test_a_removed_read_is_recorded_in_the_baseline() -> None:
    now, baseline = scan.scan(), scan.load_baseline()
    shrunk = {rel: (n, now.get(rel, 0)) for rel, n in baseline.items() if now.get(rel, 0) < n}
    assert not shrunk, f"fewer reads than the baseline says (baseline, now) {shrunk}: {ADVICE}"


def test_the_baseline_total_matches_its_counts() -> None:
    data = json.loads(scan.BASELINE.read_text())
    assert data["total"] == sum(data["counts"].values())


def test_the_scan_sees_each_kind_of_read() -> None:
    code = "\n".join(
        [
            "import os",
            "from os import environ as env, getenv",
            "a = os.environ.get('AGOS_X')",
            "b = os.environ['AGOS_Y']",
            "c = os.getenv('AGOS_Z')",
            "d = dict(os.environ)",
            "e = env.get('AGOS_W')",
            "f = getenv('AGOS_V')",
            "TEXT = 'os.environ in a string is not a read'",
        ]
    )
    assert scan.scan_file(code) == 6


def test_config_is_the_one_module_left_out() -> None:
    assert "config.py" not in scan.scan()
    assert scan.scan_file((scan.SRC / scan.CONFIG).read_text()) > 0
