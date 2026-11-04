"""A chat's own record as the owner makes and changes it on the Chats page: a new
chat, the check that a chat is in the workspace, the library agent it talks with,
and the search over the workspace's conversations.

Owns: those use-cases for the api router (api/chats.py, api/channels.py), each
through the chats repository (db/chats.py) in one transaction.
Must not: post messages or start answers (messages.py, turns.py) or rename a chat
(Hermes's /title: actions/chat.py rename).
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.library import check_agent
from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.db.connection import transaction

__all__ = [
    "create_chat",
    "has_chat",
    "require_chat",
    "search",
    "set_agent",
]


def has_chat(core: Core, workspace_id: str, chat_id: int) -> bool:
    """The chat is this workspace's (and not hidden)."""
    return repo.chat_row(core.db, workspace_id, chat_id) is not None


def require_chat(core: Core, workspace_id: str, chat_id: int) -> None:
    """NotFoundError unless the chat is this workspace's (and not hidden)."""
    if not has_chat(core, workspace_id, chat_id):
        raise NotFoundError("This chat")


def search(core: Core, workspace_id: str, query: str) -> list[dict[str, Any]]:
    """Messages matching every word, newest first (Hermes's own full-text index)."""
    return repo.search_chats(core.db, workspace_id, query)


def create_chat(core: Core, workspace_id: str, title: str) -> int:
    """A new web chat. Its name becomes its Hermes session's title with his first
    message (none given: Hermes names it itself after the first answer)."""
    with transaction(core.db):
        return repo.insert_chat(core.db, workspace_id=workspace_id, title=title, channel="web")


def set_agent(core: Core, workspace_id: str, chat_id: int, agent: str | None) -> None:
    """The library agent a chat talks with ("" for none; None leaves it). A DM or a
    group keeps its members. NotFoundError when the chat isn't this workspace's."""
    chosen = None
    if agent is not None:
        row = repo.chat_row(core.db, workspace_id, chat_id)
        if row is not None and row["kind"] != "chat":
            raise ActionError(
                "A direct message or group keeps its members; manage them in Workers."
            )
        chosen = check_agent(core, workspace_id, agent) or ""
    with transaction(core.db):
        if not repo.update_chat(core.db, workspace_id, chat_id, agent=chosen):
            raise NotFoundError("This chat")
