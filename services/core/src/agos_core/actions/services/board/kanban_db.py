"""Reads of Hermes's own board database (read-only, no Kanban CLI): the board's
stamp (has it changed), what Hermes's list leaves out (goal mode, why a card is
blocked), the latest events and who each is put down to, cards' status / result
by id (facts), by idempotency key (keyed), by the session that made them, cards
finished since a time, a profile's newest cards, the cards blocked for his input,
and the board file Hermes's CLI reads (board_file).

Owns: those reads. Must not: call Hermes's Kanban CLI or change a card
(actions/kanban_board.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.hermes_gateway import kanban_rows

__all__ = [
    "EVENTS",
    "board_file",
    "done_since",
    "events",
    "facts",
    "keyed",
    "latest_by",
    "made_in",
    "needs_input",
]


def _stamp(core: Core, workspace_id: str) -> tuple[int, ...] | None:
    """What the board's cards are now (read only from Hermes's own database): a
    hash of every field AGOS shows. Not the file's time: Hermes's CLI touches the
    file each time it lists, so that never matched."""
    import hashlib
    import sqlite3

    from agos_core.actions import agent_profiles

    base = agent_profiles.board_db(core, workspace_id)
    if not base.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with kanban_rows.opened(base) as board:
            for row in board.stamp_rows():
                digest.update(repr(tuple(row)).encode())
    except sqlite3.Error:
        return None
    return (int.from_bytes(digest.digest()[:8], "big"),)


def _extra(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    """What Hermes's list leaves out (goal mode, why a card is blocked), read from
    the board's own database (read only)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return {}
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return {}
    from agos_core.actions import reviews
    from agos_core.engine import goals as goal_rules

    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.extra_rows()
            links = [(str(p), str(c)) for p, c in board.links()]
            # Each card's review chip (its stages, round, plan): the same connection.
            review = reviews.board_rows(
                core,
                workspace_id,
                board,
                [
                    (str(i), str(st or ""), str(a or ""), str(b or ""))
                    for i, _g, _k, st, b, a in rows
                ],
            )
    except sqlite3.Error:
        return {}
    # Each card's sub-goal, its own or its nearest parent's (same read).
    served = goal_rules.card_goals(
        {str(i): (str(st or ""), str(b or "")) for i, _g, _k, st, b, _a in rows}, links
    )
    return {
        str(i): {
            "goal_mode": g,
            "block_kind": b,
            **({"goal_id": served[str(i)][0]} if str(i) in served else {}),
            **({"review_chip": review[str(i)]["review"]} if str(i) in review else {}),
        }
        for i, g, b, _st, _body, _a in rows
    }


# What happened to a card, from Hermes's own Kanban events (task_events; their kinds
# are hermes_cli/kanban_db.py _append_event's): the level and the words AGOS shows.
EVENTS: dict[str, tuple[str, str]] = {
    "created": ("info", "Created"),
    "claimed": ("info", "Started"),
    "review_requested": ("info", "Ready for review"),
    "completed": ("ok", "Done"),
    "blocked": ("warn", "Blocked"),
    "unblocked": ("info", "Unblocked"),
    "archived": ("info", "Archived"),
    "crashed": ("error", "Crashed"),
    "failed": ("error", "Failed"),
    "timed_out": ("error", "Timed out"),
    "protocol_violation": ("error", "The agent broke the board's rules"),
    "commented": ("info", "Commented"),
    "assigned": ("info", "Assigned"),
}


def events(core: Core, workspace_id: str, limit: int) -> list[dict[str, Any]]:
    """The board's latest events, newest first, read from Hermes's own board
    database (read only): id, card, kind, payload (a dict), at (seconds), title, and
    who did it (`actor`: the run's profile, the card's creator for `created`, the
    comment's author; "" when Hermes recorded nobody) with the card's idempotency
    key (`key`: an automation's cards carry `agos-automation:<id>:...`)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    kinds = tuple(EVENTS)
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.events(kinds, limit)
            extra = _event_actors(board, rows)
    except sqlite3.Error:
        return []
    found: list[dict[str, Any]] = []
    for i, task, kind, payload, at, title in rows:
        try:
            data = json.loads(payload or "{}")
        except ValueError:
            data = {}
        found.append(
            {
                "id": int(i),
                "card": str(task),
                "kind": str(kind),
                "payload": data if isinstance(data, dict) else {},
                "at": float(at or 0),
                "title": str(title or ""),
                **extra.get(int(i), {"actor": "", "key": ""}),
            }
        )
    for e in found:
        if e["kind"] == "commented" and not e["actor"]:
            e["actor"] = str(e["payload"].get("author") or "")
    return found


def _event_actors(board: kanban_rows.Board, rows: list[Any]) -> dict[int, dict[str, str]]:
    """Who each event is put down to, from the board's own rows: the run's profile
    (task_runs), else the card's creator for its `created` event. Older or partial
    boards (no task_runs, no created_by) give "" (nobody recorded)."""
    creators = board.creators(sorted({str(r[1]) for r in rows}))
    runs = board.run_profiles([int(r[0]) for r in rows])
    out: dict[int, dict[str, str]] = {}
    for i, task, kind, _payload, _at, _title in rows:
        by, key = creators.get(str(task), ("", ""))
        actor = runs.get(int(i)) or (by if kind == "created" else "")
        out[int(i)] = {"actor": actor, "key": key}
    return out


def facts(core: Core, workspace_id: str, card_ids: list[str]) -> dict[str, dict[str, str]]:
    """These cards' status, title and result (missing = gone), read from the board's
    own database (read only)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None or not card_ids:
        return {}
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return {}
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.facts(card_ids)
    except sqlite3.Error:
        return {}
    return {
        str(i): {"status": str(st or ""), "title": str(t or ""), "result": str(r or "")}
        for i, st, t, r in rows
    }


def keyed(core: Core, workspace_id: str, prefix: str) -> list[dict[str, Any]]:
    """The cards whose Hermes idempotency key starts with `prefix` (an automation's
    runs), with their parents, read from the board's own database (read only)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.keyed(prefix)
            links = board.parents_of([str(r[0]) for r in rows])
    except sqlite3.Error:
        return []
    parents: dict[str, list[str]] = {}
    for parent, child in links:
        parents.setdefault(str(child), []).append(str(parent))
    return [
        {
            "id": str(i),
            "status": str(st or ""),
            "title": str(t or ""),
            "result": str(r or ""),
            "key": str(k or ""),
            "created_at": c,
            "completed_at": done,
            "assignee": str(who or ""),
            "parents": parents.get(str(i), []),
        }
        for i, st, t, r, k, c, done, who in rows
    ]


def made_in(core: Core, workspace_id: str, session_prefix: str) -> list[dict[str, Any]]:
    """Cards made in Hermes sessions whose id starts with `session_prefix` (an
    automation's cron runs: cron_<job>_…), read from the board's database."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.made_in(session_prefix)
    except sqlite3.Error:
        return []
    return [
        {
            "id": str(i),
            "title": str(t or ""),
            "body": str(b or ""),
            "status": str(s or ""),
            "created_at": int(c or 0),
        }
        for i, t, b, s, c in rows
    ]


def done_since(core: Core, workspace_id: str, since: int) -> int:
    """Cards finished since `since` (unix seconds), read from the board's database."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return 0
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return 0
    try:
        with kanban_rows.opened(board_db) as board:
            return board.done_since(since)
    except sqlite3.Error:
        return 0


def latest_by(core: Core, workspace_id: str, profile: str, limit: int) -> list[dict[str, str]]:
    """A profile's newest cards (id, title, status, its result's first line)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    board_db = agent_profiles.board_db(core, workspace_id)
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.latest_by(profile, limit)
    except sqlite3.Error:
        return []
    return [
        {
            "id": str(i),
            "title": " ".join(str(t or "").split())[:160],
            "status": str(st or ""),
            "result": " ".join(str(r or "").split())[:200],
        }
        for i, t, st, r in rows
    ]


def needs_input(core: Core, workspace_id: str) -> list[tuple[str, str, str, str]]:
    """Cards Hermes's board holds blocked for his input: (card, title, assignee, reason)."""
    import sqlite3

    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.needs_input()
    except sqlite3.Error:
        return []
    out = []
    for card_id, title, assignee, payload in rows:
        try:
            reason = str((json.loads(payload or "{}") or {}).get("reason") or "")
        except ValueError:
            reason = ""
        out.append((str(card_id), str(title), str(assignee or ""), reason))
    return out


def board_file(core: Core, workspace_id: str) -> Path:
    """The board database Hermes's CLI reads for this workspace, when AGOS can read
    it the same way (engine/hermes_board.py board); else hermes_board.Unread."""
    from agos_core.actions import agent_profiles
    from agos_core.engine import hermes_board

    if core.engine is None:
        raise hermes_board.Unread("no engine")
    return hermes_board.board(
        agent_profiles.board_home(core, workspace_id), core.engine.settings.host_home
    )
