"""Changing what was said: editing or deleting a message, the note that tells the agent, renaming a chat, its model.
Must not: start a turn.

Split out of agos_core.actions.chat (which re-exports it); behaviour unchanged.
"""

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.services.chat.lookup import _chat
from agos_core.context import Core
from agos_core.db import chat_attachments, chat_edits, hermes_inbox
from agos_core.db import chats as repo
from agos_core.db import hermes_chats as hc
from agos_core.db.connection import transaction
from agos_core.engine import owner_keys

__all__ = [
    "delete_message",
    "edit_message",
    "edits_note",
    "rename",
    "set_model",
]


def edit_message(
    core: Core,
    workspace_id: str,
    chat_id: int,
    message_id: int,
    body: str,
    *,
    reanswer: bool = False,
) -> None:
    """The owner changes his message. Still in the queue: Hermes gets the new text.
    His last message, with `reanswer`: Hermes's own /undo takes the old exchange back
    and the new text is asked. Otherwise (an older message, or no new answer
    wanted): the chat shows the new text and the agent is told what changed with
    his next message (Hermes keeps no edit in the middle of a conversation; its
    /undo N would cut every later message too). With `reanswer` the agent answers
    the new version now."""
    text = body.strip()
    if not text:
        raise ActionError("A message can't be empty. Delete it instead.")
    text = owner_keys.hide(text)  # the new version is his words too
    row = _chat(core, workspace_id, chat_id)
    if not repo.is_hermes(row):
        _edit_line(core, workspace_id, chat_id, message_id, text)
        return
    if message_id >= hc.PENDING_BASE:
        if not _edit_queued(core, workspace_id, message_id - hc.PENDING_BASE, text):
            raise ActionError(
                "The agent already has this message. Wait a moment, then edit it.", status=409
            )
        return
    if message_id >= hc.ROW_BASE:
        _edit_line(core, workspace_id, chat_id, message_id - hc.ROW_BASE, text)
        return
    if reanswer and repo.live_turn(core.db, chat_id) is not None:
        raise ActionError(
            "The agent is answering right now. Stop it or wait, then try again.", status=409
        )
    chat = chat_view.get_chat(core.db, workspace_id, chat_id)
    before = next(
        (m for m in (chat.messages if chat else []) if m.id == message_id and m.from_ == "owner"),
        None,
    )
    if chat is None or before is None:
        raise NotFoundError("This message")
    answered = any(t.asked_up_to >= message_id and t.status == "completed" for t in chat.turns)
    again = reanswer and answered
    live = repo.live_turn(core.db, chat_id)
    if again and live is not None:
        raise ActionError(
            "The agent is answering right now. Stop it or wait, then try again.", status=409
        )
    changed = before.body.strip() != text
    if not changed and not again:
        return
    from agos_core.actions import hermes_channel

    last = max((m.id for m in chat.messages if m.from_ == "owner"), default=0)
    if again and message_id == last:
        with transaction(core.db):
            if hermes_channel.own_command(core, workspace_id, chat_id, "/undo"):
                # Hermes forgot the old exchange: the new text is simply asked.
                hermes_channel.hand_over(core, workspace_id, chat_id, text)
                return
    with transaction(core.db):
        if changed:
            chat_edits.record_hermes(
                core.db, chat_id, message_id, before.body, text, told=again, replace=True
            )
        if again:
            note = (
                "(The owner edited an earlier message and wants a new answer to it. "
                f"It was:)\n> {before.body[:1500]}\n(It now says — answer this version:)"
                if changed
                else "(The owner asks you to answer this earlier message again:)"
            )
            hermes_channel.hand_over(core, workspace_id, chat_id, f"{note}\n{text}")


def _edit_queued(core: Core, workspace_id: str, item_id: int, text: str) -> bool:
    """A message Hermes hasn't taken yet: the queue item carries the new text."""
    from agos_core.db.rows import dump_json, load_json

    row = hermes_inbox.waiting_item(core.db, workspace_id, item_id)
    if row is None:
        return False
    new = text
    if row["kind"] == "reply":
        new = dump_json({**(load_json(row["text"]) or {}), "text": text})
    with transaction(core.db):
        return hermes_inbox.set_waiting_text(core.db, item_id, new)


def _edit_line(core: Core, workspace_id: str, chat_id: int, row_id: int, text: str) -> None:
    """One of AGOS's own lines (a room's, a /command): changed in place. A room's
    line already handed over is told to its members with his next message."""
    before = repo.owner_line(core.db, chat_id, row_id)
    if before is None:
        raise NotFoundError("This message")
    if before == text:
        return
    answered = row_id <= repo.answered_up_to(core.db, chat_id)
    with transaction(core.db):
        if not repo.edit_owner_message(core.db, workspace_id, chat_id, row_id, text):
            raise NotFoundError("This message")
        if answered:
            chat_edits.record(core.db, chat_id, row_id, before, text)


def delete_message(core: Core, workspace_id: str, chat_id: int, message_id: int) -> None:
    """Gone from the chat, and from what the agent works from: his last exchange with
    Hermes's own /undo; an older message is told to the agent as deleted (Hermes
    can't take a message out of the middle of a conversation)."""
    row = _chat(core, workspace_id, chat_id)
    if not repo.is_hermes(row):
        if not repo.delete_message(core.db, workspace_id, chat_id, message_id):
            raise NotFoundError("This message")
        return
    if message_id >= hc.PENDING_BASE:
        item = message_id - hc.PENDING_BASE
        with transaction(core.db):
            gone = hermes_inbox.delete_waiting(core.db, workspace_id, item)
            if gone:
                chat_attachments.drop_of_item(core.db, item)
        if not gone:
            raise ActionError(
                "The agent already has this message. Wait a moment, then delete it.", status=409
            )
        return
    if message_id >= hc.ROW_BASE:
        with transaction(core.db):
            if not repo.delete_message(core.db, workspace_id, chat_id, message_id - hc.ROW_BASE):
                raise NotFoundError("This message")
        return
    chat = chat_view.get_chat(core.db, workspace_id, chat_id)
    found = next((m for m in (chat.messages if chat else []) if m.id == message_id), None)
    if chat is None or found is None:
        raise NotFoundError("This message")
    from agos_core.actions import hermes_channel

    owner_ids = [m.id for m in chat.messages if m.from_ == "owner"]
    last = max(owner_ids, default=0)
    last_turn = chat.turns[-1] if chat.turns else None
    answered = last_turn is not None and last_turn.asked_up_to >= last and last_turn.reply_id
    last_exchange = bool(last) and message_id >= last
    with transaction(core.db):
        if (
            last_exchange
            and answered
            and repo.live_turn(core.db, chat_id) is None
            and hermes_channel.own_command(core, workspace_id, chat_id, "/undo")
        ):
            return  # Hermes drops its last exchange (his message and the answer)
        # His own: the agent is told with his next message.
        chat_edits.record_hermes(
            core.db, chat_id, message_id, found.body, "", told=found.from_ != "owner"
        )


def edits_note(core: Core, chat_id: int) -> str:
    """Changes the owner made to messages already answered, told once."""
    rows = chat_edits.take_untold(core.db, chat_id)
    if not rows:
        return ""
    parts = [
        f"(The owner changed an earlier message. It was:)\n> {r['before'][:1500]}\n"
        f"(It now says — follow this version:)\n> {r['after'][:3000]}"
        if r["after"]
        else f"(The owner deleted an earlier message; leave it aside. It was:)\n"
        f"> {r['before'][:1500]}"
        for r in rows
    ]
    return "\n\n".join(parts)


# ---- the chat's name and model: Hermes's own /title and /model --------------------------


def _rename_member(core: Core, workspace_id: str, row: Any, title: str) -> None:
    """A DM's new name is its member's Hermes display name (Hermes's own
    write_profile_meta, engine.set_display_name); the Co-Founder's chat is always
    "Co-Founder"."""
    from agos_core.actions import team
    from agos_core.engine import profile_meta
    from agos_core.engine.hermes import EngineError

    agent = str(row["agent"] or "")
    if not agent:
        raise ActionError("The Co-Founder's chat keeps its name.")
    where = team.home(core, workspace_id, agent) if core.engine is not None else None
    if where is None or not (where / "config.yaml").is_file():
        raise ActionError("This agent has no Hermes profile to hold the name.", 409)
    name = title.strip()[: profile_meta.TITLE_MAX]
    if not name:
        raise ActionError("Give it a name.")
    assert core.engine is not None
    try:
        with profile_meta.locked(where):
            if profile_meta.display_name(profile_meta.read(where)) != name:
                core.engine.set_display_name(where, name)
    except (EngineError, OSError) as error:
        raise ActionError(f"Hermes didn't take the name: {error}", 502) from error


def rename(core: Core, workspace_id: str, chat_id: int, title: str) -> None:
    """A chat's name is its Hermes session's title (Hermes's own /title in its
    conversation), a group's its Hermes room's name (AGOS holds it until the room
    does); a DM's is its member's Hermes display name, so renaming it renames the
    member there (no AGOS copy: db/chats.py dm_title)."""
    row = _chat(core, workspace_id, chat_id)
    if row["kind"] == "dm":
        _rename_member(core, workspace_id, row, title)
        return
    if row["kind"] != "chat":
        with transaction(core.db):
            repo.update_chat(core.db, workspace_id, chat_id, title=title)
            if row["kind"] == "group":
                from agos_core.actions import rooms

                rooms.renamed(core, workspace_id, chat_id)
        return
    if repo.chat_title(core.db, row) == title:
        return
    from agos_core.actions import hermes_channel

    # Hermes decides if the name is free (its title rules); its refusal shows in the chat.
    with transaction(core.db):
        if hermes_channel.own_command(core, workspace_id, chat_id, f"/title {title}"):
            return
    # A Telegram conversation (no AGOS command there): Hermes's own `sessions rename`.
    where = repo.where_of(core.db, row)
    store = hc.store()
    sessions = store.sessions(where) if store is not None and where is not None else []
    if not sessions or core.engine is None:
        with transaction(core.db):  # nothing in Hermes yet: kept until it has a session
            repo.update_chat(core.db, workspace_id, chat_id, title=title)
        return
    from agos_core.engine.hermes import EngineError

    try:
        core.engine.rename_session(workspace_id, sessions[-1].id, title)
    except EngineError as error:
        raise ActionError(f"Hermes didn't take the name: {error}") from error


def set_model(core: Core, workspace_id: str, chat_id: int, model: Any) -> None:
    """The chat's model is Hermes's own /model for its conversation."""
    from agos_core.actions import hermes_channel

    _chat(core, workspace_id, chat_id)
    with transaction(core.db):
        hermes_channel.tell_model(core, workspace_id, chat_id, model, force=True)
