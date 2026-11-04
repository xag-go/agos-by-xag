"""The agent's AGOS tools (agos_action, agos_capability) and the owner gate's
answers, the address a tool call comes from (chat, cron run, Kanban card,
subagent), and subagents joined to their parent.

Owns: the tool schemas and their call to AGOS.
Must not: decide what needs the owner (gate.py and the core do).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import os
import re
import sys
from types import SimpleNamespace
from typing import Any

__all__ = [
    "ACTION_SCHEMA",
    "CAPABILITY_SCHEMA",
    "GATE_UNREACHABLE",
    "TOOL_WAIT_S",
    "action_tool",
    "capability_tool",
    "gate_fields",
    "owner_decides",
    "run_card",
    "subagent_started",
]

try:
    from . import bridge_core
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]


ACTION_SCHEMA = {
    "name": "agos_action",
    "description": (
        "Do things for the owner in AGOS: create or change automations, skills, agents, "
        "MCP servers, docs and team files (see 'Doing things for the owner' in your "
        "instructions for every action and its fields). Each one shows as a card with Undo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "description": 'The actions, e.g. [{"do": "create_skill", "name": "...", ...}].',
                "items": {"type": "object", "additionalProperties": True},
            }
        },
        "required": ["actions"],
    },
}

CAPABILITY_SCHEMA = {
    "name": "agos_capability",
    "description": (
        "Turn one of this workspace's apps, skills, agents, MCP servers or tools on or off "
        "(see 'Tools and apps of this workspace')."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["app", "skill", "agent", "mcp", "tool"]},
            "name": {"type": "string"},
            "on": {"type": "boolean"},
            "why": {"type": "string"},
        },
        "required": ["kind", "name"],
    },
}


# The owner gate on the plugin's side lives in gate.py (one-time asks after an
# untrusted read); these wrappers keep its old names here.
GATE_UNREACHABLE = bridge_core._beside("gate").GATE_UNREACHABLE


def owner_decides(tool: str, args: dict[str, Any], session_id: str = "") -> dict[str, str] | None:
    said: dict[str, str] | None = bridge_core._beside("gate").owner_decides(
        _me(), tool, args, session_id
    )
    return said


# How long the Co-Founder's agos_action / agos_capability wait for AGOS: a batch can take
# minutes (a batch of many skills, agents and docs, each written by Hermes).
TOOL_WAIT_S = 900


def _me() -> Any:
    """What gate.py reads of the bridge (it was handed the whole bridge module before
    the split): looked up now, so a patched name is the one it gets."""
    return SimpleNamespace(
        _address_of_session=_address_of_session,
        _parents=_parents,
        TOOL_WAIT_S=TOOL_WAIT_S,
        bridge=bridge_core.bridge,
        post=bridge_core.post,
        _post=bridge_core._post,
        _taint=bridge_core._taint,
    )


def _tool_post(path: str, session_id: str, body: dict[str, Any], what: str, tool: str, args: Any) -> str:  # fmt: skip
    return str(
        bridge_core._beside("gate").tool_post(_me(), path, session_id, body, what, tool, args)
    )


def gate_fields(session_id: str, tool: str, args: dict[str, Any]) -> dict[str, str]:
    said: dict[str, str] = bridge_core._beside("gate").gate_fields(_me(), session_id, tool, args)
    return said


def action_tool(args: dict[str, Any], session_id: str = "", **_: Any) -> str:
    raw = [a for a in args.get("actions") or [] if isinstance(a, dict)]
    return _tool_post(
        "actions", session_id, {"actions": raw}, "nothing was done", "agos_action", args
    )


def capability_tool(args: dict[str, Any], session_id: str = "", **_: Any) -> str:
    on = args.get("on", True) is not False
    body = {
        "kind": str(args.get("kind") or "app"),
        "name": str(args.get("name") or ""),
        "on": on,
        "why": str(args.get("why") or ""),
    }
    return _tool_post("capability", session_id, body, "nothing changed", "agos_capability", args)


def _address_of_session(session_id: str, _seen: frozenset[str] = frozenset()) -> str | None:
    """Where a call of AGOS's tools comes from: a chat (its turn), an automation's
    run (Hermes's cron), a Kanban card's worker (Hermes's dispatcher), or a subagent
    of any of them (Hermes's delegate_task: its parent's place)."""
    # An automation's run: Hermes names its session cron_<job id>_<date>_<time>.
    if session_id.startswith("cron_") and session_id.count("_") >= 3:
        return "cron:" + session_id[len("cron_") :].rsplit("_", 2)[0]
    with bridge_core._lock:
        for (session, _turn), address in bridge_core._busy.items():
            if session == session_id and address:
                return address
        parent = _parents.get(session_id, "")
    if parent and parent not in _seen and parent != session_id:
        found = _address_of_session(parent, _seen | {session_id})
        if found is not None:
            return found
    card = run_card()
    return f"kanban:{card}" if card else None


# A subagent's session -> its parent's (Hermes's subagent_start hook): a child of a
# chat's turn, of a card's worker or of an automation's run acts from its place.
_parents: dict[str, str] = bridge_core._shared.setdefault("parents", {})
_PARENTS_MAX = 2000


def subagent_started(parent_session_id: str, child_session_id: str) -> None:
    parent, child = str(parent_session_id or ""), str(child_session_id or "")
    if not parent or not child or parent == child:
        return
    with bridge_core._lock:
        if len(_parents) >= _PARENTS_MAX:
            for old in list(_parents)[: _PARENTS_MAX // 2]:
                _parents.pop(old, None)
        _parents[child] = parent


# A Kanban card's id: Hermes's dispatcher gives its worker HERMES_KANBAN_TASK.
_CARD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def run_card() -> str:
    """The Kanban card this process works (Hermes's dispatcher-spawned worker), if any."""
    try:
        from gateway.session_context import get_session_env  # type: ignore[import-not-found]

        value = get_session_env("HERMES_KANBAN_TASK", "")
    except Exception as error:  # noqa: BLE001 — outside Hermes's gateway
        bridge_core._broken("gateway.session_context.get_session_env", error)
        value = os.environ.get("HERMES_KANBAN_TASK", "")
    card = str(value or "").strip()
    return card if _CARD_ID.match(card) else ""


def _register_tools(ctx: Any) -> None:
    for schema, handler, emoji in (
        (ACTION_SCHEMA, action_tool, "🛠"),
        (CAPABILITY_SCHEMA, capability_tool, "🔌"),
    ):
        with bridge_core._guard("hermes_cli.plugins.PluginContext.register_tool"):
            ctx.register_tool(
                name=str(schema["name"]),
                toolset="agos",
                schema=schema,
                handler=handler,
                description=str(schema["description"]),
                emoji=emoji,
            )
