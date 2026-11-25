"""The words on the owner's Allow / Deny card for one of AGOS's own tools.

Owns: the card's text (what will change, who asks, why he is asked, what the
buttons allow), in plain English, as one string whose FIRST line is the change
itself (the plugin shows that line where Hermes would show the raw tool label).

Must not: decide whether he is asked (actions/owner_gate.py), read the db, or put
an emoji with a variation selector (U+FE0F) in the text: Hermes shows hidden
characters on approval cards as escapes (a literal "\\ufe0f" on the card).

Agent-made text (titles, names, its reason) is flattened to one line and capped
piece by piece, so it can neither push the warning off the card nor add lines that
look like AGOS's own.
"""

from __future__ import annotations

import re

__all__ = ["MAX", "card_text", "plain"]

MAX = 900  # the whole card (gate.py / owner_gate.py cut the message there)
_WHAT, _SOURCE, _REASON = 240, 240, 160
_INVISIBLE = re.compile(r"[\ufe00-\ufe0f\u200b\u2060\ufeff]")
_SPACE = re.compile(r"\s+")
# What a line may start with once the emoji in front of a title is gone.
_STARTS = "“\"'(<"


def plain(text: str, cap: int = 0) -> str:
    """`text` on one line, without invisible characters or the symbols (emoji) in
    front of it; cut to `cap` characters (0 = no cut)."""
    cleaned = _SPACE.sub(" ", _INVISIBLE.sub("", str(text or ""))).strip()
    start = 0
    while start < len(cleaned) and not (cleaned[start].isalnum() or cleaned[start] in _STARTS):
        start += 1
    cleaned = cleaned[start:].strip()
    return cleaned[: cap - 1] + "…" if cap and len(cleaned) > cap else cleaned


def card_text(
    what: str,
    workspace: str,
    *,
    source: str = "",
    reason: str = "",
    once: bool = False,
) -> str:
    """The whole card: `what` on line 1, then why he is asked, what the buttons
    allow, and last (the part a chat app may cut) the agent's own reason.

    `source` = the outside content this conversation read (a tainted ask), "" when he
    is asked only because his own setting says so. `once` = a one-time question:
    Hermes's "session" and "always" can't apply, so every Allow allows this one time.
    """
    who = f"Your Co-Founder in {plain(workspace, 80) or 'this workspace'}"
    lines = [plain(what, _WHAT) or "An AGOS change"]
    if source:
        lines.append(
            f"{who} is asking because, just before, it read outside content "
            f"({plain(source, _SOURCE)}). Outside text can hide orders: allow only if "
            "you asked for this."
        )
    else:
        lines.append(f"{who} is asking because your setting says to ask you first.")
    if once:
        lines.append("Any Allow button allows this one time only.")
    else:
        # The clean ask's rule key is per tool (gate.py `agos:<tool>`).
        lines.append("“Always” = it stops asking you before its AGOS changes.")
    said = plain(reason, _REASON)
    if said:
        lines.append(f"Its reason: {said}")
    return "\n".join(lines)[:MAX]
