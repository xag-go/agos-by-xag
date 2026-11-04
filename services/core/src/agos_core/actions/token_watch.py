"""A Kanban card using far more tokens than usual: the owner hears it, the work
goes on.

Hermes does the watching (the agos-guard plugin, hermes_plugin/agos_guard/tokens.py):
it counts each model call of the card's run, keeps the count on the card in its
own Kanban, sets the mark from the board's finished cards and decides when a card
is past it. AGOS only shows it to the owner (his app and his phone) with his two
answers: Let it go on / Stop it (Stop = Hermes's own block of the card). The
answer he gave is AGOS's control state (which warnings he has seen).
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from typing import Any

from agos_core.context import Core
from agos_core.hermes_gateway import hermes_db

log = logging.getLogger("agos.tokens")

ANSWERED = "card.tokens.answered."  # + workspace id → {card: level he answered}


def _told(core: Core, workspace_id: str) -> dict[str, dict[str, int]]:
    """Hermes's warnings on this workspace's board (read only): card → level, count."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return {}
    board = agent_profiles.board_db(core, workspace_id)
    if not board.is_file():
        return {}
    out: dict[str, dict[str, int]] = {}
    try:
        with contextlib.closing(hermes_db.connect_ro(board, timeout=2)) as db:
            for task_id, payload in db.execute(
                "SELECT task_id, payload FROM task_events WHERE kind = 'agos_tokens_told'"
                " ORDER BY id"
            ):
                with contextlib.suppress(ValueError, TypeError):
                    data = json.loads(payload or "{}")
                    out[str(task_id)] = {
                        k: int(data.get(k) or 0) for k in ("level", "tokens", "usual")
                    }
    except sqlite3.Error:
        return {}
    return out


def _answered_levels(core: Core, workspace_id: str) -> dict[str, int]:
    from agos_core.db.app_settings import get_setting

    saved = get_setting(core.db, ANSWERED + workspace_id, {})
    return saved if isinstance(saved, dict) else {}


def told(core: Core, workspace_id: str, card: str, tokens: int, usual: int) -> None:
    """Hermes says this card is far past its usual size: the owner hears it."""
    _tell(core, workspace_id, card, int(tokens), int(usual))


def _millions(n: int) -> str:
    return f"{n / 1_000_000:.1f}M".replace(".0M", "M")


def _tell(core: Core, workspace_id: str, card: str, tokens: int, usual: int) -> None:
    from agos_core.actions import kanban_board, voice
    from agos_core.actions.notification_rules import delivery_for
    from agos_core.actions.services.channel import owner_needs
    from agos_core.db.activity import add_activity

    title = kanban_board.facts(core, workspace_id, [card]).get(card, {}).get("title") or card
    text = voice.for_cofounder(
        core,
        workspace_id,
        "tokens",
        task=f"{card} “{title}”",
        used=_millions(tokens),
        usual=_millions(max(usual, 1)),
    )
    add_activity(
        core.db,
        workspace_id,
        kind="task.tokens",
        text=f"Card {card} “{title}”: {_millions(tokens)} tokens so far (far more than usual)",
    )
    delivery = delivery_for(core, "task.tokens")
    if delivery == "silent":
        return
    message_id = owner_needs.tell_owner(core, workspace_id, text)
    if delivery == "batched":  # his Daily digest: on the phone tomorrow morning
        from agos_core.actions import digest

        digest.hold(
            core,
            workspace_id,
            "task.tokens",
            f"Card {card} “{title}” used {_millions(tokens)} tokens (far more than usual)",
        )
        return
    owner_needs.push(
        core,
        workspace_id,
        text,
        f"msg:{message_id}" if message_id else f"tokens:{card}:{tokens}",
        buttons=[("Let it go on", f"tok:go:{card}"), ("Stop it", f"tok:stop:{card}")],
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )


def knows(core: Core, workspace_id: str, card: str) -> bool:
    """Hermes warned about this card on this workspace's board (its buttons may answer it)."""
    return card in _told(core, workspace_id)


def waiting(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Token warnings he hasn't answered, for cards still at work (Co-Founder's chat)."""
    from agos_core.actions import kanban_board

    answered = _answered_levels(core, workspace_id)
    told_now = _told(core, workspace_id)
    cards = [c for c, e in told_now.items() if e["level"] > int(answered.get(c) or 0)]
    if not cards:
        return []
    facts = kanban_board.facts(core, workspace_id, cards)
    return [
        {"card": c, "title": facts[c].get("title") or c, "used": _millions(told_now[c]["tokens"])}
        for c in cards
        if c in facts and facts[c].get("status") in ("ready", "running", "review", "todo")
    ]


def _answered(core: Core, workspace_id: str, card: str) -> None:
    from agos_core.db.app_settings import set_setting
    from agos_core.db.connection import transaction

    level = _told(core, workspace_id).get(card, {}).get("level", 0)
    with transaction(core.db):
        answered = _answered_levels(core, workspace_id)
        answered[card] = level
        set_setting(core.db, ANSWERED + workspace_id, dict(list(answered.items())[-300:]))


def answer(core: Core, workspace_id: str, card: str, choice: str) -> str:
    """The owner's answer from the buttons (app or phone). 'go' = nothing changes
    (he'll hear again only at the next level); 'stop' = the card is stopped like
    his Stop."""
    from agos_core.actions import kanban_board
    from agos_core.actions.errors import ActionError

    if not knows(core, workspace_id, card):
        return "This card isn't this workspace's."
    _answered(core, workspace_id, card)
    if choice == "go":
        return "OK, it goes on. You'll hear again only if it doubles."
    try:
        kanban_board.act(core, workspace_id, card, "block")
    except ActionError as error:
        return error.message
    return "Stopped. Unblock it on the board when you want it to go on."
