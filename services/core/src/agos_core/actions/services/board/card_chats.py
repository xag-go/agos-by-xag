"""A Kanban card's own chat: the owner talks with the card's member there (made
once per member), and its name is the Hermes card's title.

Split out of agos_core.actions.kanban_board (its `chat_of`, `move_card_chat_titles`).

Owns: when a card chat may be made and the one-time move of copied card titles.
Must not: hold the chat's conversation (the Chat service) or write the card.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board import card_detail, kanban_db
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db.connection import transaction

__all__ = [
    "chat_of",
    "move_card_chat_titles",
]


def chat_of(core: Core, workspace_id: str, card_id: str) -> int:
    """The card's own chat (made once): the owner talks with its member there."""
    shown = card_detail.card(core, workspace_id, card_id)  # Hermes's card: its assignee now
    if shown["chatId"] is not None:
        return int(shown["chatId"])
    if not shown["member"]:
        raise ActionError("Give the card to a member first: the chat is with them.")
    if shown["member"] == "founder":
        raise ActionError("This card is yours (the Founder's): talk about it with the Co-Founder.")
    from agos_core.actions import agent_profiles

    if shown["member"] not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("This card's member is not on the team: give the card to a member first.")
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    with transaction(core.db):
        return chats_repo.insert_card_chat(core.db, workspace_id, shown["member"], card_id)


def move_card_chat_titles(core: Core) -> int:
    """Once: the card title AGOS copied into a card chat goes where Hermes's board
    holds the card (its name is read from there, db/chats.py card_title). A card
    the board doesn't have keeps the copy. Safe to repeat."""
    rows = chats_repo.card_chats_titled(core.db)
    by_ws: dict[str, list[Any]] = {}
    for row in rows:
        by_ws.setdefault(str(row["workspace_id"]), []).append(row)
    moved = 0
    for workspace_id, chats in by_ws.items():
        held = kanban_db.facts(core, workspace_id, [str(r["kanban_card"]) for r in chats])
        for row in chats:
            if held.get(str(row["kanban_card"]), {}).get("title"):
                chats_repo.clear_copied_title(core.db, int(row["id"]), str(row["title"]))
                moved += 1
    return moved
