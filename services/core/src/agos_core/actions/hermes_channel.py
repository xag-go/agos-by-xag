"""Compatibility facade of the Channel service's Hermes side (Strangler Fig): every name
that lived here is re-exported from the module that now owns it, so old callers keep
working. New code imports the owning module; patch a name there, where it is used.

Channels served by Hermes's own gateway (the owner's rule: Hermes is the engine, AGOS
is the window onto it). The agos-guard plugin reports each turn to AGOS
(api/hermes_bridge.py), authenticated with the workspace's own bridge key.

In actions/services/channel/:
- gateway_platform: the gateway as a channel (bridge file and key, bot, token, restart);
- connections: the bot's live state (its @name, its lamp read from Hermes);
- hermes_addresses: Hermes addresses <-> AGOS chats and members, where a chat lives;
- gateway_places: Telegram groups, topics and AGOS's buttons there;
- gateway_models: model and effort picks told to Hermes;
- gateway_commands: Hermes's and AGOS's slash commands;
- gateway_messages: his messages in through the bot, and their reactions;
- gateway_mirror: the conversation mirrored between AGOS and Hermes;
- gateway_inbox: the plugin's inbox, live events, approvals in the channel;
- telegram_menu: the team's members in the bot's menu.
services/chat/gateway_turns: a gateway turn's lifecycle in the AGOS chat;
services/cofounder/agent_tools: AGOS's agent tools on a Hermes turn.

This module holds no code of its own and must not gain any.
"""

from __future__ import annotations

# The owner gate's names, re-exported here for their old callers (actions/owner_gate.py).
from agos_core.actions.owner_gate import GATE_NOT_ASKED as GATE_NOT_ASKED
from agos_core.actions.owner_gate import gate_refusal as gate_refusal
from agos_core.actions.owner_gate import tool_check as tool_check
from agos_core.actions.services.channel.connections import _telegram as _telegram
from agos_core.actions.services.channel.connections import bot_is as bot_is
from agos_core.actions.services.channel.connections import channel_ok_at as channel_ok_at
from agos_core.actions.services.channel.connections import channel_since as channel_since
from agos_core.actions.services.channel.connections import channel_state as channel_state
from agos_core.actions.services.channel.connections import telegram_state as telegram_state
from agos_core.actions.services.channel.gateway_commands import _OWN_NOTES as _OWN_NOTES
from agos_core.actions.services.channel.gateway_commands import AGOS_COMMANDS as AGOS_COMMANDS
from agos_core.actions.services.channel.gateway_commands import CONTROL_CHAT as CONTROL_CHAT
from agos_core.actions.services.channel.gateway_commands import OWN_COMMAND_KEY as OWN_COMMAND_KEY
from agos_core.actions.services.channel.gateway_commands import (
    _answered_by_hermes as _answered_by_hermes,
)
from agos_core.actions.services.channel.gateway_commands import (
    _own_command_note as _own_command_note,
)
from agos_core.actions.services.channel.gateway_commands import command_in as command_in
from agos_core.actions.services.channel.gateway_commands import command_out as command_out
from agos_core.actions.services.channel.gateway_commands import commands as commands
from agos_core.actions.services.channel.gateway_commands import (
    hand_over_command as hand_over_command,
)
from agos_core.actions.services.channel.gateway_commands import (
    is_hermes_command as is_hermes_command,
)
from agos_core.actions.services.channel.gateway_commands import mark_own_command as mark_own_command
from agos_core.actions.services.channel.gateway_commands import own_command as own_command
from agos_core.actions.services.channel.gateway_commands import read_ahead as read_ahead
from agos_core.actions.services.channel.gateway_commands import reload_mcp as reload_mcp
from agos_core.actions.services.channel.gateway_inbox import LIVE_EVENTS as LIVE_EVENTS
from agos_core.actions.services.channel.gateway_inbox import _live_hermes_turn as _live_hermes_turn
from agos_core.actions.services.channel.gateway_inbox import _said as _said
from agos_core.actions.services.channel.gateway_inbox import _topic_of as _topic_of
from agos_core.actions.services.channel.gateway_inbox import answer_approval as answer_approval
from agos_core.actions.services.channel.gateway_inbox import approval_answered as approval_answered
from agos_core.actions.services.channel.gateway_inbox import approval_asked as approval_asked
from agos_core.actions.services.channel.gateway_inbox import channel_prompt as channel_prompt
from agos_core.actions.services.channel.gateway_inbox import inbox_done as inbox_done
from agos_core.actions.services.channel.gateway_inbox import live_events as live_events
from agos_core.actions.services.channel.gateway_inbox import take_inbox as take_inbox
from agos_core.actions.services.channel.gateway_inbox import tidy_inbox as tidy_inbox
from agos_core.actions.services.channel.gateway_messages import REACTION_CLAIM_S as REACTION_CLAIM_S
from agos_core.actions.services.channel.gateway_messages import (
    REACTION_GIVE_UP_H as REACTION_GIVE_UP_H,
)
from agos_core.actions.services.channel.gateway_messages import (
    REACTION_SETTLE_S as REACTION_SETTLE_S,
)
from agos_core.actions.services.channel.gateway_messages import (
    _hold_for_check_in as _hold_for_check_in,
)
from agos_core.actions.services.channel.gateway_messages import _keep_eyes as _keep_eyes
from agos_core.actions.services.channel.gateway_messages import (
    _reaction_outcome as _reaction_outcome,
)
from agos_core.actions.services.channel.gateway_messages import _telegram_files as _telegram_files
from agos_core.actions.services.channel.gateway_messages import incoming as incoming
from agos_core.actions.services.channel.gateway_messages import keeps_eyes as keeps_eyes
from agos_core.actions.services.channel.gateway_messages import reaction_done as reaction_done
from agos_core.actions.services.channel.gateway_messages import reactions_open as reactions_open
from agos_core.actions.services.channel.gateway_messages import reactions_ready as reactions_ready
from agos_core.actions.services.channel.gateway_messages import (
    waits_for_check_in as waits_for_check_in,
)
from agos_core.actions.services.channel.gateway_mirror import _recent_answers as _recent_answers
from agos_core.actions.services.channel.gateway_mirror import _tell_name as _tell_name
from agos_core.actions.services.channel.gateway_mirror import hand_over as hand_over
from agos_core.actions.services.channel.gateway_mirror import platform_said as platform_said
from agos_core.actions.services.channel.gateway_mirror import set_media as set_media
from agos_core.actions.services.channel.gateway_models import EFFORT_KEY as EFFORT_KEY
from agos_core.actions.services.channel.gateway_models import MOVE_KEY as MOVE_KEY
from agos_core.actions.services.channel.gateway_models import OLD_MODEL_KEY as OLD_MODEL_KEY
from agos_core.actions.services.channel.gateway_models import _gateway_mark as _gateway_mark
from agos_core.actions.services.channel.gateway_models import _mark as _mark
from agos_core.actions.services.channel.gateway_models import _own_model_switch as _own_model_switch
from agos_core.actions.services.channel.gateway_models import effort_note as effort_note
from agos_core.actions.services.channel.gateway_models import model_command as model_command
from agos_core.actions.services.channel.gateway_models import move_old_models as move_old_models
from agos_core.actions.services.channel.gateway_models import tell_model as tell_model
from agos_core.actions.services.channel.gateway_places import GROUPS_KEY as GROUPS_KEY
from agos_core.actions.services.channel.gateway_places import TEAM_GROUP_KEY as TEAM_GROUP_KEY
from agos_core.actions.services.channel.gateway_places import _alias_names as _alias_names
from agos_core.actions.services.channel.gateway_places import _groups as _groups
from agos_core.actions.services.channel.gateway_places import _hermes_groups as _hermes_groups
from agos_core.actions.services.channel.gateway_places import _move_old_names as _move_old_names
from agos_core.actions.services.channel.gateway_places import _seen_group as _seen_group
from agos_core.actions.services.channel.gateway_places import _write_names as _write_names
from agos_core.actions.services.channel.gateway_places import callback as callback
from agos_core.actions.services.channel.gateway_places import move_group_names as move_group_names
from agos_core.actions.services.channel.gateway_places import place_names as place_names
from agos_core.actions.services.channel.gateway_places import places as places
from agos_core.actions.services.channel.gateway_places import set_team_group as set_team_group
from agos_core.actions.services.channel.gateway_places import team_groups as team_groups
from agos_core.actions.services.channel.gateway_places import topic_for as topic_for
from agos_core.actions.services.channel.gateway_platform import _IN_TURN as _IN_TURN
from agos_core.actions.services.channel.gateway_platform import _OLD_REACTIONS as _OLD_REACTIONS
from agos_core.actions.services.channel.gateway_platform import AGOS_OWNER as AGOS_OWNER
from agos_core.actions.services.channel.gateway_platform import BOT_SWITCH as BOT_SWITCH
from agos_core.actions.services.channel.gateway_platform import BRIDGE_FILE as BRIDGE_FILE
from agos_core.actions.services.channel.gateway_platform import ENGINE_HERMES as ENGINE_HERMES
from agos_core.actions.services.channel.gateway_platform import ENV_PREFIX as ENV_PREFIX
from agos_core.actions.services.channel.gateway_platform import MOVE_OFF as MOVE_OFF
from agos_core.actions.services.channel.gateway_platform import REACTIONS as REACTIONS
from agos_core.actions.services.channel.gateway_platform import STALE_AFTER_S as STALE_AFTER_S
from agos_core.actions.services.channel.gateway_platform import TOKEN_LINE as TOKEN_LINE
from agos_core.actions.services.channel.gateway_platform import TURN_WAIT_S as TURN_WAIT_S
from agos_core.actions.services.channel.gateway_platform import _answers_running as _answers_running
from agos_core.actions.services.channel.gateway_platform import _bot_on_now as _bot_on_now
from agos_core.actions.services.channel.gateway_platform import _bot_seen as _bot_seen
from agos_core.actions.services.channel.gateway_platform import (
    _move_old_reactions as _move_old_reactions,
)
from agos_core.actions.services.channel.gateway_platform import _write_bridge as _write_bridge
from agos_core.actions.services.channel.gateway_platform import bot_on as bot_on
from agos_core.actions.services.channel.gateway_platform import bot_token as bot_token
from agos_core.actions.services.channel.gateway_platform import bridge_key as bridge_key
from agos_core.actions.services.channel.gateway_platform import cofounder_chat as cofounder_chat
from agos_core.actions.services.channel.gateway_platform import connection as connection
from agos_core.actions.services.channel.gateway_platform import inside_turn as inside_turn
from agos_core.actions.services.channel.gateway_platform import key_ok as key_ok
from agos_core.actions.services.channel.gateway_platform import log as log
from agos_core.actions.services.channel.gateway_platform import (
    move_old_switches as move_old_switches,
)
from agos_core.actions.services.channel.gateway_platform import prepare_profile as prepare_profile
from agos_core.actions.services.channel.gateway_platform import profile_env as profile_env
from agos_core.actions.services.channel.gateway_platform import reactions_on as reactions_on
from agos_core.actions.services.channel.gateway_platform import refresh_bridge as refresh_bridge
from agos_core.actions.services.channel.gateway_platform import restart_gateway as restart_gateway
from agos_core.actions.services.channel.gateway_platform import set_bot_on as set_bot_on
from agos_core.actions.services.channel.gateway_platform import set_reactions as set_reactions
from agos_core.actions.services.channel.gateway_platform import token_held_by as token_held_by
from agos_core.actions.services.channel.gateway_platform import write_token as write_token
from agos_core.actions.services.channel.hermes_addresses import _AGOS_ADDRESS as _AGOS_ADDRESS
from agos_core.actions.services.channel.hermes_addresses import AGOS_PREFIX as AGOS_PREFIX
from agos_core.actions.services.channel.hermes_addresses import AGOS_TOOL_RULE as AGOS_TOOL_RULE
from agos_core.actions.services.channel.hermes_addresses import MIRROR_MARK as MIRROR_MARK
from agos_core.actions.services.channel.hermes_addresses import _dm_member as _dm_member
from agos_core.actions.services.channel.hermes_addresses import _platform_chat as _platform_chat
from agos_core.actions.services.channel.hermes_addresses import _session_of as _session_of
from agos_core.actions.services.channel.hermes_addresses import _target as _target
from agos_core.actions.services.channel.hermes_addresses import address_of as address_of
from agos_core.actions.services.channel.hermes_addresses import chat_at as chat_at
from agos_core.actions.services.channel.hermes_addresses import chat_of_address as chat_of_address
from agos_core.actions.services.channel.hermes_addresses import chat_on_hermes as chat_on_hermes
from agos_core.actions.services.channel.hermes_addresses import owner_member as owner_member
from agos_core.actions.services.channel.hermes_addresses import split_agos as split_agos
from agos_core.actions.services.channel.telegram_menu import MENU_FIRST as MENU_FIRST
from agos_core.actions.services.channel.telegram_menu import NEXT_TO as NEXT_TO
from agos_core.actions.services.channel.telegram_menu import NEXT_TO_S as NEXT_TO_S
from agos_core.actions.services.channel.telegram_menu import choose_member as choose_member
from agos_core.actions.services.channel.telegram_menu import chosen_member as chosen_member
from agos_core.actions.services.channel.telegram_menu import command_name as command_name
from agos_core.actions.services.channel.telegram_menu import member_command as member_command
from agos_core.actions.services.channel.telegram_menu import member_commands as member_commands
from agos_core.actions.services.channel.telegram_menu import member_of_command as member_of_command
from agos_core.actions.services.channel.telegram_menu import sync_member_menus as sync_member_menus
from agos_core.actions.services.chat.gateway_turns import _IDLE_SEEN as _IDLE_SEEN
from agos_core.actions.services.chat.gateway_turns import ANSWERED as ANSWERED
from agos_core.actions.services.chat.gateway_turns import NO_AGENT as NO_AGENT
from agos_core.actions.services.chat.gateway_turns import SETTLED_S as SETTLED_S
from agos_core.actions.services.chat.gateway_turns import STOPPED as STOPPED
from agos_core.actions.services.chat.gateway_turns import STOPPED_BY_HIM as STOPPED_BY_HIM
from agos_core.actions.services.chat.gateway_turns import UNANSWERED_S as UNANSWERED_S
from agos_core.actions.services.chat.gateway_turns import WHY as WHY
from agos_core.actions.services.chat.gateway_turns import _answer_kept as _answer_kept
from agos_core.actions.services.chat.gateway_turns import _answers_nothing as _answers_nothing
from agos_core.actions.services.chat.gateway_turns import _asked_up_to as _asked_up_to
from agos_core.actions.services.chat.gateway_turns import _close_unanswered as _close_unanswered
from agos_core.actions.services.chat.gateway_turns import _dm_speaker as _dm_speaker
from agos_core.actions.services.chat.gateway_turns import _open_turn as _open_turn
from agos_core.actions.services.chat.gateway_turns import _refresh_view_soon as _refresh_view_soon
from agos_core.actions.services.chat.gateway_turns import _views as _views
from agos_core.actions.services.chat.gateway_turns import _views_lock as _views_lock
from agos_core.actions.services.chat.gateway_turns import close_stale as close_stale
from agos_core.actions.services.chat.gateway_turns import close_unanswered as close_unanswered
from agos_core.actions.services.chat.gateway_turns import exit_status as exit_status
from agos_core.actions.services.chat.gateway_turns import open_turn as open_turn
from agos_core.actions.services.chat.gateway_turns import turn_ended as turn_ended
from agos_core.actions.services.chat.gateway_turns import turn_finish as turn_finish
from agos_core.actions.services.chat.gateway_turns import turn_start as turn_start
from agos_core.actions.services.chat.gateway_turns import turn_stopped as turn_stopped
from agos_core.actions.services.cofounder.agent_tools import RUN_JOIN_S as RUN_JOIN_S
from agos_core.actions.services.cofounder.agent_tools import RUN_MARK as RUN_MARK
from agos_core.actions.services.cofounder.agent_tools import RUN_PREFIXES as RUN_PREFIXES
from agos_core.actions.services.cofounder.agent_tools import _chat_turn as _chat_turn
from agos_core.actions.services.cofounder.agent_tools import _run_title as _run_title
from agos_core.actions.services.cofounder.agent_tools import _run_turn as _run_turn
from agos_core.actions.services.cofounder.agent_tools import ask_capability as ask_capability
from agos_core.actions.services.cofounder.agent_tools import clarify_asked as clarify_asked
from agos_core.actions.services.cofounder.agent_tools import is_run as is_run
from agos_core.actions.services.cofounder.agent_tools import run_actions as run_actions
