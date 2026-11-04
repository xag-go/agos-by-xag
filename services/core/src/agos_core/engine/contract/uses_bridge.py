"""Hermes contract entries: the bridge (agos_guard/bridge.py): the gateway, Telegram and AGOS chats.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _ALIVE,
    _CARDS,
    _CHATS,
    _CLOCK,
    _EYES,
    _MENU,
    _ROUTE,
    _TG,
    _UNANSWERED,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # ---- bridge: agos_guard/bridge.py (the gateway, Telegram and AGOS chats) ----
    _u(
        "gateway.status",
        "read_runtime_status",
        "function",
        "bridge",
        "a draining gateway takes no AGOS work",
    ),
    # Hermes's own verdict on a home's gateway (engine/hermes.py gateway_status).
    _u(
        "gateway.status", "get_running_pid", "function", "engine", _ALIVE, pos=1, kw="cleanup_stale"
    ),
    _u("gateway.status", "runtime_status_pid_is_live", "function", "engine", _ALIVE, pos=1),
    _u("gateway.status", "runtime_status_is_stale", "function", "engine", _ALIVE, pos=1),
    # ...asked first on the gateway's own control socket (engine/hermes.py
    # gateway_socket_status): its file names, protocol, request line and the keys of
    # its `status` answer (the runtime status + what the socket adds).
    _u(
        "gateway.control_socket",
        "CONTROL_PROTOCOL_VERSION",
        "text",
        "engine",
        _ALIVE,
        text="CONTROL_PROTOCOL_VERSION = 1",
    ),
    _u(
        "gateway.control_socket",
        "_SOCKET_FILENAME",
        "text",
        "engine",
        _ALIVE,
        text='_SOCKET_FILENAME = "gateway.sock"',
    ),
    _u(
        "gateway.control_socket",
        "_POINTER_FILENAME",
        "text",
        "engine",
        _ALIVE,
        text='_POINTER_FILENAME = "gateway.sock.path"',
    ),
    _u(
        "gateway.control_socket",
        "query_gateway_control",
        "text",
        "engine",
        _ALIVE,
        text='{"verb": verb, "id": 1, "protocol": CONTROL_PROTOCOL_VERSION}',
    ),
    _u(
        "gateway.control_socket",
        "GatewayControlServer.handle_request_line",
        "text",
        "engine",
        _ALIVE,
        text='response = {"ok": True, "protocol": CONTROL_PROTOCOL_VERSION,',
    ),
    _u(
        "gateway.control_socket",
        "GatewayControlServer._handlers",
        "text",
        "engine",
        _ALIVE,
        text='"status": build_status_payload',
    ),
    _u(
        "gateway.control_socket",
        "build_status_payload",
        "text",
        "engine",
        _ALIVE,
        text='return {**(read_runtime_status() or {}), "protocol": CONTROL_PROTOCOL_VERSION,',
    ),
    _u(
        "gateway.control_socket",
        "build_status_payload.answering_pid",
        "text",
        "engine",
        _ALIVE,
        text='"answered_at": time.time(), "answering_pid": os.getpid()}',
    ),
    # A turn Hermes answered without its agent is closed when Hermes's own in-flight
    # count says it answers nothing (actions/hermes_channel.close_unanswered): the
    # count it persists at each turn boundary, of all its work.
    _u(
        "gateway.run",
        "GatewayRunner._persist_active_agents",
        "text",
        "engine",
        _UNANSWERED,
        text="_write_runtime_status_quiet(active_agents=self._active_work_count())",
    ),
    _u(
        "gateway.run_shutdown",
        "_active_work_count",
        "text",
        "engine",
        _UNANSWERED,
        text="def _active_work_count(self) -> int:",
    ),
    _u("gateway.run", "_gateway_runner_ref", "constant", "bridge", _ROUTE),
    _u("gateway.run", "GatewayRunner.config", "attr", "bridge", _ROUTE),
    _u("gateway.run", "GatewayRunner.session_store", "attr", "bridge", _ROUTE),
    _u(
        "gateway.run",
        "GatewayRunner._session_key_for_source",
        "method",
        "bridge",
        "an AGOS chat keeps its own Hermes session",
        pos=1,
    ),
    _u("gateway.config", "GatewayConfig.group_sessions_per_user", "attr", "bridge", _ROUTE),
    _u("gateway.config", "GatewayConfig.thread_sessions_per_user", "attr", "bridge", _ROUTE),
    _u("gateway.config", "Platform", "class", "bridge", _CHATS),
    _u(
        "gateway.session",
        "build_session_key",
        "function",
        "bridge",
        _ROUTE,
        pos=1,
        kw="group_sessions_per_user thread_sessions_per_user profile",
    ),
    _u(
        "gateway.session",
        "SessionSource.from_dict",
        "method",
        "bridge",
        "a command he types in AGOS runs in its Telegram chat",
        pos=1,
    ),
    *[
        _u("gateway.session", f"SessionSource.{a}", "attr", "bridge", _TG)
        for a in ("chat_id", "thread_id", "user_id", "chat_name", "platform", "profile")
    ],
    _u("gateway.session", "SessionStore.lookup_by_session_key", "method", "bridge", _ROUTE, pos=1),
    _u("gateway.session", "SessionStore.list_sessions", "method", "bridge", _ROUTE),
    _u("gateway.session", "SessionEntry.origin", "attr", "bridge", _ROUTE),
    _u("gateway.session", "SessionEntry.session_key", "attr", "bridge", _ROUTE),
    _u("gateway.session", "SessionStore.get_or_create_session", "method", "bridge", _ROUTE, pos=1),
    _u(
        "gateway.session",
        "SessionStore.switch_session",
        "method",
        "bridge",
        _ROUTE,
        pos=2,
        kw="preserve_prompt_pin",
    ),
    _u("gateway.session", "SessionEntry.session_id", "attr", "bridge", _ROUTE),
    _u("gateway.platforms.base", "ProcessingOutcome", "class", "bridge", _EYES),
    *[
        _u("gateway.platforms.base", f"ProcessingOutcome.{a}", "attr", "bridge", _EYES)
        for a in ("SUCCESS", "FAILURE", "CANCELLED")
    ],
    _u(
        "gateway.platforms.base",
        "SendResult",
        "class",
        "bridge",
        _CHATS,
        kw="success error message_id",
    ),
    *[
        _u("gateway.platforms.base", f"SendResult.{a}", "attr", "bridge", _TG)
        for a in ("success", "error", "message_id")
    ],
    *[
        _u("gateway.platforms.base", f"ExecApprovalPrompt.{a}", "attr", "bridge", _CARDS)
        for a in ("session_key", "actions", "command", "description", "smart_denied")
    ],
    _u(
        "gateway.platforms.event",
        "MessageEvent",
        "class",
        "bridge",
        "his AGOS messages into Hermes (chat, voice notes, files, commands)",
        kw="text message_type source media_urls media_types metadata timestamp message_id channel_prompt",
    ),
    *[
        _u("gateway.platforms.event", f"MessageEvent.{a}", "attr", "bridge", _TG)
        for a in (
            "internal",
            "metadata",
            "source",
            "text",
            "message_id",
            "message_type",
            "raw_message",
            "reply_to_message_id",
            "reply_to_text",
            "reply_to_is_own_message",
            "media_urls",
            "media_types",
            "media_text_inlined",
        )
    ],
    *[
        _u("gateway.platforms.event", f"MessageType.{a}", "attr", "bridge", _CHATS)
        for a in ("TEXT", "COMMAND", "VOICE", "PHOTO", "DOCUMENT")
    ],
    _u("gateway.platforms._shared", "get_scoped_secret", "function", "bridge", _CHATS, pos=2),
    _u(
        "tools.clarify_gateway",
        "mark_awaiting_text",
        "function",
        "bridge",
        "Hermes's clarify question answered in AGOS",
        pos=1,
    ),
    _u(
        "utils",
        "load_yaml_file_readonly",
        "function",
        "bridge",
        "a member's name on its answers in a routed topic",
        pos=1,
    ),
    # Hermes's platform adapter: AGOS's own adapter subclasses it; on Telegram's,
    # AGOS wraps a few public methods and calls a few private ones.
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter",
        "class",
        "bridge",
        _CHATS,
        kw="config platform",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._configure_text_batch_delays",
        "method",
        "bridge",
        _CHATS,
    ),
    _u("gateway.platforms.base", "BasePlatformAdapter._mark_connected", "method", "bridge", _CHATS),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._mark_disconnected",
        "method",
        "bridge",
        _CHATS,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._wire_plugin_handlers",
        "method",
        "bridge",
        _CHATS,
        pos=1,
    ),
    _u("gateway.platforms.base", "BasePlatformAdapter._running", "attr", "bridge", _CHATS),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._text_batch_key",
        "method",
        "bridge",
        _CHATS,
        pos=1,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._enqueue_text_event",
        "method",
        "bridge",
        _CHATS,
        pos=1,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._flush_text_batch_now",
        "method",
        "bridge",
        _CHATS,
        pos=1,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.handle_message",
        "method",
        "bridge",
        _CHATS,
        pos=1,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.build_source",
        "method",
        "bridge",
        _CHATS,
        kw="chat_id chat_name chat_type user_id chat_topic thread_id",
    ),
    # Read with getattr (4096 when absent): AGOS's adapter sets its own.
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.MAX_MESSAGE_LENGTH",
        "text",
        "bridge",
        _CHATS,
        text='getattr(self, "MAX_MESSAGE_LENGTH"',
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.connect",
        "override",
        "bridge",
        _CHATS,
        accepts="is_reconnect",
    ),
    _u("gateway.platforms.base", "BasePlatformAdapter.disconnect", "override", "bridge", _CHATS),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._pop_text_batch",
        "override",
        "bridge",
        _CHATS,
        accepts="key",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._dispatch_text_batch",
        "override",
        "bridge",
        _CHATS,
        accepts="event",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.send",
        "override",
        "bridge",
        _CHATS + "; " + _TG,
        accepts="chat_id content reply_to metadata",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.send_clarify",
        "override",
        "bridge",
        "Hermes's clarify question shown in AGOS",
        accepts="chat_id question choices clarify_id session_key metadata",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.edit_message",
        "override",
        "bridge",
        _CHATS,
        accepts="chat_id message_id content",
        more=True,
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.send_typing",
        "override",
        "bridge",
        _CHATS,
        accepts="chat_id metadata",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter._send_exec_approval_prompt",
        "override",
        "bridge",
        _CARDS,
        accepts="prompt",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.get_chat_info",
        "override",
        "bridge",
        _CHATS,
        accepts="chat_id",
    ),
    _u(
        "gateway.platforms.base",
        "BasePlatformAdapter.on_processing_complete",
        "override",
        "bridge",
        _EYES,
        accepts="event outcome",
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter.send",
        "override",
        "bridge",
        _TG,
        accepts="chat_id content",
        more=True,
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter.send_exec_approval",
        "override",
        "bridge",
        _CARDS,
        accepts="chat_id command session_key",
        more=True,
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter.send_exec_approval",
        "method",
        "bridge",
        _CARDS,
        kw="chat_id command session_key description metadata allow_permanent allow_session smart_denied",
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter._register_command_menu",
        "method",
        "bridge",
        _MENU,
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter._callback_authorized",
        "method",
        "bridge",
        "who may press AGOS's Telegram buttons (Hermes's allowlist)",
        pos=3,
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter._callback_ctx",
        "method",
        "bridge",
        "who may press AGOS's Telegram buttons (Hermes's allowlist)",
        pos=1,
    ),
    _u(
        "plugins.platforms.telegram.adapter",
        "TelegramAdapter.build_source",
        "method",
        "bridge",
        "a command he types in AGOS runs in its Telegram chat",
        kw="chat_id chat_type user_id thread_id",
    ),
    _u(
        "gateway.message_timestamps",
        "format_message_timestamp",
        "function",
        "bridge",
        _CLOCK,
        pos=1,
        kw="tz",
    ),
    _u("hermes_time", "get_timezone", "function", "bridge", _CLOCK),
)
