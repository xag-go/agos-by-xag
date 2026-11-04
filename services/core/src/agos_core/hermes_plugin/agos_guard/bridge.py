"""AGOS bridge: a Telegram bot that runs on this profile's own Hermes gateway.

Hermes receives and answers the bot (everything Hermes does on Telegram); AGOS
keeps the same conversation in the workspace's chat. AGOS (its only writer) puts
`agos-bridge.json` in the profile home when the bot runs here:

  {"core": "http://127.0.0.1:8766", "workspace": "<id>", "key": "<bridge key>"}

- every message he sends the bot → the AGOS chat too, once Hermes admitted it (its
  post_gateway_admission hook: its allowlist and DM pairing let him in; a stranger
  is Hermes's to answer: its pairing code, which the owner approves in AGOS);
- a chat's Full access from AGOS → Hermes's own /yolo command in that
  conversation (a command item, run like one he typed);
- each answer starts → AGOS opens the turn in its chat, only to show it (what the
  agent is told is the profile's SOUL.md and Hermes's own session context; AGOS
  adds only the current time to a turn Hermes's gateway didn't stamp, clock.py);
- each answer ends (post_llm_call) → AGOS shows it; Hermes sends it as it is;
- an approval asked in an AGOS conversation → Hermes's own Telegram Allow / Deny
  card in that chat's Telegram place (AGOS says where), answered by Hermes;
- AGOS's own buttons (a Kanban card's Allow once / Deny, a token warning, a room
  member's command) → AGOS, once Hermes's own button check lets the presser in;
- AGOS's outbox (the replies of chats AGOS answers itself, its own cards) → sent
  here: replies with Hermes's own Telegram send, cards with their buttons;
- his message in a topic AGOS answers itself (a group's room): Hermes's 👀 stays
  until AGOS says that answer is out, then Hermes's own 👍 / 👎. A member's topic
  is Hermes's own: Hermes routes it to the member's profile (gateway.profile_routes)
  and answers and reacts there itself.
No bridge file = nothing here runs (the bot is AGOS's, or there is none).

This module is the bridge's compatibility facade: every name that lived here is
re-exported from the part that now owns it (bridge_core, bridge_text, bridge_sessions,
bridge_runner, bridge_delivery, bridge_stream, bridge_platform, bridge_menu,
bridge_approvals, bridge_hooks, bridge_tools, bridge_kanban, bridge_wiring), so
Hermes, the plugin's other modules and old callers keep working. It holds no feature
code: a name set here (callers and tests patch the bridge's names here) is passed on
to the part that owns it, and the parts never import this module.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

# The parts, in the order they load (each imports only parts before it).
_STEMS = (
    "bridge_core",
    "bridge_text",
    "bridge_sessions",
    "bridge_runner",
    "bridge_delivery",
    "bridge_stream",
    "bridge_platform",
    "bridge_menu",
    "bridge_approvals",
    "bridge_hooks",
    "bridge_tools",
    "bridge_kanban",
    "bridge_wiring",
)
# Rebound inside their part (`global`): read there, never copied here.
_LIVE = frozenset({"_ends_sending"})

if __package__:
    from . import (
        bridge_approvals,
        bridge_core,
        bridge_delivery,
        bridge_hooks,
        bridge_kanban,
        bridge_menu,
        bridge_platform,
        bridge_runner,
        bridge_sessions,
        bridge_stream,
        bridge_text,
        bridge_tools,
        bridge_wiring,
    )
    from .bridge_approvals import _allowed_users as _allowed_users
    from .bridge_approvals import _chat_of as _chat_of
    from .bridge_approvals import _watch_cards as _watch_cards
    from .bridge_approvals import post_approval_response as post_approval_response
    from .bridge_approvals import pre_approval_request as pre_approval_request
    from .bridge_core import _MEMBER_PATHS as _MEMBER_PATHS
    from .bridge_core import _PROCESS as _PROCESS
    from .bridge_core import AGOS_ADDRESS as AGOS_ADDRESS
    from .bridge_core import AGOS_BUTTONS as AGOS_BUTTONS
    from .bridge_core import AGOS_PLATFORM as AGOS_PLATFORM
    from .bridge_core import ANSWERED_IN_AGOS as ANSWERED_IN_AGOS
    from .bridge_core import BRIDGE_FILE as BRIDGE_FILE
    from .bridge_core import COMMAND_WINDOW_S as COMMAND_WINDOW_S
    from .bridge_core import FROM_AGOS as FROM_AGOS
    from .bridge_core import INBOUND_MAX as INBOUND_MAX
    from .bridge_core import KEEP_EYES_MAX as KEEP_EYES_MAX
    from .bridge_core import OLD_KEYS_FILE as OLD_KEYS_FILE
    from .bridge_core import SENT_FILE as SENT_FILE
    from .bridge_core import SENT_MAX as SENT_MAX
    from .bridge_core import _awaiting as _awaiting
    from .bridge_core import _beside as _beside
    from .bridge_core import _broken as _broken
    from .bridge_core import _busy as _busy
    from .bridge_core import _cache as _cache
    from .bridge_core import _cards as _cards
    from .bridge_core import _contract as _contract
    from .bridge_core import _ctx as _ctx
    from .bridge_core import _from_agos as _from_agos
    from .bridge_core import _guard as _guard
    from .bridge_core import _home as _home
    from .bridge_core import _inbound as _inbound
    from .bridge_core import _keep_eyes as _keep_eyes
    from .bridge_core import _keys as _keys
    from .bridge_core import _lock as _lock
    from .bridge_core import _missing as _missing
    from .bridge_core import _name_of as _name_of
    from .bridge_core import _phone as _phone
    from .bridge_core import _post as _post
    from .bridge_core import _process as _process
    from .bridge_core import _sent as _sent
    from .bridge_core import _shared as _shared
    from .bridge_core import _sources as _sources
    from .bridge_core import _taint as _taint
    from .bridge_core import _turn_keys as _turn_keys
    from .bridge_core import _turns as _turns
    from .bridge_core import _unread as _unread
    from .bridge_core import bridge as bridge
    from .bridge_core import log as log
    from .bridge_core import post as post
    from .bridge_delivery import BOT_WAIT_S as BOT_WAIT_S
    from .bridge_delivery import FINAL_REACTIONS as FINAL_REACTIONS
    from .bridge_delivery import UNSURE as UNSURE
    from .bridge_delivery import _close_card as _close_card
    from .bridge_delivery import _eyes_stay as _eyes_stay
    from .bridge_delivery import _in_gateway as _in_gateway
    from .bridge_delivery import _load_sent as _load_sent
    from .bridge_delivery import _mark_sent as _mark_sent
    from .bridge_delivery import _poll_forever as _poll_forever
    from .bridge_delivery import _poll_once as _poll_once
    from .bridge_delivery import _react as _react
    from .bridge_delivery import _run_on_bot as _run_on_bot
    from .bridge_delivery import _send_forever as _send_forever
    from .bridge_delivery import _send_item as _send_item
    from .bridge_delivery import _send_once as _send_once
    from .bridge_delivery import _serving as _serving
    from .bridge_delivery import _start_poller as _start_poller
    from .bridge_delivery import _start_sender as _start_sender
    from .bridge_delivery import _watch_reactions as _watch_reactions
    from .bridge_hooks import ENDS_RETRY_S as ENDS_RETRY_S
    from .bridge_hooks import LANGUAGE_NOTE as LANGUAGE_NOTE
    from .bridge_hooks import OWNER_RULES_SECTION as OWNER_RULES_SECTION
    from .bridge_hooks import OWNER_RULES_SECTIONS as OWNER_RULES_SECTIONS
    from .bridge_hooks import _agents as _agents
    from .bridge_hooks import _closed as _closed
    from .bridge_hooks import _end as _end
    from .bridge_hooks import _ends_backlog as _ends_backlog
    from .bridge_hooks import _ends_lock as _ends_lock
    from .bridge_hooks import _finish as _finish
    from .bridge_hooks import _here as _here
    from .bridge_hooks import _hide_keys as _hide_keys
    from .bridge_hooks import _keep_inbound as _keep_inbound
    from .bridge_hooks import _keys_module as _keys_module
    from .bridge_hooks import _keys_told as _keys_told
    from .bridge_hooks import _owner_rules as _owner_rules
    from .bridge_hooks import _room_turn as _room_turn
    from .bridge_hooks import _send_backlog as _send_backlog
    from .bridge_hooks import _stopped as _stopped
    from .bridge_hooks import _tell_surely as _tell_surely
    from .bridge_hooks import _turn_opens as _turn_opens
    from .bridge_hooks import agent_loop_stopped as agent_loop_stopped
    from .bridge_hooks import agent_of_session as agent_of_session
    from .bridge_hooks import on_session_end as on_session_end
    from .bridge_hooks import owner_rules_part as owner_rules_part
    from .bridge_hooks import owner_rules_section as owner_rules_section
    from .bridge_hooks import post_gateway_admission as post_gateway_admission
    from .bridge_hooks import post_llm_call as post_llm_call
    from .bridge_hooks import pre_gateway_dispatch as pre_gateway_dispatch
    from .bridge_hooks import pre_llm_call as pre_llm_call
    from .bridge_kanban import AUTOMATION_KEY as AUTOMATION_KEY
    from .bridge_kanban import NOTHING_DONE as NOTHING_DONE
    from .bridge_kanban import RUN_MARK as RUN_MARK
    from .bridge_kanban import _nothing_done as _nothing_done
    from .bridge_kanban import _quiet as _quiet
    from .bridge_kanban import _run_card as _run_card
    from .bridge_kanban import kanban_claimed as kanban_claimed
    from .bridge_kanban import kanban_completed as kanban_completed
    from .bridge_menu import MEMBERS_EVERY_S as MEMBERS_EVERY_S
    from .bridge_menu import _member_handler as _member_handler
    from .bridge_menu import _member_handles as _member_handles
    from .bridge_menu import _members as _members
    from .bridge_menu import _members_menu as _members_menu
    from .bridge_menu import _send_menu as _send_menu
    from .bridge_menu import _sync_members as _sync_members
    from .bridge_menu import _wanted_members as _wanted_members
    from .bridge_platform import AGOS_OWNER_ID as AGOS_OWNER_ID
    from .bridge_platform import PLATFORM_GROUPS as PLATFORM_GROUPS
    from .bridge_platform import PLATFORM_LOOK_S as PLATFORM_LOOK_S
    from .bridge_platform import _agos_adapter as _agos_adapter
    from .bridge_platform import _agos_arrived as _agos_arrived
    from .bridge_platform import _phone_card as _phone_card
    from .bridge_platform import _platform_alone as _platform_alone
    from .bridge_platform import _platform_group as _platform_group
    from .bridge_platform import _platform_items as _platform_items
    from .bridge_platform import _platform_join as _platform_join
    from .bridge_platform import _platform_leave as _platform_leave
    from .bridge_platform import _platform_on as _platform_on
    from .bridge_platform import _platform_seed as _platform_seed
    from .bridge_platform import _register_platform as _register_platform
    from .bridge_runner import MEDIA_KINDS as MEDIA_KINDS
    from .bridge_runner import _await_answer as _await_answer
    from .bridge_runner import _bind as _bind
    from .bridge_runner import _run_command as _run_command
    from .bridge_runner import _run_event as _run_event
    from .bridge_runner import _run_message as _run_message
    from .bridge_runner import _took_from_agos as _took_from_agos
    from .bridge_runner import sent_at as sent_at
    from .bridge_sessions import _address as _address
    from .bridge_sessions import _has_session as _has_session
    from .bridge_sessions import _key_for as _key_for
    from .bridge_sessions import _key_in_hermes as _key_in_hermes
    from .bridge_sessions import _remember_key as _remember_key
    from .bridge_sessions import _runner as _runner
    from .bridge_sessions import _session_key_of as _session_key_of
    from .bridge_sessions import _source_for as _source_for
    from .bridge_sessions import drop_old_keys_file as drop_old_keys_file
    from .bridge_stream import CARD_STEP as CARD_STEP
    from .bridge_stream import LIVE_DRAIN_S as LIVE_DRAIN_S
    from .bridge_stream import LIVE_EVERY_S as LIVE_EVERY_S
    from .bridge_stream import LIVE_QUEUE_MAX as LIVE_QUEUE_MAX
    from .bridge_stream import QUIET_AFTER_S as QUIET_AFTER_S
    from .bridge_stream import _agos_turn as _agos_turn
    from .bridge_stream import _card_record as _card_record
    from .bridge_stream import _card_tokens as _card_tokens
    from .bridge_stream import _card_told as _card_told
    from .bridge_stream import _card_used as _card_used
    from .bridge_stream import _command_answer as _command_answer
    from .bridge_stream import _ended as _ended
    from .bridge_stream import _live as _live
    from .bridge_stream import _live_add as _live_add
    from .bridge_stream import _live_out as _live_out
    from .bridge_stream import _live_send as _live_send
    from .bridge_stream import _live_send_forever as _live_send_forever
    from .bridge_stream import _live_sender as _live_sender
    from .bridge_stream import _live_sent as _live_sent
    from .bridge_stream import _member_names as _member_names
    from .bridge_stream import _plugin_root as _plugin_root
    from .bridge_stream import _preview as _preview
    from .bridge_stream import _watch_sends as _watch_sends
    from .bridge_stream import _with_member_name as _with_member_name
    from .bridge_stream import _yaml_loader as _yaml_loader
    from .bridge_stream import api_call_done as api_call_done
    from .bridge_stream import on_stream_delta as on_stream_delta
    from .bridge_stream import on_stream_end as on_stream_end
    from .bridge_stream import tool_done as tool_done
    from .bridge_stream import tool_started as tool_started
    from .bridge_stream import transform_llm_output as transform_llm_output
    from .bridge_text import _is_agos as _is_agos
    from .bridge_text import _is_telegram as _is_telegram
    from .bridge_text import _ours as _ours
    from .bridge_text import _text_of as _text_of
    from .bridge_text import _topic_name as _topic_name
    from .bridge_tools import _CARD_ID as _CARD_ID
    from .bridge_tools import _PARENTS_MAX as _PARENTS_MAX
    from .bridge_tools import ACTION_SCHEMA as ACTION_SCHEMA
    from .bridge_tools import CAPABILITY_SCHEMA as CAPABILITY_SCHEMA
    from .bridge_tools import GATE_UNREACHABLE as GATE_UNREACHABLE
    from .bridge_tools import TOOL_WAIT_S as TOOL_WAIT_S
    from .bridge_tools import _address_of_session as _address_of_session
    from .bridge_tools import _me as _me
    from .bridge_tools import _parents as _parents
    from .bridge_tools import _register_tools as _register_tools
    from .bridge_tools import _tool_post as _tool_post
    from .bridge_tools import action_tool as action_tool
    from .bridge_tools import capability_tool as capability_tool
    from .bridge_tools import gate_fields as gate_fields
    from .bridge_tools import owner_decides as owner_decides
    from .bridge_tools import run_card as run_card
    from .bridge_tools import subagent_started as subagent_started
    from .bridge_wiring import register as register
    from .bridge_wiring import telegram_buttons as telegram_buttons

    _PARTS: tuple[ModuleType, ...] = (
        bridge_core,
        bridge_text,
        bridge_sessions,
        bridge_runner,
        bridge_delivery,
        bridge_stream,
        bridge_platform,
        bridge_menu,
        bridge_approvals,
        bridge_hooks,
        bridge_tools,
        bridge_kanban,
        bridge_wiring,
    )
else:  # loaded by file (agos_guard._sibling): its parts the same way, in this order
    import importlib.util
    from pathlib import Path

    for _stem in _STEMS:
        _name = f"agos_guard_{_stem}"
        if _name not in sys.modules:
            _spec = importlib.util.spec_from_file_location(
                _name, Path(__file__).parent / (_stem + ".py")
            )
            if _spec is None or _spec.loader is None:
                raise ImportError(_stem)
            sys.modules[_name] = _module = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_module)
        globals().update(
            {
                k: v
                for k, v in vars(sys.modules[_name]).items()
                if not k.startswith("__") and k not in _LIVE
            }
        )
    _PARTS = tuple(sys.modules[f"agos_guard_{_stem}"] for _stem in _STEMS)

# name -> the part(s) it lives in: a name set here (Hermes's callers and the tests patch
# the bridge's names here) is set there too, so the parts, which never import this
# module, see it.
_MISSING = object()
_OWNERS: dict[str, tuple[ModuleType, ...]] = {
    name: tuple(part for part in _PARTS if vars(part).get(name, _MISSING) is value)
    for name, value in list(globals().items())
    if not name.startswith("__")
}


def __getattr__(name: str) -> Any:
    """A name rebound inside its part (_LIVE): read where it lives."""
    for part in _PARTS:
        if name in _LIVE and name in vars(part):
            return vars(part)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Facade(ModuleType):
    """This module, with its writes passed on to the part that owns the name."""

    def __setattr__(self, name: str, value: Any) -> None:
        for owner in _OWNERS.get(name, ()):
            setattr(owner, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Facade
