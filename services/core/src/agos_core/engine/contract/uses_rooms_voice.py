"""Hermes contract entries: group chats (agos_guard/rooms.py) and voice notes (stt_gemini.py).

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _KEYS,
    _ROOMS,
    _VOICE,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # ---- rooms: agos_guard/rooms.py (Hermes hosted rooms = AGOS group chats) ----
    _u("tui_gateway.methods_groups", "get_hosted_room_service", "function", "rooms", _ROOMS),
    _u(
        "gateway.hosted_rooms",
        "room_state",
        "function",
        "rooms",
        _ROOMS,
        pos=1,
        kw="room_id include_disbanded",
    ),
    _u("gateway.hosted_rooms", "HostedRoomError", "class", "rooms", _ROOMS),
    _u(
        "gateway.hosted_rooms",
        "disband_room",
        "function",
        "rooms",
        "a group whose members changed gets its new room",
        pos=1,
        kw="room_id expected_gateway_id expected_epoch",
    ),
    _u("gateway.hosted_rooms", "user_event_id", "function", "rooms", _ROOMS, pos=1),
    _u(
        "gateway.hosted_rooms",
        "rename_room",
        "function",
        "rooms",
        "a group's name is its room's: renamed in Hermes",
        pos=1,
        kw="room_id event_id name",
    ),
    _u(
        "gateway.hosted_rooms",
        "read_events",
        "function",
        "rooms",
        _ROOMS,
        pos=1,
        kw="room_id since_seq limit include_disbanded",
    ),
    _u("gateway.hosted_rooms", "default_db_path", "function", "rooms", _ROOMS),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.create_room",
        "method",
        "rooms",
        _ROOMS,
        kw="room_id name members",
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.stop_room",
        "method",
        "rooms",
        _ROOMS,
        pos=1,
        kw="cancel_id",
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.revoke_room_routes",
        "method",
        "rooms",
        _ROOMS,
        pos=1,
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.approve_room_task",
        "method",
        "rooms",
        _ROOMS,
        pos=1,
        kw="member_id task_id execution_generation choice request_id",
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.send",
        "method",
        "rooms",
        _ROOMS,
        kw="room_id event_id payload",
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.status",
        "method",
        "rooms",
        _ROOMS,
        pos=1,
    ),
    _u("tui_gateway.hosted_room_service", "HostedRoomService.db_path", "attr", "rooms", _ROOMS),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService.local_profiles",
        "method",
        "rooms",
        "moving a workspace to its own root: the roster wall",
    ),
    _u(
        "tui_gateway.hosted_room_service",
        "HostedRoomService",
        "class",
        "rooms",
        "moving a workspace to its own root: the roster wall",
    ),
    _u(
        "gateway.hosted_room_discussion",
        "validate_roster",
        "function",
        "rooms",
        "moving a workspace to its own root: the roster wall",
        pos=1,
        kw="local_profiles",
    ),
    # ---- voice: agos_guard/stt_gemini.py, engine/attachments.py ----
    _u("agent.transcription_provider", "TranscriptionProvider", "class", "voice", _VOICE),
    *[
        _u(
            "agent.transcription_provider",
            f"TranscriptionProvider.{m}",
            "override",
            "voice",
            _VOICE,
        )
        for m in ("name", "display_name", "is_available", "default_model", "list_models")
    ],
    _u(
        "agent.transcription_provider",
        "TranscriptionProvider.transcribe",
        "override",
        "voice",
        _VOICE,
        accepts="file_path model language",
        more=True,
    ),
    _u("hermes_cli.config", "get_env_value", "function", "voice", _VOICE + "; " + _KEYS, pos=1),
    _u(
        "tools.transcription_tools",
        "transcribe_audio",
        "function",
        "voice",
        "voice notes sent in AGOS",
        pos=1,
        kw="source",
    ),
)
