"""A card's thread on Hermes's board: pure rules (Step 58, F18 / F29).

The thread IS Hermes's: a card's comments are its `task_comments`, written with
`hermes kanban comment` (the owner) or the agents' own `kanban_comment` tool. AGOS
adds only who a comment wakes, read from the comment itself:

- the card's assignee, never the whole team, never the author itself, never on a
  finished card (Paperclip's issue-comment-wakeup rule). How it is woken is Hermes's
  own path for the card's state (`wake_plan`): a running worker gets the comment
  steered into its turn by Hermes itself (tools/kanban_tools.py
  inject_new_comments_from_env), a card waiting for the owner's answer is unblocked
  (Hermes's dispatcher then starts the assignee with the comment in its context), a
  Ready card is started by the dispatcher anyway, a card held on purpose (To do on
  its parents, Scheduled, Triage, stopped) reads it when it starts;
- the current reviewer when the card is in Review: on Hermes's board that is the
  card's assignee (engine/reviews.py), and the owner's stage (`owner`) lands in his
  Inbox;
- `@<member>` in a comment: that member follows the card from now on (a Hermes
  notify subscription of its conversation, `hermes kanban notify-subscribe
  --delivery-mode wake`) and is woken once with the comment, never reassigned;
- `@owner`: the comment is in his Inbox (derived from the board, actions/threads.py);
- a card id (`t_a5ba7050`) is a reference: the web shows it as a chip (its title and
  status) that opens the card.

A card's labels are a block in its Hermes body (engine/card_blocks.py), their names,
colours and folders AGOS's (Hermes's board has no labels: hermes_cli/kanban_db.py
tasks has no label or tag column).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agos_core.engine import card_blocks

OWNER = "owner"
COFOUNDER = "cofounder"
EVERYONE = ("all", "everyone", "team")  # never a mention: a comment wakes no team

# `@name` (a member's name, `cofounder`, `owner`); not inside an e-mail address.
_MENTION = re.compile(r"(?<![\w@.])@(?P<name>[A-Za-z0-9][A-Za-z0-9_-]{0,63})\b")
# Hermes's card ids: `t_` and hex (hermes_cli/kanban_db.py _new_task_id).
_CARD_REF = re.compile(r"(?<![\w/])(?P<id>t_[0-9a-f]{4,32})\b")
MAX_MENTIONS = 10
MAX_REFS = 20

LABELS_BLOCK = "agos-labels"  # {"ids": [label ids]} in the card's Hermes body
MAX_LABELS = 20


def mentions(text: str, names: list[str] | set[str]) -> list[str]:
    """The known names a comment @mentions, in order, once each (`owner` and
    `cofounder` count; `@all` never does: a comment never wakes the team)."""
    known = {n.lower() for n in names} | {OWNER, COFOUNDER}
    out: list[str] = []
    for m in _MENTION.finditer(text or ""):
        name = m["name"].lower()
        if name in ("co-founder", "co_founder"):
            name = COFOUNDER
        if name in known and name not in EVERYONE and name not in out:
            out.append(name)
        if len(out) >= MAX_MENTIONS:
            break
    return out


def card_refs(text: str, own: str = "") -> list[str]:
    """The card ids a text names (a reference chip each), once each, not its own."""
    out: list[str] = []
    for m in _CARD_REF.finditer(text or ""):
        if m["id"] != own and m["id"] not in out:
            out.append(m["id"])
        if len(out) >= MAX_REFS:
            break
    return out


@dataclass(frozen=True)
class Wake:
    """One person a comment reaches, and Hermes's way of reaching them."""

    who: str  # a member's name, cofounder or owner
    how: str  # see HOW
    why: str  # assignee | reviewer | mention


HOW = {
    "steer": "working on it now: Hermes puts the comment into its turn",
    "unblock": "its question is answered: Hermes starts it again with the comment",
    "dispatch": "Hermes starts it soon and it reads the comment",
    "waits": "reads it when the card starts (held on purpose until then)",
    "review": "its review turn reads the comment",
    "inbox": "in your Inbox",
    "mention": "follows the card now, woken once with the comment",
}


def wake_plan(
    *,
    status: str,
    assignee: str,
    author: str,
    mentioned: list[str],
    block_kind: str = "",
    owner_answer: bool = False,
    resume: bool = False,
) -> list[Wake]:
    """Who one comment wakes (names, not profiles: `assignee` and `author` are a
    member's name, `cofounder`, `owner` or "" for nobody).

    `owner_answer`: the comment is the owner's answer to a question the card waits
    on (a needs_input block that is not an Autonomy ask); `resume`: he asked to
    start a stopped card again with it (Paperclip's comment `resume`)."""
    out: list[Wake] = []
    if status in ("done", "archived"):
        targets: list[tuple[str, str]] = []
    else:
        targets = [(assignee, "reviewer" if status == "review" else "assignee")]
    for who, why in targets:
        if not who or who == author:
            continue
        if who == OWNER:
            out.append(Wake(OWNER, "inbox", why))
        elif status == "running":
            out.append(Wake(who, "steer", why))
        elif status == "blocked" and (
            (owner_answer and block_kind == "needs_input") or (resume and author == OWNER)
        ):
            out.append(Wake(who, "unblock", why))
        elif status == "ready":
            out.append(Wake(who, "dispatch", why))
        elif status == "review":
            out.append(Wake(who, "review", why))
        else:
            out.append(Wake(who, "waits", why))
    reached = {w.who for w in out}
    for name in mentioned:
        if name == author or name in reached:
            continue
        reached.add(name)
        out.append(Wake(name, "inbox" if name == OWNER else "mention", "mention"))
    return out


# ---- labels on the card -------------------------------------------------------------


def card_labels(body: str) -> list[int]:
    found = card_blocks.read_block(body or "", LABELS_BLOCK) or {}
    ids = found.get("ids")
    if not isinstance(ids, list):
        return []
    out: list[int] = []
    for value in ids:
        good = isinstance(value, int) and not isinstance(value, bool) and value > 0
        if good and value not in out:
            out.append(value)
    return out[:MAX_LABELS]


def without_labels(body: str) -> str:
    return card_blocks.strip_block(body or "", LABELS_BLOCK)


def with_labels(body: str, ids: list[int]) -> str:
    """The body with exactly these labels (none: no block at all)."""
    clean = without_labels(body)
    kept: list[int] = []
    for i in ids:
        if i > 0 and i not in kept:
            kept.append(i)
    if not kept:
        return clean
    return card_blocks.with_block(clean, LABELS_BLOCK, {"ids": kept[:MAX_LABELS]})
