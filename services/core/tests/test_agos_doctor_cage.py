"""`agos doctor` reports the cage (audit F9): the core's own "Workspace isolation"
section (actions/isolation.py, tests/test_cage_required.py) plus the command's own
bwrap self-test as the AGOS user, so a broken cage shows its code and fix even
when the core's view is stale."""

from __future__ import annotations

import stat
from pathlib import Path

from test_agos_cli import Machine, machine  # noqa: F401 - the fake machine fixture


def _bwrap(machine: Machine, *, works: bool) -> None:  # noqa: F811
    shim = Path(machine.env["FAKE"]) / "bin" / "bwrap"
    shim.write_text("#!/usr/bin/env bash\n" + ("exit 0\n" if works else "exit 1\n"))
    shim.chmod(stat.S_IRWXU)


def test_doctor_says_the_cage_works(machine: Machine) -> None:  # noqa: F811
    _bwrap(machine, works=True)
    text = machine.agos("doctor").stdout
    assert "- cage self-test (bwrap as " in text and "): ok" in text


def test_doctor_shows_a_broken_cage_with_its_code_and_the_fix(machine: Machine) -> None:  # noqa: F811
    _bwrap(machine, works=False)
    text = machine.agos("doctor").stdout
    assert "FAILED (cage_refused)" in text
    assert "deploy/cage-setup.sh self-test" in text
