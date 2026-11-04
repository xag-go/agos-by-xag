"""The apps the owner trusts in a workspace (read vs act, owner decision 2026-11-03).

An app or MCP server's answer (Hermes's `mcp_<server>_*` tools) counts as untrusted
content by default: a session that read one asks him before any power action
(agos_guard/taint_sources.py). The apps he names here are his own (his Linear, his
own MCP server): their answers don't mark the session. Empty by default.

Kept where the plugin reads it, beside his Autonomy rules: the workspace's agos-guard
policy file (`trustedApps`, actions/autonomy.py's one copy), and each member's copy
(actions/agent_profiles.py). Settings → Autonomy → Trusted apps; the Co-Founder's
`set_trusted_apps` (an owner-only power: its card waits for his yes, with Undo).
"""

from __future__ import annotations

import re

from agos_core.actions.errors import ActionError
from agos_core.context import Core

KEY = "trustedApps"
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX = 50


def listed(core: Core, workspace_id: str) -> list[str]:
    from agos_core.actions import autonomy

    found = autonomy._read_policy(core, workspace_id).get(KEY)
    return [str(n) for n in found if isinstance(n, str)] if isinstance(found, list) else []


def clean(names: list[str]) -> list[str]:
    out: list[str] = []
    for raw in names:
        name = str(raw).strip().lower()
        if not name:
            continue
        if not _NAME.match(name):
            raise ActionError(f"“{name[:64]}” isn't an app's name (letters, digits, - and _).")
        if name not in out:
            out.append(name)
    if len(out) > MAX:
        raise ActionError(f"At most {MAX} trusted apps.")
    return out


def save(core: Core, workspace_id: str, names: list[str]) -> list[str]:
    """His list (the old one is returned, for Undo)."""
    from agos_core.actions import agent_profiles, autonomy
    from agos_core.actions.workspaces import require_workspace
    from agos_core.db.activity import add_activity

    require_workspace(core, workspace_id)
    wanted = clean(names)
    path = autonomy._policy_file(core, workspace_id)
    if path is None or not path.parent.is_dir():
        raise ActionError("The workspace's Hermes isn't ready yet. Try again in a moment.", 503)
    with autonomy._write_lock:
        policy = autonomy._read_policy(core, workspace_id)
        before = listed(core, workspace_id)
        policy[KEY] = wanted
        autonomy._write_policy_file(path, policy)
    agent_profiles.write_policies(core, workspace_id)
    shown = ", ".join(wanted) or "none"
    add_activity(core.db, workspace_id, kind="autonomy.changed", text=f"Trusted apps → {shown}")
    return before
