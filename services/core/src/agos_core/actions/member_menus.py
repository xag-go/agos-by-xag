"""When the members' Telegram menus need a look: only after the team or a group changed.

A workspace's "/" menu on Telegram lists the members of its Telegram groups
(hermes_channel.sync_member_menus writes them into the agos-guard policy and
Hermes's command_menu.priority). Building that list reads every member's Hermes
profile. Before, it ran twice a second for every workspace with a bot. Now a cheap
mark is taken first: the groups' member lists (AGOS's database), the root's
profiles folder (a member added or deleted), each named member's profile.yaml
(its job title) and parked marker (on or off), and the policy file itself. Only
these are stat()ed: no file is read. The menus are rebuilt for a workspace only
when its mark moved since the last rebuild that worked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agos_core.context import Core

# The workspace's Hermes home → the mark of its last rebuild that worked (per process).
_DONE: dict[str, tuple[Any, ...]] = {}


def _key(core: Core, workspace_id: str) -> str:
    assert core.engine is not None
    return str(core.engine.profile_home(workspace_id))


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        found = path.stat()
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size)


def mark(core: Core, workspace_id: str) -> tuple[Any, ...]:
    """What the workspace's menu depends on, without reading any profile."""
    from agos_core.actions import hermes_channel, team
    from agos_core.engine.profile_meta import PARKED, PROFILE_YAML
    from agos_core.shared.guard_contract import POLICY_FILE

    assert core.engine is not None
    groups = sorted(
        str(r["members"] or "")
        for r in core.db.execute(
            """SELECT DISTINCT c.members FROM chat_addresses a
                 JOIN chats c ON c.id = a.chat_id
                 JOIN channel_connections k ON k.id = a.connection_id
               WHERE c.kind = 'group' AND NOT agos_hidden(c.id, c.workspace_id, c.kind, c.deleted_at) AND agos_bot_on(k.workspace_id)
                 AND k.engine = ? AND a.address LIKE '-%' AND c.workspace_id = ?""",
            (hermes_channel.ENGINE_HERMES, workspace_id),
        ).fetchall()
    )
    names: set[str] = set()
    for raw in groups:
        try:
            listed = json.loads(raw) if raw else []
        except ValueError:
            listed = []
        names |= {str(n) for n in listed if isinstance(n, str)}
    members = []
    for name in sorted(names):
        where = team.home(core, workspace_id, name)
        if where is None:
            continue
        members.append((name, _stat(where / PROFILE_YAML), (where / PARKED).exists()))
    return (
        tuple(groups),
        _stat(core.engine.root(workspace_id) / "profiles"),
        tuple(members),
        _stat(core.engine.profile_home(workspace_id) / POLICY_FILE),
    )


def changed(core: Core) -> set[str]:
    """The workspaces with a bot whose mark moved since their last rebuild."""
    from agos_core.actions import hermes_channel

    if core.engine is None:
        return set()
    out = set()
    for r in core.db.execute(
        "SELECT DISTINCT workspace_id FROM channel_connections WHERE engine = ? AND agos_bot_on(workspace_id)",
        (hermes_channel.ENGINE_HERMES,),
    ).fetchall():
        workspace_id = str(r["workspace_id"] or "")
        if workspace_id and _DONE.get(_key(core, workspace_id)) != mark(core, workspace_id):
            out.add(workspace_id)
    return out


def sync(core: Core) -> int:
    """The menus of the workspaces whose team or groups changed; the others are left
    alone. Returns how many workspaces were looked at."""
    from agos_core.actions import hermes_channel

    todo = changed(core)
    if not todo:
        return 0
    marks = {ws: mark(core, ws) for ws in todo}
    hermes_channel.sync_member_menus(core, only=todo)
    for ws in todo:
        # The policy file may have been written just now: take its new mark.
        after = mark(core, ws)
        _DONE[_key(core, ws)] = after if after[:3] == marks[ws][:3] else marks[ws]
    return len(todo)
