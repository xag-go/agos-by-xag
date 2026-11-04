"""Each team member (an agent of the workspace's team) is its own Hermes profile.

`agos-<workspace>--a-<agent>` (Hermes's `<root>/profiles/a-<agent>`): a full Hermes
agent — its own SOUL.md (who it is and its job), memory, sessions, skills and
model. It runs no gateway of its own: the root's one gateway serves it (Hermes
multiplexing), and Hermes's Kanban dispatcher starts its cards. The Co-Founder is the
root's default profile.

What the team shares comes from the workspace, written by AGOS (the agents can't
reach their profile from the sandbox):
- the same sandbox: the workspace's files (read-write) and added folders, behind
  the workspace's walls (its own internal network, the egress proxy);
- the root's own Hermes settings, copied in: its MCP servers and apps
  (`mcp_servers` + their keys), tools, skills and plugins. A Hermes profile
  inherits nothing from another (hermes_cli/profiles.py), so the root's config is
  the one source and each member gets a copy of it;
- the owner's rules (USER.md entries, actions/owner_rules.py) and the AGOS Brain;
- its SOUL.md, written from its own profile's data (actions/team.py: the team and
  who each member is live in the members' profiles only);
- the owner's Autonomy rules for this member, enforced by the guard plugin.

A member never gets the Co-Founder's tools (AGOS's `agos` toolset: actions, plans,
capabilities) nor Hermes's cronjob tool: it does its job, the Co-Founder leads. The
automations the owner gives it are jobs in its own profile's Hermes cron
(actions/services/automation/): the root's gateway ticks them, and Hermes runs them as
this member.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agos_core.actions import memory_plugin
from agos_core.actions import staging as staging_copy
from agos_core.context import Core
from agos_core.db import workspaces as workspaces_repo
from agos_core.engine.hermes import EngineError
from agos_core.engine.rules import MountRefusedError
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.storage.layout import workspace_paths

log = logging.getLogger("agos.agent_profiles")

_KEY = re.compile(r"^(?P<ws>[a-z0-9-]+?)--a-(?P<agent>[a-z0-9][a-z0-9-]*)$")
# Scheduling is the Co-Founder's (its cronjob tool); the Co-Founder's own AGOS tools are
# refused by the guard (agos_guard.COFOUNDER_TOOLS).
MEMBER_OFF = ("cronjob",)


def off_reasons(core: Core, workspace_id: str, agent: str) -> dict[str, str]:
    """Why a member's `agent.disabled_toolsets` holds toolsets its Co-Founder's doesn't
    (written by _make: MEMBER_OFF plus the member's own Autonomy "Never")."""
    from agos_core.actions import autonomy
    from agos_core.shared.guard_contract import ACTIONS

    out: dict[str, str] = {}
    every = autonomy.rules(core, workspace_id)
    for action, toolsets in autonomy.NATIVE.items():
        mine = every.get(agent, {}).get(action) or every["*"].get(action)
        if mine == "never":
            for toolset in toolsets:
                out.setdefault(
                    toolset,
                    f"Autonomy: “{ACTIONS.get(action, action)}” is set to Never for this agent.",
                )
    for toolset in MEMBER_OFF:
        out[toolset] = "Scheduling is the Co-Founder's (its cronjob tool): members never schedule."
    return out


def key(workspace_id: str, agent: str) -> str:
    """The engine's id for a member's profile (a workspace id never has `--`)."""
    return f"{workspace_id}--a-{agent}"


def split_key(value: str) -> tuple[str, str] | None:
    found = _KEY.match(value)
    return (found["ws"], found["agent"]) if found else None


# ---- the workspace's Kanban (Hermes's board, one per workspace) ----------------------
# Each workspace has its own board: Hermes's default board of its root. A root lives
# outside ~/.hermes, so Hermes's board home is the root itself, shared by every
# profile in <root>/profiles (hermes_cli/kanban_db.py kanban_home,
# hermes_constants.py get_default_hermes_root). A workspace's Co-Founder and members
# never see another workspace's cards. The Co-Founder's gateway runs the dispatcher and
# claims only its members' cards; members work their cards, they never dispatch.


def board_home(core: Core, workspace_id: str) -> Path:
    """Hermes's board home of the workspace: its root."""
    assert core.engine is not None
    return core.engine.root(workspace_id)


def board_db(core: Core, workspace_id: str) -> Path:
    """Hermes's default board database: <root>/kanban.db (kanban_db.py kanban_db_path)."""
    return board_home(core, workspace_id) / "kanban.db"


def dispatch_list(core: Core, workspace_id: str) -> str:
    """The profiles the Co-Founder's dispatcher may start cards for (JSON). A member
    hired with a kit that isn't ready yet is left out (step 62, actions/hire_kit.py):
    it gets no work until its Readiness is done or the owner starts it anyway.
    An agent that is off-hours (Settings → Work hours, actions/work_hours.py; "" the
    Co-Founder) is left out the same way until its check-in."""
    from agos_core.actions import hire_kit, work_hours

    if core.engine is None:
        return json.dumps([])
    names = team_names(core, workspace_id)
    held = hire_kit.held_names(core, workspace_id, names)
    off = work_hours.off_now(core, workspace_id)
    lead = [] if work_hours.COFOUNDER in off else [core.engine.hermes_name(workspace_id)]
    return json.dumps(
        lead
        + [
            core.engine.hermes_name(key(workspace_id, n))
            for n in names
            if n not in held and n not in off
        ]
    )


# Triage like Hermes: rough ideas are fleshed out and split for the team (AGOS's
# recommendation, the owner's choice: engine/owner_choices.py).
KANBAN_TRIAGE = {"kanban.auto_decompose": "true"}


def kanban_pairs(core: Core, workspace_id: str, *, cofounder: bool) -> dict[str, str]:
    """Hermes's Kanban settings for the workspace's Co-Founder, or a member."""
    pairs = {
        # A staging copy never works cards by itself (the copied cards would spend
        # real money on the shared provider logins): no dispatcher there at all.
        "kanban.dispatch_in_gateway": "true" if cofounder and not staging_copy.on() else "false",
        # The Co-Founder's dispatcher claims only this workspace's cards: its own
        # (the Co-Founder works cards too) and its members'. The owner's account
        # pause is Hermes's own pause (the root's ESTOP holds the dispatcher),
        # so the list always stays the true one.
        "kanban.dispatch_profiles": dispatch_list(core, workspace_id),
        **KANBAN_TRIAGE,
    }
    return pairs


def set_board_folder(core: Core, workspace_id: str) -> None:
    """Cards work in the workspace's own folder (kept; the team sees the files):
    the board's own default workdir (Hermes's board settings)."""
    if core.engine is None:
        return
    hermes_cli.cli(
        core.engine,
        workspace_id,
        "kanban",
        "boards",
        "set-default-workdir",
        "default",
        str(workspace_paths(core.layout, workspace_id).files),
    )


def _kanban_on(pairs: dict[str, str]) -> None:
    """The kanban toolset on (Hermes's own board tools)."""
    off = [t for t in json.loads(pairs.get("agent.disabled_toolsets", "[]")) if t != "kanban"]
    pairs["agent.disabled_toolsets"] = json.dumps(off)


def refresh_plugins(core: Core, workspace_id: str) -> None:
    from agos_core.actions import autonomy

    if core.engine is None:
        return
    for ws, agent in existing(core, workspace_id):
        home = core.engine.profile_home(key(ws, agent))
        if home.is_dir() and not autonomy.plugin_current(home):
            with contextlib.suppress(OSError):
                autonomy.install_plugin(home)


def team_names(core: Core, workspace_id: str) -> list[str]:
    """The members on the team (read only: safe anywhere)."""
    from agos_core.actions import team as team_actions

    return team_actions.names(core, workspace_id)


def team(core: Core, workspace_id: str) -> list[Any]:
    """The workspace's members on the team, as their profiles say (actions/team.py)."""
    from agos_core.actions import team as team_actions

    return team_actions.members(core, workspace_id, on_only=True)


def model_of(core: Core, workspace_id: str, agent: Any) -> tuple[str, str, str] | None:
    """The member's model as Hermes runs it: its own, else the workspace's."""
    from agos_core.actions.engine import _default_model
    from agos_core.engine.models import hermes_slug

    own = agent.model
    if isinstance(own, dict) and own.get("model") and own.get("provider"):
        return (
            hermes_slug(str(own["provider"]), str(own.get("mode") or "subscription")),
            str(own["model"]),
            # None: Hermes's own default (no agent.reasoning_effort: the model's own)
            str(own.get("effort") or ""),
        )
    return _default_model(core, workspace_id)


def _write_policy(core: Core, workspace_id: str, agent: str, home: Path) -> None:
    """The owner's Autonomy rules for this member: everything in this profile is it."""
    from agos_core.actions import autonomy, trusted_apps
    from agos_core.shared.guard_contract import POLICY_FILE

    every = autonomy.rules(core, workspace_id)
    trusted = trusted_apps.listed(core, workspace_id)  # read vs act: the owner's own apps
    mine = {**every.get("*", {}), **every.get(agent, {})}
    target = home / POLICY_FILE
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        rules = {"": mine, agent: mine, "*": every.get("*", {})}
        json.dump({"rules": rules, "member": agent, "trustedApps": trusted}, handle)
    tmp.replace(target)


def soul_text(
    core: Core,
    workspace_id: str,
    *,
    title: str,
    instructions: str,
    local: str,
    reads: list[dict[str, str]],
    agent: str = "",
) -> str:
    """The member's SOUL.md: who it is, the project, who it reports to, the
    workspace goal (its own sub-goals first), its role (the owner's role text, his
    notes for it here, the rule files it follows), and the same working rules as
    the whole workspace. Hermes reads it in every conversation and card it works."""
    from agos_core.actions import docs, goals, hire_kit, org
    from agos_core.engine import identity
    from agos_core.engine import library as lib

    workspace = workspaces_repo.get_workspace(core.db, workspace_id)
    role = lib.agent_instructions(title, {"instructions": instructions}, local)
    rules = docs.agent_block(core, workspace_id, {"reads": reads})
    project = workspace.name if workspace else workspace_id
    about = (workspace.description if workspace else "").strip()
    return identity.member_soul(
        title,
        project,
        about,
        f"{role}\n\n{rules}" if rules else role,
        goal=goals.prompt_for(core, workspace_id, agent),
        chain=org.chain_line(core, workspace_id, agent) if agent else "",
        team=hire_kit.team_section(core, workspace_id, agent) if agent else "",
    )


def write_soul(
    core: Core,
    workspace_id: str,
    agent: str,
    *,
    title: str,
    instructions: str,
    local: str,
    reads: list[dict[str, str]],
) -> bool:
    """Writes the member's SOUL.md (Hermes has no command for it); False when it
    already said exactly this."""
    from agos_core.engine import identity

    assert core.engine is not None
    text = soul_text(
        core,
        workspace_id,
        title=title,
        instructions=instructions,
        local=local,
        reads=reads,
        agent=agent,
    )
    return identity.write_soul(core.engine.profile_home(key(workspace_id, agent)), text)


def _link_tokens(workspace_home: Path, home: Path) -> None:
    """The workspace's app logins (its MCP tokens), seen by the member too."""
    link = home / "mcp-tokens"
    target = workspace_home / "mcp-tokens"
    if not target.exists():
        if link.is_symlink():
            link.unlink()
        return
    if link.is_symlink():
        if link.readlink() == target:
            return
        link.unlink()
    elif link.exists():
        return  # its own logins (never replaced)
    link.symlink_to(target, target_is_directory=True)


def _plan(
    core: Core,
    workspace_id: str,
    item: Any,
    pairs: dict[str, str],
    grants: list[Any],
    secrets: dict[str, str],
) -> dict[str, Any]:
    """Everything one member's profile needs, read from AGOS's data (here, on the
    caller's thread); `_make` then only writes files and runs Hermes."""
    from agos_core.actions import apps, autonomy, hermes_channel, owner_rules, workspace_skills

    agent = str(item.name)
    every = autonomy.rules(core, workspace_id)
    mine = {**every.get("*", {}), **every.get(agent, {})}
    return {
        "workspace": workspace_id,
        "agent": agent,
        "files_dir": workspace_paths(core.layout, workspace_id).files,
        "grants": grants,
        "model": model_of(core, workspace_id, item),
        "policy": {"rules": {"": mine, agent: mine, "*": every.get("*", {})}, "member": agent},
        "secrets": secrets,
        "bridge": {
            "core": apps.core_url(),
            "workspace": workspace_id,
            "key": hermes_channel.bridge_key(core, workspace_id),
            "member": agent,
        },
        # The Co-Founder's pairs, with the workspace's skill folder read as a member's
        # (skills.external_dirs: the same files its Co-Founder changes, read-only here).
        "pairs": {
            **pairs,
            "skills.external_dirs": json.dumps(
                workspace_skills.external_dirs(core, workspace_id, member=True)
            ),
        },
        "kanban": kanban_pairs(core, workspace_id, cofounder=False),
        # The toolsets this member may never use (its own Autonomy "Never",
        # Hermes's own switch).
        "never": autonomy.never_toolsets(core, workspace_id, agent),
        "rules": owner_rules.in_user_md(owner_rules.texts(core)),
        "soul": soul_text(
            core,
            workspace_id,
            title=item.title,
            instructions=item.instructions,
            local=item.local,
            reads=item.reads,
            agent=agent,
        ),
    }


def _make(core: Core, plan: dict[str, Any]) -> None:
    """Creates or updates one member's profile from its plan. Safe to repeat."""
    engine = core.engine
    if engine is None:
        return
    from agos_core.actions import autonomy, owner_rules
    from agos_core.engine import identity
    from agos_core.engine import library as lib

    workspace_id, agent = str(plan["workspace"]), str(plan["agent"])
    profile_key = key(workspace_id, agent)
    # Not set up by AGOS yet (the team made its bare profile: actions/team.py).
    made = not (engine.profile_home(profile_key) / "agos-bridge.json").is_file()
    # A member's apply may stop and start its root's one gateway: one member's
    # apply at a time per root, while the rest of the members' setup runs side
    # by side (_make_all).
    with _root_apply(workspace_id):
        engine.apply(
            profile_key,
            files_dir=plan["files_dir"],
            workspaces_dir=core.layout.workspaces,
            agos_data=core.layout.root,
            grants=plan["grants"],
            model=plan["model"],
        )
    home = engine.profile_home(profile_key)
    autonomy.install_plugin(home)
    _write_json(home / _policy_file(), plan["policy"])
    _link_tokens(engine.profile_home(workspace_id), home)
    lib.write_mcp_env(home, plan["secrets"])
    _write_bridge(home, plan["bridge"])
    # Skills: the folders it reads (skills.external_dirs: the shared ones and its
    # workspace's) and skills.disabled come with the plan's pairs.
    mine = {**plan["pairs"], **plan["kanban"]}
    _kanban_on(mine)
    off = json.loads(mine.get("agent.disabled_toolsets", "[]"))
    extra = [*MEMBER_OFF, *plan["never"]]
    mine["agent.disabled_toolsets"] = json.dumps(
        off + [t for t in dict.fromkeys(extra) if t not in off]
    )
    from agos_core.engine import config_file
    from agos_core.engine.owner_choices import keep_owner

    # AGOS's recommendations only where the member has none yet; a new member
    # starts on its Co-Founder's value (engine/owner_choices.py).
    mine = keep_owner(
        mine, config_file.read(home), config_file.read(engine.profile_home(workspace_id))
    )
    # One Hermes process, only the keys the member doesn't hold already.
    hermes_cli.config_writes(
        engine,
        profile_key,
        [("config", "set", "--force", name, value) for name, value in mine.items()],
    )
    # The workspace's access switch: Hermes's approvals, as its Co-Founder has them now.
    from agos_core.actions import access

    access.follow_cofounder(engine, workspace_id, profile_key)
    owner_rules.write_user_profile(home, list(plan["rules"]))
    identity.write_soul(home, str(plan["soul"]))
    from agos_core.actions import general_sync

    general_sync.sync_home(core, home)  # General Settings' keys (no inheritance)
    from agos_core.actions import tool_keys

    tool_keys.share(core, workspace_id, only=profile_key)  # Settings → Keys, like the root
    if made:
        # A new member: the tools' services set up in Settings, like the workspace,
        # and the time limits and fallback models its Co-Founder has (Hermes's own
        # settings).
        from agos_core.actions import hermes_all_settings, tool_services

        tool_services.apply_home(core, home)
        # The fallback chain, limits, time limits and timezone: Hermes's managed
        # scope (actions/hermes_managed.py), nothing to copy.
        # And what the owner changed in Settings → Hermes settings for its Co-Founder.
        hermes_all_settings.give_new_profile(core, profile_key)
        # Holographic memory (named by engine/rules.py) is installed right away,
        # unwalled: a walled gateway (engine/wall.py) can't write Hermes's shared
        # dependency store, so Hermes's own install at the agent's start would fail.
        memory_plugin.install_new(core, profile_key)
    # Its Learn "Ask me": Hermes's own write_approval gates in its profile.
    autonomy.sync_write_gates(core, workspace_id, only=agent)


def _policy_file() -> str:
    from agos_core.shared.guard_contract import POLICY_FILE

    return POLICY_FILE


def _write_json(target: Path, value: Any) -> None:
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, sort_keys=True)
    tmp.replace(target)


def _write_bridge(home: Path, bridge: dict[str, str]) -> None:
    """Its gateway takes ONLY its own AGOS conversations (the agos platform): a group
    turn of it, its DM. No Telegram of its own: the Co-Founder's bot carries it."""
    from agos_core.actions import hermes_channel
    from agos_core.engine import envfile

    envfile.rewrite(
        home / ".env",
        hermes_channel.ENV_PREFIX,
        [
            "AGOS_PLATFORM_ENABLED=true",
            f"AGOS_PLATFORM_ALLOWED_USERS={hermes_channel.AGOS_OWNER}",
        ],
    )
    _write_json(home / hermes_channel.BRIDGE_FILE, bridge)


def ready(core: Core, workspace_id: str, agent: str) -> bool:
    """Its own profile answers for it (made, and it is on the team)."""
    engine = core.engine
    if engine is None or not workspace_id:
        return False
    home = engine.profile_home(key(workspace_id, agent))
    from agos_core.engine import profile_meta

    return (home / "agos-bridge.json").is_file() and not profile_meta.parked(home)


_ROOT_APPLY_GUARD = threading.Lock()
_ROOT_APPLY: dict[str, threading.Lock] = {}


@contextlib.contextmanager
def _root_apply(workspace_id: str) -> Iterator[None]:
    with _ROOT_APPLY_GUARD:
        lock = _ROOT_APPLY.setdefault(workspace_id, threading.Lock())
    with lock:
        yield


# Making the members' profiles runs Hermes's CLI many times (minutes for a team):
# live it runs in the background, so the owner's click never waits for it.
IN_BACKGROUND = True
_making: dict[str, Any] = {}
_making_lock = __import__("threading").Lock()


def apply_team(
    core: Core, workspace_id: str, pairs: dict[str, str], secrets: dict[str, str]
) -> list[str]:
    """Every member on the workspace's team gets its profile set up, up to date
    (members off the team stay as they are, their sandboxes stopped). Returns the
    ones that failed (when it ran here; in the background they are logged)."""
    engine = core.engine
    if engine is None:
        return []
    from agos_core.actions.engine import _grants

    grants = _grants(core, workspace_id)
    plans = [_plan(core, workspace_id, i, pairs, grants, secrets) for i in team(core, workspace_id)]
    on = {str(p["agent"]) for p in plans}
    tidy = [agent for ws, agent in existing(core, workspace_id) if agent not in on]
    if not IN_BACKGROUND:
        return _make_all(core, workspace_id, plans, tidy)
    import threading

    with _making_lock:
        if workspace_id in _making:
            _making[workspace_id] = (plans, tidy)  # the newest, once this round ends
            return []
        _making[workspace_id] = None

    def run(job: tuple[Any, Any]) -> None:
        while True:
            _make_all(core, workspace_id, *job)
            with _making_lock:
                nxt = _making.get(workspace_id)
                if nxt is None:
                    _making.pop(workspace_id, None)
                    return
                _making[workspace_id] = None
            job = nxt

    threading.Thread(
        target=run, args=((plans, tidy),), name=f"team-{workspace_id}", daemon=True
    ).start()
    return []


def _make_all(
    core: Core, workspace_id: str, plans: list[dict[str, Any]], tidy: list[str]
) -> list[str]:
    engine = core.engine
    if engine is None:
        return []
    failed = []

    def one(plan: dict[str, Any]) -> None:
        try:
            _make(core, plan)
        except (EngineError, MountRefusedError, OSError, ValueError) as error:
            log.error("member %s of %s not synced: %s", plan["agent"], workspace_id, error)
            failed.append(str(plan["agent"]))

    # Members already set up: up to 4 side by side (each its own home and write
    # lock; their roots' gateway restarts stay one at a time). A new member is
    # made alone: its first setup installs into Hermes's shared dependency store.
    new = [
        p
        for p in plans
        if not (
            engine.profile_home(key(workspace_id, str(p["agent"]))) / "agos-bridge.json"
        ).is_file()
    ]
    known = [p for p in plans if p not in new]
    if len(known) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(known))) as pool:
            list(pool.map(one, known))
    else:
        for plan in known:
            one(plan)
    # A new member's Holographic install holds its home's config lock while it
    # downloads: it starts once the member's setup is written.
    with memory_plugin.after_setup(core):
        for plan in new:
            one(plan)
    failed.sort(key=[str(p["agent"]) for p in plans].index)
    from agos_core.actions import automations

    for agent in tidy:
        # Its automations' jobs leave its cron first: the Co-Founder does them now.
        try:
            automations.hand_over(core, workspace_id, agent)
        except Exception:
            log.exception("automations of %s in %s not handed over", agent, workspace_id)
        # Off the team (Hermes's parked marker): kept (its memory), its sandboxes go.
        with contextlib.suppress(EngineError, OSError):
            engine.park(key(workspace_id, agent))
    return failed


def missing(core: Core, workspace_id: str) -> bool:
    """A member on the team whose profile isn't set up yet (the sync must run)."""
    engine = core.engine
    if engine is None:
        return False
    return any(
        not (engine.profile_home(key(workspace_id, n)) / "agos-bridge.json").is_file()
        for n in team_names(core, workspace_id)
    )


def existing(core: Core, workspace_id: str | None = None) -> list[tuple[str, str]]:
    engine = core.engine
    if engine is None:
        return []
    return [
        parsed
        for name in profile_names(core, workspace_id)
        if (parsed := split_key(name[len(engine.settings.profile_prefix) :])) is not None
        and (workspace_id is None or parsed[0] == workspace_id)
    ]


def profile_names(core: Core, workspace_id: str | None = None) -> list[str]:
    """AGOS's names of the profiles on disk, in each workspace's own root (ADR 0020)."""
    engine = core.engine
    if engine is None:
        return []
    names: set[str] = set()
    if workspace_id is not None:
        names |= set(engine.own_profiles(workspace_id))
    else:
        for each in workspaces_repo.ids(core.db):
            names |= set(engine.own_profiles(each))
    return sorted(names)


def remove(core: Core, workspace_id: str, agent: str) -> None:
    if core.engine is None:
        return
    try:
        core.engine.delete_profile(key(workspace_id, agent))
    except (EngineError, OSError):
        log.exception("could not delete the profile of %s in %s", agent, workspace_id)


def remove_for_workspace(core: Core, workspace_id: str) -> None:
    """The workspace is purged: its members' profiles go too."""
    for ws, agent in existing(core, workspace_id):
        remove(core, ws, agent)


def write_policies(core: Core, workspace_id: str) -> None:
    """The owner's Autonomy rules changed: each member's copy follows."""
    engine = core.engine
    if engine is None:
        return
    for item in team(core, workspace_id):
        home = engine.profile_home(key(workspace_id, str(item.name)))
        if (home / "config.yaml").is_file():
            with contextlib.suppress(OSError):
                _write_policy(core, workspace_id, str(item.name), home)


def write_texts(core: Core, workspace_id: str) -> None:
    """Who each member is (SOUL.md, from its own profile's data: the project's name
    and description or a rule file may have changed) and the owner's rules (USER.md)."""
    engine = core.engine
    if engine is None:
        return
    from agos_core.actions import owner_rules
    from agos_core.actions import team as team_actions

    for agent in team_actions.members(core, workspace_id):
        home = engine.profile_home(key(workspace_id, agent.name))
        try:
            owner_rules.sync_profile(core, home)
            write_soul(
                core,
                workspace_id,
                agent.name,
                title=agent.title,
                instructions=agent.instructions,
                local=agent.local,
                reads=agent.reads,
            )
        except OSError:
            log.exception("could not write the texts of %s in %s", agent.name, workspace_id)
