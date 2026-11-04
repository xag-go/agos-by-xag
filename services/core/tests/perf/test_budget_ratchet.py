"""The speed / RAM / bundle-size budget ratchet (scripts/ci/budget_ratchet.py).

A measurement may be up to 20% worse than its recorded baseline (noise); more fails.
Better numbers are recorded with --update, which never raises a baseline. A metric
the baseline has but the run lost fails too (a budget can't go away unseen).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "budget_ratchet", REPO / "scripts" / "ci" / "budget_ratchet.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ratchet = _load()


def _m(**values: tuple[float, str]) -> dict[str, dict[str, object]]:
    return {k: {"value": v, "unit": u} for k, (v, u) in values.items()}


BASE = _m(**{"api.board.p50_ms": (100.0, "ms"), "core.rss_mb": (200.0, "MB")})


def test_up_to_twenty_percent_worse_passes() -> None:
    now = _m(**{"api.board.p50_ms": (119.0, "ms"), "core.rss_mb": (240.0, "MB")})
    rows = ratchet.compare(BASE, now)
    assert [r.status for r in rows] == ["ok", "ok"]


def test_more_than_twenty_percent_worse_fails() -> None:
    now = _m(**{"api.board.p50_ms": (121.0, "ms"), "core.rss_mb": (200.0, "MB")})
    rows = {r.name: r for r in ratchet.compare(BASE, now)}
    assert rows["api.board.p50_ms"].status == "worse"
    assert rows["core.rss_mb"].status == "ok"
    assert not ratchet.passed(list(rows.values()))


def test_a_tiny_absolute_change_is_noise_not_a_regression() -> None:
    base = _m(**{"api.settings.p50_ms": (4.0, "ms"), "web.login.gzip_kb": (2.0, "kB")})
    now = _m(**{"api.settings.p50_ms": (8.0, "ms"), "web.login.gzip_kb": (2.6, "kB")})
    assert [r.status for r in ratchet.compare(base, now)] == ["ok", "ok"]


def test_a_lost_metric_fails_and_a_new_one_is_told() -> None:
    now = _m(**{"api.board.p50_ms": (90.0, "ms"), "api.new.p50_ms": (5.0, "ms")})
    rows = {r.name: r.status for r in ratchet.compare(BASE, now)}
    assert rows == {"api.board.p50_ms": "better", "core.rss_mb": "missing", "api.new.p50_ms": "new"}
    assert not ratchet.passed(ratchet.compare(BASE, now))


def test_update_records_only_improvements_and_new_metrics() -> None:
    now = _m(**{"api.board.p50_ms": (80.0, "ms"), "core.rss_mb": (230.0, "MB"), "x.s": (1.0, "s")})
    new = ratchet.updated(BASE, now)
    assert new["api.board.p50_ms"]["value"] == 80.0  # better: recorded
    assert new["core.rss_mb"]["value"] == 200.0  # worse (within noise): kept
    assert new["x.s"]["value"] == 1.0  # new: recorded


def test_update_refuses_while_anything_is_worse() -> None:
    now = _m(**{"api.board.p50_ms": (300.0, "ms"), "core.rss_mb": (100.0, "MB")})
    with pytest.raises(SystemExit, match="worse"):
        ratchet.updated(BASE, now)


def test_the_command_checks_a_report_against_its_baseline(tmp_path: Path) -> None:
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"metrics": BASE}))
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"metrics": BASE}))
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {"metrics": _m(**{"api.board.p50_ms": (500.0, "ms"), "core.rss_mb": (1.0, "MB")})}
        )
    )
    script = REPO / "scripts" / "ci" / "budget_ratchet.py"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, str(script), *args], capture_output=True, text=True, check=False
        )

    assert run(str(good), "--baseline", str(base)).returncode == 0
    failed = run(str(bad), "--baseline", str(base))
    assert (
        failed.returncode == 1 and "api.board.p50_ms" in failed.stdout and "worse" in failed.stdout
    )
    assert run(str(bad), "--baseline", str(base), "--update").returncode == 1
    assert json.loads(base.read_text())["metrics"] == BASE  # refused: unchanged
