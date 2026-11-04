"""One Kanban card as its page shows it: Hermes's card (read from its board database
the way `hermes kanban show` reads it, else asked from the CLI) with its comments,
events, files, references, watchers, the member's own plan for it, its review, the
goal it serves, the asks waiting on it and its chat.

Split out of agos_core.actions.kanban_board (its `card`, `_shown`, `_plan`).

Owns: putting that page together from Hermes's reads and AGOS's own rows.
Must not: write the card (card_writes.py) or hold its pieces' rules (reviews,
threads, goals, asks keep theirs).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import (
    card_files,
    card_members,
    card_shape,
    kanban_cli,
    kanban_db,
)
from agos_core.actions.services.board.card_text import (
    _event_detail,
    _question,
    done_needs_summary,
    readable_result,
)
from agos_core.actions.services.board.kanban_workflow import _columns, _manual, _workflow
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.hermes_gateway import state_rows

__all__ = [
    "card",
    "plan",
    "shown",
]

log = logging.getLogger("agos.kanban_board")


def shown(core: Core, workspace_id: str, card_id: str) -> tuple[Any, dict[str, Any]]:
    """`hermes kanban show <card> --json` and what its list leaves out (goal mode, the
    kind of block): read from Hermes's board database the way the CLI reads it
    (engine/hermes_board.py), else asked from the CLI."""
    from agos_core.engine import hermes_board

    try:
        found = hermes_board.show(kanban_db.board_file(core, workspace_id), card_id)
    except hermes_board.Unread as why:
        log.debug("card %s of %s from Hermes's CLI: %s", card_id, workspace_id, why)
    else:
        if found is None:
            raise NotFoundError("This card")
        return found
    try:
        raw = kanban_cli.answer(kanban_cli.run(core, workspace_id, "show", card_id, "--json"))
    except ActionError as error:
        raise NotFoundError("This card") from error
    return raw, kanban_db._extra(core, workspace_id).get(card_id, {})


def card(core: Core, workspace_id: str, card_id: str) -> dict[str, Any]:
    members = card_members.shown_members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""
    raw, extra = shown(core, workspace_id, card_id)
    if not isinstance(raw, dict) or not isinstance(raw.get("task"), dict):
        raise NotFoundError("This card")

    def who(author: str) -> str:
        found = members.get(author)
        if found:
            return found["title"]
        if author == cofounder:
            return "Co-Founder"
        return "You" if author in (card_members.OWNER, "user") else author

    out = card_shape.card_of({**raw["task"], **extra}, members, cofounder)
    out["summary"] = readable_result(str(raw.get("latest_summary") or raw.get("result") or ""))
    out["comments"] = _comments(raw, who)
    from agos_core.actions import threads

    # The cards its text and thread name (reference chips) and who follows it
    # (Hermes's notify subscriptions), read with the card.
    out["refs"] = threads.refs(
        core, workspace_id, [out["body"], *(c["body"] for c in out["comments"])], card_id
    )
    out["watchers"] = threads.watchers(core, workspace_id, card_id)
    out["events"] = _events(raw, who, members)
    out["attachments"] = card_files.attachments(core, workspace_id, card_id)
    out["plan"] = plan(core, workspace_id, card_id, str(raw["task"].get("assignee") or ""))
    out["question"] = _question(raw) if out["status"] == "blocked" else ""
    from agos_core.actions import kanban_asks

    out["asks"] = [a for a in kanban_asks.waiting(core, workspace_id, 50) if a["card"] == card_id]
    # The card's chat is with the member Hermes has on the card now (a reassigned
    # card gets a chat with its new member; the old one's stays in its profile).
    out["chatId"] = chats_repo.card_chat_id(
        core.db, workspace_id, card_id, str(out["member"] or "")
    )
    out["parents"] = [str(p) for p in raw.get("parents") or []]
    out["children"] = [str(p) for p in raw.get("children") or []]
    from agos_core.actions import goals
    from agos_core.engine import goals as goal_rules

    if out["goalId"] is None and out["parents"]:
        # No line of its own: the goal of its nearest parent with one (one board read).
        cards, links = goals.board_cards(core, workspace_id)
        served = goal_rules.card_goals(cards, links).get(card_id)
        if served is not None:
            out["goalId"], out["goalInherited"] = served[0], True
    out["goals"] = [goal_rules.as_dict(g) for g in goal_rules.walk(goals.top(core, workspace_id))]
    from agos_core.actions import reviews

    # Its review stages, rounds and plan (the same card read; actions/reviews.py).
    flow = reviews.situation(core, workspace_id, card_id, raw=raw)
    out["review"] = reviews.view(flow)
    out["reviewChip"] = reviews.chip(flow)
    workflow = _workflow(core)
    page = card_shape.with_actions(out, _columns(workflow), _manual(workflow))
    # Mark done asks him what was done first where Hermes would refuse it without.
    page["doneNeedsSummary"] = "done" in page["actions"] and done_needs_summary(
        page["status"], raw["task"].get("result")
    )
    return page


def _comments(raw: dict[str, Any], who: Callable[[str], str]) -> list[dict[str, Any]]:
    from agos_core.actions import work_hours

    return [
        {
            "id": int(c.get("id") or 0),
            "author": who(str(c.get("author") or "")),
            "body": str(c.get("body") or ""),
            "at": int(c.get("created_at") or 0),
        }
        for c in raw.get("comments") or []
        # The agents' where-I-stopped notes and AGOS's check-out / check-in words are
        # theirs (work hours), not the owner's to read.
        if isinstance(c, dict) and not work_hours.hidden_comment(c)
    ]


def _events(
    raw: dict[str, Any], who: Callable[[str], str], members: dict[str, dict[str, str]]
) -> list[dict[str, Any]]:
    """The card's last 40 events (Hermes's heartbeats and scratch tips left out)."""
    return [
        {
            "kind": str(e.get("kind") or ""),
            "at": int(e.get("created_at") or 0),
            "detail": who(d) if (d := _event_detail(e.get("payload"))) in members else d,
        }
        for e in raw.get("events") or []
        if isinstance(e, dict) and e.get("kind") not in ("heartbeat", "tip_scratch_workspace")
    ][-40:]


def plan(core: Core, workspace_id: str, card_id: str, profile: str) -> list[dict[str, str]]:
    """The steps the member set itself for this card: Hermes's own todo list in
    its latest work session on the card (the member's sessions, read only)."""
    import sqlite3

    if core.engine is None or not profile:
        return []
    state = core.engine.home_in(workspace_id, profile) / "state.db"
    if not state.is_file():
        return []
    try:
        content = state_rows.card_todos(state, card_id)
    except sqlite3.Error:
        return []
    if content is None:
        return []
    try:
        todos = json.loads(content).get("todos") or []
    except (ValueError, AttributeError):
        return []
    return [
        {"text": str(t.get("content") or ""), "status": str(t.get("status") or "pending")}
        for t in todos
        if isinstance(t, dict)
    ]
