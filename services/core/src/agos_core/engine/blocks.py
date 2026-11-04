"""Blocked cards with an owner, and what state a blocked card is in: pure rules.

Hermes types a block (hermes_cli/kanban_db.py VALID_BLOCK_KINDS: dependency,
needs_input, capability, transient) and keeps the reason on the card's `blocked`
event. AGOS adds, in the reason itself, WHO must act (Paperclip's unblock
descriptor, study §5) — the agent writes one of:

    waiting for the owner: <what>        -> the owner (his Inbox)
    waiting for @cofounder: <what>       -> the Co-Founder
    waiting for @<member name>: <what>   -> that team member

`descriptor(reason)` reads it: {"owner": "owner" | "cofounder" | "<name>", "action"}.
A reason with no owner is the owner's (someone has to read it).

`attention(cards, links)` derives, from one read of the board (every task's
status, block_kind, assignee, run and the task_links), the state of each card
that waits (status blocked, or todo with a dependency block):
- covered: what it waits on moves by itself (an open blocker has a live run or is
  ready / todo with its own path clear; a block routed to an agent);
- stalled: it waits on cards that wait themselves and nothing in the chain moves;
- needs_attention: the owner must act (a needs_input block for him, a capability
  or transient or untyped block, a stalled chain, a blocker in triage).
"""

from __future__ import annotations

import re
from typing import Any

OWNER_OK = "waiting for the owner:"
_AT = re.compile(
    r"^\s*waiting for @(?P<who>[a-z0-9][a-z0-9-]{0,63})\s*:\s*(?P<action>.*)$", re.I | re.S
)
_OWNER = re.compile(r"^\s*waiting for the owner\s*:\s*(?P<action>.*)$", re.I | re.S)
COFOUNDER = "cofounder"
# Spellings of the root bot's name an agent may write (manager: the name before step 44).
COFOUNDER_NAMES = ("cofounder", "co-founder", "manager", "root")


def descriptor(reason: str) -> dict[str, str]:
    """Who must act on a blocked card and what they must do, from its reason."""
    found = _AT.match(reason or "")
    if found is not None:
        who = found["who"].lower()
        if who in ("owner", "me", "you"):
            who = "owner"
        elif who in COFOUNDER_NAMES:
            who = COFOUNDER
        return {"owner": who, "action": found["action"].strip()[:900]}
    owner = _OWNER.match(reason or "")
    if owner is not None:
        return {"owner": "owner", "action": owner["action"].strip()[:900]}
    return {"owner": "owner", "action": (reason or "").strip()[:900]}


def agent_reason(who: str, action: str) -> str:
    """The reason an agent blocks with when a teammate must act (the tool writes it)."""
    return f"waiting for @{who}: {action.strip()}"


def route_marker(card: str, who: str) -> str:
    """The comment AGOS leaves on the card it hands to a teammate (its idempotency)."""
    return f"[agos-routed {card} to @{who}]"


_ROUTED = re.compile(r"^\[agos-routed (?P<card>[A-Za-z0-9_-]+) to @(?P<who>[a-z0-9-]+)\]")


def read_route_marker(comment: str) -> tuple[str, str] | None:
    found = _ROUTED.match(comment.strip())
    return (found["card"], found["who"]) if found else None


TERMINAL = ("done", "archived")
WAITING = ("blocked", "scheduled", "triage")


def attention(
    cards: dict[str, dict[str, Any]],
    links: list[tuple[str, str]],
    agents: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """State of every waiting card: {card: {state, why, owner, action, blockers}}.
    `cards`: id -> {status, block_kind, reason, running (bool)}; `links`: (parent,
    child) pairs; `agents`: the names a block may be routed to (None = any name);
    a block for a name nobody has is the owner's. A chain is walked through open
    parents; cycles stop."""
    parents: dict[str, list[str]] = {}
    for parent, child in links:
        parents.setdefault(child, []).append(parent)
    out: dict[str, dict[str, Any]] = {}
    for card_id, card in cards.items():
        status = str(card.get("status") or "")
        kind = str(card.get("block_kind") or "")
        open_parents = [
            p
            for p in parents.get(card_id, [])
            if str(cards.get(p, {}).get("status")) not in TERMINAL
        ]
        waits_on_parents = bool(open_parents) and status in ("todo", "blocked")
        if status != "blocked" and not waits_on_parents:
            continue
        desc = _who(str(card.get("reason") or ""), agents)
        if status == "blocked" and kind == "needs_input":
            if desc["owner"] == "owner":
                state, why = "needs_attention", "waits for you"
            else:
                state, why = "covered", f"waits for @{desc['owner']}"
        elif status == "blocked" and not open_parents:
            state, why = (
                "needs_attention",
                {
                    "capability": "needs something the agent lacks",
                    "transient": "stopped on a passing error",
                }.get(kind, "blocked without a typed reason"),
            )
        else:
            moving = _chain_moves(card_id, cards, parents, set(), agents)
            if moving:
                state, why = "covered", f"waits on {', '.join(open_parents[:3])}, which moves"
            else:
                state, why = (
                    "stalled",
                    f"waits on {', '.join(open_parents[:3])}, and nothing in that chain moves",
                )
        out[card_id] = {
            "state": state if state != "stalled" else "needs_attention",
            "stalled": state == "stalled",
            "why": why,
            "owner": desc["owner"],
            "action": desc["action"],
            "blockers": open_parents,
        }
    return out


def _who(reason: str, agents: set[str] | None) -> dict[str, str]:
    desc = descriptor(reason)
    if agents is not None and desc["owner"] not in agents and desc["owner"] != "owner":
        return {"owner": "owner", "action": desc["action"]}  # nobody of that name: his
    return desc


def _chain_moves(
    card_id: str,
    cards: dict[str, dict[str, Any]],
    parents: dict[str, list[str]],
    seen: set[str],
    agents: set[str] | None,
) -> bool:
    """True when some open ancestor of `card_id` has a live run, or sits ready / todo
    with its own parents clear (the dispatcher will take it)."""
    if card_id in seen:
        return False
    seen.add(card_id)
    for parent in parents.get(card_id, []):
        p = cards.get(parent)
        if p is None or str(p.get("status")) in TERMINAL:
            continue
        status = str(p.get("status") or "")
        if p.get("running") or status == "running":
            return True
        grand_open = [
            g
            for g in parents.get(parent, [])
            if str(cards.get(g, {}).get("status")) not in TERMINAL
        ]
        if status in ("ready", "todo", "review") and not grand_open:
            return True
        if status in ("ready", "todo", "review") and _chain_moves(
            parent, cards, parents, seen, agents
        ):
            return True
        if (
            status == "blocked"
            and str(p.get("block_kind") or "") == "needs_input"
            and _who(str(p.get("reason") or ""), agents)["owner"] != "owner"
        ):
            return True  # routed to an agent: it moves when that agent answers
    return False
