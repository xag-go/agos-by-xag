"""Blocked cards with an owner (who must act), routed; and the state of every
waiting card, derived from Hermes's board in one read-only query.

A member blocks its card (Hermes's kanban_block, needs_input) with a reason that
names who must act (engine/blocks.py descriptor):
- the owner ("waiting for the owner: …"): his Inbox shows it (derived, nothing
  recorded) — an Autonomy ask, a proposal or a question is recorded by its own
  module first (actions/kanban_asks.py settle);
- a teammate or the Co-Founder ("waiting for @<name>: …"): AGOS hands the card
  over through Hermes — a comment that says what is needed (with a stable marker,
  so a replayed block routes once), `kanban assign` to that agent's profile, then
  `kanban unblock`, so Hermes's dispatcher gives the card to the named agent, who
  answers on it (and hands it back the same way, or completes it).
`dependency` blocks are Hermes's own (it wakes the card when its parents finish)
and are never touched here.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from agos_core.context import Core
from agos_core.engine import blocks as rules
from agos_core.hermes_gateway import kanban_rows

log = logging.getLogger(__name__)


def route(core: Core, workspace_id: str, card: str, reason: str, assignee: str) -> bool:
    """A card just blocked needs_input for someone (the hook): routed to the named
    agent (True), or left for the owner's Inbox (False)."""
    from agos_core.actions import agent_profiles, kanban_board
    from agos_core.actions.kanban_asks import _hermes_kanban

    who = rules.descriptor(reason)
    if who["owner"] == "owner":
        return False
    name = who["owner"]
    if name != rules.COFOUNDER and name not in agent_profiles.team_names(core, workspace_id):
        log.info(
            "card %s of %s waits for an unknown @%s: left to the owner", card, workspace_id, name
        )
        return False
    if _routed(core, workspace_id, card, name):
        return True  # a replayed block: handed over already
    asker = kanban_board._members(core, workspace_id).get(assignee, {}).get("title") or (
        assignee or "The Co-Founder"
    )
    text = (
        f"{rules.route_marker(card, name)} @{name}, {asker} waits for you on this card: "
        f"{who['action'] or 'see the block reason'}. Answer in a comment here; then hand "
        'the card back (kanban_block, kind needs_input, reason "'
        f"{rules.agent_reason(_name_of(core, workspace_id, assignee), '<what you did>')}"
        '") or complete it if nothing is left.'
    )
    _hermes_kanban(core, workspace_id, "comment", card, text, "--author", "agos")
    _hermes_kanban(
        core, workspace_id, "assign", card, kanban_board._profile_of(core, workspace_id, name)
    )
    _hermes_kanban(core, workspace_id, "unblock", card)
    return True


def _name_of(core: Core, workspace_id: str, assignee: str) -> str:
    from agos_core.actions import kanban_board

    found = kanban_board._members(core, workspace_id).get(assignee)
    return str(found["name"]) if found else rules.COFOUNDER


def _routed(core: Core, workspace_id: str, card: str, name: str) -> bool:
    from agos_core.actions import kanban_board
    from agos_core.actions.errors import ActionError, NotFoundError

    try:
        raw, _extra = kanban_board._shown(core, workspace_id, card)
    except (ActionError, NotFoundError):
        return False
    for c in raw.get("comments") or [] if isinstance(raw, dict) else []:
        found = rules.read_route_marker(str(c.get("body") or "")) if isinstance(c, dict) else None
        if found is not None and found == (card, name):
            return True
    return False


# ---- derived attention ----------------------------------------------------------------------


def attention(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    """Every waiting card's state (engine/blocks.py attention), from one read-only
    query of Hermes's board: tasks with their latest block reason and run, and the
    task_links. {} when the board can't be read."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return {}
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return {}
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.open_with_blocks()
            links = board.links()
    except sqlite3.Error:
        return {}
    cards: dict[str, dict[str, Any]] = {}
    titles: dict[str, str] = {}
    since: dict[str, float] = {}
    for card_id, status, kind, assignee, title, running, payload, at in rows:
        try:
            reason = str((json.loads(payload or "{}") or {}).get("reason") or "")
        except ValueError:
            reason = ""
        cards[str(card_id)] = {
            "status": str(status or ""),
            "block_kind": str(kind or ""),
            "reason": reason,
            "running": bool(running),
            "assignee": str(assignee or ""),
        }
        titles[str(card_id)] = str(title or "")
        since[str(card_id)] = float(at or 0)
    agents = set(agent_profiles.team_names(core, workspace_id)) | {rules.COFOUNDER}
    found = rules.attention(cards, [(str(p), str(c)) for p, c in links], agents)
    for card_id, state in found.items():
        state["title"] = titles.get(card_id, "")
        state["assignee"] = cards[card_id]["assignee"]
        state["since"] = since.get(card_id, 0)
        state["reason"] = cards[card_id]["reason"]
        state["blockKind"] = cards[card_id]["block_kind"]
    return found
