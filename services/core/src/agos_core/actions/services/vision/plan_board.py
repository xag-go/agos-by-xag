"""The plan on Hermes's board: the cards of each goal, their rollup, the plan's view and status text, a card's goal line.
Must not: change a goal or project.

Split out of agos_core.actions.goals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import sqlite3
from typing import Any

from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.vision.plan_rows import _one, top
from agos_core.context import Core
from agos_core.engine import goals as rules
from agos_core.hermes_gateway import board_reads, hermes_db

__all__ = [
    "board_cards",
    "board_tasks",
    "card_line",
    "rollup",
    "set_card_goal",
    "status_text",
    "view",
]

# ---- the board: links and rollup (one read) ----------------------------------------


def board_tasks(
    core: Core, workspace_id: str
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Hermes's cards (id, status, body, title, assignee, idempotency key) and their
    links, read once from the board's own database (read only). Empty when there
    is no board."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return [], []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return [], []
    try:
        with contextlib.closing(hermes_db.connect_ro(board_db, timeout=2)) as db:
            tasks = [
                {
                    "id": str(i),
                    "status": str(s or ""),
                    "body": str(b or ""),
                    "title": str(t or ""),
                    "assignee": str(a or ""),
                    "key": str(k or ""),
                    "priority": int(p or 0),
                    "created_at": int(c or 0),
                }
                for i, s, b, t, a, k, p, c in board_reads.plan_tasks(db)
            ]
            links = [(str(p), str(c)) for p, c in board_reads.links(db)]
    except sqlite3.Error:
        return [], []
    return tasks, links


def board_cards(
    core: Core, workspace_id: str
) -> tuple[dict[str, tuple[str, str]], list[tuple[str, str]]]:
    """Hermes's cards (id -> (status, body)) and their links (one board read)."""
    tasks, links = board_tasks(core, workspace_id)
    return {t["id"]: (t["status"], t["body"]) for t in tasks}, links


def rollup(
    core: Core, workspace_id: str, goal: rules.Goal | None = None
) -> dict[int, dict[str, int]]:
    found = goal if goal is not None else top(core, workspace_id)
    cards, links = board_cards(core, workspace_id)
    return rules.rollup(found, cards, links)


def view(core: Core, workspace_id: str) -> dict[str, Any]:
    """The Vision page in one read: the Vision, its goals (key results, progress)
    and their projects (cards, progress), today's column, the Co-Founder's daily
    rhythm and the team (who may own a goal or a project)."""
    from agos_core.actions import org, rhythm, today

    vision = top(core, workspace_id)
    tasks, links = board_tasks(core, workspace_id)
    counts = rules.rollup(vision, {t["id"]: (t["status"], t["body"]) for t in tasks}, links)
    # The board's order inside a column: higher priority first, then the oldest.
    ordered = sorted(
        tasks, key=lambda t: (-int(t.get("priority") or 0), int(t.get("created_at") or 0))
    )
    upcoming = rules.next_cards(vision, ordered, links)
    empty = {"done": 0, "open": 0, "blocked": 0}

    def shown(g: rules.Goal) -> dict[str, Any]:
        return {
            **rules.as_dict(g),
            "cards": counts.get(g.id, empty),
            "next_card": upcoming.get(g.id),
            "progress": rules.progress(g, counts),
            "results": [rules.result_dict(k) for k in g.results],
            "children": [shown(c) for c in g.children],
        }

    team = org.people(core, workspace_id)
    return {
        "vision": shown(vision) if vision is not None else None,
        "today": today.view(core, workspace_id, tasks, team),
        "rhythm": rhythm.list_all(core, workspace_id),
        "members": [
            {"name": p.name, "title": p.title}
            for p in sorted(team.values(), key=lambda p: p.title.lower())
        ],
    }


def status_text(core: Core, workspace_id: str) -> str:
    """The plan and its progress as short lines (the agents' agos_goals status):
    the Vision, each goal with its key results, each project with its cards, then
    today's plan and the last recap."""
    from agos_core.actions import today

    vision = top(core, workspace_id)
    if vision is None:
        return (
            "No Vision is set yet: the owner writes it on the Vision page. You may suggest "
            "one with agos_goals (action propose, kind vision)."
        )
    head = [f"Vision #{vision.id}: {vision.title}"]
    if vision.strategy:
        head.append(f"Strategy: {' '.join(vision.strategy.split())[:600]}")
    return "\n".join(
        [
            *head,
            "",
            "Progress (cards done / open / blocked; key results as numbers):",
            *rules.rollup_lines(vision, rollup(core, workspace_id, vision)),
            "",
            *today.status_lines(core, workspace_id),
        ]
    )


# ---- a card's goal ------------------------------------------------------------------


def card_line(core: Core, workspace_id: str, goal_id: int) -> str:
    """The '## Goal' section a card made for this goal or project starts with."""
    goal = _one(core, workspace_id, goal_id)
    return rules.card_line(goal, rules.parent_of(top(core, workspace_id), goal.id))


def set_card_goal(core: Core, workspace_id: str, card_id: str, goal_id: int | None) -> None:
    """The card's goal or project: its Hermes body's '## Goal' section (Hermes's
    `kanban edit --body`; the one copy, read by the agent working it)."""
    from agos_core.actions import kanban_board

    goal = _one(core, workspace_id, goal_id) if goal_id else None
    raw, _extra = kanban_board._shown(core, workspace_id, card_id)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    body = str(task.get("body") or "")
    parent = rules.parent_of(top(core, workspace_id), goal.id) if goal is not None else None
    new = rules.with_card_goal(body, goal, parent)
    if new.strip() != body.strip():
        kanban_board._cli(core, workspace_id, "edit", card_id, "--body", new)
