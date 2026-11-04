"""Page helpers for the browser tests: wait until a page is really ready, freeze what
moves, and compare a screenshot with its stored baseline (pixel diff + threshold).

Baselines live in tests/browser/screens/<render key>/<name>.png. The render key names
the browser build (Playwright's own Chromium, the same on every machine with the same
Playwright version), so text renders the same here and on a CI runner: the web's fonts
are its own (next/font), the system fonts it names are the rig's copies (conftest.py
pin_fonts), only a missing glyph falls back to the system's fonts.

    AGOS_SHOTS_UPDATE=1      write the baselines instead of comparing (then review them)
    AGOS_SHOTS_MAX_PIXELS    pixels allowed to differ per screen (default 400: a glyph the
                             system's fonts draw, never a moved button or a new color)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
BASELINES = HERE / "screens"
# A pixel "differs" when one of its channels moved more than this (anti-aliasing noise
# stays under it).
PIXEL_TOLERANCE = 40
MAX_HEIGHT = 6000

# Nothing moves while a screenshot is taken: no animation, no transition, no caret.
FREEZE_CSS = (
    "*,*::before,*::after{animation:none!important;transition:none!important;"
    "caret-color:transparent!important;scroll-behavior:auto!important}"
)

READY_JS = """() => document.readyState === 'complete'
  && !document.querySelector('[role=status][aria-label=Loading]')
  && document.fonts.status === 'loaded'
  && (Object.keys(document).some(k => k.startsWith('__reactContainer'))
      || !!document.querySelector('#__next, body > div'))"""

# Live things a baseline can't hold: clocks, relative times ("2 min ago"), server-timed
# text ("1.2 ms"), the answer's "Thinking…" ring, ids made from the time.
MASK_SELECTORS = (
    "time",
    "[data-live]",
    "[aria-label='Thinking']",
)
# Text patterns whose smallest element is masked (JS RegExp source, case-insensitive).
MASK_TEXT = (
    r"^\s*\d+(\.\d+)?\s*ms\s*$",
    r"\b(just now|\d+\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)\.?\s+ago)\b",
    r"\bThinking\b",
    r"\b\d{1,2}:\d{2}(\s*[AP]M)?\b",
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+\w+\s+\d{1,2}\b",
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(,\s*\d{4})?\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b(today|yesterday|tomorrow)\b",
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b",
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    # git shas (the running version), error refs and digests.
    r"\b[0-9a-f]{7,40}\b",
    # This machine: folders (the rig's data dir) and sizes (disk free, data size).
    r"(^|\s)/[\w.@+-]+/",
    r"\b\d+(\.\d+)?\s*(B|KB|MB|GB|TB|KiB|MiB|GiB)\b",
)

# This machine's values (folders, sizes): their LENGTH differs by machine and run (the
# rig's data dir sits under pytest's numbered temp dir; disk free moves), so a mask
# over them would be as wide as the text. The element's whole text is replaced with
# one fixed placeholder before it is masked: the same box on every machine. Tested on
# the element's whole text when it holds only text (React splits "{n} GB free of {m}
# GB" into several text nodes).
MACHINE_TEXT = MASK_TEXT[-2:]
MACHINE_PLACEHOLDER = "machine value"

NORMALISE_JS = """([patterns, placeholder]) => {
  const res = patterns.map(p => new RegExp(p, 'i'));
  const found = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const el = walker.currentNode.parentElement;
    if (!el || found.has(el) || el.children.length) continue;
    if (res.some(r => r.test(el.textContent || ''))) found.add(el);
  }
  for (const el of found) { el.textContent = placeholder; el.setAttribute('data-shot-mask', ''); }
  return found.size;
}"""

MARK_TEXT_JS = """(patterns) => {
  const res = patterns.map(p => new RegExp(p, 'i'));
  let n = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.nodeValue || '';
    if (!text.trim() || !res.some(r => r.test(text))) continue;
    const el = node.parentElement;
    if (el && !el.hasAttribute('data-shot-mask')) { el.setAttribute('data-shot-mask', ''); n++; }
  }
  return n;
}"""


def ready(page: Any, timeout_s: float = 25) -> None:
    """The page drew its data: loaded, hydrated, no section still loading."""
    page.wait_for_load_state("load")
    page.wait_for_function(READY_JS, timeout=timeout_s * 1000)


def freeze(page: Any) -> None:
    page.add_style_tag(content=FREEZE_CSS)
    page.evaluate(
        "() => document.activeElement && document.activeElement.blur && document.activeElement.blur()"
    )


def render_key(browser: Any) -> str:
    major = str(browser.version).split(".", 1)[0]
    # Another browser (AGOS_BROWSER_EXECUTABLE) renders with the machine's own build.
    return f"{'local-' if os.environ.get('AGOS_BROWSER_EXECUTABLE') else ''}chromium-{major}"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    text: str
    ratio: float


def compare(actual: Path, baseline: Path, diff_out: Path, max_pixels: int) -> Verdict:
    """Pixels that differ beyond the anti-aliasing tolerance, at most `max_pixels`."""
    with Image.open(actual) as a_img, Image.open(baseline) as b_img:
        a, b = a_img.convert("RGB"), b_img.convert("RGB")
        if a.size != b.size:
            return Verdict(False, f"size {a.size} != baseline {b.size}", 1.0)
        delta = ImageChops.difference(a, b)
        channels = delta.split()
        worst = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
        mask = worst.point(lambda v: 255 if v > PIXEL_TOLERANCE else 0)
        differing = mask.histogram()[255]
        total = a.size[0] * a.size[1]
        ratio = differing / total
        if differing:
            Image.composite(Image.new("RGB", a.size, (255, 0, 64)), a.convert("RGB"), mask).save(
                diff_out
            )
        ok = differing <= max_pixels
        return Verdict(ok, f"{differing} px differ ({ratio:.4%}; limit {max_pixels} px)", ratio)


def max_pixels() -> int:
    return int(os.environ.get("AGOS_SHOTS_MAX_PIXELS", "400"))


def updating() -> bool:
    return os.environ.get("AGOS_SHOTS_UPDATE", "") not in ("", "0")
