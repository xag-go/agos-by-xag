"""Hermes's Kanban workflow as AGOS's board uses it: its columns (read from the
installed Hermes, v0.22.2's list while it can't be read), the moves the owner may
make by hand, how often Hermes's dispatcher starts Ready cards, and the buttons a
card in each status shows.

Owns: reading the workflow and the dispatcher setting. Must not: read or change
cards (actions/kanban_board.py).
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.context import Core
from agos_core.engine.hermes import EngineError

__all__ = [
    "DISPATCH_KEY",
    "MANUAL",
    "STATUSES",
    "card_actions",
    "columns",
    "dispatch_seconds",
]

log = logging.getLogger("agos.kanban_board")


# Hermes's Kanban columns come from Hermes (its DEFAULT_WORKFLOW, read in its
# runtime with its settings list: `columns`). This is v0.22.2's list, used only while
# Hermes's can't be read (tests/test_web_reads_core.py checks it is the installed
# Hermes's).
STATUSES = (
    "triage",
    "todo",
    "scheduled",
    "ready",
    "running",
    "blocked",
    "review",
    "done",
    "archived",
)


# Hermes's own status names AGOS's buttons stand on (its CLI's block / complete /
# archive set them: hermes_cli/kanban_db.py).
BLOCKED, DONE, ARCHIVED = "blocked", "done", "archived"


# v0.22.2's manual move table (hermes_cli/kanban_workflow.py DEFAULT_WORKFLOW
# `manual`), used only while Hermes's workflow can't be read, like STATUSES
# (tests/test_web_reads_core.py checks it is the installed Hermes's).
MANUAL: dict[str, tuple[str, ...]] = {
    "triage": ("ready", "todo"),
    "todo": ("ready", "scheduled", "triage"),
    "scheduled": ("ready", "todo", "triage"),
    "ready": ("blocked", "done", "review", "scheduled", "todo", "triage"),
    "running": ("blocked", "done", "ready", "review", "scheduled", "todo", "triage"),
    "blocked": ("done", "ready", "scheduled", "todo", "triage"),
    "review": ("done", "ready", "todo", "triage"),
    "done": ("ready", "todo", "triage"),
    "archived": ("ready", "todo", "triage"),
}


def _workflow(core: Core) -> dict[str, Any] | None:
    from agos_core.engine import hermes_schema

    if core.engine is None:
        return None
    try:
        core.engine.config_schema()
        return hermes_schema.kanban_workflow()
    except (EngineError, OSError) as error:
        log.info("Hermes's Kanban workflow not read: %s", error)
        return None


def _columns(workflow: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Hermes's columns; `open`: a card there still has work ahead (every column but
    `done` and the archive: Hermes's terminal states, hermes_cli/kanban_db.py
    complete_task / archive), so the web needs no list of its own."""
    if workflow and isinstance(workflow.get("columns"), list):
        out: list[dict[str, Any]] = [
            {"status": str(c["key"]), "label": str(c.get("label") or c["key"])}
            for c in workflow["columns"]
            if isinstance(c, dict) and c.get("key")
        ]
        archived = str(workflow.get("archived") or ARCHIVED)
        out = [*out, {"status": archived, "label": archived.title()}]
    else:
        archived = ARCHIVED
        out = [{"status": s, "label": s.title()} for s in STATUSES]
    return [{**c, "open": c["status"] not in (DONE, archived)} for c in out]


DISPATCH_KEY = "kanban.dispatch_interval_seconds"


def dispatch_seconds(core: Core, workspace_id: str) -> int | None:
    """How often Hermes's dispatcher starts Ready cards, as the workspace's gateway
    reads it: the managed scope, else the root profile's config.yaml, else Hermes's
    default from its schema (H: hermes_cli/config_defaults.py:1901,
    gateway/kanban_watchers_dispatcher.py:50). None when none can be read."""
    from agos_core.actions import hermes_managed
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return None
    for source in ("managed", "profile"):
        try:
            cfg = (
                hermes_managed.current(core)
                if source == "managed"
                else config_file.read(engine.profile_home(workspace_id))
            )
            value = config_file.get(cfg, DISPATCH_KEY)
        except (EngineError, OSError, ValueError):
            value = None
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            return int(value)
    try:
        fields = {f.key: f for f in engine.config_schema()}
    except (EngineError, OSError) as error:
        log.info("Hermes's dispatch interval not read: %s", error)
        return None
    found = fields.get(DISPATCH_KEY)
    default = found.default if found is not None else None
    return int(default) if isinstance(default, int | float) and default > 0 else None


def _manual(workflow: dict[str, Any] | None) -> dict[str, set[str]]:
    table = workflow.get("manual") if workflow else None
    if not isinstance(table, dict):
        return {src: set(dsts) for src, dsts in MANUAL.items()}
    return {
        str(src): {str(d) for d in dsts}
        for src, dsts in table.items()
        if isinstance(dsts, list | tuple)
    }


def columns(core: Core) -> list[dict[str, Any]]:
    """Hermes's Kanban columns in its order (status, Hermes's label), then its
    archive. Falls back to STATUSES while Hermes's workflow can't be read."""
    return _columns(_workflow(core))


def card_actions(status: str, manual: dict[str, set[str]]) -> list[str]:
    """What the owner may do with a card in this status (the board's buttons), from
    Hermes's own manual move table (hermes_cli/kanban_workflow.py `manual`, what
    its dashboard lets a human request): mark done / stop (block) only where
    Hermes allows a move to `done` / `blocked` (its `complete_task` /
    `block_task` gates agree: kanban_db.py), unblock a blocked card that may go
    back to `ready`, archive any not archived (Hermes: always allowed)."""
    moves = manual.get(status, set())
    out: list[str] = []
    if status == BLOCKED and "ready" in moves:
        out.append("unblock")
    if DONE in moves:
        out.append("done")
    if BLOCKED in moves:
        out.append("block")
    if status != ARCHIVED:
        out.append("archive")
    return out
