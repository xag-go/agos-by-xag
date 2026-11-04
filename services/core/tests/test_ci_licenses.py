"""scripts/ci/licenses.py: the dependency licence gate (allowed ids + reviewed exceptions)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ci" / "licenses.py"


def _gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("licenses_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POLICY = {
    "allowed": ["MIT", "Apache-2.0", "BSD-3-Clause"],
    "own": ["agos"],
    "exceptions": {"node": {"libvips": {"license": "LGPL-3.0-or-later", "why": "dynamic"}}},
}


def test_copyleft_unknown_and_source_available_fail() -> None:
    gate = _gate()
    packages = {
        "ok": "MIT",
        "gpl": "GPL-3.0-only",
        "agpl": "AGPL-3.0-or-later",
        "sspl": "SSPL-1.0",
        "none": "UNKNOWN",
        "agos": "UNKNOWN",
    }
    problems = gate.check("node", packages, POLICY)
    assert problems == [
        "node: agpl is AGPL-3.0-or-later",
        "node: gpl is GPL-3.0-only",
        "node: none is UNKNOWN",
        "node: sspl is SSPL-1.0",
    ]


def test_or_needs_one_side_and_needs_both() -> None:
    gate = _gate()
    ids = set(POLICY["allowed"])
    assert gate.allowed("(MIT OR GPL-3.0-only)", ids)
    assert gate.allowed("Apache-2.0 OR BSD-3-Clause", ids)
    assert not gate.allowed("MIT AND GPL-2.0-only", ids)
    assert gate.allowed("MIT AND Apache-2.0", ids)
    assert gate.allowed("MIT License", ids)  # the Python spelling


def test_an_exception_holds_only_for_its_reviewed_licence() -> None:
    gate = _gate()
    assert gate.check("node", {"libvips": "LGPL-3.0-or-later"}, POLICY) == []
    assert gate.check("node", {"libvips": "GPL-3.0-only"}, POLICY) == [
        "node: libvips is GPL-3.0-only"
    ]
    assert gate.check("python", {"libvips": "LGPL-3.0-or-later"}, POLICY) == [
        "python: libvips is LGPL-3.0-or-later"
    ]


def test_the_cli_fails_on_a_new_incompatible_licence(tmp_path: Path) -> None:
    report = tmp_path / "pnpm.json"
    report.write_text(
        json.dumps(
            {
                "MIT": [{"name": "left-pad", "versions": ["1.3.0"]}],
                "AGPL-3.0": [{"name": "copyleft-thing", "versions": ["2.0.0"]}],
            }
        )
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "node", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1
    assert "copyleft-thing is AGPL-3.0" in done.stdout
    report.write_text(json.dumps({"MIT": [{"name": "left-pad", "versions": ["1.3.0"]}]}))
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "node", str(report)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout


def test_the_policy_never_allows_copyleft_or_source_available_outright() -> None:
    policy = json.loads((REPO / "scripts" / "ci" / "licenses-allowed.json").read_text())
    for lic in policy["allowed"]:
        assert not any(bad in lic.upper() for bad in ("GPL", "SSPL", "BUSL", "FSL", "UNKNOWN")), lic
    for ecosystem in policy["exceptions"].values():
        for name, reviewed in ecosystem.items():
            assert reviewed["why"].strip(), name


def test_this_environment_passes() -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "python"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout
