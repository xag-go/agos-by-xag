"""Finding a chat of a workspace (and checking it is that workspace's), its team and its Hermes session id.
Must not: change a chat.

Split out of agos_core.actions.chat (which re-exports it); behaviour unchanged.
"""

import logging
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.engine import attachments as files
from agos_core.engine import team

__all__ = [
    "team_members",
]

log = logging.getLogger("agos.chat")


def team_members(core: Core, workspace_id: str, names: list[str]) -> list[team.Member]:
    """The group's members that are still on in the workspace (Connectors)."""
    from agos_core.actions import team as team_actions  # late: it imports library

    out = []
    for name in names:
        agent = team_actions.get(core, workspace_id, name)
        if agent is not None and agent.on:
            out.append(team.Member(name=name, title=agent.title, summary=agent.summary))
    return out


def _chat(core: Core, workspace_id: str, chat_id: int) -> Any:
    row = repo.chat_row(core.db, workspace_id, chat_id)
    if row is None:
        raise NotFoundError("This chat")
    return row


def _checked(body: str, attached: list[files.Incoming]) -> None:
    if not body.strip() and not attached:
        raise ActionError("Write a message or attach something.")
    try:
        files.check_all(attached)
    except files.AttachmentError as error:
        raise ActionError(str(error)) from error
