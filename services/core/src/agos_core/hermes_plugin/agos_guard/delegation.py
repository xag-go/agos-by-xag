"""The delegation-cycle guard (Step 51, F06): an agent may not hand a card back to
the agent that handed it the work (A -> B -> A on the same subtree).

Paperclip's rule (server/src/routes/issues.ts assertNoAgentDelegationCycle): an
agent creating a child card assigned to the agent that CREATED a still-open
ancestor of it is refused. The ancestors are the new card's parents and the card
the agent is working on (HERMES_KANBAN_TASK), and theirs, up Hermes's task_links.
Self-assignment is decomposition, not delegation; humans' cards (created by the
owner) never count; done or archived ancestors don't either (re-engaging the
author of finished work is normal). Paperclip refuses nothing about delegating UP
the org chart, so neither does AGOS: such a card is only logged.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

log = logging.getLogger("agos_guard")

CLOSED = ("done", "archived")
HUMANS = ("", "owner", "user")  # cards a person made: never a delegation
MAX_STEPS = 1024  # Paperclip's request_depth clamp: a walk never runs away


def refusal(
    *,
    me: str,
    assignee: str,
    starts: Iterable[str],
    read: Callable[[str], tuple[str, str, str, list[str]] | None],
) -> str:
    """The refusal message, or "" when the card may be made. `read(card)`:
    (created_by, status, title, parents) of a card, None when it isn't there."""
    if not assignee or not me or assignee == me:
        return ""
    seen: set[str] = set()
    layer = [s for s in starts if s]
    steps = 0
    while layer and steps < MAX_STEPS:
        nxt: list[str] = []
        for card in layer:
            if card in seen:
                continue
            seen.add(card)
            steps += 1
            found = read(card)
            if found is None:
                continue
            created_by, status, title, parents = found
            if created_by == assignee and created_by not in HUMANS and status not in CLOSED:
                return (
                    f"Delegation loop: card {card} ({title[:80]}) in this chain was made by "
                    f"{assignee}, who handed this work to you. Don't hand it back: do the "
                    "remaining work on your own card, or ask your lead or the owner "
                    "(agos_ask_owner) for what is missing."
                )
            nxt += parents
        layer = nxt
    return ""


def check(args: dict[str, Any], *, me: str, current: str, conn: Any) -> str:
    """kanban_create's arguments against Hermes's board (an open sqlite connection)."""
    assignee = str(args.get("assignee") or "").strip()
    raw = args.get("parents")
    parents = [str(p) for p in raw] if isinstance(raw, list) else []

    def read(card: str) -> tuple[str, str, str, list[str]] | None:
        row = conn.execute(
            "SELECT created_by, status, title FROM tasks WHERE id = ?", (card,)
        ).fetchone()
        if row is None:
            return None
        ups = [
            str(r[0])
            for r in conn.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (card,))
        ]
        return str(row[0] or ""), str(row[1] or ""), str(row[2] or ""), ups

    found = refusal(me=me, assignee=assignee, starts=[*parents, current], read=read)
    if not found and assignee == "default" and me != "default":
        log.info("AGOS: %s hands a card up to the Co-Founder (allowed, logged)", me)
    return found


def guard(args: dict[str, Any], *, me: str, current: str, report: Callable[..., None]) -> str:
    """The guard's check inside Hermes: its own board connection (the one Hermes's
    kanban tools use). Fails open: a board AGOS can't read never stops a card."""
    try:
        from hermes_cli import kanban_db_connect as kbc  # type: ignore[import-not-found]
    except ImportError as error:
        report("hermes_cli.kanban_db_connect.connect", error)
        return ""
    try:
        conn = kbc.connect()
    except Exception as error:  # noqa: BLE001 — no board here: nothing to check
        report("hermes_cli.kanban_db_connect.connect", error)
        return ""
    try:
        return check(args, me=me, current=current, conn=conn)
    except Exception as error:  # noqa: BLE001 — a schema AGOS can't read: let it through
        log.info("AGOS: delegation check skipped: %s", error)
        return ""
    finally:
        conn.close()
