"""The agent in a workspace chat: every answer is Hermes's, in the chat's own conversation.

- A chat or DM is a Hermes conversation (db/hermes_chats.py). What the owner writes
  goes straight into the agos platform's queue (the agos-guard plugin's adapter
  takes it into the workspace's gateway); Hermes keeps it, answers it and keeps the
  answer. Messages sent one after another are one turn (Hermes's inbound text
  batching); a message while it works redirects it (Hermes's default busy_input_mode, interrupt).
  AGOS keeps no copy of what is said and no queue of its own.
- AGOS mirrors only the answer working now: the plugin reports the run's events
  into an in-memory `LiveTurn` the web reads (long-poll) to stream the text and the
  folded activity; at its end AGOS keeps only what Hermes has no place for (the
  approvals asked, its error, its cards).
- Stop, approvals (once or deny only), retry, undo and the edit of his last message
  are Hermes's own commands. An older message changed or deleted: Hermes has no
  edit in the middle of a conversation (its /undo N cuts every later turn too), so
  AGOS shows the change and tells the agent with his next message.
- A group chat is a Hermes room (actions/rooms.py): its lines are AGOS's room bridge.
- A key he pastes is masked by Hermes's own masking before any of this keeps or
  hands on his words (engine/owner_keys.py, ADR 0023): new messages, edits, room
  lines; the agent is told with a short note so it tells him where keys go.

The database is only touched on the event loop; HTTP runs in threads.

This module keeps posting the owner's message and starting its answer (`_kick`, looked
up here by api/hermes_bridge.py); the rest lives in actions/services/chat/ and is
re-exported here so every import path and patch target keeps working.
"""

from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.engine import attachments as files

# isort: off
from agos_core.actions.services.chat.lookup import (
    log as log,
    team_members as team_members,
    _chat as _chat,
)
from agos_core.actions.services.chat.live_turns import (
    _Live as _Live,
    _STATES as _STATES,
    _state as _state,
    _registry as _registry,
    live_snapshot as live_snapshot,
    AROUND_LOOK_S as AROUND_LOOK_S,
    PENDING_LOOK_S as PENDING_LOOK_S,
    live_moved as live_moved,
    wait_live as wait_live,
    pending as pending,
    _T as _T,
    in_thread as in_thread,
    _spawn as _spawn,
)
from agos_core.actions.services.chat.history import (
    edit_message as edit_message,
    delete_message as delete_message,
    edits_note as edits_note,
    rename as rename,
    set_model as set_model,
)
from agos_core.actions.services.chat.turns import (
    stop_turn as stop_turn,
    answer_approval as answer_approval,
    retry as retry,
    delete_chat as delete_chat,
    start_turn as start_turn,
    _start as _start,
    _stored as _stored,
    _transcribe as _transcribe,
    _gateway_up as _gateway_up,
    _finish as _finish,
    _answered as _answered,
    _close as _close,
    shutdown as shutdown,
    close_pre_hermes as close_pre_hermes,
    tick as tick,
)
from agos_core.actions.services.chat.messages import (
    send as send,
    _message as _message,
    _wake as _wake,
    save_owner_message as save_owner_message,
    attachment_file as attachment_file,
)
# isort: on


# ---- owner actions ------------------------------------------------------------


def post_message(
    core: Core,
    workspace_id: str,
    chat_id: int,
    body: str,
    attached: list[files.Incoming] | None = None,
    *,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int:
    """His message: into the chat's Hermes conversation (a room: its members). The
    id the web shows for it."""
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
    message_id = save_owner_message(
        core,
        workspace_id,
        chat_id,
        body,
        attached,
        reply_to=reply_to,
        reply_excerpt=reply_excerpt,
    )
    if core.engine is not None:
        _kick(core, workspace_id, chat_id)
    return message_id


def _kick(core: Core, workspace_id: str, chat_id: int) -> None:
    """A room's new lines go to its members now (on the running event loop)."""
    _spawn(core, start_turn(core, workspace_id, chat_id))
