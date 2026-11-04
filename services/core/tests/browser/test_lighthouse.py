"""Lighthouse budgets: performance, accessibility and best-practices scores of the main
screens on the light rig, as a ratchet.

Each screen's score per category (0-100) is kept as the points it misses
(`lighthouse.<screen>.<category>.missing_pts`, lower is better) and checked against
lighthouse-baseline.json with scripts/ci/budget_ratchet.py: more than 20% and 5 points
worse fails (a perf score moves a few points run to run). Better scores are recorded,
never a worse one:

    AGOS_LIGHTHOUSE_UPDATE=1 pytest tests/browser/test_lighthouse.py

Lighthouse is the web's pinned dev dependency (apps/web/node_modules/.bin/lighthouse),
driving Playwright's own Chromium (desktop preset, no throttling: the rig is local). The
whole report of each screen lands in AGOS_BROWSER_OUT/lighthouse/.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
LIGHTHOUSE = REPO / "apps" / "web" / "node_modules" / ".bin" / "lighthouse"
BASELINE = HERE / "lighthouse-baseline.json"
CATEGORIES = ("performance", "accessibility", "best-practices")
SCREENS = {
    "settings-general": "/settings/general",
    "ws-dashboard": "/w/{w}",
    "ws-kanban": "/w/{w}/kanban",
    "ws-inbox": "/w/{w}/inbox",
    "ws-vision": "/w/{w}/vision",
}


def _ratchet() -> ModuleType:
    path = REPO / "scripts" / "ci" / "budget_ratchet.py"
    spec = importlib.util.spec_from_file_location("budget_ratchet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def metrics(screen: str, report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """A Lighthouse report's category scores as the points each one misses."""
    out: dict[str, dict[str, Any]] = {}
    for category in CATEGORIES:
        score = (report.get("categories", {}).get(category) or {}).get("score")
        assert score is not None, f"{screen}: Lighthouse gave no {category} score"
        out[f"lighthouse.{screen}.{category}.missing_pts"] = {
            "value": round((1 - float(score)) * 100),
            "unit": "pts",
        }
    return out


# Lighthouse sometimes loses its own page-load trace ("NO_NAVSTART ... Please run
# Lighthouse again", seen on a 2-CPU runner): that run is made again.
# On GitHub's ubuntu-24.04 image 20261101 Chrome's page also dies under Lighthouse at
# random ("Page.enable: Session closed"); Lighthouse then exits on an uncaught error
# and leaves its Chrome running, and those leftovers slow every later screen into
# timeouts. Each failed try ends its Chrome, waits, and tries again.
TRIES = 5
RETRY_WAIT = 5.0
# GitHub's ubuntu-24.04 image 20261101 kills the workspace dashboard's page under
# Lighthouse ("Page.enable: Session closed", 3 tries in a row; image 20261025 passed):
# shared memory goes to /tmp instead of the runner's small /dev/shm, and WebGL keeps
# its software renderer with the GPU off.
CHROME_FLAGS = " ".join(
    (
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--enable-unsafe-swiftshader",
    )
)


def _run(url: str, chrome: str, out: Path) -> dict[str, Any]:
    for attempt in range(1, TRIES + 1):
        try:
            _lighthouse(url, chrome, out)
            break
        except subprocess.CalledProcessError:
            _end_lighthouse_chrome()
            if attempt == TRIES:
                raise
            time.sleep(RETRY_WAIT)
    report: dict[str, Any] = json.loads(out.read_text(encoding="utf-8"))
    return report


def _end_lighthouse_chrome() -> None:
    """End the Chrome a crashed Lighthouse left behind (its profile is a
    `lighthouse.XXXX` temp folder, so the test's own Playwright browser is kept)."""
    subprocess.run(
        ["/usr/bin/pkill", "-f", r"user-data-dir=\S*/lighthouse\.[A-Za-z0-9]+"],
        check=False,
        capture_output=True,
    )


def _lighthouse(url: str, chrome: str, out: Path) -> None:
    subprocess.run(  # noqa: S603 - our pinned lighthouse, our URLs
        [
            str(LIGHTHOUSE),
            url,
            f"--chrome-path={chrome}",
            f"--chrome-flags={CHROME_FLAGS}",
            f"--only-categories={','.join(CATEGORIES)}",
            "--preset=desktop",
            "--throttling-method=provided",
            "--output=json",
            f"--output-path={out}",
            "--quiet",
        ],
        check=True,
        timeout=180,
        env={**os.environ, "CHROME_PATH": chrome},
    )


def test_main_screens_keep_their_lighthouse_scores(rig: Any, browser: Any) -> None:
    assert LIGHTHOUSE.is_file(), f"no {LIGHTHOUSE}: run pnpm install"
    ratchet = _ratchet()
    folder = rig.out / "lighthouse"
    folder.mkdir(exist_ok=True)
    chrome = browser.browser_type.executable_path
    now: dict[str, dict[str, Any]] = {}
    for screen, path in SCREENS.items():
        report = _run(rig.web + path.format(w=rig.workspace), chrome, folder / f"{screen}.json")
        now.update(metrics(screen, report))
    (folder / "metrics.json").write_text(json.dumps({"metrics": now}, indent=2) + "\n")
    base = ratchet.load(BASELINE) if BASELINE.is_file() else {}
    rows = ratchet.compare(base, now)
    print("\n".join(row.line() for row in rows))
    if os.environ.get("AGOS_LIGHTHOUSE_UPDATE") == "1":
        kept = (
            json.loads(BASELINE.read_text())
            if BASELINE.is_file()
            else {"about": __doc__.split("\n\n")[0]}
        )
        kept["metrics"] = dict(sorted(ratchet.updated(base, now).items()))
        BASELINE.write_text(json.dumps(kept, indent=2) + "\n")
        return
    assert ratchet.passed(rows), "Lighthouse scores fell:\n" + "\n".join(
        row.line() for row in rows if row.status in ("worse", "missing")
    )


def test_a_score_becomes_the_points_it_misses() -> None:
    report = {
        "categories": {c: {"score": s} for c, s in zip(CATEGORIES, (0.93, 1, 0.78), strict=True)}
    }
    assert metrics("x", report) == {
        "lighthouse.x.performance.missing_pts": {"value": 7, "unit": "pts"},
        "lighthouse.x.accessibility.missing_pts": {"value": 0, "unit": "pts"},
        "lighthouse.x.best-practices.missing_pts": {"value": 22, "unit": "pts"},
    }
    with pytest.raises(AssertionError):
        metrics("x", {"categories": {"performance": {"score": None}}})


def test_a_few_points_of_noise_pass_and_a_real_drop_fails() -> None:
    ratchet = _ratchet()
    base = {"p": {"value": 4, "unit": "pts"}, "a": {"value": 0, "unit": "pts"}}
    assert ratchet.passed(
        ratchet.compare(base, {"p": {"value": 9, "unit": "pts"}, "a": {"value": 5, "unit": "pts"}})
    )
    assert not ratchet.passed(
        ratchet.compare(base, {"p": {"value": 10, "unit": "pts"}, "a": {"value": 0, "unit": "pts"}})
    )
    assert not ratchet.passed(
        ratchet.compare(base, {"p": {"value": 4, "unit": "pts"}, "a": {"value": 6, "unit": "pts"}})
    )


def test_a_lighthouse_runtime_error_is_run_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lighthouse's own errors ("NO_NAVSTART ... Please run Lighthouse again", "Page.enable:
    Session closed") are retried after its leftover Chrome is ended; a run that keeps
    failing still fails the test."""
    out = tmp_path / "x.json"
    calls: list[str] = []
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    def run(args: list[str], **_kw: Any) -> None:
        calls.append("pkill" if args[0].endswith("pkill") else "lighthouse")
        if calls == ["lighthouse"]:
            raise subprocess.CalledProcessError(1, args)
        if calls[-1] == "lighthouse":
            out.write_text('{"categories": {}}')

    monkeypatch.setattr(subprocess, "run", run)
    assert _run("http://x", "/chrome", out) == {"categories": {}}
    assert calls == ["lighthouse", "pkill", "lighthouse"]

    calls.clear()
    out.unlink()

    def broken(args: list[str], **_kw: Any) -> None:
        calls.append("pkill" if args[0].endswith("pkill") else "lighthouse")
        if calls[-1] == "lighthouse":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(subprocess.CalledProcessError):
        _run("http://x", "/chrome", out)
    assert calls == ["lighthouse", "pkill"] * TRIES
