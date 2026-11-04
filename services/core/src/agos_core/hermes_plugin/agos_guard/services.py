"""A card's dev servers and previews (Step 59): `agos_service`.

A card's worker starts a dev server / preview with Hermes's own background
process (its terminal tool: background, persist_on_release, so it outlives the
run; Hermes's process registry and processes.json have it), and AGOS records the
card, the port and Hermes's process id so the owner sees it on the card with a
preview link (through AGOS's web, never public) and a Stop button.

- start (command, port, label): PORT and AGOS_PREVIEW_BASE (the path the preview
  is shown under) are set for the command.
- list: the card's services (running or not, answering or not).
- stop (port): Hermes stops its process (process_registry.kill_process).
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 20

SCHEMA = {
    "name": "agos_service",
    "description": (
        "Run a dev server or preview for the card you work on, so the owner can open it "
        "from the card in AGOS (a private link, never public) and stop it there. action "
        "'start' (command, port, label): runs the command in the background (it keeps "
        "running after your run ends); the env has PORT and AGOS_PREVIEW_BASE (the path "
        "it is shown under: use it as the base path, or keep links relative). 'list': "
        "this card's services. 'stop' (port): stops it. Bind to 0.0.0.0 or 127.0.0.1."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "stop", "list"]},
            "command": {"type": "string", "description": "The command (start)."},
            "port": {"type": "integer", "description": "The port it listens on."},
            "label": {"type": "string", "description": "A short name (start)."},
        },
        "required": ["action"],
    },
}


def _registry(guard: Any) -> Any:
    with guard("tools.process_registry.process_registry"):
        from tools.process_registry import process_registry  # type: ignore[import-not-found]

        return process_registry
    return None


def _start(
    args: dict[str, Any],
    *,
    card: str,
    workspace: str,
    task_id: str,
    terminal: Callable[..., str],
) -> tuple[dict[str, Any] | None, str]:
    command = str(args.get("command") or "").strip()
    try:
        port = int(args.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if not command or not 1024 <= port <= 65535:
        return None, "Give the command and the port it listens on (1024-65535)."
    base = f"/preview/{workspace}/{card}/{port}/"
    started = terminal(
        command=f"export PORT={port} AGOS_PREVIEW_BASE={shlex.quote(base)}; {command}",
        background=True,
        task_id=task_id or None,
        persist_on_release=True,
    )
    try:
        result = json.loads(started)
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict) or not result.get("session_id"):
        error = result.get("error") if isinstance(result, dict) else None
        return None, str(error or "Hermes didn't start it.")
    return {
        "processId": str(result["session_id"]),
        "pid": int(result["pid"]) if result.get("pid") else None,
        "command": command[:2000],
        "port": port,
        "label": str(args.get("label") or "")[:80],
    }, ""


def service_tool(
    args: dict[str, Any],
    *,
    card: str,
    profile: str,
    workspace: str,
    task_id: str,
    post: Callable[..., Any],
    guard: Any,
    terminal: Callable[..., str] | None = None,
) -> str:
    if not card:
        return json.dumps({"error": "Only a card's worker runs services (the card's run)."})
    action = str(args.get("action") or "list")
    if action == "start":
        if terminal is None:
            with guard("tools.terminal_tool.terminal_tool"):
                from tools.terminal_tool import terminal_tool  # type: ignore[import-not-found]

                terminal = terminal_tool
        if terminal is None or not workspace:
            return json.dumps({"error": "Hermes's terminal isn't here; try again later."})
        found, error = _start(
            args, card=card, workspace=workspace, task_id=task_id, terminal=terminal
        )
        if found is None:
            return json.dumps({"error": error})
        registry = _registry(guard)
        scope = "host"
        if registry is not None:
            session = registry.get(found["processId"])
            if session is not None:
                scope = str(getattr(session, "pid_scope", "host") or "host")
                found["pid"] = getattr(session, "pid", None) or found["pid"]
        answer = post(
            "service",
            {"action": "started", "card": card, "profile": profile, "pidScope": scope, **found},
            TOOL_WAIT_S,
        )
        if answer is None:
            return json.dumps(
                {
                    "error": "AGOS can't be reached: the server runs, but AGOS doesn't show it.",
                    "processId": found["processId"],
                }
            )
        return json.dumps({**answer, "processId": found["processId"]}, ensure_ascii=False)
    listed = post("service", {"action": "list", "card": card}, TOOL_WAIT_S)
    if listed is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    if action != "stop":
        return json.dumps(listed, ensure_ascii=False)
    try:
        port = int(args.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    running = [
        s
        for s in listed.get("services") or []
        if s.get("running") and int(s.get("port") or 0) == port
    ]
    if not running:
        return json.dumps({"error": f"No service of this card runs on port {port}."})
    registry = _registry(guard)
    for s in running:
        if registry is not None:
            registry.kill_process(str(s.get("processId") or ""))
        post(
            "service",
            {"action": "stopped", "card": card, "processId": s.get("processId")},
            TOOL_WAIT_S,
        )
    return json.dumps({"ok": True, "stopped": len(running)})


def register(
    ctx: Any,
    *,
    card: Callable[[], str],
    profile: Callable[[], str],
    workspace: Callable[[], str],
    post: Callable[..., Any],
    guard: Any,
) -> None:
    def handle(args: dict[str, Any], **kwargs: Any) -> str:
        return service_tool(
            args,
            card=card(),
            profile=profile(),
            workspace=workspace(),
            task_id=str(kwargs.get("task_id") or ""),
            post=post,
            guard=guard,
        )

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(SCHEMA["name"]),
            toolset="agos",
            schema=SCHEMA,
            handler=handle,
            description=str(SCHEMA["description"]),
            emoji="🖥️",
        )
