"""Posting the owner's message into the chat's Hermes conversation, and sending it on.
Must not: keep a copy of what is said.

Split out of agos_core.actions.chat (which re-exports it); behaviour unchanged.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.chat import chat_writes
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.services.chat.live_turns import _spawn
from agos_core.actions.services.chat.lookup import _chat, _checked
from agos_core.actions.services.chat.turns import _gateway_up
from agos_core.context import Core
from agos_core.db import chat_attachments
from agos_core.db import chats as repo
from agos_core.db import hermes_chats as hc
from agos_core.db.connection import transaction
from agos_core.db.records import ChatMessage
from agos_core.engine import attachments as files
from agos_core.engine import owner_keys
from agos_core.storage.layout import workspace_paths

__all__ = [
    "attachment_file",
    "save_owner_message",
    "send",
]


def send(
    core: Core,
    workspace_id: str,
    chat_id: int,
    body: str,
    attached: list[files.Incoming] | None = None,
    *,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int:
    """His message goes into the chat's Hermes conversation as he wrote it: his files
    as files (Hermes reads, hears and looks at them itself), a reply as Hermes's own
    reply context. Kept nowhere else: until Hermes has it, it is in the agos
    platform's queue (shown from there)."""
    from agos_core.actions import hermes_channel

    attached = attached or []
    _checked(body, attached)
    text = body.strip()
    command = not attached and hermes_channel.is_hermes_command(text)
    text = owner_keys.hide(text, command=command)  # before AGOS or Hermes keeps it
    if command:
        # A Hermes /command: Hermes runs it (it keeps no transcript of commands, so
        # the chat shows it as AGOS's own line).
        with transaction(core.db):
            added = chat_writes.add_chat_message(core.db, workspace_id, chat_id, "owner", text)
        if added is None:
            raise NotFoundError("This chat")
        hermes_channel.hand_over_command(core, workspace_id, chat_id, added, text)
        return hc.ROW_BASE + added
    reply = _reply_of(core, workspace_id, chat_id, reply_to, reply_excerpt)
    where = hermes_channel.chat_on_hermes(core, chat_id)
    if where is None:
        raise NotFoundError("This chat")
    on_platform = where["connection_id"] is None
    folder = workspace_paths(core.layout, workspace_id).files
    written: list[str] = []
    try:
        with transaction(core.db):
            stored: list[dict[str, Any]] = []
            item = hermes_channel.hand_over(core, workspace_id, chat_id, text, reply=reply)
            if item is None:
                raise NotFoundError("This chat")
            for index, one in enumerate(attached):
                relative = files.relative_path(chat_id, item, index, one.name)
                path = files.write(folder, relative, one.data)
                written.append(relative)
                chat_attachments.add_attachment(
                    core.db,
                    None,
                    kind=one.kind,
                    name=one.name,
                    mime=one.mime,
                    size=len(one.data),
                    path=relative,
                    duration=one.duration,
                    chat_id=chat_id,
                    inbox_id=item,
                )
                stored.append(
                    {"path": str(path), "mime": one.mime, "kind": one.kind, "relative": relative}
                )
            if stored:
                hermes_channel.set_media(core, item, stored)
    except BaseException:
        for relative in written:  # no orphan files when the message wasn't saved
            with contextlib.suppress(OSError):
                (folder / relative).unlink()
        raise
    if on_platform:
        _spawn(core, _wake(core, workspace_id))
    return hc.PENDING_BASE + item


def _reply_of(
    core: Core, workspace_id: str, chat_id: int, reply_to: int | None, excerpt: str | None
) -> tuple[str, bool] | None:
    """What his message replies to, as Hermes takes a reply: the quoted text (the
    part he selected, else the whole message) and whether it is the agent's."""
    if reply_to is None:
        return None
    found = _message(core, workspace_id, chat_id, reply_to)
    if found is None:
        return None
    part = repo.excerpt_in(found.body, excerpt)
    text = (part or found.body).strip()
    return (text, found.from_ == "agent") if text else None


def _message(core: Core, workspace_id: str, chat_id: int, message_id: int) -> ChatMessage | None:
    chat = chat_view.get_chat(core.db, workspace_id, chat_id)
    if chat is None:
        return None
    return next((m for m in chat.messages if m.id == message_id), None)


async def _wake(core: Core, workspace_id: str) -> None:
    """The workspace's gateway carries AGOS's conversations: up before it takes them."""
    await asyncio.to_thread(_gateway_up, core, workspace_id)


def save_owner_message(
    core: Core,
    workspace_id: str,
    chat_id: int,
    body: str,
    attached: list[files.Incoming] | None = None,
    *,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int:
    """His line in a room, and its attachments (the room is handed it by the caller,
    or by the tick). A Hermes chat: his message goes to Hermes (`send`)."""
    row = _chat(core, workspace_id, chat_id)
    if repo.is_hermes(row):
        return send(
            core,
            workspace_id,
            chat_id,
            body,
            attached,
            reply_to=reply_to,
            reply_excerpt=reply_excerpt,
        )
    attached = attached or []
    _checked(body, attached)
    body = owner_keys.hide(body)  # before AGOS keeps it or hands it to the room
    folder = workspace_paths(core.layout, workspace_id).files
    written: list[str] = []
    try:
        with transaction(core.db):
            message_id = chat_writes.add_chat_message(
                core.db,
                workspace_id,
                chat_id,
                "owner",
                body,
                reply_to=reply_to,
                reply_excerpt=reply_excerpt,
            )
            if message_id is None:
                raise NotFoundError("This chat")
            for index, item in enumerate(attached):
                relative = files.relative_path(chat_id, message_id, index, item.name)
                files.write(folder, relative, item.data)
                written.append(relative)
                chat_attachments.add_attachment(
                    core.db,
                    message_id,
                    kind=item.kind,
                    name=item.name,
                    mime=item.mime,
                    size=len(item.data),
                    path=relative,
                    duration=item.duration,
                    chat_id=chat_id,
                )
    except BaseException:
        for relative in written:  # no orphan files when the message wasn't saved
            with contextlib.suppress(OSError):
                (folder / relative).unlink()
        raise
    return message_id


def checked_attachments(raw: list[Any]) -> list[Any]:
    """The files he sends with a message (kind, name, mime, data, duration), each
    checked (engine/attachments.py); ActionError with the reason otherwise."""
    try:
        return [files.check(a.kind, a.name, a.mime, a.data, a.duration) for a in raw]
    except files.AttachmentError as error:
        raise ActionError(str(error)) from error


def shown_inline(mime: str) -> bool:
    """A chat file the page shows in place (an image, a voice note); others download."""
    return mime in files.IMAGE_TYPES or mime in files.AUDIO_TYPES


def attachment_file(
    core: Core, workspace_id: str, chat_id: int, attachment_id: int
) -> tuple[Path, str, str]:
    """(path, mime, name) of an attachment of this chat, never anything else."""
    row = chat_attachments.attachment(core.db, workspace_id, chat_id, attachment_id)
    if row is None:
        raise NotFoundError("This attachment")
    path = files.resolve(workspace_paths(core.layout, workspace_id).files, row["path"])
    if path is None:
        raise NotFoundError("This attachment")
    return path, row["mime"], row["name"]
