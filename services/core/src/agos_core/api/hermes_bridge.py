"""The workspace's Hermes (its agos-guard plugin) → AGOS, for a Telegram bot that
runs on Hermes's own gateway (actions/hermes_channel.py).

Not behind the web app's internal token: each call carries the workspace's own
bridge key, which only that workspace's profile has (agos-bridge.json, 0600).

Compatibility facade: the routes live in one module per caller group, each with its
own router (bridge_turns, bridge_waits, bridge_tools, bridge_telegram,
bridge_approvals, bridge_rooms, bridge_upkeep; the key check in bridge_access). This
module keeps the one `router` app.py mounts and re-exports every old name; it holds
no code of its own. Patch a name in the module that owns it.
"""

from fastapi import APIRouter

from agos_core.api import (
    bridge_approvals,
    bridge_rooms,
    bridge_telegram,
    bridge_tools,
    bridge_turns,
    bridge_upkeep,
    bridge_waits,
)
from agos_core.api.bridge_access import ADDRESS as ADDRESS
from agos_core.api.bridge_access import Auth as Auth
from agos_core.api.bridge_access import Taker as Taker
from agos_core.api.bridge_access import _checked as _checked
from agos_core.api.bridge_approvals import Answered as Answered
from agos_core.api.bridge_approvals import Approval as Approval
from agos_core.api.bridge_approvals import approval as approval
from agos_core.api.bridge_approvals import approval_done as approval_done
from agos_core.api.bridge_rooms import ROOM_ID as ROOM_ID
from agos_core.api.bridge_rooms import ROOM_WAIT_MAX_S as ROOM_WAIT_MAX_S
from agos_core.api.bridge_rooms import ROOM_WAIT_S as ROOM_WAIT_S
from agos_core.api.bridge_rooms import RoomApproval as RoomApproval
from agos_core.api.bridge_rooms import RoomDone as RoomDone
from agos_core.api.bridge_rooms import RoomEvents as RoomEvents
from agos_core.api.bridge_rooms import RoomHeld as RoomHeld
from agos_core.api.bridge_rooms import RoomHeldNow as RoomHeldNow
from agos_core.api.bridge_rooms import RoomLive as RoomLive
from agos_core.api.bridge_rooms import RoomNext as RoomNext
from agos_core.api.bridge_rooms import _rooms_of_workspace as _rooms_of_workspace
from agos_core.api.bridge_rooms import room_approval as room_approval
from agos_core.api.bridge_rooms import room_done as room_done
from agos_core.api.bridge_rooms import room_events as room_events
from agos_core.api.bridge_rooms import room_held as room_held
from agos_core.api.bridge_rooms import room_live as room_live
from agos_core.api.bridge_rooms import room_next as room_next
from agos_core.api.bridge_telegram import Callback as Callback
from agos_core.api.bridge_telegram import CommandIn as CommandIn
from agos_core.api.bridge_telegram import CommandList as CommandList
from agos_core.api.bridge_telegram import CommandOut as CommandOut
from agos_core.api.bridge_telegram import Incoming as Incoming
from agos_core.api.bridge_telegram import MemberCommandIn as MemberCommandIn
from agos_core.api.bridge_telegram import _handled as _handled
from agos_core.api.bridge_telegram import callback as callback
from agos_core.api.bridge_telegram import command_in as command_in
from agos_core.api.bridge_telegram import command_out as command_out
from agos_core.api.bridge_telegram import incoming as incoming
from agos_core.api.bridge_telegram import member_command as member_command
from agos_core.api.bridge_telegram import telegram_connected as telegram_connected
from agos_core.api.bridge_tools import AskOwner as AskOwner
from agos_core.api.bridge_tools import CardCommentCall as CardCommentCall
from agos_core.api.bridge_tools import CardDocumentCall as CardDocumentCall
from agos_core.api.bridge_tools import CardTokensTold as CardTokensTold
from agos_core.api.bridge_tools import Clarify as Clarify
from agos_core.api.bridge_tools import GoalsCall as GoalsCall
from agos_core.api.bridge_tools import KanbanAsk as KanbanAsk
from agos_core.api.bridge_tools import KanbanBlocked as KanbanBlocked
from agos_core.api.bridge_tools import LabelCall as LabelCall
from agos_core.api.bridge_tools import PipelineEvent as PipelineEvent
from agos_core.api.bridge_tools import Propose as Propose
from agos_core.api.bridge_tools import ReviewCall as ReviewCall
from agos_core.api.bridge_tools import ReviewCheck as ReviewCheck
from agos_core.api.bridge_tools import SearchCall as SearchCall
from agos_core.api.bridge_tools import ServiceCall as ServiceCall
from agos_core.api.bridge_tools import SkillReviewCall as SkillReviewCall
from agos_core.api.bridge_tools import SkillTest as SkillTest
from agos_core.api.bridge_tools import StatusCardCall as StatusCardCall
from agos_core.api.bridge_tools import WatchdogObserve as WatchdogObserve
from agos_core.api.bridge_tools import _change_of as _change_of
from agos_core.api.bridge_tools import ask_owner as ask_owner
from agos_core.api.bridge_tools import card_comment as card_comment
from agos_core.api.bridge_tools import card_document as card_document
from agos_core.api.bridge_tools import card_tokens_told as card_tokens_told
from agos_core.api.bridge_tools import clarify as clarify
from agos_core.api.bridge_tools import goals_call as goals_call
from agos_core.api.bridge_tools import kanban_ask as kanban_ask
from agos_core.api.bridge_tools import kanban_blocked as kanban_blocked
from agos_core.api.bridge_tools import label_call as label_call
from agos_core.api.bridge_tools import pipeline_event as pipeline_event
from agos_core.api.bridge_tools import pipeline_sweep as pipeline_sweep
from agos_core.api.bridge_tools import propose as propose
from agos_core.api.bridge_tools import review_call as review_call
from agos_core.api.bridge_tools import review_check as review_check
from agos_core.api.bridge_tools import search_call as search_call
from agos_core.api.bridge_tools import service_call as service_call
from agos_core.api.bridge_tools import skill_review_call as skill_review_call
from agos_core.api.bridge_tools import status_card_call as status_card_call
from agos_core.api.bridge_tools import watchdog_observe as watchdog_observe
from agos_core.api.bridge_turns import MEMBER_HOLD_S as MEMBER_HOLD_S
from agos_core.api.bridge_turns import WAIT_S as WAIT_S
from agos_core.api.bridge_turns import Done as Done
from agos_core.api.bridge_turns import LiveEvents as LiveEvents
from agos_core.api.bridge_turns import PlatformSaid as PlatformSaid
from agos_core.api.bridge_turns import TurnEnd as TurnEnd
from agos_core.api.bridge_turns import TurnFinish as TurnFinish
from agos_core.api.bridge_turns import TurnStart as TurnStart
from agos_core.api.bridge_turns import TurnStop as TurnStop
from agos_core.api.bridge_turns import done as done
from agos_core.api.bridge_turns import events as events
from agos_core.api.bridge_turns import next_items as next_items
from agos_core.api.bridge_turns import platform_next as platform_next
from agos_core.api.bridge_turns import platform_send as platform_send
from agos_core.api.bridge_turns import turn_end as turn_end
from agos_core.api.bridge_turns import turn_finish as turn_finish
from agos_core.api.bridge_turns import turn_start as turn_start
from agos_core.api.bridge_turns import turn_stop as turn_stop
from agos_core.api.bridge_upkeep import ContractBroken as ContractBroken
from agos_core.api.bridge_upkeep import contract_broken as contract_broken
from agos_core.api.bridge_upkeep import digest_now as digest_now
from agos_core.api.bridge_upkeep import owner_rules_section as owner_rules_section
from agos_core.api.bridge_waits import OUTBOX_WAIT_S as OUTBOX_WAIT_S
from agos_core.api.bridge_waits import REACTION_LOOK_S as REACTION_LOOK_S
from agos_core.api.bridge_waits import OutboxDone as OutboxDone
from agos_core.api.bridge_waits import T as T
from agos_core.api.bridge_waits import outbox as outbox
from agos_core.api.bridge_waits import outbox_done as outbox_done
from agos_core.api.bridge_waits import waited as waited

router = APIRouter()
for _part in (
    bridge_turns,
    bridge_waits,
    bridge_tools,
    bridge_telegram,
    bridge_approvals,
    bridge_rooms,
    bridge_upkeep,
):
    router.include_router(_part.router)
