"""Group chats as Hermes hosted rooms, run by Hermes as it runs them (ADR 0020).

A group chat of a workspace on its own Hermes root IS a Hermes room ("Bot Mode
Group Chat") of that root: the Co-Founder (the root's default profile, handle
@cofounder) and the group's members (profiles under the root). Hermes runs the
discussion inside the workspace's one gateway; AGOS only bridges it:

- AGOS → room (the hermes_inbox, taken by the agos-guard plugin IN the gateway,
  which calls Hermes's in-process room service — no `hermes serve`):
  `room-sync` (create, or disband + recreate after a membership change),
  `room-send` (his message as he wrote it: Hermes decides who answers — the
  members he @mentions, or everyone; a member picked in Telegram's "/" menu is
  that @mention),
  `room-stop`, `room-approve` (Allow once / Deny for a member's command).
- room → AGOS (`/room-events`, the plugin reads the room log after AGOS's
  cursor): each member message becomes the chat's message under that member's
  name (the Co-Founder as Co-Founder), once (room_events), and reaches the group's
  Telegram topic through channel_outbox like every agent reply. When Hermes ends
  the discussion (settled, or its own limits) the chat's live answer closes; AGOS
  never adds a turn of its own.
- live work (`/room-live`, Hermes's on_room_member_activity hook) and approvals
  (Hermes's room status, reported with each `/room-next` and at once by
  `/room-approval` on Hermes's request.opened) show in the chat and Telegram;
  Stop is Hermes's own stop_room.

Isolation: a room's roster only ever names profiles of the workspace's own root,
and Hermes itself refuses any other (its roster validation accepts only
<root>/profiles/* and default).

This module is a compatibility facade: the code lives in actions/services/chat/ and
is re-exported here so every import path and patch target keeps working.
"""

from __future__ import annotations

# isort: off
from agos_core.db.connection import transaction as transaction
from agos_core.actions.services.chat.room_names import (
    log as log,
    ROOM_PREFIX as ROOM_PREFIX,
    COFOUNDER as COFOUNDER,
    THREAD as THREAD,
    RECAP_CHARS as RECAP_CHARS,
    MAX_MEMBERS as MAX_MEMBERS,
    ROOM_KINDS as ROOM_KINDS,
    VIA as VIA,
    SPEAKER_AGOS as SPEAKER_AGOS,
    on as on,
    is_room_chat as is_room_chat,
    address as address,
    chat_of as chat_of,
    chat_of_room as chat_of_room,
    roster as roster,
    room_name as room_name,
    hermes_event_id as hermes_event_id,
    mentions as mentions,
)
from agos_core.actions.services.chat.room_sync import (
    renamed as renamed,
    move_old_names as move_old_names,
    _queue as _queue,
    ensure_room as ensure_room,
    members_changed as members_changed,
    _wake as _wake,
    _seen as _seen,
    forget as forget,
)
from agos_core.actions.services.chat.room_turns import (
    hand_over as hand_over,
    _open_turn as _open_turn,
    _live as _live,
    stop as stop,
    take as take,
    done as done,
    events as events,
    live as live,
)
from agos_core.actions.services.chat.room_asks import (
    approval as approval,
    told as told,
    held_mark as held_mark,
    waiting_approval as waiting_approval,
    still_asks as still_asks,
    answer as answer,
)
# isort: on
