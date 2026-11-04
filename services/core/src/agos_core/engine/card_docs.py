"""A card's documents, as rules on text alone (no files, no database).

A card's documents are markdown files in the workspace folder the agents already
read and write (`cards/<card>/<key>.md`, actions/card_docs.py). Every save is a
revision: the body is kept as `.revisions/<key>/v<N>.md` and one line goes to that
document's CHANGES.md (who, why, when). This module knows the names, the CHANGES
lines, and how a passage comment finds its passage again after the text changed.

Re-anchoring (Paperclip's dual selector, packages/shared/src/document-anchors.ts):
a comment keeps the quoted passage with a little context before and after it and
its positions in the text it was made on. On a new revision the quote is looked
for again: found once (or found several times and told apart by its context) =
`active`; not found as is but a passage close enough (difflib ratio >= 0.6) =
`stale`, with the new positions; nothing close = `orphaned` (its old positions
kept, marked as such).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

FOLDER = "cards"  # <workspace files>/cards/<card id>/<key>.md
REVISIONS = ".revisions"  # <card folder>/.revisions/<key>/v<N>.md + CHANGES.md
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CONTEXT = 32  # letters of context kept before and after a quoted passage
FUZZY = 0.6  # the least likeness for a moved passage to still be the same one
MAX_SCAN = 400_000  # letters: past this a fuzzy search is only tried near the context
# A document key from a file name: letters, digits, "-" and "_"; the rest becomes "-".
_SLUG = re.compile(r"[^A-Za-z0-9_-]+")


def clean_key(key: str) -> str | None:
    """The document key of what was asked (`notes`, `notes.md`), or None when it
    can't be one (a path, a hidden name, spaces...)."""
    text = key.strip()
    text = text.removesuffix(".md")
    return text if KEY.match(text) else None


def slug(name: str) -> str:
    """A key for a file's name: `Launch plan v2.md` -> `Launch-plan-v2`."""
    stem = name.rsplit("/", 1)[-1]
    stem = stem.removesuffix(".md").removesuffix(".markdown")
    out = _SLUG.sub("-", stem).strip("-_")[:64]
    return out if KEY.match(out) else "document"


@dataclass(frozen=True)
class Revision:
    n: int
    at: str
    who: str
    why: str


# One CHANGES.md line per revision (oldest first; appended, never rewritten).
_LINE = re.compile(r"^- v(\d+) \| ([^|]*) \| ([^|]*) \| (.*)$")


def changes_header(key: str) -> str:
    return f"# Changes: {key}.md\n\n"


def changes_line(rev: Revision) -> str:
    who = rev.who.replace("|", "/").strip() or "?"
    why = " ".join(rev.why.split()).replace("|", "/")[:300]
    return f"- v{rev.n} | {rev.at} | {who} | {why}\n"


def parse_changes(text: str) -> list[Revision]:
    """The revisions a CHANGES.md lists, oldest first (a line that isn't one is skipped)."""
    out = []
    for line in text.splitlines():
        found = _LINE.match(line.strip())
        if found:
            out.append(
                Revision(int(found[1]), found[2].strip(), found[3].strip(), found[4].strip())
            )
    out.sort(key=lambda r: r.n)
    return out


# ---- passage comments: finding the passage again ------------------------------------------


@dataclass(frozen=True)
class Anchor:
    """Where a comment's passage is: its quote with its context, its positions, and
    how surely it was found in the text those positions are for."""

    quote: str
    prefix: str
    suffix: str
    start: int
    end: int
    state: str = "active"  # active | stale | orphaned


def anchor_of(text: str, start: int, end: int) -> Anchor | None:
    """A new comment's anchor from a selection in `text` (None: an empty or
    impossible selection)."""
    if not (0 <= start < end <= len(text)):
        return None
    quote = text[start:end]
    if not quote.strip():
        return None
    return Anchor(
        quote, text[max(0, start - CONTEXT) : start], text[end : end + CONTEXT], start, end
    )


def reanchor(anchor: Anchor, text: str) -> Anchor:
    """The same comment on a new text: its new positions and state."""
    quote = anchor.quote
    if not quote:
        return replace(anchor, state="orphaned")
    hits = _all(text, quote)
    if len(hits) == 1:
        return replace(anchor, start=hits[0], end=hits[0] + len(quote), state="active")
    if hits:
        best = max(
            hits,
            key=lambda at: (_context_score(anchor, text, at, len(quote)), -abs(at - anchor.start)),
        )
        return replace(anchor, start=best, end=best + len(quote), state="active")
    found = _fuzzy(anchor, text)
    if found is None:
        return replace(anchor, state="orphaned")
    start, end = found
    return replace(anchor, start=start, end=end, state="stale")


def _all(text: str, quote: str) -> list[int]:
    out: list[int] = []
    at = text.find(quote)
    while at >= 0 and len(out) < 200:
        out.append(at)
        at = text.find(quote, at + 1)
    return out


def _context_score(anchor: Anchor, text: str, at: int, length: int) -> int:
    """How many letters of the kept context match around a hit."""
    before = text[max(0, at - len(anchor.prefix)) : at]
    after = text[at + length : at + length + len(anchor.suffix)]
    return _common_suffix(before, anchor.prefix) + _common_prefix(after, anchor.suffix)


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def _common_suffix(a: str, b: str) -> int:
    return _common_prefix(a[::-1], b[::-1])


def _fuzzy(anchor: Anchor, text: str) -> tuple[int, int] | None:
    """The passage most like the quote, when it is like enough (FUZZY): its
    positions. Looked for first where the context still is (the prefix or the
    suffix found as is), then along the whole text in steps (skipped on a text
    past MAX_SCAN letters: the context is the only guide there)."""
    quote = anchor.quote
    length = len(quote)
    candidates: list[int] = []
    if anchor.prefix:
        for at in _all(text, anchor.prefix)[:20]:
            candidates.append(at + len(anchor.prefix))
    if anchor.suffix:
        for at in _all(text, anchor.suffix)[:20]:
            candidates.append(max(0, at - length))
    if len(text) <= MAX_SCAN:
        step = max(1, length // 3)
        candidates.extend(range(0, max(1, len(text) - length // 2), step))
    best: tuple[float, int, int] | None = None
    matcher = difflib.SequenceMatcher(None, quote, "", autojunk=False)
    seen: set[tuple[int, int]] = set()
    for at in candidates:
        for span in (length, int(length * 1.25) + 1, max(1, int(length * 0.8))):
            start, end = max(0, at), min(len(text), at + span)
            if start >= end or (start, end) in seen:
                continue
            seen.add((start, end))
            window = text[start:end]
            matcher.set_seq2(window)
            if matcher.real_quick_ratio() < FUZZY or matcher.quick_ratio() < FUZZY:
                continue
            ratio = matcher.ratio()
            if ratio >= FUZZY and (best is None or ratio > best[0]):
                best = (ratio, start, end)
    if best is None:
        return None
    return _trim(text, best[1], best[2])


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    """A found window without the blank letters at its edges, and never cut in the
    middle of a word (the window is the quote's length; the words moved a little)."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    while start > 0 and text[start - 1].isalnum() and text[start].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum() and text[end - 1].isalnum():
        end += 1
    return start, end


# ---- artifacts: what kind of file ----------------------------------------------------------

TYPES = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"),
    "pdf": (".pdf",),
    "html": (".html", ".htm"),
    "md": (".md", ".markdown", ".txt"),
}


def kind_of(name: str) -> str:
    """image / pdf / html / md / other, from the file's name."""
    low = name.lower()
    for kind, ends in TYPES.items():
        if low.endswith(ends):
            return kind
    return "other"
