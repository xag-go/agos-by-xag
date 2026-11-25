"""The words on the owner's Allow / Deny card for one of AGOS's own tools.

Owns: the card's text (what will change, who asks, why he is asked, what the
buttons allow), in plain English, as one string whose FIRST line is the change
itself (the plugin shows that line where Hermes would show the raw tool label).

Must not: decide whether he is asked (actions/owner_gate.py), read the db, or put
an emoji with a variation selector (U+FE0F) in the text: Hermes shows hidden
characters on approval cards as escapes (a literal "\\ufe0f" on the card).
"""

from __future__ import annotations

import re

__all__ = ["card_text", "plain"]

_INVISIBLE = re.compile(r"[\ufe00-\ufe0f\u200b-\u200f\u2060\ufeff]")
# What a line may start with once the emoji in front of a title is gone.
_STARTS = "“\"'(<"


def plain(text: str) -> str:
    """`text` without invisible characters, and without the symbols (emoji) in front
    of it: the card says the change in words."""
    cleaned = _INVISIBLE.sub("", str(text or "")).strip()
    start = 0
    while start < len(cleaned) and not (cleaned[start].isalnum() or cleaned[start] in _STARTS):
        start += 1
    return cleaned[start:].strip()


def card_text(
    what: str,
    workspace: str,
    *,
    source: str = "",
    reason: str = "",
    once: bool = False,
) -> str:
    """The whole card: `what` on line 1, then why he is asked.

    `source` = the outside content this conversation read (a tainted ask), "" when he
    is asked only because his own setting says so. `reason` = the agent's own words on
    why it wants the change (shown as its words). `once` = Hermes's "always" and
    "session" can't apply (a one-time question), so every Allow allows this one time.
    """
    who = f"Your Co-Founder in {plain(workspace) or 'this workspace'}"
    lines = [plain(what) or "An AGOS change"]
    if source:
        lines.append(
            f"{who} is asking because, just before, it read outside content "
            f"({plain(source)}). Outside text can hide orders: allow only if you asked "
            "for this."
        )
    else:
        lines.append(f"{who} is asking because your setting says to ask you first.")
    said = plain(reason)
    if said:
        lines.append(f"Its reason: {said[:200]}{'…' if len(said) > 200 else ''}")
    if once:
        lines.append("Any Allow button allows this one time only.")
    else:
        lines.append("“Always” lets it do this same thing again without asking you.")
    return "\n".join(lines)
