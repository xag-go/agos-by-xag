"""The web's accessibility lint ratchet (scripts/ci/a11y_lint.py).

jsx-a11y findings are counted per file and rule; a file may never get more than its
baseline (a new button with no name fails), and a fixed finding must be recorded so it
can't come back.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / "ci" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


a11y = _load("a11y_lint")


def _result(web: Path, rel: str, *rules: str) -> dict[str, object]:
    return {
        "filePath": str(web / rel),
        "messages": [{"ruleId": r, "message": "m", "line": 1} for r in rules],
    }


def test_counts_only_jsx_a11y_findings_per_file_and_rule(tmp_path: Path) -> None:
    results = [
        _result(
            tmp_path,
            "src/a.tsx",
            "jsx-a11y/no-autofocus",
            "jsx-a11y/no-autofocus",
            "react-hooks/exhaustive-deps",
            "jsx-a11y/control-has-associated-label",
        ),
        _result(tmp_path, "src/b.tsx", "@next/next/no-img-element"),
    ]
    assert a11y.counts(results, tmp_path) == {
        "apps/web/src/a.tsx": {"control-has-associated-label": 1, "no-autofocus": 2}
    }


def test_a_file_eslint_cannot_parse_stops_the_check(tmp_path: Path) -> None:
    broken = {
        "filePath": str(tmp_path / "src/x.tsx"),
        "messages": [{"ruleId": None, "fatal": True, "message": "Unexpected token"}],
    }
    with pytest.raises(SystemExit, match=r"can.t parse src/x\.tsx"):
        a11y.counts([broken], tmp_path)


def test_a_new_finding_is_worse_and_a_fixed_one_is_better() -> None:
    base = {"apps/web/src/a.tsx": {"no-autofocus": 2}, "apps/web/src/b.tsx": {"x": 1}}
    now = {"apps/web/src/a.tsx": {"no-autofocus": 1}, "apps/web/src/c.tsx": {"y": 1}}
    worse, better = a11y.compare(now, base)
    assert worse == ["  apps/web/src/c.tsx: y 1 (baseline 0)"]
    assert better == [
        "  apps/web/src/a.tsx: no-autofocus 1 < 2",
        "  apps/web/src/b.tsx: x 0 < 1",
    ]
    assert a11y.compare(base, base) == ([], [])


@pytest.mark.skipif(
    not (REPO / "apps/web/node_modules").is_dir() or shutil.which("pnpm") is None,
    reason="the check needs apps/web's node_modules and pnpm",
)
def test_the_web_has_no_new_accessibility_finding() -> None:
    done = subprocess.run(  # noqa: S603 - our own script with our interpreter
        [sys.executable, str(REPO / "scripts/ci/a11y_lint.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
