"""Giving a member its kit's files: docs and examples copied into its folder, its memory note and SOUL, its skills, the dispatch sync.
Must not: judge readiness.

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.hire.kit_rules import library_skills
from agos_core.context import Core
from agos_core.engine import hire_kit as rules
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "MEMORY_MARK",
    "copy_docs",
    "sync_dispatch",
]

log = logging.getLogger("agos.hire_kit")  # the old module's logger (one name)

# ---- provisioning ----------------------------------------------------------------------


def _files(core: Core, workspace_id: str) -> Path:
    from agos_core.storage.layout import workspace_paths

    return workspace_paths(core.layout, workspace_id).files


def _inside(base: Path, rel: str) -> Path | None:
    """`rel` under `base`, or None when it would leave it."""
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        return None
    target = (base / rel).resolve()
    with contextlib.suppress(ValueError):
        target.relative_to(base.resolve())
        return target
    return None


def copy_docs(core: Core, workspace_id: str, member: str, kit: dict[str, Any]) -> list[str]:
    """Each kit file that is in the workspace's files and not yet in the member's
    folder is copied there (the owner's original stays). Returns the copied paths."""
    base = _files(core, workspace_id)
    copied = []
    for doc in kit.get("docs") or []:
        if not doc.get("path"):
            continue
        source = _inside(base, str(doc["path"]))
        target = _inside(base, rules.doc_target(member, doc))
        if source is None or target is None or target.exists() or not source.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied.append(rules.doc_target(member, doc))
        except OSError as error:
            log.warning("kit doc %s of %s not copied: %s", doc["path"], member, error)
    return copied


MEMORY_MARK = "My hire kit:"


def _remember(core: Core, workspace_id: str, member: str, kit: dict[str, Any]) -> None:
    """One entry in the member's own memory (Hermes's MEMORY.md): where its kit is."""
    from agos_core.actions import agent_profiles
    from agos_core.engine import identity

    if core.engine is None:
        return
    home = core.engine.profile_home(agent_profiles.key(workspace_id, member))
    tools = ", ".join(t["name"] for t in kit.get("tools") or []) or "none"
    entry = (
        f"{MEMORY_MARK} my files are in /workspace/team/{member}/ (docs/ to follow, "
        f"examples/ of good work); my tools: {tools}; 'Your team' in my SOUL.md says "
        "who I work with."
    )
    try:
        found = identity.read_memory(home, "memory")
        kept = [e for e in found.entries if not e.startswith(MEMORY_MARK)]
        identity.write_memory(home, "memory", [*kept, entry])
    except (identity.IdentityError, OSError) as error:
        log.info("kit memory of %s not written: %s", member, error)


def _rewrite_soul(core: Core, workspace_id: str, member: str) -> None:
    from agos_core.actions import agent_profiles, team

    agent = team.get(core, workspace_id, member)
    if agent is None or core.engine is None:
        return
    agent_profiles.write_soul(
        core,
        workspace_id,
        member,
        title=agent.title,
        instructions=agent.instructions,
        local=agent.local,
        reads=agent.reads,
    )


def _give(core: Core, workspace_id: str, member: str, view: dict[str, Any]) -> bool:
    """What AGOS provisions itself: kit skills that are in the library now, files
    that are in the workspace's files now. True when something changed."""
    from agos_core.actions import agent_revisions, team
    from agos_core.actions import library as library_actions

    kit = view["kit"]
    changed = bool(copy_docs(core, workspace_id, member, kit))
    agent = team.get(core, workspace_id, member)
    if agent is None:
        return changed
    wanted = [s for s in library_skills(core, workspace_id, kit) if s not in agent.skills]
    if wanted:
        definition = {**agent.definition, "skills": [*agent.skills, *wanted]}
        try:
            with agent_revisions.by("agos", "installed its hire kit's skills"):
                library_actions.save_item(
                    core,
                    agent.id,
                    kind="agent",
                    name=member,
                    title=agent.title,
                    summary=agent.summary,
                    definition=definition,
                    workspace_id=workspace_id,
                )
            changed = True
        except ActionError as error:
            log.warning("kit skills of %s not installed: %s", member, error.message)
    return changed


def sync_dispatch(core: Core, workspace_id: str) -> bool:
    """The root's kanban.dispatch_profiles as the team is now (held members out).
    True when Hermes's value changed."""
    from agos_core.actions import agent_profiles
    from agos_core.engine import config_file
    from agos_core.engine.hermes import EngineError

    if core.engine is None:
        return False
    home = core.engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        return False
    value = agent_profiles.dispatch_list(core, workspace_id)
    if config_file.get(config_file.read(home), "kanban.dispatch_profiles") == json.loads(value):
        return False
    try:
        hermes_cli.config_writes(
            core.engine,
            workspace_id,
            [("config", "set", "--force", "kanban.dispatch_profiles", value)],
        )
    except (EngineError, OSError) as error:
        log.warning("dispatch list of %s not written: %s", workspace_id, error)
        return False
    return True
