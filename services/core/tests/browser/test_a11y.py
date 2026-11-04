"""Accessibility checks: axe-core run in the browser on the owner's main screens.

What axe finds (WCAG 2.0/2.1 A and AA rules) is counted per screen and rule, as the
number of elements that break the rule, and checked against axe-baseline.json: a screen
may never break a rule on more elements than recorded (a new button with no name fails).
Fixed findings are recorded so they can't come back:

    AGOS_AXE_UPDATE=1 pytest tests/browser/test_a11y.py   # records only lower counts

axe-core is the web's pinned dev dependency (apps/web/node_modules/axe-core), injected
into the page; it reads the page and changes nothing on it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from browser import pages

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
AXE = REPO / "apps" / "web" / "node_modules" / "axe-core" / "axe.min.js"
BASELINE = HERE / "axe-baseline.json"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]

# The screens the owner lives in (path: {w} = the seeded workspace).
MAIN = {
    "new-workspace": "/new",
    "settings-general": "/settings/general",
    "settings-models": "/settings/models",
    "ws-dashboard": "/w/{w}",
    "ws-kanban": "/w/{w}/kanban",
    "ws-inbox": "/w/{w}/inbox",
    "ws-vision": "/w/{w}/vision",
    "ws-hierarchy": "/w/{w}/hierarchy",
    "ws-automations": "/w/{w}/automations",
    "ws-messages": "/w/{w}/messages",
    "ws-settings": "/w/{w}/settings",
}

RUN_JS = """async (tags) => {
  const result = await window.axe.run(document, {
    runOnly: { type: "tag", values: tags },
    resultTypes: ["violations"],
  });
  return result.violations.map((v) => ({
    id: v.id,
    nodes: v.nodes.map((n) => n.target.join(" ")),
  }));
}"""


def _updating() -> bool:
    return os.environ.get("AGOS_AXE_UPDATE") == "1"


def _baseline() -> dict[str, dict[str, int]]:
    if not BASELINE.is_file():
        return {}
    data: dict[str, dict[str, int]] = json.loads(BASELINE.read_text(encoding="utf-8"))["screens"]
    return data


def grown(found: dict[str, int], recorded: dict[str, int]) -> list[str]:
    """The rules a screen now breaks on more elements than recorded."""
    return [
        f"{rule}: {count} > {recorded.get(rule, 0)}"
        for rule, count in sorted(found.items())
        if count > recorded.get(rule, 0)
    ]


def lowered(found: dict[str, int], recorded: dict[str, int]) -> dict[str, int]:
    """The recorded counts with every improvement taken (never a higher one)."""
    out = {rule: min(count, found.get(rule, 0)) for rule, count in recorded.items()}
    return {rule: count for rule, count in sorted(out.items()) if count > 0}


def _record(name: str, counts: dict[str, int]) -> None:
    screens = {**_baseline(), name: counts}
    data = {
        "about": "tests/browser/test_a11y.py: axe-core findings (elements per rule) on the main screens; only shrinks",
        "tags": TAGS,
        "screens": dict(sorted(screens.items())),
    }
    BASELINE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("name", sorted(MAIN))
def test_main_screen_has_no_new_axe_findings(page: Any, rig: Any, name: str) -> None:
    assert AXE.is_file(), f"no {AXE}: run pnpm install"
    page.goto(MAIN[name].format(w=rig.workspace))
    pages.ready(page)
    pages.freeze(page)
    page.wait_for_timeout(300)
    page.add_script_tag(path=str(AXE))
    violations = page.evaluate(RUN_JS, TAGS)
    found = {v["id"]: len(v["nodes"]) for v in violations}
    recorded = _baseline().get(name)
    if _updating():
        _record(name, found if recorded is None else lowered(found, recorded))
        return
    assert recorded is not None, f"{name}: not in {BASELINE.name}: run with AGOS_AXE_UPDATE=1"
    worse = grown(found, recorded)
    detail = {
        v["id"]: v["nodes"][:5] for v in violations if v["id"] in {w.split(":")[0] for w in worse}
    }
    assert not worse, f"{name}: new accessibility findings {worse}; elements {detail}"


def test_every_baseline_entry_is_a_main_screen() -> None:
    assert set(_baseline()) <= set(MAIN)


def test_the_ratchet_only_shrinks() -> None:
    assert grown({"label": 2, "region": 1}, {"label": 2}) == ["region: 1 > 0"]
    assert grown({"label": 1}, {"label": 2}) == []
    assert lowered({"label": 1, "region": 4}, {"label": 2, "list": 1}) == {"label": 1}
