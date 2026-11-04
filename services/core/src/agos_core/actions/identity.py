"""Workspace identity (SOUL.md) and the agent's memory, as the owner sees them."""

from typing import Literal

from agos_core.actions.engine import own_identity, write_identity
from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.db.records import Record
from agos_core.engine import identity as soul
from agos_core.engine.identity import IdentityError, MemoryTarget


class MemoryView(Record):
    target: Literal["memory", "user"]
    entries: list[str]
    used: int
    limit: int


class IdentityView(Record):
    # What the owner wrote; empty means the default below is used.
    identity: str
    default_identity: str
    rules: str
    # The exact SOUL.md Hermes loads (identity + rules).
    soul: str
    # False while the workspace's engine isn't set up (nothing written yet).
    ready: bool
    memory: MemoryView
    user: MemoryView


def _memory_view(memory: soul.Memory) -> MemoryView:
    return MemoryView(
        target=memory.target, entries=memory.entries, used=memory.used, limit=memory.limit
    )


def get_identity(core: Core, workspace_id: str) -> IdentityView:
    workspace = require_workspace(core, workspace_id)
    own = own_identity(core, workspace_id)
    home = core.engine.profile_home(workspace_id) if core.engine else None
    ready = home is not None and (home / "config.yaml").is_file()
    empty = soul.Memory("memory", [], soul.LIMITS["memory"])
    on_disk = home / "SOUL.md" if home is not None and ready else None
    return IdentityView(
        identity=own,
        default_identity=soul.default_identity(workspace.name, workspace.description),
        rules=soul.RULES,
        # The exact SOUL.md Hermes loads (with the Co-Founder's view of the workspace).
        soul=on_disk.read_text(encoding="utf-8")
        if on_disk is not None and on_disk.is_file()
        else soul.soul_text(workspace.name, workspace.description, own),
        ready=ready,
        memory=_memory_view(soul.read_memory(home, "memory") if home and ready else empty),
        user=_memory_view(
            soul.read_memory(home, "user")
            if home and ready
            else soul.Memory("user", [], soul.LIMITS["user"])
        ),
    )


def save_identity(core: Core, workspace_id: str, text: str) -> None:
    require_workspace(core, workspace_id)
    try:
        value = soul.check_identity(text)
    except IdentityError as error:
        raise ActionError(str(error)) from error
    if not write_identity(core, workspace_id, own=value):
        raise ActionError("This workspace's agent isn't set up yet.", 409)
    add_activity(
        core.db, workspace_id, kind="identity.changed", text="Agent identity updated (next session)"
    )


def save_memory(core: Core, workspace_id: str, target: MemoryTarget, entries: list[str]) -> None:
    require_workspace(core, workspace_id)
    if core.engine is None:
        raise ActionError("The engine is off, so there is no memory to edit.", 409)
    home = core.engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        raise ActionError("This workspace's agent isn't set up yet.", 409)
    try:
        soul.write_memory(home, target, entries)
    except IdentityError as error:
        raise ActionError(str(error)) from error
    add_activity(
        core.db,
        workspace_id,
        kind="memory.changed",
        text=f"{'Agent memory' if target == 'memory' else 'What the agent knows about you'} edited",
    )
