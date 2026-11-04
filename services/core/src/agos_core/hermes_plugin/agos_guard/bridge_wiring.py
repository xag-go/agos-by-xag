"""The bridge plugged into Hermes: register() adds its hooks, tools, platform and
prompt sections, and the Telegram bot, once connected, gets AGOS's buttons, the
watchers and the loops.

Owns: the wiring order (what is registered, when the loops start).
Must not: hold feature logic.

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sys
from typing import Any

__all__ = [
    "register",
    "telegram_buttons",
]

try:
    from . import (
        bridge_approvals,
        bridge_core,
        bridge_delivery,
        bridge_hooks,
        bridge_kanban,
        bridge_menu,
        bridge_platform,
        bridge_sessions,
        bridge_stream,
        bridge_tools,
    )
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_approvals = sys.modules["agos_guard_bridge_approvals"]
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_delivery = sys.modules["agos_guard_bridge_delivery"]
    bridge_hooks = sys.modules["agos_guard_bridge_hooks"]
    bridge_kanban = sys.modules["agos_guard_bridge_kanban"]
    bridge_menu = sys.modules["agos_guard_bridge_menu"]
    bridge_platform = sys.modules["agos_guard_bridge_platform"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]
    bridge_stream = sys.modules["agos_guard_bridge_stream"]
    bridge_tools = sys.modules["agos_guard_bridge_tools"]


log = logging.getLogger("agos.bridge")


def telegram_buttons(native: Any, adapter: Any) -> None:
    """AGOS's own buttons in this bot go to AGOS (Hermes's buttons are untouched).
    Called when the gateway connects the bot: what he writes in AGOS starts flowing in."""
    bridge_delivery._start_poller()
    if bridge_core.bridge() is None:
        log.info("AGOS bridge: no bridge file, AGOS buttons not wired")
        return
    bridge_approvals._watch_cards(adapter)
    bridge_stream._watch_sends(adapter)
    bridge_delivery._watch_reactions(adapter)
    bridge_core._ctx["native"] = native
    bridge_delivery._start_sender()
    with contextlib.suppress(RuntimeError):
        loop = asyncio.get_event_loop()
        bridge_core._ctx["loop"] = bridge_core._process()["loop"] = (
            loop  # the gateway's loop (commands, cards)
        )
        bridge_core._ctx["menu"] = loop.create_task(bridge_menu._send_menu(native))
        bridge_core._ctx["members_menu"] = loop.create_task(bridge_menu._members_menu(adapter))
    from telegram.ext import CallbackQueryHandler  # type: ignore[import-not-found, unused-ignore]

    async def pressed(update: Any, context: Any) -> None:
        query = update.callback_query
        message = query.message
        # Hermes's own check of who may press its buttons (its allowlist).
        gate = getattr(adapter, "_callback_authorized", None)
        ctx_of = getattr(adapter, "_callback_ctx", None)
        if gate is None or ctx_of is None or not await gate(query, ctx_of(query), "Not allowed."):
            return
        answer = await asyncio.to_thread(
            bridge_core.post,
            "callback",
            {
                "chat": bridge_sessions._address(
                    message.chat.id, getattr(message, "message_thread_id", None)
                ),
                "data": str(query.data or ""),
                "messageId": str(message.message_id),
            },
            30,
        )

        shown = str((answer or {}).get("text") or "")
        # Like Hermes's own buttons: a short note on the tap, and the card shows
        # what was done, without its buttons (pressed once is enough).
        with contextlib.suppress(Exception):
            await query.answer(shown[:190] or None)
        if shown and not shown.startswith("Already"):
            with contextlib.suppress(Exception):
                body = str(getattr(message, "text", "") or "")
                await query.edit_message_text(f"{body}\n\n→ {shown}".strip(), reply_markup=None)

    native.add_handler(CallbackQueryHandler(pressed, pattern=re.compile(bridge_core.AGOS_BUTTONS)))


def register(ctx: Any) -> None:
    bridge_core._ctx["ctx"] = ctx
    with bridge_core._guard("hermes_cli.plugins.PluginContext.register_system_prompt_section"):
        ctx.register_system_prompt_section(
            bridge_hooks.OWNER_RULES_SECTION, bridge_hooks.owner_rules_section, max_chars=4000
        )
        for n, section_id in enumerate(bridge_hooks.OWNER_RULES_SECTIONS[1:], start=1):
            ctx.register_system_prompt_section(
                section_id, bridge_hooks.owner_rules_part(n), max_chars=4000
            )
    with bridge_core._guard("hermes_cli.plugins.kanban_task_claimed"):
        ctx.register_hook("kanban_task_claimed", bridge_kanban.kanban_claimed)
        ctx.register_hook("kanban_task_completed", bridge_kanban.kanban_completed)
    bridge_platform._register_platform(ctx)
    bridge_tools._register_tools(ctx)
    bridge_delivery._start_poller()
    from . import rooms

    with bridge_core._guard("hermes_cli.plugins.on_room_member_activity"):
        ctx.register_hook("on_room_member_activity", rooms.member_activity)
    rooms.start()
    ctx.register_hook("pre_gateway_dispatch", bridge_hooks.pre_gateway_dispatch)
    ctx.register_hook("post_gateway_admission", bridge_hooks.post_gateway_admission)
    ctx.register_hook("pre_llm_call", bridge_hooks.pre_llm_call)
    ctx.register_hook("post_llm_call", bridge_hooks.post_llm_call)
    ctx.register_hook("on_session_end", bridge_hooks.on_session_end)
    with bridge_core._guard("hermes_cli.plugins.agent_loop_stopped"):
        ctx.register_hook("agent_loop_stopped", bridge_hooks.agent_loop_stopped)
    ctx.register_hook("pre_approval_request", bridge_approvals.pre_approval_request)
    ctx.register_hook("transform_llm_output", bridge_stream.transform_llm_output)
    ctx.register_hook("on_stream_delta", bridge_stream.on_stream_delta)
    ctx.register_hook("on_stream_end", bridge_stream.on_stream_end)
    ctx.register_hook("pre_tool_call", bridge_stream.tool_started)
    ctx.register_hook("post_api_request", bridge_stream.api_call_done)
    ctx.register_hook("post_tool_call", bridge_stream.tool_done)
    ctx.register_hook("post_approval_response", bridge_approvals.post_approval_response)
    ctx.register_telegram_handler(telegram_buttons)
    # The members' commands are this plugin's from the start, in any process that
    # loads it: Hermes's own menu builder (telegram_menu_commands) lists them, so
    # AGOS's "/" list (read from Hermes) shows what Telegram shows.
    with contextlib.suppress(Exception):
        bridge_menu._sync_members()
