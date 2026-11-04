"""What a workspace has on in its own Hermes (switches, enabled servers, toolsets, profile settings), read only; the per-workspace lock.
Must not: write a workspace's Hermes (that is apply) or change library rows.

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import Field

from agos_core.actions import hermes_config as hc
from agos_core.actions import team
from agos_core.actions.services.library.records import hermes_tools_module, locked_tool, log
from agos_core.context import Core
from agos_core.db import connector_notes as notes_repo
from agos_core.db import library as repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.records import Record
from agos_core.engine import library as lib
from agos_core.engine.hermes import RESTART_DRAIN_S, EngineError
from agos_core.engine.rules import DISABLED_TOOLSETS
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "BASE_TOOLSETS",
    "SPILL_KEY",
    "SPILL_MOVED",
    "Switch",
    "enabled",
    "move_spill_cap",
    "notes",
    "oauth_signed_in",
    "profile_settings",
    "switches",
    "workspace_lock",
]

# ---- connectors: what a workspace has on, in its own Hermes -------------------------

_ws_locks: dict[str, threading.RLock] = {}
_ws_locks_guard = threading.Lock()


def workspace_lock(workspace_id: str) -> threading.RLock:
    """One change of a workspace's Hermes settings at a time (read, change, write)."""
    with _ws_locks_guard:
        return _ws_locks.setdefault(workspace_id, threading.RLock())


def notes(core: Core, workspace_id: str) -> dict[int, str]:
    """The owner's notes on a skill, tool, plugin or MCP server in this workspace
    (shown in AGOS only; an agent's are its team row's)."""
    return notes_repo.notes(core.db, workspace_id)


def _set_notes(core: Core, workspace_id: str, row: Any, text: str) -> None:
    if row["kind"] == "agent":
        return  # an agent's are its connector row's (its team place)
    notes_repo.save(core.db, workspace_id, int(row["id"]), text)


class Switch(Record):
    """One item as one workspace has it."""

    on: bool
    allowed_tools: list[str] = Field(default_factory=list)
    local: str = ""
    secret_last4: str | None = None


def switches(core: Core, workspace_id: str, here: hc.Here | None = None) -> dict[int, Switch]:
    """Every item's switch in this workspace: its Hermes for skills, tools, plugins
    and MCP servers; the members' own profiles for agents."""
    here = here if here is not None else hc.here(core, workspace_id)
    written = notes(core, workspace_id)
    out: dict[int, Switch] = {
        a.id: Switch(on=a.on, local=a.local) for a in team.members(core, workspace_id)
    }
    for row in repo.list_items(core.db, None, workspace_id):
        item_id, kind, name = int(row["id"]), str(row["kind"]), str(row["name"])
        local = written.get(item_id, "")
        if kind == "mcp":
            entry = here.mcp.get(name) if row["workspace_id"] == workspace_id else None
            if entry is None:
                continue
            key = here.keys.get(name)
            out[item_id] = Switch(
                on=hc.is_on(entry),
                allowed_tools=hc.allowed_tools(entry),
                local=local,
                secret_last4=key[-4:] if key else None,
            )
            continue
        on = (
            (kind == "skill" and name in here.skills)
            or (kind == "tool" and name in here.tools and not locked_tool(name))
            or (kind == "plugin" and hc.plugin_name(name, repo.definition(row)) in here.plugins)
        )
        out[item_id] = Switch(on=on, local=local)
    return out


def _entry(
    name: str,
    entry: dict[str, Any],
    *,
    has_key: bool,
    definition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The same server written again: its switch, tool filter and Hermes's other
    keys kept (its definition replaced when one is given: its new url too; a local
    server's url stays its container's address)."""
    rest = {
        k: v
        for k, v in entry.items()
        if k not in ("url", "headers", "tools", "enabled", hc.AGOS, "auth")
    }
    wanted = definition if definition is not None else hc.definition_of(entry)
    fresh = hc.entry_of(
        name,
        wanted,
        on=hc.is_on(entry),
        allowed_tools=hc.allowed_tools(entry),
        has_key=has_key,
        url=str(entry.get("url") or "") if lib.is_local(wanted) else None,
    )
    tools = hc._mapping(entry.get("tools"))
    tools.pop("include", None)
    if tools:
        fresh["tools"] = {**tools, **hc._mapping(fresh.get("tools"))}
    return {**rest, **fresh}


def enabled(core: Core, workspace_id: str, here: hc.Here | None = None) -> list[lib.Enabled]:
    """What is on in the workspace: from its Hermes (the team: actions/team.py)."""
    here = here if here is not None else hc.here(core, workspace_id)
    result = [
        lib.Enabled(
            kind="tool", name=name, definition={"toolset": name}, allowed_tools=[], secret=None
        )
        for name in sorted(here.tools)
        if not locked_tool(name)
    ]
    for row in repo.list_items(core.db, None, workspace_id):
        kind, name = str(row["kind"]), str(row["name"])
        if kind in ("agent", "mcp", "tool"):
            continue  # tools: Hermes's own names; MCP: below, from Hermes's entries
        if (kind == "skill" and name in here.skills) or (
            kind == "plugin" and hc.plugin_name(name, repo.definition(row)) in here.plugins
        ):
            result.append(
                lib.Enabled(
                    kind=kind,  # type: ignore[arg-type]
                    name=name,
                    definition=repo.definition(row),
                    allowed_tools=[],
                    secret=None,
                )
            )
    for name, entry in sorted(here.mcp.items()):
        if hc.is_on(entry):
            result.append(
                lib.Enabled(
                    kind="mcp",
                    name=name,
                    definition=hc.definition_of(entry),
                    allowed_tools=hc.allowed_tools(entry),
                    secret=here.keys.get(name),
                )
            )
    return result


SPILL_KEY = "hooks.output_spill.max_chars"
_SPILL_FORCED = "1000000"  # what AGOS forced until area3 W1
SPILL_MOVED = "moved.spill_cap"


def move_spill_cap(core: Core) -> list[str]:
    """AGOS forced `hooks.output_spill.max_chars` to 1,000,000 while its plugin
    handed the owner's rules to every turn as hook context. They are system-prompt
    sections now and the only hook context is the clock line, so the key goes back
    to Hermes's default (tools/hook_output_spill.py) in every profile, once
    (Hermes's own `config unset`); a value the owner sets later stays. Returns the
    profiles changed."""
    from agos_core.db.app_settings import get_setting, set_setting
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None or get_setting(core.db, SPILL_MOVED, None) is not None:
        return []
    prefix = engine.settings.profile_prefix
    changed: list[str] = []
    for workspace_id in workspaces_repo.ids(core.db):
        if not (engine.root(workspace_id) / "config.yaml").is_file():
            continue
        for name in engine.own_profiles(workspace_id):
            key = name[len(prefix) :] if name.startswith(prefix) else name
            found = config_file.get(config_file.read(engine.profile_home(key)), SPILL_KEY)
            if str(found).strip() != _SPILL_FORCED:
                continue
            try:
                hermes_cli.cli(engine, key, "config", "unset", SPILL_KEY)
            except EngineError as error:
                log.warning("%s not given back to Hermes in %s: %s", SPILL_KEY, key, error)
                return changed  # tried again at the next start
            changed.append(key)
    set_setting(core.db, SPILL_MOVED, True)
    return changed


def profile_settings(
    items: list[lib.Enabled],
    servers: dict[str, dict[str, Any]] | None = None,
    *,
    nous_apps: bool = False,
    never: list[str] | None = None,
    skill_dirs: list[str] | None = None,
    skills_off: list[str] | None = None,
) -> dict[str, str]:
    """The `hermes config set` pairs for a workspace's capabilities and apps.
    `servers`: its whole `mcp_servers` (its own servers and its apps' `app-` ones).
    The tools the owner turned on are in every platform's list even when his
    Autonomy "Never" takes them away (agent.disabled_toolsets, which Hermes applies
    last): the list keeps his switch, the disabled list what really runs."""
    plugins = sorted(
        {str(i.definition.get("plugin") or i.name) for i in items if i.kind == "plugin"}
        | {"agos-guard"}  # the owner's Autonomy rules + read-only watcher, always on
    )
    optional = set(hermes_tools_module().optional())
    turned_on = {i.name for i in items if i.kind == "tool" and i.name in optional}
    if nous_apps:
        turned_on.add(hc.NOUS_TOOLSET)
    disabled = [
        t
        for t in dict.fromkeys(
            [*DISABLED_TOOLSETS, *hermes_tools_module().LOCKED, *sorted(optional)]
        )
        if t not in turned_on and t not in hermes_tools_module().ALWAYS
    ]
    switched = list(disabled)
    # The owner's "Never" for everyone, where Hermes has the switch (Autonomy).
    disabled += [t for t in never or [] if t not in disabled]
    return {
        "mcp_servers": json.dumps(servers or {}),
        "plugins.enabled": json.dumps(plugins),
        "agent.disabled_toolsets": json.dumps(disabled),
        # The skill folders this profile reads where they are (AGOS's own and the
        # Brain's; a member also its workspace's): actions/workspace_skills.py.
        # What is off here (a skill not turned on, a Brain method "Not here") is
        # this profile's skills.disabled.
        "skills.external_dirs": json.dumps(list(skill_dirs or [])),
        "skills.disabled": json.dumps(sorted(skills_off or [])),
        # SOUL.md carries AGOS's standing rules and the Co-Founder's view of the
        # workspace: Hermes loads it whole (no size cap: the owner's rule).
        "context_file_max_chars": "1000000",
        # One conversation per Telegram group or topic (like the AGOS chat linked to
        # it). Someone new writing to the bot in private gets Hermes's DM pairing
        # code; the owner approves him in AGOS (actions/telegram_people.py). Telegram's
        # own key too: with an allowlist set, Hermes reads the global "pair" as its
        # default and ignores strangers (gateway/authz_mixin.py
        # _get_unauthorized_dm_behavior); a platform's key wins over that.
        "group_sessions_per_user": "false",
        "unauthorized_dm_behavior": "pair",
        "platforms.telegram.extra.unauthorized_dm_behavior": "pair",
        # The owner's rule: no reasoning, no "what runs in the background" (tool
        # progress, background processes), no self-improvement notes, on any channel.
        "display.show_reasoning": "false",
        "display.tool_progress": "off",
        "display.platforms.telegram.tool_progress": "off",
        "display.platforms.telegram.cleanup_progress": "true",
        # In Telegram only the answer is sent (once): no mid-answer commentary as
        # messages of their own that the answer then repeats, no "⏳ Working" bubble
        # (Hermes's mobile defaults keep both on: H: gateway/display_config.py).
        "display.platforms.telegram.interim_assistant_messages": "false",
        "display.platforms.telegram.long_running_notifications": "false",
        # A gateway AGOS restarts (new routes, new mounts) lets a running answer
        # finish and go out first, instead of cutting it and re-running or
        # re-sending it after the restart (Hermes's default is 0: cut at once).
        "agent.restart_drain_timeout": str(RESTART_DRAIN_S),
        # The plugin sets its 👍 / 👎 on a room message through Hermes's own
        # platform actions (ctx.platform_actions), a capability Hermes gates.
        "plugins.entries.agos-guard.granted_capabilities": json.dumps(["gateway.platform_actions"]),
        "display.memory_notifications": "off",
        "display.background_process_notifications": "off",
        "display.busy_ack_detail": "false",
        # AGOS's own conversations (agos platform): AGOS shows "Working…" itself, so
        # Hermes sends only the answer there (no progress / heartbeat / interim lines).
        "display.platforms.agos.tool_progress": "off",
        "display.platforms.agos.long_running_notifications": "false",
        "display.platforms.agos.interim_assistant_messages": "false",
        "display.platforms.agos.busy_ack_detail": "false",
        "display.platforms.agos.streaming": "false",
        # Webhooks reach the workspace's Hermes on this machine only (the public relay
        # passes them on).
        "platforms.webhook.host": "127.0.0.1",
        # What he writes while it works is Hermes's own default, as on his own Hermes:
        # it interrupts the run and Hermes redirects it with his correction ("↪
        # Redirected current run…" on Telegram).
        "display.busy_input_mode": "interrupt",
        "display.platforms.agos.busy_steer_ack_enabled": "false",
        # Every Hermes tool the workspace has on, on every place it works: AGOS's own
        # chats, Telegram, its automations (cron), its group rooms (api_server). Hermes's clarify (an agent asks the
        # owner and waits) and Kanban (the team's cards) in the chats and on his phone.
        "platform_toolsets.agos": json.dumps(_toolsets(turned_on, switched, kanban=True)),
        "platform_toolsets.telegram": json.dumps(_toolsets(turned_on, switched, kanban=True)),
        # Kanban in its automations too: a run proposes cards with kanban_create (the
        # guard keeps them waiting for the owner and the rest of the board read only).
        "platform_toolsets.cron": json.dumps(_toolsets(turned_on, switched, kanban=True)),
        # Hermes rooms (a group chat on a workspace's own root, ADR 0020) run each
        # member's turn with the api_server platform's tools: the same as in chats.
        "platform_toolsets.api_server": json.dumps(_toolsets(turned_on, switched, kanban=True)),
        # Hermes improves its own skills over time: its curator also merges overlaps.
        "curator.consolidate": "true",
        # An edited MCP entry is Hermes's /reload-mcp with no confirm to answer (H:
        # gateway/slash_commands.py `_handle_reload_mcp_command`); added or removed
        # servers are its own MCP reconcile (actions/hermes_channel.py reload_mcp).
        "approvals.mcp_reload_confirm": "false",
    }


# Hermes's toolsets every workspace has (its learning ones included: skills, memory,
# past conversations); the optional ones follow the workspace's switches.
BASE_TOOLSETS = (
    "web",
    "terminal",
    "file",
    "skills",
    "todo",
    "memory",
    "session_search",
    "clarify",
    "cronjob",
)


def _toolsets(turned_on: set[str], disabled: list[str], *, kanban: bool) -> list[str]:
    optional = set(hermes_tools_module().optional())
    names = [*BASE_TOOLSETS, *sorted(t for t in turned_on if t in optional)]
    if hc.NOUS_TOOLSET in turned_on:
        names.append(hc.NOUS_TOOLSET)  # the Nous apps (connections)
    if kanban:
        names.append("kanban")
    names.append("agos")  # AGOS's own tools (the guard plugin)
    return [n for n in dict.fromkeys(names) if n not in disabled]


def _signing_in(workspace_id: str) -> set[str]:
    from agos_core.actions.mcp_signin import signing_in

    return {server for ws, server in signing_in if ws == workspace_id}


def oauth_signed_in(home: Path) -> set[str]:
    """MCP servers with an OAuth sign-in saved in this Hermes profile."""
    folder = home / "mcp-tokens"
    if not folder.is_dir():
        return set()
    return {
        f.name[: -len(".json")]
        for f in folder.glob("*.json")
        if not f.name.endswith((".client.json", ".meta.json"))
    }
