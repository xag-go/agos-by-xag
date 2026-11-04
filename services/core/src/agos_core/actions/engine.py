"""Keeps each workspace's Hermes profile and sandbox in line with AGOS's data.

Called after every change that affects what an agent may see. Fails closed:
if the sandbox can't be brought in line, the workspace's engine is stopped and
its sandboxes removed, so an old grant never outlives the owner's decision.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import workspaces as repo
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.records import AddedFolder
from agos_core.engine import identity
from agos_core.engine.hermes import EngineError
from agos_core.engine.rules import Grant, MountRefusedError, build_mounts
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.storage.layout import workspace_paths

log = logging.getLogger("agos.engine")


def _grants(core: Core, workspace_id: str) -> list[Grant]:
    """The folders the owner added: Hermes's own list, the `/shared/<name>` mounts in
    the workspace's root profile `terminal.docker_volumes` (rules.grants_in). AGOS
    keeps no list of its own; the old one (folders.move.<ws>, from the dropped
    workspace_folders table) is read only until the next sync has put it into
    Hermes (then it goes: sync_workspace)."""
    legacy = repo.legacy_folders(core.db, workspace_id)
    if legacy:
        return [Grant(name=f.name, host_path=f.host_path, access=f.access) for f in legacy]
    if core.engine is None:
        return []
    from agos_core.engine import config_file
    from agos_core.engine.rules import grants_in

    volumes = config_file.string_list(
        config_file.get(
            config_file.read(core.engine.profile_home(workspace_id)), "terminal.docker_volumes"
        )
    )
    return grants_in(volumes or [])


def folders(core: Core, workspace_id: str) -> list[AddedFolder]:
    """The workspace's added folders as its Hermes mounts them."""
    return [
        AddedFolder(name=g.name, host_path=g.host_path, access=g.access)
        for g in _grants(core, workspace_id)
    ]


def check_grant(core: Core, workspace_id: str, host_path: Path, name: str) -> None:
    """Refuses a folder before it is saved (secrets, Docker, Hermes's home…)."""
    if core.engine is None:
        return
    grants = [
        *_grants(core, workspace_id),
        Grant(name=name, host_path=str(host_path), access="read"),
    ]
    try:
        build_mounts(
            workspace_paths(core.layout, workspace_id).files,
            grants,
            workspaces_dir=core.layout.workspaces,
            forbidden=core.engine.forbidden(core.layout.root),
        )
    except MountRefusedError as error:
        raise ActionError(f"Can't add it: {error}.") from error


def _default_model(core: Core, workspace_id: str) -> tuple[str, str, str] | None:
    """The workspace's model as Hermes runs it (provider slug, model, effort)."""
    from agos_core.engine.models import hermes_slug

    selection = workspace_model(core, workspace_id)
    if selection is None:
        return None
    return hermes_slug(selection.provider, selection.mode), selection.model, selection.effort


# ---- the workspace's default model: Hermes's own (model.*, agent.reasoning_effort) --

_SEEN: dict[str, tuple[float, dict[str, str]]] = {}


def _hermes_model(core: Core, workspace_id: str) -> dict[str, str]:
    """model.provider / model.default / agent.reasoning_effort as the profile's
    config.yaml has them now (read straight from Hermes's file, cached by its time)."""
    if core.engine is None:
        return {}
    return _config_model(workspace_id, core.engine.profile_home(workspace_id) / "config.yaml")


def _config_model(key: str, path: Any) -> dict[str, str]:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return {}
    seen = _SEEN.get(key)
    if seen and seen[0] == stamp:
        return seen[1]
    found: dict[str, str] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line[0].isspace():
            section = line.split(":", 1)[0].strip()
            continue
        if line.startswith("  ") and not line.startswith("   ") and ":" in line:
            key_, _, value = line.strip().partition(":")
            value = value.split(" #", 1)[0].strip().strip("'\"")
            if (section, key_) in (("model", "provider"), ("model", "default")):
                found[key_] = value
            elif (section, key_) == ("agent", "reasoning_effort"):
                found["effort"] = value
    _SEEN[key] = (stamp, found)
    return found


def shared_model(core: Core) -> Any:
    """The model a NEW workspace starts on: the shared Hermes home's own model.* and
    agent.reasoning_effort (the home General Settings writes; the owner sets it with
    `hermes model` there). None when that home has no model (Hermes's own default
    config leaves `model.default` empty)."""
    from agos_core.engine.models import selection_from_hermes

    if core.engine is None:
        return None
    got = _config_model("", core.engine.settings.hermes_home / "config.yaml")
    return selection_from_hermes(got.get("provider", ""), got.get("default", ""), got.get("effort"))


def workspace_model(core: Core, workspace_id: str) -> Any:
    """The workspace's default model: Hermes's own (the Co-Founder profile's model.* and
    agent.reasoning_effort), the one copy. None before the profile has one."""
    from agos_core.engine.models import selection_from_hermes

    got = _hermes_model(core, workspace_id)
    return selection_from_hermes(got.get("provider", ""), got.get("default", ""), got.get("effort"))


def set_model(core: Core, workspace_id: str, selection: Any) -> None:
    """The owner picked the workspace's model: written into its Hermes (only there)."""
    from agos_core.engine.models import hermes_slug
    from agos_core.engine.rules import model_pairs

    if core.engine is None:
        return
    pairs = model_pairs(
        hermes_slug(selection.provider, selection.mode), selection.model, selection.effort
    )
    # One Hermes process for the 3-4 keys (Hermes's own writer, in this order: a
    # provider change drops the old route there), only the ones that changed.
    hermes_cli.config_writes(
        core.engine, workspace_id, [("config", "set", key, value) for key, value in pairs.items()]
    )
    _SEEN.pop(workspace_id, None)


VERIFY_TRIES = 4
VERIFY_WAIT_SECONDS = 5.0


def _mismatched(
    engine: Any, workspace_id: str, mounts: Any, shared: tuple[Any, ...] = ()
) -> list[Any]:
    """Live sandboxes that don't match the grants. Right after an update the old
    gateway's sandbox may still be going away (seen at every restart: the agent
    was stopped for nothing, then came back): a mismatch is checked again a few
    times before the agent is stopped. A real mismatch still stops it."""
    import time

    bad: list[Any] = []
    for attempt in range(VERIFY_TRIES):
        bad = [
            (cid, check)
            for cid, check in engine.verify(workspace_id, mounts, shared)
            if not check.ok
        ]
        if not bad:
            return []
        if attempt < VERIFY_TRIES - 1:
            time.sleep(VERIFY_WAIT_SECONDS)
    return bad


def workspace_description(core: Core, workspace_id: str) -> str:
    """The workspace's description: its Co-Founder's (root profile's) Hermes description."""
    if core.engine is None:
        return ""
    from agos_core.engine import profile_meta

    return profile_meta.description(profile_meta.read(core.engine.profile_home(workspace_id)))


def workspace_name(core: Core, workspace_id: str) -> str:
    """The workspace's name: its Co-Founder's (root profile's) Hermes display name."""
    if core.engine is None:
        return ""
    from agos_core.engine import profile_meta

    return profile_meta.display_name(profile_meta.read(core.engine.profile_home(workspace_id)))


def move_name(core: Core, workspace_id: str) -> bool:
    """The workspace's name waiting in AGOS goes into its Hermes: the Co-Founder's
    profile.yaml `display_name` (Hermes's write_profile_meta, what `hermes profile
    rename default <name>` writes for a root's own profile), then AGOS's copy goes.
    Kept waiting (shown from there) while the engine is off or the profile isn't
    made yet; tried again at every sync."""
    waiting = repo.pending_name(core.db, workspace_id)
    if waiting is None or core.engine is None:
        return False
    home = core.engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        return False
    from agos_core.engine import profile_meta

    try:
        with profile_meta.locked(home):
            if profile_meta.display_name(profile_meta.read(home)) != waiting.strip():
                core.engine.set_display_name(home, waiting.strip())
    except (EngineError, OSError) as error:
        log.warning("name of %s not in Hermes yet: %s", workspace_id, error)
        return False
    with transaction(core.db):
        repo.drop_pending_name(core.db, workspace_id, waiting)
    return True


def move_names(core: Core) -> int:
    """At start: every name still waiting (the step-28 migration's) goes into its
    Hermes (a workspace in the trash too: its profile stays until it's purged)."""
    rows = core.db.execute(
        "SELECT key FROM app_settings WHERE key LIKE ?", (repo.MOVE_NAME + "%",)
    ).fetchall()
    return sum(move_name(core, str(r["key"])[len(repo.MOVE_NAME) :]) for r in rows)


def move_description(core: Core, workspace_id: str) -> bool:
    """The workspace's description waiting in AGOS goes into its Hermes: the Co-Founder's
    profile.yaml `description` (Hermes's write_profile_meta, what `hermes profile
    describe --text` writes), then AGOS's copy goes. Kept waiting (shown from there)
    while the engine is off or the profile isn't made yet; tried again at every sync."""
    waiting = repo.pending_description(core.db, workspace_id)
    if waiting is None or core.engine is None:
        return False
    home = core.engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        return False
    from agos_core.engine import profile_meta

    try:
        with profile_meta.locked(home):
            if profile_meta.description(profile_meta.read(home)) != waiting.strip():
                core.engine.set_description(home, waiting.strip())
    except (EngineError, OSError) as error:
        log.warning("description of %s not in Hermes yet: %s", workspace_id, error)
        return False
    with transaction(core.db):
        repo.drop_pending_description(core.db, workspace_id, waiting)
    return True


def sync_workspace(
    core: Core, workspace_id: str, grants: list[Grant] | None = None, *, members: bool = False
) -> None:
    """Profile config = the folders (Hermes's own list, or `grants` when the owner
    changes it); sandbox rebuilt; live sandboxes verified. `members`: the team's
    members take a new sandbox setup in the root's same restart (a folder click)."""
    engine = core.engine
    if engine is None:
        return
    if repo.get_workspace(core.db, workspace_id) is None:
        # Deleted (or purged) meanwhile: a late sync must never bring back its
        # profile, folders or network.
        log.warning("sync of %s skipped: the workspace is gone", workspace_id, stack_info=True)
        return
    new = not (engine.profile_home(workspace_id) / "config.yaml").is_file()
    # The model and the fallback models are Hermes's own: set only when the owner
    # picks them (set_model; General settings → Fallback models).
    try:
        result = engine.apply(
            workspace_id,
            files_dir=workspace_paths(core.layout, workspace_id).files,
            workspaces_dir=core.layout.workspaces,
            agos_data=core.layout.root,
            # Hermes's own list, read once the setup is this apply's (a folder
            # click written meanwhile is never written back over).
            grants=(lambda: _grants(core, workspace_id)) if grants is None else grants,
            members=_team_members(core, workspace_id) if members else (),
        )
        # AGOS's old folder list is in Hermes now (written just above): it goes.
        if repo.drop_legacy_folders(core.db, workspace_id):
            log.info("added folders of %s: Hermes's list now", workspace_id)
        # A name and a description waiting in AGOS (new workspace, or an old row) go
        # into Hermes.
        move_name(core, workspace_id)
        move_description(core, workspace_id)
        if new:
            # The loop detector, run budget, fallback chain, time limits and
            # timezone: Hermes's managed scope, read by every workspace (nothing to
            # copy, actions/hermes_managed.py).
            from agos_core.actions import hermes_all_settings

            # What the owner changed in Settings → Hermes settings, where every
            # other workspace has it.
            hermes_all_settings.give_new_profile(core, workspace_id)
            from agos_core.actions import memory_plugin

            memory_plugin.install_new(core, workspace_id)
        from agos_core.actions import workspace_skills

        # Hermes mounts each profile's skills.external_dirs read-only: the shared
        # folders, and the workspace's own skill folder for its members.
        own = workspace_skills.folder(core, workspace_id)
        shared = (*workspace_skills.shared_dirs(core), *([own] if own is not None else []))
        bad = _mismatched(engine, workspace_id, result.mounts, shared)
        if bad:
            log.error(
                "sandbox check of %s failed: %s",
                workspace_id,
                "; ".join(
                    f"{cid[:12]} missing={c.missing} unexpected={c.unexpected}" for cid, c in bad
                ),
            )
            raise EngineError("a sandbox does not match the folders you allowed")
        write_identity(core, workspace_id)
        from agos_core.actions import general_sync

        general_sync.sync(core, workspace_id)  # General Settings, into its own root
        from agos_core.actions import tool_keys

        tool_keys.share(core, workspace_id)  # Settings → Keys, into every member
        from agos_core.actions import library  # late: library needs workspaces

        library.apply_workspace(core, workspace_id)
    except (EngineError, MountRefusedError, OSError) as error:
        _blocked(core, workspace_id, error)


def _team_members(core: Core, workspace_id: str) -> list[tuple[str, Any]]:
    """The team's members whose profiles exist, each with the model it runs on (as
    the team's own re-sync applies them, actions/agent_profiles)."""
    from agos_core.actions import agent_profiles

    made = {agent for _ws, agent in agent_profiles.existing(core, workspace_id)}
    return [
        (
            agent_profiles.key(workspace_id, str(i.name)),
            agent_profiles.model_of(core, workspace_id, i),
        )
        for i in agent_profiles.team(core, workspace_id)
        if str(i.name) in made
    ]


def _blocked(core: Core, workspace_id: str, error: Exception) -> NoReturn:
    """A sync that failed: fail closed (the workspace stopped, its sandboxes gone),
    the Log says it, the owner is told why."""
    log.error("sync failed for %s: %s", workspace_id, error)
    stopped = _fail_closed(core, workspace_id)
    add_activity(
        core.db,
        workspace_id,
        kind="engine.blocked",
        text="The agent was stopped: its sandbox could not be updated"
        if stopped
        else "The agent's sandbox could not be updated or stopped",
    )
    raise ActionError(
        "Saved, but the agent's sandbox could not be updated, so the agent is stopped. "
        "Check that Docker is running, then open the workspace again.",
        503,
    ) from error


def save_folders(core: Core, workspace_id: str, grants: list[Grant]) -> None:
    """The owner's folder click, its first half: Hermes's terminal.docker_volumes
    (and the other sandbox keys a sync writes) take the new folders now, by
    Hermes's own writer. The restart that makes the running gateway and its
    sandboxes take them (ADR 0010) follows in the background (restart_later), so
    the click answers in a second, not after 20-40 s. Fails closed like a sync."""
    engine = core.engine
    if engine is None:
        return
    if repo.get_workspace(core.db, workspace_id) is None:
        log.warning("folders of %s not saved: the workspace is gone", workspace_id)
        return
    try:
        engine.apply(
            workspace_id,
            files_dir=workspace_paths(core.layout, workspace_id).files,
            workspaces_dir=core.layout.workspaces,
            agos_data=core.layout.root,
            # In the order Hermes's list is read back (rules.grants_in), so the
            # restart's own apply finds it as written (no second write).
            grants=sorted(grants, key=lambda g: g.name),
            restart=False,
        )
    except (EngineError, MountRefusedError, OSError) as error:
        _blocked(core, workspace_id, error)
    # AGOS's old folder list is in Hermes now (written just above): it goes, so the
    # restart reads Hermes's list.
    if repo.drop_legacy_folders(core.db, workspace_id):
        log.info("added folders of %s: Hermes's list now", workspace_id)


# The restart after a folder click (stop, drop the sandboxes, start, verify: a whole
# sync) runs in the background, one per workspace at a time; clicks in a row are one
# restart, the newest setup (Hermes's list when it starts) wins. Tests run it at once.
RESTART_IN_BACKGROUND = True
RESTART_SETTLE_S = 2.0  # a click this soon after the last one joins its restart


@dataclass
class _Restart:
    state: Literal["restarting", "done", "failed"] = "done"
    reason: str = ""
    running: bool = False
    again: bool = False  # a click came after this round read Hermes's list
    last: float = 0.0  # time.monotonic() of the newest click


_RESTARTS: dict[str, _Restart] = {}
_RESTARTS_LOCK = threading.Lock()


def restart_later(core: Core, workspace_id: str) -> None:
    """The gateway restart a folder click needs, after the click's answer."""
    with _RESTARTS_LOCK:
        job = _RESTARTS.setdefault(workspace_id, _Restart())
        job.state, job.reason, job.last = "restarting", "", time.monotonic()
        if job.running:
            job.again = True  # the round running now, or the next one, takes it
            return
        job.running = True
    if not RESTART_IN_BACKGROUND:
        _restart(core, workspace_id, job)
        return
    threading.Thread(
        target=_restart, args=(core, workspace_id, job), name=f"restart-{workspace_id}", daemon=True
    ).start()


def restart_state(workspace_id: str) -> tuple[Literal["restarting", "done", "failed"], str]:
    """The folder click's restart for the page: restarting, done (also: none since
    the core started), or failed with the reason the owner reads."""
    with _RESTARTS_LOCK:
        job = _RESTARTS.get(workspace_id)
        return (job.state, job.reason) if job is not None else ("done", "")


def _settle(job: _Restart) -> None:
    """Waits until no click came for RESTART_SETTLE_S (clicks in a row: one restart)."""
    while (left := job.last + RESTART_SETTLE_S - time.monotonic()) > 0:
        time.sleep(min(left, 0.5))


def _restart(core: Core, workspace_id: str, job: _Restart) -> None:
    while True:
        _settle(job)
        with _RESTARTS_LOCK:
            job.again = False
        reason = ""
        try:
            # The same sync a click ran before (same stop, quiet-stop marker, waits,
            # verify; fail closed when it fails), on Hermes's list as it is now.
            sync_workspace(core, workspace_id, members=True)
        except ActionError as error:
            reason = error.message
        except Exception:  # a thread: never lost silently
            log.exception("restart of %s failed", workspace_id)
            reason = "The agent's restart failed. Open the workspace again to retry."
        with _RESTARTS_LOCK:
            if job.again:
                continue  # a newer click: one more round, with its setup
            job.running = False
            job.state, job.reason = ("failed", reason) if reason else ("done", "")
            return


def own_identity(core: Core, workspace_id: str) -> str:
    """The owner's identity text, read from the workspace's SOUL.md (its only home;
    "" = the default)."""
    workspace = repo.get_workspace(core.db, workspace_id)
    if core.engine is None or workspace is None:
        return ""
    path = core.engine.profile_home(workspace_id) / "SOUL.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    return identity.own_identity(text) or ""


def write_identity(core: Core, workspace_id: str, own: str | None = None) -> bool:
    """SOUL.md = the workspace's identity + AGOS's rules + the Co-Founder's view of the
    workspace (`own`: the owner's new text; None keeps the one SOUL.md has). False
    when the profile doesn't exist yet."""
    engine = core.engine
    workspace = repo.get_workspace(core.db, workspace_id)
    if engine is None or workspace is None:
        return False
    home = engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        return False
    from agos_core.actions import owner_rules

    # His rules for every workspace: Hermes's own user profile (USER.md); the Brain
    # is shared Hermes skills (workspace_skills.shared_dirs), not in the identity.
    try:
        owner_rules.sync_profile(core, home)
    except OSError:
        log.exception("could not write USER.md for %s", workspace_id)

    from agos_core.actions import goals

    text = identity.soul_text(
        workspace.name,
        workspace.description,
        own_identity(core, workspace_id) if own is None else own,
        cofounder=cofounder_view(core, workspace_id),
        goal=goals.prompt_for(core, workspace_id),
    )
    try:
        identity.write_soul(home, text)
    except OSError:
        log.exception("could not write SOUL.md for %s", workspace_id)
        return False
    return True


def cofounder_view(core: Core, workspace_id: str) -> str:
    """What only AGOS knows about this workspace, for its Co-Founder: its apps and tools
    (on / off), how to change automations, skills, agents and docs, its team and
    where each member's Hermes is. It lives in the Co-Founder's SOUL.md."""
    from agos_core.actions import capabilities, cofounder_actions  # late: they import chat

    try:
        asks = capabilities.instructions(core, workspace_id)
        doing = cofounder_actions.instructions(core, workspace_id)
    except (ActionError, OSError) as error:  # never block an answer on this text
        log.warning("the Co-Founder's view of %s not made: %s", workspace_id, error)
        return ""
    from agos_core.actions import tool_keys

    keys = tool_keys.cofounder_note(core, workspace_id)  # names only, never a value
    return "\n\n".join(p for p in (asks, doing, keys, _cofounder_knows(core, workspace_id)) if p)


def _cofounder_knows(core: Core, workspace_id: str) -> str:
    """How the Co-Founder knows the whole project: Hermes's own records, read when
    needed (no AGOS copy). Only this workspace's: its own Hermes and its members'."""
    from agos_core.actions import agent_profiles

    members = (
        [
            f"{core.engine.profile(agent_profiles.key(workspace_id, n))} (@{n})"
            for n in agent_profiles.team_names(core, workspace_id)
        ]
        if core.engine is not None
        else []
    )
    team_line = (
        "Each team member is its own Hermes; read its conversations with "
        "session_search and profile=<its profile>: " + ", ".join(members) + "."
        if members
        else "There are no team members yet."
    )
    return (
        "## You are the Co-Founder: you know the whole project\n"
        "When the owner asks what happened, who said what, or where something stands, "
        "look it up in Hermes before answering, and say where it was said:\n"
        "- conversations: session_search (your own: this chat, Telegram, groups, "
        "Sessions). " + team_line + "\n"
        "- the work: the Kanban (kanban_list, kanban_show: cards, results, comments, "
        "who did what).\n"
        "- automations: their runs are Kanban cards, their schedules are in "
        "cronjob_manage (action list).\n"
        "Never look at another workspace's Hermes: only the profiles named here."
    )


def refresh_cofounder_view(core: Core, workspace_id: str) -> None:
    """The Co-Founder's view in SOUL.md made current. Hermes reads SOUL.md when a
    conversation starts (and keeps that system prompt for the conversation, its
    prompt cache): a conversation going on keeps the view it started with, a new
    one reads this one."""
    workspace = repo.get_workspace(core.db, workspace_id)
    if core.engine is None or workspace is None:
        return
    home = core.engine.profile_home(workspace_id)
    path = home / "SOUL.md"
    if not (home / "config.yaml").is_file():
        return
    soul = path.read_text(encoding="utf-8") if path.is_file() else ""
    now = cofounder_view(core, workspace_id)
    from agos_core.actions import goals

    aim = goals.prompt_for(core, workspace_id)
    if identity.cofounder_view(soul) != now.strip() or identity.goal_of(soul) != aim.strip():
        text = identity.soul_text(
            workspace.name,
            workspace.description,
            own_identity(core, workspace_id),
            cofounder=now,
            goal=aim,
        )
        try:
            identity.write_soul(home, text)
        except OSError:
            log.exception("could not write SOUL.md for %s", workspace_id)


def write_all_identities(core: Core) -> int:
    """On startup: every workspace's SOUL.md matches AGOS's data (migration), and its
    team members' (who each is, the owner's rules)."""
    from agos_core.actions import agent_profiles

    done = 0
    for w in repo.list_workspaces(core.db, include_archived=True):
        done += write_identity(core, w.id)
        agent_profiles.write_texts(core, w.id)
    return done


def _fail_closed(core: Core, workspace_id: str) -> bool:
    if core.engine is None:
        return True
    try:
        core.engine.park(workspace_id)
    except (EngineError, OSError):
        log.exception("could not stop %s after a failed sync", workspace_id)
        return False
    return True


def park_workspace(core: Core, workspace_id: str) -> None:
    """Archived or in the trash: nothing runs for it."""
    if core.engine is None:
        return
    try:
        core.engine.park(workspace_id)
    except (EngineError, OSError) as error:
        log.error("park failed for %s: %s", workspace_id, error)
        raise ActionError(
            "The workspace's agent could not be stopped. Is Docker running?", 503
        ) from error


def delete_engine_data(core: Core, workspace_id: str) -> None:
    """Purged for good: the Hermes profile (memory, sessions, keys) goes too."""
    if core.engine is None:
        return
    try:
        core.engine.delete_profile(workspace_id)
    except (EngineError, OSError):
        log.exception("could not delete the engine data of %s", workspace_id)
    from agos_core.actions import agent_profiles

    agent_profiles.remove_for_workspace(core, workspace_id)


def _finish(core: Core, workspace_id: str, finish: Callable[[Core, str], list[str]]) -> None:
    """A create that left setup steps (its saga needs attention): Hermes may take them
    now. One that still can't stays journaled for the next try, never stops the start."""
    try:
        left = finish(core, workspace_id)
    except Exception:
        log.exception("setup of %s not finished at start", workspace_id)
        return
    if left:
        log.warning("setup of %s still not finished: %s", workspace_id, ", ".join(left))


async def resync_all(core: Core, *, finish: Callable[[Core, str], list[str]] | None = None) -> None:
    """At startup: every active workspace's sandbox is brought in line, then `finish`
    (the Workspace service's finish_setup, handed in by the start) runs the setup
    steps its create left to finish, if any."""
    import asyncio

    from agos_core.actions import team_files

    for workspace in repo.list_workspaces(core.db):
        if repo.get_workspace(core.db, workspace.id) is None:
            continue  # deleted while this ran: never brought back to life
        try:
            # Once: the old hand-kept masters in playbooks/ make way for the one
            # copy AGOS shows there (nothing deleted: moved to archive/).
            report = await asyncio.to_thread(team_files.adopt, core, workspace.id)
            if report["archived"] or report["files_added"]:
                log.info("playbooks of %s: one copy now %s", workspace.id, report)
                add_activity(
                    core.db,
                    workspace.id,
                    kind="playbooks.one_copy",
                    text="playbooks/agents and automations now show what the team "
                    f"uses (old copies kept in {report['archived'] or 'place'}; "
                    f"{len(report['files_added'])} skill file(s) added to the skills)",
                )
        except Exception:  # never blocks the sandbox sync below
            log.exception("playbooks of %s not moved to one copy", workspace.id)
        if repo.get_workspace(core.db, workspace.id) is None:
            continue
        try:
            await asyncio.to_thread(sync_workspace, core, workspace.id)
        except ActionError as error:
            log.warning("startup sync of %s failed: %s", workspace.id, error.message)
        if finish is not None:
            await asyncio.to_thread(_finish, core, workspace.id, finish)
