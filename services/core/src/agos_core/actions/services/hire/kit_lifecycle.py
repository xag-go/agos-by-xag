"""A kit's life: provisioned on approve, saved by the owner, dropped, shown in the Inbox.
Must not: hold the readiness rules (readiness does).

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.hire import kit_files  # sync_dispatch: looked up there
from agos_core.actions.services.hire.kit_files import (
    MEMORY_MARK,
    _remember,
    _rewrite_soul,
    copy_docs,
)
from agos_core.actions.services.hire.kit_rules import fill, kit_problems
from agos_core.actions.services.hire.kit_store import (
    KIT_FACT,
    _home,
    _store,
    forget_pending,
    kit_members,
    kit_of,
)
from agos_core.actions.services.hire.onboarding import advance
from agos_core.actions.services.hire.readiness import readiness
from agos_core.context import Core
from agos_core.db import member_readiness as readiness_repo
from agos_core.db.connection import transaction
from agos_core.engine import hire_kit as rules
from agos_core.engine import profile_meta

__all__ = [
    "drop_kit",
    "inbox_items",
    "provision",
    "save_kit",
]

log = logging.getLogger("agos.hire_kit")  # the old module's logger (one name)


def provision(
    core: Core, workspace_id: str, member: str, kit: dict[str, Any], *, fresh: bool = True
) -> dict[str, Any] | None:
    """After the hire (or the owner's kit edit): the kit on the member, its files
    copied, its SOUL 'Your team' section and memory written, then readiness moves on.
    `fresh`: a new hire (the owner's earlier choices for that name go)."""
    if fresh:
        with transaction(core.db):
            readiness_repo.clear_member(core.db, workspace_id, member)
    _store(core, workspace_id, member, kit)
    copy_docs(core, workspace_id, member, kit)
    _rewrite_soul(core, workspace_id, member)
    _remember(core, workspace_id, member, kit)
    return advance(core, workspace_id, member)


def save_kit(core: Core, workspace_id: str, member: str, raw: dict[str, Any]) -> dict[str, Any]:
    """The owner's own kit for a member (his own hire, or a member hired before kits)."""
    from agos_core.actions import team
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    agent = team.get(core, workspace_id, member)
    if agent is None:
        raise NotFoundError("This member")
    before = kit_of(core, workspace_id, member) or {}
    kit = fill(core, workspace_id, raw)
    problems = kit_problems(core, workspace_id, kit)
    if problems:
        raise ActionError("; ".join(problems) + ".")
    for key in ("goal_id", "telegram_topic"):
        if key in before:
            kit[key] = before[key]
    shown = provision(core, workspace_id, member, kit, fresh=False)
    assert shown is not None
    return shown


def drop_kit(core: Core, workspace_id: str, member: str) -> None:
    """Back to no kit (the Undo of a member's first kit): the kit fact leaves its
    profile, its SOUL's 'Your team' section and its kit memory entry go, and it is
    no longer held from work. Its own memory, sessions and copied files stay."""
    from agos_core.actions import agent_profiles
    from agos_core.engine import identity

    home = _home(core, workspace_id, member)
    if home is None:
        raise NotFoundError("This member")
    with profile_meta.locked(home):
        facts = profile_meta.agos(profile_meta.read_fresh(home))
        if facts.pop(KIT_FACT, None) is not None:
            profile_meta.write(home, agos_facts=facts)
    forget_pending(workspace_id, member)
    _rewrite_soul(core, workspace_id, member)
    if core.engine is not None:
        mem = core.engine.profile_home(agent_profiles.key(workspace_id, member))
        try:
            found = identity.read_memory(mem, "memory")
            kept = [e for e in found.entries if not e.startswith(MEMORY_MARK)]
            if len(kept) != len(found.entries):
                identity.write_memory(mem, "memory", kept)
        except (identity.IdentityError, OSError) as error:
            log.info("kit memory of %s not cleared: %s", member, error)
    kit_files.sync_dispatch(core, workspace_id)


# ---- the owner's Inbox ------------------------------------------------------------------


def inbox_items(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """One item per member that waits for the owner: items only he can give
    (connect, a key, a file, a decision), or an onboarding test that failed every try."""
    out = []
    for member in kit_members(core, workspace_id):
        view = readiness(core, workspace_id, member)
        if view is None or view["state"] == "ready":
            continue
        mine = [i for i in view["items"] if i["state"] == "missing" and i["owner"]]
        escalated = bool(view["onboarding"] and view["onboarding"]["escalated"])
        if not mine and not escalated:
            continue
        stamp = rules.missing_digest([i["id"] for i in mine] + (["escalated"] if escalated else []))
        title = (
            f"@{member}'s onboarding test failed {rules.MAX_TRIES} times"
            if escalated and not mine
            else f"@{member} isn't ready yet: {len(mine)} thing{'s' if len(mine) != 1 else ''} need you"
        )
        out.append(
            {
                "key": f"readiness:{member}:{stamp}",
                "title": title,
                "member": member,
                "memberName": view["title"],
                "readiness": view,
            }
        )
    return out
