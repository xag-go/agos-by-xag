"""The Board's bulk actions: many cards edited, given to a member, or moved by one
of the board's buttons, with as few Hermes processes as Hermes allows.

Split out of agos_core.actions.kanban_board (its `_bulk`, `edit_bodies`,
`assign_many`, `act_many`).

Owns: batching ops into the agos-guard plugin's `hermes agos-bulk` (chunks under
the argv limit), the one-call-per-card fallback, and which cards moved or failed.
Must not: hold a single card's write rules (card_writes.py).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board import card_members, card_writes, kanban_cli
from agos_core.actions.services.board.card_text import complete_args
from agos_core.context import Core
from agos_core.engine.hermes import EngineError

__all__ = [
    "BULK_ARGV",
    "act_many",
    "assign_many",
    "bulk",
    "edit_bodies",
]

log = logging.getLogger("agos.kanban_board")

BULK_ARGV = 900_000  # characters of ops per `hermes agos-bulk` (well under argv limits)


def bulk(core: Core, workspace_id: str, ops: list[dict[str, str]]) -> dict[str, Any]:
    """Ops through Hermes's own writers in one Hermes process per chunk (the
    agos-guard plugin's `hermes agos-bulk`; Hermes's CLI takes one card per assign /
    edit). When that command can't run, one `hermes kanban` call per card."""
    done: list[str] = []
    failed: dict[str, str] = {}
    chunks: list[list[str]] = [[]]
    size = 0
    for op in ops:
        text = json.dumps(op, ensure_ascii=False)
        if chunks[-1] and size + len(text) > BULK_ARGV:
            chunks.append([])
            size = 0
        chunks[-1].append(text)
        size += len(text)
    for chunk, start in zip(chunks, _starts(chunks), strict=True):
        found = _bulk_once(core, workspace_id, chunk)
        if found is None:
            for op in ops[start : start + len(chunk)]:
                try:
                    if op["op"] == "assign":
                        kanban_cli.run(core, workspace_id, "assign", op["card"], op["to"] or "none")
                    else:
                        kanban_cli.run(core, workspace_id, "edit", op["card"], "--body", op["body"])
                    done.append(op["card"])
                except ActionError as error:
                    failed[op["card"]] = str(error)
            continue
        done += [str(c) for c in found.get("done") or []]
        failed.update({str(k): str(v) for k, v in (found.get("failed") or {}).items()})
    return {"done": done, "failed": failed}


def _starts(chunks: list[list[str]]) -> list[int]:
    out, at = [], 0
    for chunk in chunks:
        out.append(at)
        at += len(chunk)
    return out


def _bulk_once(core: Core, workspace_id: str, ops: list[str]) -> dict[str, Any] | None:
    if core.engine is None or not ops:
        return None
    try:
        out = kanban_cli.plugin(core, workspace_id, "agos-bulk", *ops, timeout=120)
        found = kanban_cli.answer(out)
    except (EngineError, ActionError, OSError, ValueError) as error:
        log.info("bulk edit of %s one card at a time: %s", workspace_id, error)
        return None
    if not isinstance(found, dict) or "error" in found or "done" not in found:
        log.info("bulk edit of %s one card at a time: %s", workspace_id, found)
        return None
    return found


def edit_bodies(core: Core, workspace_id: str, bodies: dict[str, str]) -> dict[str, Any]:
    """New Hermes bodies for these cards (Hermes's edit_task), batched."""
    return bulk(
        core, workspace_id, [{"op": "body", "card": c, "body": b} for c, b in bodies.items()]
    )


def assign_many(
    core: Core, workspace_id: str, cards: list[str], member: str, *, founder: bool = False
) -> dict[str, Any]:
    """These cards to one member (Hermes's assign_task), batched."""
    profile = card_members.profile_of(core, workspace_id, member, founder=founder)
    found = bulk(
        core,
        workspace_id,
        [{"op": "assign", "card": c, "to": "" if profile == "none" else profile} for c in cards],
    )
    if profile == "founder":
        from agos_core.actions import founder as founder_actions

        founder_actions.tell(core, workspace_id)
    return found


def act_many(
    core: Core, workspace_id: str, cards: list[str], action: str, summary: str = ""
) -> dict[str, Any]:
    """One of the board's buttons on many cards: ONE Hermes CLI call (its archive,
    complete and unblock take many ids, block takes `--ids`). Refused as a whole
    (one card can't move): each card alone, so the others still move."""
    if action not in card_writes.ACTIONS:
        raise ActionError("Unknown action.")
    if not cards:
        return {"done": [], "failed": {}}

    def argv(ids: list[str]) -> list[str]:
        if action == "done":
            return [*complete_args(ids[0], summary)[:1], *ids, *complete_args(ids[0], summary)[2:]]
        if action == "block":
            return [
                "block",
                ids[0],
                "Stopped by the owner.",
                *(["--ids", *ids[1:]] if ids[1:] else []),
            ]
        return [*card_writes.ACTIONS[action], *ids]

    try:
        kanban_cli.run(core, workspace_id, *argv(cards))
        return {"done": list(cards), "failed": {}}
    except ActionError:
        if len(cards) == 1:
            return {"done": [], "failed": {cards[0]: "Hermes refused it."}}
    done: list[str] = []
    failed: dict[str, str] = {}
    for card in cards:
        try:
            kanban_cli.run(core, workspace_id, *argv([card]))
            done.append(card)
        except ActionError as error:
            failed[card] = str(error)
    return {"done": done, "failed": failed}
