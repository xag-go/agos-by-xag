"""Writing a workspace's library state (MCP servers, toolsets, skills folder) into its own Hermes, and adopting what Hermes has.
Must not: decide what is on (workspace_state) or edit library items (catalog, lifecycle).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agos_core.actions import hermes_config as hc
from agos_core.actions import mcp_relays, team
from agos_core.actions.errors import ActionError
from agos_core.actions.services.library.records import log, used_by, workspace_skills_module
from agos_core.actions.services.library.tool_rows import ensure_tools
from agos_core.actions.services.library.workspace_state import (
    _entry,
    _signing_in,
    enabled,
    oauth_signed_in,
    profile_settings,
    workspace_lock,
)
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.engine import library as lib
from agos_core.engine.apps import AppError
from agos_core.engine.hermes import EngineError
from agos_core.engine.library import LibraryError
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.security import mcp_address

__all__ = [
    "FORMAT",
    "adopt_servers",
    "agent_text",
    "apply_workspace",
    "change",
    "refresh_tools",
    "reload_gateway",
    "resync_users",
]


def resync_users(core: Core, item_id: int) -> None:
    row = repo.get_item(core.db, item_id)
    if row is None:
        return
    for workspace_id in used_by(core, row):
        apply_workspace(core, workspace_id)


def change(core: Core, workspace_id: str, edit: Callable[[hc.Here], None]) -> None:
    """Reads what the workspace has on from its Hermes, changes it, writes it back."""
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    if not hc.has_root(core, workspace_id):
        raise ActionError("This workspace's agent isn't set up yet.", 409)
    with workspace_lock(workspace_id):
        here = hc.here(core, workspace_id)
        edit(here)
        problem = apply_workspace(core, workspace_id, here)
    if problem:
        raise ActionError(f"Not saved: the agent's setup wasn't updated: {problem}", 503)


def adopt_servers(core: Core, workspace_id: str) -> None:
    """Every MCP server of the workspace's Hermes has its id in AGOS (one added with
    `hermes mcp add` too); the id of a server gone from Hermes goes."""
    if not hc.has_root(core, workspace_id):
        return
    with workspace_lock(workspace_id):
        servers = hc.here(core, workspace_id).mcp
        rows = {
            str(r["name"]): r
            for r in repo.list_items(core.db, "mcp", workspace_id)
            if r["workspace_id"] == workspace_id
        }
        for name in servers:
            if name not in rows and lib.NAME.fullmatch(name):
                repo.insert_item(
                    core.db,
                    kind="mcp",
                    name=name,
                    title=lib.readable_title(name),
                    summary="",
                    definition={},
                    source="hermes",
                    workspace_id=workspace_id,
                )
        for name, row in rows.items():
            if name not in servers:
                repo.delete_item(core.db, int(row["id"]))


def refresh_tools(core: Core) -> None:
    """Hermes's list of tools read again; anything new appears and is on (a toolset
    in neither of a workspace's Hermes lists is on: hermes_config.from_hermes)."""
    from agos_core.db.workspaces import list_workspaces
    from agos_core.engine import hermes_tools

    if hermes_tools.refresh(core):
        ensure_tools(core)
        for workspace in list_workspaces(core.db):
            with contextlib.suppress(Exception):
                apply_workspace(core, workspace.id)


# Bumped when what AGOS writes into a root changes shape: the next apply writes it.
FORMAT = "hermes-config-3"  # 3: each workspace's own skill folder


def apply_workspace(core: Core, workspace_id: str, here: hc.Here | None = None) -> str | None:
    """Writes what the workspace has on (`here`: read from its Hermes when not given)
    into its root and its members' profiles. Rows AGOS kept from before move into
    the root here, once. Returns a problem (shown to the owner) instead of failing
    silently."""
    engine = core.engine
    if engine is None:
        return None
    from agos_core.db.workspaces import get_workspace

    if get_workspace(core.db, workspace_id) is None:
        return None  # deleted meanwhile: nothing is written back
    engine.forget_tools(workspace_id)  # its tools' state is checked again
    home = engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        return "This workspace's agent isn't set up yet."
    with workspace_lock(workspace_id):
        here = here if here is not None else hc.here(core, workspace_id)
        try:
            _write(core, workspace_id, here, home)
            mcp_edited = _mcp_edited(home, _mcp_stamp_of(home))
        except (EngineError, OSError, LibraryError, AppError) as error:
            log.error("connectors of %s not applied: %s", workspace_id, error)
            return f"Not applied: {error}"
    if mcp_edited:
        reload_gateway(core, workspace_id)
    return None


_MCP_STAMP = ".agos-mcp"


def _mcp_stamp_of(home: Path) -> dict[str, str]:
    """Each MCP server as written now, hashed: its `mcp_servers` entry (without its
    `enabled` switch) and the values of the keys it names (never stored)."""
    from agos_core.engine import config_file

    servers = config_file.get(config_file.read(home), "mcp_servers") or {}
    keys = {k: v for k, v in _env_lines(home / ".env").items() if k.startswith(lib.MCP_ENV_PREFIX)}
    out: dict[str, str] = {}
    for name, entry in servers.items():
        body = (
            {k: v for k, v in entry.items() if k != "enabled"} if isinstance(entry, dict) else entry
        )
        text = json.dumps(body, sort_keys=True, default=str)
        used = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in keys.items() if k in text}
        out[str(name)] = hashlib.sha256(
            json.dumps([body, used], sort_keys=True, default=str).encode()
        ).hexdigest()
    return out


def _mcp_edited(home: Path, now: dict[str, str]) -> bool:
    """An MCP server that was there before and is there now changed (its url,
    headers, tools or key). Only that needs Hermes's /reload-mcp: a server added,
    removed, enabled or disabled is Hermes's own MCP reconcile, every housekeeping
    tick of the running gateway (H: gateway/run.py `_mcp_config_reconciler`,
    tools/mcp_tool_discovery.py `reconcile_mcp_servers_with_config`), and its new
    toolset list rebuilds the cached agents (gateway/run_agent_cache.py
    `_agent_config_signature`)."""
    stamp = home / _MCP_STAMP
    try:
        before = json.loads(stamp.read_text())
    except (OSError, ValueError):
        before = {}
    if not isinstance(before, dict):  # the older single-hash stamp: nothing to compare
        before = {}
    stamp.write_text(json.dumps(now, sort_keys=True))
    return any(name in before and before[name] != digest for name, digest in now.items())


def _env_lines(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for line in path.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep:
                out[name.strip()] = value.strip()
    return out


def _write(core: Core, workspace_id: str, here: hc.Here, home: Path) -> bool:
    """True when something was written (False: Hermes already had it all)."""
    engine = core.engine
    assert engine is not None
    items = enabled(core, workspace_id, here)
    from agos_core.actions import apps, autonomy

    # The guard first: it enforces the owner's rules and members' limits, so it is
    # never left old because a later step (an app login) failed.
    autonomy.install_plugin(home)
    skill_dirs, skills_off = workspace_skills_module().pairs(
        core, workspace_id, here.skills, member=False
    )
    # The keys: Hermes's .env of the root (and of every member), ${AGOS_MCP_…}.
    mcp_secrets = {**here.keys, **apps.profile_secrets(core, workspace_id, here.apps)}
    mcp_secrets.update(mcp_relays.secrets(core, workspace_id, here))
    lib.write_mcp_env(home, mcp_secrets)
    apps.prepare_profile(core, workspace_id, home)
    from agos_core.actions import hermes_channel

    channel_mark = hermes_channel.prepare_profile(core, workspace_id, home, apps.core_url())
    autonomy.write_policy(core, workspace_id)
    pairs = profile_settings(
        items,
        _servers(core, workspace_id, here, home),
        nous_apps=apps.NOUS_APP in here.apps,
        never=autonomy.never_toolsets(core, workspace_id),
        skill_dirs=skill_dirs,
        skills_off=skills_off,
    )
    # The workspace's own Kanban (Hermes's board): the Co-Founder runs its dispatcher.
    from agos_core.actions import agent_profiles

    pairs.update(agent_profiles.kanban_pairs(core, workspace_id, cofounder=True))
    agent_profiles._kanban_on(pairs)
    # Same connectors as last time: nothing to reload (Hermes reads the skills'
    # text from their folders at each session start),
    # so a running answer is never cut by a routine re-check.
    stamp = home / ".agos-connectors"
    digest = hashlib.sha256(
        json.dumps(
            [
                FORMAT,
                pairs,
                channel_mark,
                sorted(mcp_secrets),
                # A member's own Autonomy "Never" is its profile's toolsets.
                {
                    name: autonomy.never_toolsets(core, workspace_id, name)
                    for name in agent_profiles.team_names(core, workspace_id)
                },
                sorted((i.kind, i.name, json.dumps(i.definition, sort_keys=True)) for i in items),
            ],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    if stamp.is_file() and stamp.read_text().strip() == digest:
        if agent_profiles.missing(core, workspace_id):
            agent_profiles.apply_team(core, workspace_id, pairs, mcp_secrets)
        # A new AGOS: the members' guard is updated too (their next run reads it).
        agent_profiles.refresh_plugins(core, workspace_id)
        _show_in_playbooks(core, workspace_id)
        return False
    from agos_core.engine import config_file
    from agos_core.engine.owner_choices import keep_owner

    # AGOS's recommendations only where the profile has none yet (owner_choices).
    # These sections are AGOS's alone, so they are replaced whole (Hermes refuses a
    # whole-section write without --force). All in one Hermes process, and only
    # the keys whose value Hermes doesn't hold already (a switch changes one or
    # two of them; each as its own CLI was ~0.65 s, ~24 of them per click).
    hermes_cli.config_writes(
        engine,
        workspace_id,
        [
            ("config", "set", "--force", key, value)
            for key, value in keep_owner(pairs, config_file.read(home)).items()
        ],
    )
    # The team's members: each its own Hermes profile, with the root's setup.
    agent_profiles.apply_team(core, workspace_id, pairs, mcp_secrets)
    with contextlib.suppress(EngineError, OSError):
        agent_profiles.set_board_folder(core, workspace_id)
    stamp.write_text(digest)
    _show_in_playbooks(core, workspace_id)
    return True


def _servers(core: Core, workspace_id: str, here: hc.Here, home: Path) -> dict[str, dict[str, Any]]:
    """The root's whole `mcp_servers`: its own servers as Hermes has them (a local
    one at its container's address now; `auth: oauth` while signed in), then its
    apps. An entry AGOS can't check (a command on this machine, a private address)
    is dropped: no MCP server ever runs outside the workspace's container."""
    from agos_core.actions import apps

    local_urls = mcp_relays.local_servers(core, workspace_id, here)
    signed = oauth_signed_in(home) | _signing_in(workspace_id)
    servers: dict[str, dict[str, Any]] = {}
    for name, entry in sorted(here.mcp.items()):
        try:
            definition = lib.check_mcp(hc.definition_of(entry), resolve=False)
        except LibraryError as error:
            log.warning("MCP server %s of %s left out: %s", name, workspace_id, error)
            continue
        local = lib.is_local(definition)
        fresh = _entry(name, entry, has_key=bool(here.keys.get(name)) and not local)
        if local:  # its container's relay, with the relay's own bearer
            fresh.update(url=local_urls.get(name, ""), headers=mcp_relays.header(name))
        elif name in signed and "headers" not in fresh:
            fresh["auth"] = "oauth"
        servers[name] = fresh
    # Apps (each workspace's own logins) have their own `app-` names.
    servers.update(
        apps.profile_servers(core, workspace_id, here.apps, local_urls.get(apps.GOOGLE_SERVER))
    )
    return mcp_address.with_private_off(mcp_relays.with_google_header(servers))


def _show_in_playbooks(core: Core, workspace_id: str) -> None:
    """What the team uses, shown in playbooks/; and the Co-Founder's view of it in its
    SOUL.md (the next conversation reads it there)."""
    from agos_core.actions import engine as engine_actions
    from agos_core.actions import team_files

    team_files.write(core, workspace_id)
    engine_actions.refresh_cofounder_view(core, workspace_id)


def reload_gateway(core: Core, workspace_id: str) -> None:
    """The running gateway takes the new MCP setup now: Hermes's own /reload-mcp in
    each profile (actions/hermes_channel.py `reload_mcp`). It is never stopped for
    it, so no Kanban card, cron run or room is cut. The rest of the config (tools,
    skills, limits) Hermes reads for each new agent by itself."""
    from agos_core.actions import hermes_channel

    try:
        hermes_channel.reload_mcp(core, workspace_id)
    except (EngineError, OSError) as error:
        log.warning("%s: MCP reload not asked (%s)", workspace_id, error)


def _applied_or_raise(core: Core, workspace_id: str) -> None:
    problem = apply_workspace(core, workspace_id)
    if problem and problem != "This workspace's agent isn't set up yet.":
        raise ActionError(f"Saved, but the agent's setup wasn't updated: {problem}", 503)


def agent_text(core: Core, workspace_id: str, name: str) -> str | None:
    """Role instructions for a run, if the agent is on in this workspace (read from
    its Hermes profile: the same role its SOUL.md holds)."""
    agent = team.get(core, workspace_id, name)
    if agent is None or not agent.on:
        return None
    text = lib.agent_instructions(agent.title, agent.definition, agent.local)
    from agos_core.actions import docs  # late: docs imports workspaces

    rules = docs.agent_block(core, workspace_id, agent.definition)
    return f"{text}\n\n{rules}" if rules else text
