"""Autonomy rules: what each agent may do on its own (Do it / Ask me / Never).

Enforced inside Hermes by the `agos-guard` plugin (hermes_plugin/agos_guard),
which AGOS installs in every workspace profile. The plugin's own file in the
workspace's root, `agos-guard.json`, is the one copy of the rules: AGOS reads it
and writes the owner's changes into it (whole-file atomic writes, so the plugin
never reads half a file); each member's profile gets its own copy. "Ask me"
becomes Hermes's own approval (Approve / Deny on the
card and the phone), and Full access never answers it by itself
(`access.owner_rule`; the guard still asks under Hermes's YOLO / approvals off).
"Save to memory and skills" is the exception: its Ask me / Do it is Hermes's own
write_approval in each profile (held for his review under Full access too), so the
file keeps only "never" / "allow" for it and the guard asks nothing for those writes.
"Never" is Hermes's own `agent.disabled_toolsets` wherever a whole toolset is
off for that profile (`never_toolsets`: everyone's Never on the Co-Founder's
profile, a member's own Never on its profile); the guard blocks the rest before
it runs (files and apps share a toolset with reading).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.engine.guard_files import PLUGIN_SOURCE
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.shared.guard_contract import ACTIONS, POLICY_FILE

log = logging.getLogger("agos.autonomy")

PLUGIN_NAME = "agos-guard"
CHOICES = ("do", "ask", "never")

# Safe defaults: anything that changes the outside world asks first; deleting in
# a connected app asks; working in the workspace (files, commands, memory) runs.
DEFAULTS: dict[str, str] = {
    "files": "do",
    "commands": "do",
    "messages": "ask",
    "apps_change": "ask",
    "apps_delete": "ask",
    "browser": "do",
    "desktop": "do",
    "images": "do",
    "memory": "do",
    # A new Kanban card from an agent (the Co-Founder): he sees it first.
    "cards": "ask",
}
# What a NEW workspace starts with: the owner's own General config (the one his
# workspaces run on). Everyone does everything on its own except deleting in a
# connected app (asks first); the Co-Founder does all of it, deleting included.
# Written as real rows, so he changes any of it in that workspace's Settings and
# existing workspaces never move.
NEW_WORKSPACE: dict[str, dict[str, str]] = {
    "*": {**DEFAULTS, "messages": "do", "apps_change": "do", "cards": "do"},
    # The Co-Founder: only where it differs from everyone (the rest follows everyone).
    "": {"apps_delete": "do"},
}
HINTS: dict[str, str] = {
    "files": "Write or edit files in the workspace",
    "commands": "Run commands in the workspace's sandbox",
    "messages": "Send a message to someone (email, chat…) through a tool",
    "apps_change": "Create or change things in a connected app (Notion, GitHub…)",
    "apps_delete": "Delete or archive something in a connected app",
    "browser": "Open sites and click in its own browser",
    "desktop": "Use mouse and keyboard on its own virtual desktop",
    "images": "Generate images or audio",
    "memory": "Learn: save notes and improve its skills",
    "cards": "Make a new card on the workspace's Kanban (it starts by itself once given)",
}


def _policy_file(core: Core, workspace_id: str) -> Path | None:
    """The plugin's own file in the workspace's root (its Co-Founder's profile)."""
    if core.engine is None:
        return None
    return core.engine.profile_home(workspace_id) / POLICY_FILE


def _read_policy(core: Core, workspace_id: str) -> dict[str, Any]:
    path = _policy_file(core, workspace_id)
    if path is None:
        return {}
    try:
        found = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


# "Save to memory and skills": Ask me / Do it is Hermes's own write_approval in each
# profile (memory.write_approval, skills.write_approval: H: tools/write_approval.py
# evaluate_gate holds the write for his review, with no YOLO bypass, so it asks under
# Full access too). AGOS's file keeps only what Hermes has no switch for: "never",
# or "allow" (not Never; a member's own exception to everyone's rule).
MEMORY = "memory"
ALLOW = "allow"


def _clean(found: Any) -> dict[str, dict[str, str]]:
    """{agent: {action: choice}} with only known actions and choices (memory: never
    or allow; an older ask / do there was Hermes's gate already and reads as allow)."""
    out: dict[str, dict[str, str]] = {}
    for agent, choices in (found or {}).items() if isinstance(found, dict) else ():
        if not isinstance(choices, dict):
            continue
        kept = {
            str(a): str(c)
            for a, c in choices.items()
            if a in ACTIONS and (c in CHOICES or (a == MEMORY and c == ALLOW))
        }
        if kept.get(MEMORY) in ("ask", "do"):
            kept[MEMORY] = ALLOW
        if kept:
            out[str(agent)] = kept
    return out


def _filled(found: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Everyone's row always has every action (the plugin reads a missing one as Do it)."""
    everyone = {**DEFAULTS, **found.get("*", {})}
    if everyone.get(MEMORY) != "never":
        everyone[MEMORY] = ALLOW
    return {**found, "*": everyone}


def rules(core: Core, workspace_id: str) -> dict[str, dict[str, str]]:
    """{agent: {action: choice}}; '*' = everyone (defaults filled in). Read from the
    agos-guard plugin's own file in the workspace's Hermes (the one copy)."""
    return _filled(_clean(_read_policy(core, workspace_id).get("rules")))


_write_lock = threading.Lock()


def _write_policy_file(path: Path, policy: dict[str, Any]) -> None:
    """Hermes-safe: the plugin reads either the old file or the new one, never a
    half-written one (written aside, synced, then renamed over it; 0600)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(policy, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def _change(core: Core, workspace_id: str, change: Any) -> bool:
    """Read the plugin's file, change its rules, write it back (one writer at a time).
    False: the workspace has no Hermes profile yet."""
    path = _policy_file(core, workspace_id)
    if path is None or not path.parent.is_dir():
        return False
    from agos_core.actions import hermes_channel

    with _write_lock:
        policy = _read_policy(core, workspace_id)
        found = _clean(policy.get("rules"))
        found = change(found) or found
        if found or "rules" in policy:
            # (none yet: a new workspace's table comes with seed_new_workspace)
            policy["rules"] = _filled(found)
        # The team's members in Hermes's own Telegram "/" menu (the plugin registers them).
        policy["members"] = hermes_channel.member_commands(core, workspace_id)
        _write_policy_file(path, policy)
    from agos_core.actions import agent_profiles

    agent_profiles.write_policies(core, workspace_id)
    return True


def view(core: Core, workspace_id: str) -> dict[str, Any]:
    require_workspace(core, workspace_id)
    from agos_core.actions import team, trusted_apps

    agents = [{"id": a.name, "title": a.title} for a in team.members(core, workspace_id)]
    return {
        "actions": [
            {"key": k, "label": ACTIONS[k], "hint": HINTS.get(k, ""), "default": DEFAULTS[k]}
            for k in ACTIONS
        ],
        "agents": [
            {"id": "*", "title": "Everyone (default)"},
            {"id": "", "title": "Co-Founder"},
            *agents,
        ],
        "rules": shown_rules(core, workspace_id),
        # Apps whose answers don't count as untrusted (read vs act: actions/trusted_apps.py).
        "trustedApps": trusted_apps.listed(core, workspace_id),
    }


def set_rule(core: Core, workspace_id: str, agent: str, action: str, choice: str | None) -> None:
    require_workspace(core, workspace_id)
    if action not in ACTIONS:
        raise ActionError("Unknown action.")
    if choice is not None and choice not in CHOICES:
        raise ActionError("Choose Do it, Ask me or Never.")
    if action == MEMORY:
        _set_memory(core, workspace_id, agent, choice)
        _said(core, workspace_id, agent, action, choice)
        return

    def change(found: dict[str, dict[str, str]]) -> None:
        everyone = _filled(found)["*"]
        mine = found.setdefault(agent, {})
        if choice is None or (agent != "*" and choice == everyone.get(action)):
            mine.pop(action, None)
        else:
            mine[action] = choice
        if not mine:
            found.pop(agent, None)

    if not _change(core, workspace_id, change):
        raise ActionError("The workspace's Hermes isn't ready yet. Try again in a moment.", 503)
    _said(core, workspace_id, agent, action, choice)


def _said(core: Core, workspace_id: str, agent: str, action: str, choice: str | None) -> None:
    who = "everyone" if agent == "*" else (agent or "the Co-Founder")
    add_activity(
        core.db,
        workspace_id,
        kind="autonomy.changed",
        text=f"Autonomy: “{ACTIONS[action]}” for {who} → {choice or 'default'}",
    )
    # A Never for everyone may turn a whole Hermes toolset off: the profile is
    # written again (Hermes's own setting).
    from agos_core.actions import library

    library.apply_workspace(core, workspace_id)


def seed_new_workspace(core: Core, workspace_id: str) -> None:
    """The starting Autonomy table of a just-created workspace, written into its
    Hermes guard once (a file that already has rules keeps them)."""

    def change(found: dict[str, dict[str, str]]) -> None:
        if found:
            return
        for agent, choices in NEW_WORKSPACE.items():
            found[agent] = dict(choices)

    _change(core, workspace_id, change)


# ---- what the plugin reads -------------------------------------------------------


# A "Never" for everyone that Hermes has its own switch for: the whole toolset is
# off (the agent doesn't even see the tool). Files and apps share a toolset with
# reading, so they stay with the guard.
NATIVE: dict[str, tuple[str, ...]] = {
    "commands": ("terminal", "code_execution"),
    "browser": ("browser",),
    "desktop": ("computer_use",),
    "images": ("image_gen", "tts"),
    "memory": ("memory",),
}


def never_toolsets(core: Core, workspace_id: str, member: str | None = None) -> list[str]:
    """Hermes toolsets off because of the owner's "Never" (`agent.disabled_toolsets`).

    - The Co-Founder's profile (`member` None): Never for everyone, and no agent has its
      own rule letting it (an answer there may speak for another agent; the guard
      covers that agent's own rules).
    - A member's own profile (`member`): only that member works in it, so its own
      rule decides (else everyone's)."""
    all_rules = rules(core, workspace_id)
    off: list[str] = []
    for action, toolsets in NATIVE.items():
        if member is not None:
            mine = all_rules.get(member, {}).get(action) or all_rules["*"].get(action)
            if mine == "never":
                off.extend(toolsets)
            continue
        if all_rules["*"].get(action) != "never":
            continue
        if any(r.get(action) not in (None, "never") for a, r in all_rules.items() if a != "*"):
            continue
        off.extend(toolsets)
    return off


# An agent's "Ask me" on learning (memory and skills) is Hermes's own review gate in
# its profile (tools/write_approval.py evaluate_gate: a write is held for his review,
# Workspace → Held-back writes). AGOS reads it from there and writes it only when he
# changes the rule (Hermes's own `config set`); the guard never asks for these writes.
WRITE_GATES = ("memory.write_approval", "skills.write_approval")


def _learning_profiles(core: Core, workspace_id: str) -> list[tuple[str, str]]:
    """(the rules' agent key, its Hermes profile): the Co-Founder ("") and each member."""
    from agos_core.actions import agent_profiles
    from agos_core.actions import team as team_actions

    out = [("", workspace_id)]
    for agent in team_actions.members(core, workspace_id):
        out.append((agent.name, agent_profiles.key(workspace_id, agent.name)))
    return out


def _hermes_asks(core: Core, key: str) -> bool | None:
    """Hermes's write_approval in this profile is on (either gate); None: no profile."""
    from agos_core.engine import config_file

    assert core.engine is not None
    home = core.engine.profile_home(key)
    if not (home / "config.yaml").is_file():
        return None
    cfg = config_file.read(home)
    return any(str(config_file.get(cfg, name)).lower() == "true" for name in WRITE_GATES)


def shown_rules(core: Core, workspace_id: str) -> dict[str, dict[str, str]]:
    """The rules as the card shows them: AGOS's file, with each profile's memory
    Ask me / Do it read from its Hermes write_approval. Everyone's is "Ask me" when a
    profile that follows it asks; a profile that differs shows its own."""
    import copy

    stored = rules(core, workspace_id)
    out = copy.deepcopy(stored)
    if core.engine is None:
        out["*"][MEMORY] = DEFAULTS[MEMORY] if out["*"][MEMORY] == ALLOW else "never"
        return out
    everyone_never = stored["*"].get(MEMORY) == "never"
    values: dict[str, str] = {}
    followers: list[str] = []
    for agent, key in _learning_profiles(core, workspace_id):
        own = stored.get(agent, {}).get(MEMORY)
        if own == "never" or (own is None and everyone_never):
            values[agent] = "never"
            continue
        values[agent] = "ask" if _hermes_asks(core, key) else "do"
        if own is None:
            followers.append(values[agent])
    if everyone_never:
        star = "never"
    elif followers:
        star = "ask" if "ask" in followers else "do"
    else:
        star = DEFAULTS[MEMORY]
    out["*"][MEMORY] = star
    for agent, value in values.items():
        row = out.setdefault(agent, {})
        if value != star:
            row[MEMORY] = value
        else:
            row.pop(MEMORY, None)
        if not row:
            out.pop(agent, None)
    return out


def _set_memory(core: Core, workspace_id: str, agent: str, choice: str | None) -> None:
    """His Learn rule: "never" (and back) in AGOS's file, Ask me / Do it in Hermes."""
    stored = rules(core, workspace_id)
    star = shown_rules(core, workspace_id)["*"][MEMORY]

    def change(found: dict[str, dict[str, str]]) -> None:
        mine = found.setdefault(agent, {})
        if choice == "never":
            mine[MEMORY] = "never"
        elif agent == "*" or choice is None or choice == star:
            mine.pop(MEMORY, None)  # everyone's: not never; an agent's: follows everyone
        else:
            mine[MEMORY] = ALLOW  # its own exception; Ask / Do is its Hermes gate
        if not mine:
            found.pop(agent, None)

    if not _change(core, workspace_id, change):
        raise ActionError("The workspace's Hermes isn't ready yet. Try again in a moment.", 503)
    if choice == "never":
        return
    if agent == "*":
        for member, _key in _learning_profiles(core, workspace_id):
            if MEMORY not in stored.get(member, {}):
                sync_write_gates(core, workspace_id, only=member, want=choice == "ask")
    else:
        want = (choice or (star if star != "never" else DEFAULTS[MEMORY])) == "ask"
        sync_write_gates(core, workspace_id, only=agent, want=want)


def sync_write_gates(
    core: Core, workspace_id: str, only: str | None = None, want: bool | None = None
) -> None:
    """Hermes's write_approval gates of one profile (`only`: "" the Co-Founder, else a
    member) set to `want`, with Hermes's own `config set`, only when they differ.
    `want` None (a member just set up): what everyone's rule shows, when the member
    follows it."""
    engine = core.engine
    if engine is None or only is None:
        return
    from agos_core.actions import agent_profiles
    from agos_core.engine import config_file

    if want is None:
        if MEMORY in rules(core, workspace_id).get(only, {}):
            return  # its own rule: its own gate
        star = shown_rules(core, workspace_id)["*"][MEMORY]
        if star == "never":
            return
        want = star == "ask"
    key = workspace_id if only == "" else agent_profiles.key(workspace_id, only)
    home = engine.profile_home(key)
    if not (home / "config.yaml").is_file():
        return
    cfg = config_file.read(home)
    for name in WRITE_GATES:
        have = config_file.get(cfg, name)
        if have is None or (str(have).lower() == "true") != want:
            hermes_cli.cli(engine, key, "config", "set", name, "true" if want else "false")


def write_policy(core: Core, workspace_id: str) -> None:
    """The plugin's file again: its rules as they are, the members' menu now, and
    each member's own copy."""
    _change(core, workspace_id, lambda found: None)


def plugin_current(home: Path) -> bool:
    """The profile's guard is this AGOS's (same files)."""
    target = home / "plugins" / PLUGIN_NAME
    for source in PLUGIN_SOURCE.iterdir():
        if source.is_file():
            try:
                if (target / source.name).read_bytes() != source.read_bytes():
                    return False
            except OSError:
                return False
    return True


def install_plugin(home: Path) -> None:
    """The guard plugin in the profile (copied fresh; AGOS is its only writer)."""
    target = home / "plugins" / PLUGIN_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{PLUGIN_NAME}.new")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(PLUGIN_SOURCE, tmp, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
