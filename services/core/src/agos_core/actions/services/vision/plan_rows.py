"""Reading the workspace's plan: its goals, projects and results as rows, the top of the plan, what the agents' prompt carries, refreshing it.
Must not: change a row.

Split out of agos_core.actions.goals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from agos_core.actions.errors import NotFoundError
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import key_results as key_results_repo
from agos_core.engine import goals as rules

__all__ = [
    "GOALS_MAX",
    "PROJECTS_MAX",
    "RESULTS_MAX",
    "prompt_for",
    "refresh",
    "results",
    "rows",
    "top",
]

log = logging.getLogger("agos.goals")

GOALS_MAX = 6  # the owner's design says 2-4; a little room, never a long list
PROJECTS_MAX = 5  # per goal (1-3 by design)
RESULTS_MAX = 6  # per goal


# ---- reading ------------------------------------------------------------------------


def _goal(r: Any) -> rules.Goal:
    keys = r.keys()

    def text(name: str) -> str:
        return str(r[name] or "") if name in keys else ""

    return rules.Goal(
        id=int(r["id"]),
        parent_id=int(r["parent_id"]) if r["parent_id"] is not None else None,
        title=str(r["title"]),
        why=str(r["why"]),
        measure=str(r["measure"]),
        owner=str(r["owner"]),
        status=str(r["status"]),
        position=int(r["position"]),
        level=text("level") or ("vision" if r["parent_id"] is None else "goal"),
        strategy=text("strategy"),
        due_on=text("due_on"),
        project_kind=text("project_kind"),
        starts_on=text("starts_on"),
        ends_on=text("ends_on"),
        rhythm=text("rhythm"),
    )


def _result(r: Any) -> rules.KeyResult:
    return rules.KeyResult(
        id=int(r["id"]),
        goal_id=int(r["goal_id"]),
        title=str(r["title"]),
        start=float(r["start_value"]),
        current=float(r["current"]),
        target=float(r["target"]) if r["target"] is not None else None,
        unit=str(r["unit"]),
        due_on=str(r["due_on"]),
        source=str(r["source"]),
        position=int(r["position"]),
    )


def rows(core: Core, workspace_id: str) -> list[rules.Goal]:
    return [_goal(r) for r in goals_repo.rows(core.db, workspace_id)]


def results(core: Core, workspace_id: str) -> list[rules.KeyResult]:
    return [_result(r) for r in key_results_repo.rows(core.db, workspace_id)]


def top(core: Core, workspace_id: str) -> rules.Goal | None:
    """The Vision with its goals, key results and projects (None: none set)."""
    return rules.tree(rows(core, workspace_id), results(core, workspace_id))


def _one(core: Core, workspace_id: str, goal_id: int) -> rules.Goal:
    r = goals_repo.get(core.db, workspace_id, goal_id)
    if r is None:
        raise NotFoundError("This goal")
    return _goal(r)


def _one_result(core: Core, workspace_id: str, kr_id: int) -> rules.KeyResult:
    r = key_results_repo.get(core.db, workspace_id, kr_id)
    if r is None:
        raise NotFoundError("This key result")
    return _result(r)


def prompt_for(core: Core, workspace_id: str, member: str = "") -> str:
    """The plan section of a profile's SOUL.md ("" without a Vision)."""
    try:
        return rules.prompt(top(core, workspace_id), member)
    except sqlite3.Error:
        log.exception("plan of %s not read", workspace_id)
        return ""


# ---- the prompts --------------------------------------------------------------------


def refresh(core: Core, workspace_id: str) -> None:
    """The plan section in the Co-Founder's SOUL.md and in every member's (the next
    conversation or run reads it). Never fails the change that called it."""
    from agos_core.actions import agent_profiles
    from agos_core.actions import engine as engine_actions

    if core.engine is None:
        return
    try:
        engine_actions.write_identity(core, workspace_id)
        agent_profiles.write_texts(core, workspace_id)
    except Exception:
        log.exception("the plan not written into the prompts of %s", workspace_id)
