"""Browser tests run only when asked for by path (`pytest tests/browser`): they need a
web build and a browser, so the core suite (`pytest`, CI's core-tests job) skips them.

Fixtures: `rig` (the light core + the web server, rig.py), `browser` (Playwright's
Chromium; AGOS_BROWSER_EXECUTABLE runs another one, e.g. /usr/bin/google-chrome, for a
quick local click run — screenshots then need their own baselines), `page` (a fresh
context (1440x900, its uncaught page errors fail the test).

Fonts: the web names some system fonts (the Vision line's serif is "Noto Serif", then
DejaVu Serif), so a page would draw with whatever this machine has installed. Every
context gets the rig's own copy of those fonts (fonts/, OFL) under the same family
name, served by the context itself: the same glyphs on every machine, with or without
the fonts installed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from explicit_only import ignore_unless_asked
from playwright.sync_api import sync_playwright

from browser.rig import light_rig

HERE = Path(__file__).resolve().parent
VIEWPORT = {"width": 1440, "height": 900}

# The system fonts the web asks for by name -> the rig's copy (family, weight, file).
FONTS_DIR = HERE / "fonts"
PINNED_FONTS = (
    ("Noto Serif", "400", "NotoSerif-Regular.ttf"),
    ("Noto Serif", "700", "NotoSerif-Bold.ttf"),
)
FONT_ROUTE = "/__agos-rig-fonts/"
# A FontFace added before the page's own scripts wins over an installed font of the
# same family; loading them up front means the first paint already uses them.
PIN_FONTS_JS = """(() => {
  const faces = %s;
  for (const [family, weight, file] of faces) {
    const face = new FontFace(family, `url(%s${file})`, {weight, style: 'normal'});
    document.fonts.add(face);
    face.load().catch(() => {});
  }
})();"""


def pin_fonts(context: Any) -> None:
    """Serve the rig's fonts to this context and make the page use them."""

    def serve(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        known = {file for _, _, file in PINNED_FONTS}
        if name not in known:
            route.fulfill(status=404, body="")
            return
        route.fulfill(
            status=200, body=(FONTS_DIR / name).read_bytes(), headers={"content-type": "font/ttf"}
        )

    context.route(f"**{FONT_ROUTE}*", serve)
    faces = json.dumps([list(face) for face in PINNED_FONTS])
    context.add_init_script(script=PIN_FONTS_JS % (faces, FONT_ROUTE))


pytest_ignore_collect = ignore_unless_asked(HERE)


@pytest.fixture(scope="session")
def rig() -> Iterator[Any]:
    with light_rig() as started:
        yield started


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    with sync_playwright() as p:
        executable = os.environ.get("AGOS_BROWSER_EXECUTABLE") or None
        launched = p.chromium.launch(
            executable_path=executable,
            args=[
                "--force-color-profile=srgb",
                "--font-render-hinting=none",
                "--disable-lcd-text",
                "--hide-scrollbars",
            ],
        )
        yield launched
        launched.close()


@pytest.fixture
def page(rig: Any, browser: Any) -> Iterator[Any]:
    context = browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=1,
        locale="en-US",
        timezone_id="UTC",
        color_scheme="light",
        reduced_motion="reduce",
        bypass_csp=True,  # the frozen-animation style tag (pages.freeze) is inline
        base_url=rig.web,
    )
    context.set_default_timeout(15_000)
    pin_fonts(context)
    opened = context.new_page()
    errors: list[str] = []
    opened.on("pageerror", lambda error: errors.append(str(error)))
    yield opened
    context.close()
    assert not errors, f"uncaught errors in the page: {errors}"
