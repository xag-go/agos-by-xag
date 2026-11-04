"""The review rows of the board and of the Inbox.
Must not: change a card.

Split out of agos_core.actions.reviews (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.actions.services.board.review_rules import OWNER, defaults, org
from agos_core.actions.services.board.review_situation import Situation, chip, situation, view
from agos_core.context import Core
from agos_core.engine import reviews as rules
from agos_core.hermes_gateway import kanban_rows

__all__ = [
    "board_rows",
    "inbox",
]

# ---- many cards at once (the board's chips, the Inbox) -------------------------------------


def board_rows(
    core: Core,
    workspace_id: str,
    board: kanban_rows.Board,
    rows: list[tuple[str, str, str, str]],
) -> dict[str, dict[str, Any]]:
    """The chips of the board's cards: `rows` (id, status, assignee, body) as the
    board's own read has them, plus ONE query of their marker comments and their
    links on the same connection."""
    candidates = {r[0] for r in rows if rules.FENCE in (r[3] or "")}
    base = defaults(core, workspace_id)
    if not candidates and not base["stages"] and not base["planFirst"]:
        return {}
    by_card: dict[str, list[dict[str, Any]]] = {}
    try:
        for task, author, body, at in board.review_marks():
            by_card.setdefault(str(task), []).append(
                {"author": author, "body": body, "created_at": at}
            )
        children: dict[str, list[str]] = {}
        for parent, child in board.links():
            children.setdefault(str(parent), []).append(str(child))
    except sqlite3.Error:
        return {}
    people = org(core, workspace_id)
    out: dict[str, dict[str, Any]] = {}
    for card_id, status, assignee, body in rows:
        raw = {
            "task": {"id": card_id, "status": status, "assignee": assignee, "body": body or ""},
            "comments": by_card.get(card_id, []),
            "children": children.get(card_id, []),
            "events": [],
        }
        s = situation(core, workspace_id, card_id, raw=raw, people=people, base=base)
        found = chip(s)
        if found is not None:
            out[card_id] = {"review": found, "situation": s}
    return out


def inbox(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The cards waiting for the owner's review decision, from ONE read of Hermes's
    board: a stage or a plan at him (review column, assignee `owner`), and the cards
    stuck in review (blocked after the round cap)."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = [
                (str(i), str(st or ""), str(a or ""), str(b or ""))
                for i, st, a, b in board.at_owner(OWNER)
            ]
            titles = {str(i): str(t or "") for i, t in board.titles_at_owner(OWNER)}
            found = board_rows(core, workspace_id, board, rows)
    except sqlite3.Error:
        return []
    out = []
    for card_id, data in found.items():
        s: Situation = data["situation"]
        s.title = titles.get(card_id, "")
        at_owner = s.status == "review" and s.assignee == OWNER
        if s.state.phase == "stuck" and s.status == "blocked":
            kind, key = "stuck", f"review:{card_id}:stuck:{s.state.rounds}"
        elif at_owner and s.plan_open and s.state.plan == "waiting":
            kind, key = "plan", f"review:{card_id}:plan:{s.state.plan_revision}"
        elif at_owner and s.current:
            kind, key = "stage", f"review:{card_id}:{s.state.round}:{s.current}"
        else:
            continue
        shown = view(s) or {}
        out.append(
            {
                "key": key,
                "card": card_id,
                "title": s.title,
                "member": s.people.names.get(s.implementer, ""),
                "at": _last_at(s),
                "review": {
                    "kind": kind,
                    "stage": s.current,
                    "stages": s.total,
                    "label": s.stage_label(s.current) if s.current else "",
                    "round": s.state.round,
                    "rounds": s.state.rounds,
                    "cap": s.pol.cap,
                    "planRevision": s.state.plan_revision,
                    "notes": shown.get("notes") or [],
                    "ownerCan": shown.get("ownerCan") or [],
                    # Who may take a stuck card (his Reassign).
                    "members": [
                        {"name": name, "title": s.people.titles.get(p, name)}
                        for p, name in s.people.names.items()
                    ]
                    if kind == "stuck"
                    else [],
                },
            }
        )
    return out


def _last_at(s: Situation) -> str:
    from datetime import UTC, datetime

    at = max((int(n.get("at") or 0) for n in s.state.notes), default=0)
    if not at:
        return ""
    return datetime.fromtimestamp(at, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
