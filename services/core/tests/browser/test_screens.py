"""Screenshot tests: ~40 key screens of the owner's UI against stored baselines.

The owner's design stays exactly as he made it (engineering standards, hard rule 3):
a refactor that moves a pixel beyond the threshold fails here. Live parts (times,
"x ms", the Thinking ring) are masked before the shot (pages.py).

Update the baselines after an intended change, then look at every changed PNG:

    AGOS_SHOTS_UPDATE=1 pytest tests/browser/test_screens.py
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from typing import Any

import pytest
from PIL import Image, ImageDraw

from browser import pages

SETTINGS = (
    "general",
    "rules",
    "brain",
    "models",
    "tools",
    "health",
    "errors",
    "usage",
    "access",
    "notifications",
    "server",
)
WS_PAGES = (
    "",
    "/artifacts",
    "/automations",
    "/docs",
    "/hierarchy",
    "/inbox",
    "/kanban",
    "/log",
    "/messages",
    "/screen",
    "/search",
    "/sessions",
    "/settings",
    "/status",
    "/vision",
)
WS_SETTINGS = (
    "channels",
    "connections",
    "export",
    "identity",
    "keys",
    "labels",
    "learned",
    "review",
    "skill-growth",
    "work-hours",
)

# Pages that read Hermes itself (settings/hermes, helper-models, connectors, the
# workspace's capabilities) show an error on the light rig, which has no Hermes: they
# are left out here. Paths that only redirect (/settings, /w/x/chats, /w/x/goals...)
# are left out too: their target is here.


@dataclass(frozen=True)
class Screen:
    name: str
    path: str  # {w} = the seeded workspace
    action: str = ""  # done before the shot (_act)
    full: bool = True  # the whole page, else the first 1440x900
    masks: tuple[str, ...] = ()  # more live parts of this page


# Lists that grow with whatever the run did before (errors, log lines): their rows are
# masked and only the first screen is kept.
GROWING = ("main li", "main ul")
SCREENS: list[Screen] = [
    Screen("new-workspace", "/new"),
    *[Screen(f"settings-{s}", f"/settings/{s}") for s in SETTINGS if s != "errors"],
    Screen("settings-errors", "/settings/errors", full=False, masks=(*GROWING, "#errors-list")),
    *[
        Screen("ws" + (p.replace("/", "-") or "-dashboard"), "/w/{w}" + p)
        for p in WS_PAGES
        if p != "/log"
    ],
    Screen(
        "ws-log",
        "/w/{w}/log",
        full=False,
        masks=(*GROWING, "a[href*='problems'], [href*='problems']"),
    ),
    *[Screen(f"ws-settings-{s}", f"/w/{{w}}/settings/{s}") for s in WS_SETTINGS],
    Screen("ws-kanban-card-open", "/w/{w}/kanban", "card"),
    Screen("ws-command-palette", "/w/{w}/kanban", "palette"),
]


def _act(page: Any, action: str) -> None:
    if action == "card":
        page.get_by_text("Write the launch post", exact=True).first.click()
        page.locator("dialog[open]", has_text="Description").wait_for()
    elif action == "palette":
        page.keyboard.press("Control+k")
        page.locator("dialog[open]", has_text="New automation").wait_for()
    page.wait_for_timeout(400)


def _name(screen: Screen) -> str:
    return screen.name


@pytest.mark.parametrize("screen", SCREENS, ids=_name)
def test_screen_matches_its_baseline(page: Any, rig: Any, browser: Any, screen: Screen) -> None:
    name, action = screen.name, screen.action
    page.goto(screen.path.format(w=rig.workspace))
    pages.ready(page)
    pages.freeze(page)
    page.wait_for_timeout(500)
    if action:
        _act(page, action)
        pages.ready(page)
    page.evaluate(pages.NORMALISE_JS, [list(pages.MACHINE_TEXT), pages.MACHINE_PLACEHOLDER])
    page.evaluate(pages.MARK_TEXT_JS, list(pages.MASK_TEXT))
    masks = [page.locator(", ".join((*pages.MASK_SELECTORS, "[data-shot-mask]", *screen.masks)))]
    shots = rig.out / "screens"
    shots.mkdir(exist_ok=True)
    actual = shots / f"{name}.png"
    page.screenshot(
        path=str(actual),
        full_page=screen.full,
        mask=masks,
        mask_color="#ff00ff",
        animations="disabled",
        caret="hide",
    )
    folder = pages.BASELINES / pages.render_key(browser)
    baseline = folder / f"{name}.png"
    if pages.updating():
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual, baseline)
        return
    if not baseline.is_file():
        pytest.fail(
            f"no baseline {baseline.relative_to(pages.HERE)}: run with AGOS_SHOTS_UPDATE=1 and review it"
        )
    verdict = pages.compare(actual, baseline, shots / f"{name}.diff.png", pages.max_pixels())
    assert verdict.ok, (
        f"{name}: {verdict.text}; actual {actual}, diff {shots / (name + '.diff.png')}"
    )


def test_every_baseline_is_a_screen(browser: Any) -> None:
    """A screen dropped from SCREENS takes its baseline along (no stale PNG kept)."""
    folder = pages.BASELINES / pages.render_key(browser)
    names = {s.name for s in SCREENS}
    stale = sorted(p.stem for p in folder.glob("*.png") if p.stem not in names)
    assert not stale, f"baselines with no screen: {stale}"
    assert all(re.fullmatch(r"[a-z0-9-]+", n) for n in names)


def test_the_diff_fails_on_a_moved_block_and_passes_on_noise(tmp_path: Any) -> None:
    """The gate itself: a real change (a block moved by 6 px) fails, anti-aliasing
    noise (every pixel off by a few levels) passes."""
    base = Image.new("RGB", (400, 300), (245, 247, 250))
    ImageDraw.Draw(base).rectangle((40, 40, 140, 90), fill=(13, 148, 136))
    moved = Image.new("RGB", (400, 300), (245, 247, 250))
    ImageDraw.Draw(moved).rectangle((46, 40, 146, 90), fill=(13, 148, 136))
    noisy = base.point(lambda v: min(255, v + 6))
    for name, img in (("base", base), ("moved", moved), ("noisy", noisy)):
        img.save(tmp_path / f"{name}.png")
    bad = pages.compare(tmp_path / "moved.png", tmp_path / "base.png", tmp_path / "d1.png", 400)
    assert not bad.ok and (tmp_path / "d1.png").is_file(), bad.text
    good = pages.compare(tmp_path / "noisy.png", tmp_path / "base.png", tmp_path / "d2.png", 400)
    assert good.ok and good.ratio == 0, good.text
