"""The workspace's whole board as the Board page and the dashboard read it: Hermes's
own card list (asked again only when the board changed), its columns and members,
the goals and labels of the toolbar, and Hermes's own counters.

Split out of agos_core.actions.kanban_board (its `board`, `_listed`, `counters`,
`by_where`, `read_ahead`).

Owns: those reads and their caches (one per board file, keyed on the board's stamp).
Must not: write a card or read one card's detail (card_detail.py).
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board import card_members, card_shape, kanban_cli, kanban_db
from agos_core.actions.services.board.kanban_workflow import (
    _columns,
    _manual,
    _workflow,
    dispatch_seconds,
)
from agos_core.context import Core

__all__ = [
    "board",
    "by_where",
    "counters",
    "listed",
    "read_ahead",
]

log = logging.getLogger("agos.kanban_board")


def board(core: Core, workspace_id: str) -> dict[str, Any]:
    members = card_members.shown_members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""
    raw = listed(core, workspace_id)
    extra = kanban_db._extra(core, workspace_id)
    cards = [
        card_shape.card_of({**r, **extra.get(str(r.get("id")), {})}, members, cofounder)
        for r in raw
        if isinstance(r, dict)
    ]
    workflow = _workflow(core)
    cols, manual = _columns(workflow), _manual(workflow)
    known = {c["status"] for c in cols}
    from agos_core.actions import goals
    from agos_core.engine import goals as goal_rules

    return {
        "columns": cols,
        "dispatchSeconds": dispatch_seconds(core, workspace_id),
        "cards": [card_shape.with_actions(c, cols, manual) for c in cards if c["status"] in known],
        # The Co-Founder first, the Founder (the owner) next, then the team.
        "members": sorted(
            members.values(),
            key=lambda m: (
                m["name"] != card_members.COFOUNDER,
                m["name"] != "founder",
                m["title"].lower(),
            ),
        ),
        # The goals a card may serve (its chip's title, the modal's picker).
        "goals": [goal_rules.as_dict(g) for g in goal_rules.walk(goals.top(core, workspace_id))],
        # The workspace's labels and saved views (AGOS's rows), for the toolbar.
        **_toolbar(core, workspace_id),
    }


def _toolbar(core: Core, workspace_id: str) -> dict[str, Any]:
    from agos_core.actions import board_views, labels

    return {
        "labels": labels.listing(core, workspace_id),
        "views": board_views.listing(core, workspace_id),
    }


_listed_cache: dict[str, tuple[tuple[int, ...], Any]] = {}


def listed(core: Core, workspace_id: str) -> Any:
    """Hermes's own list of cards; asked again only when the board changed (each
    ask starts Hermes, which takes most of a second)."""
    from agos_core.actions import agent_profiles

    stamp = kanban_db._stamp(core, workspace_id) if core.engine is not None else None
    where = str(agent_profiles.board_db(core, workspace_id)) if stamp is not None else ""
    seen = _listed_cache.get(where)
    if stamp is not None and seen is not None and seen[0] == stamp:
        return seen[1]
    raw = kanban_cli.answer(
        kanban_cli.run(core, workspace_id, "list", "--json", "--archived", "--sort", "created-desc")
        or "[]"
    )
    if stamp is not None and stamp == kanban_db._stamp(core, workspace_id):
        _listed_cache[where] = (stamp, raw)
    return raw


def read_ahead(core: Core) -> None:
    """engine/read_ahead.py: each workspace's board as Hermes lists it and its
    counters (`hermes kanban list` / `stats`), asked once after a start so the
    first Board page doesn't wait for Hermes. The list stays Hermes's CLI: it also
    promotes the cards whose parents finished (kanban.py _cmd_list recompute_ready)."""
    from agos_core.actions import agent_profiles
    from agos_core.db import workspaces as workspaces_repo

    if core.engine is None:
        return
    for ws in workspaces_repo.list_workspaces(core.db):
        if not agent_profiles.board_db(core, ws.id).is_file():
            continue  # no board yet: the page shows none without Hermes
        try:
            listed(core, ws.id)
            counters(core, ws.id)
        except ActionError as error:
            log.info("the board of %s not read ahead: %s", ws.id, error)


_stats_cache: dict[str, tuple[tuple[int, ...], dict[str, int]]] = {}


def counters(core: Core, workspace_id: str) -> dict[str, int]:
    """The workspace's cards by where they stand (its dashboard): Hermes's own
    `hermes kanban stats --json` (by_status, archived left out; hermes_cli/
    kanban_db.py board_stats). Asked again only when the board changed."""
    from agos_core.actions import agent_profiles

    counts = {"working": 0, "waiting_for_you": 0, "suggestions": 0, "done": 0}
    if core.engine is None or not agent_profiles.board_db(core, workspace_id).is_file():
        return counts
    stamp = kanban_db._stamp(core, workspace_id)
    where = str(agent_profiles.board_db(core, workspace_id))
    seen = _stats_cache.get(where)
    if stamp is not None and seen is not None and seen[0] == stamp:
        return dict(seen[1])
    try:
        counts = by_where(
            kanban_cli.answer(kanban_cli.run(core, workspace_id, "stats", "--json") or "{}")
        )
    except ActionError:
        return counts
    if stamp is not None:
        _stats_cache[where] = (stamp, dict(counts))
    return counts


def by_where(stats: Any) -> dict[str, int]:
    """Hermes's stats, as the dashboard groups them."""
    group = {
        "running": "working",
        "blocked": "waiting_for_you",
        "review": "waiting_for_you",
        "triage": "suggestions",
        "todo": "suggestions",
        "done": "done",
    }
    counts = {"working": 0, "waiting_for_you": 0, "suggestions": 0, "done": 0}
    by_status = stats.get("by_status") if isinstance(stats, dict) else None
    for status, n in (by_status or {}).items():
        if str(status) in group and isinstance(n, int):
            counts[group[str(status)]] += n
    return counts
