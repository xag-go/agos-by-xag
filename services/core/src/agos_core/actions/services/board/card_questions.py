"""The cards waiting for his answer (❓, Hermes's needs_input block): what each asks,
and his answer (a comment, then the card goes on).

Split out of agos_core.actions.kanban_board (its `questions`, `answer`, `OWNER_OK`).

Owns: which blocked cards are questions to him (an Autonomy ask is not one).
Must not: read Hermes's board database itself (kanban_db.py) or hold Autonomy's asks.
"""

from __future__ import annotations

from agos_core.actions.services.board import card_members, card_writes, kanban_cli, kanban_db
from agos_core.context import Core

__all__ = [
    "OWNER_OK",
    "answer",
    "questions",
]

OWNER_OK = "waiting for the owner:"  # the reason a card blocks with for an Autonomy ask


def questions(core: Core, workspace_id: str) -> list[dict[str, str]]:
    """Cards waiting for his answer (❓), with what they ask (Hermes's board)."""
    members = card_members.members(core, workspace_id)
    out = []
    for card_id, title, assignee, reason in kanban_db.needs_input(core, workspace_id):
        if reason.startswith(OWNER_OK):
            continue  # an Autonomy ask: answered with Allow once / Deny, not a question
        who = members.get(assignee)
        out.append(
            {
                "card": card_id,
                "title": title,
                "memberTitle": who["title"] if who else "",
                "question": reason,
            }
        )
    return out


def answer(core: Core, workspace_id: str, card_id: str, text: str) -> None:
    """His answer to a card waiting for him (❓): a comment, then it goes on."""
    card_writes.comment(core, workspace_id, card_id, text)
    kanban_cli.run(core, workspace_id, "unblock", card_id)
