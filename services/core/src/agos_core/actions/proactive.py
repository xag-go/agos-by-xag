"""The learning loop of each workspace.

Learning is Hermes's: its background review writes memory and improves skills,
its curator tidies them, and every skill change is in its ledger with a
before/after copy. AGOS shows that in "What I learned" with Undo, and says the
owner's decisions (approve, cancel, undo) to Hermes the moment he makes them, in
the workspace's learning conversation (learning.py), never writing the agents'
memory itself. No loop: Hermes's own gateway reads the conversation.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.watcher")

# ---- feedback -> lessons -----------------------------------------------------------


def record(
    core: Core,
    workspace_id: str,
    *,
    kind: str,
    subject: str,
    detail: str = "",
    agent: str | None = None,
    ref: str | None = None,
) -> None:
    """An owner signal (approve, reject, changes asked, undo, dismiss…): said to the
    workspace's Hermes at once, in its learning conversation (learning.py); Hermes
    decides what to learn and keeps the conversation ("What I learned" reads it)."""
    from agos_core.actions import learning

    learning.say(core, workspace_id, learning.decision_text(kind, subject[:2000], detail, agent))


# ---- what was learned -------------------------------------------------------------


def _profiles(core: Core, workspace_id: str) -> list[tuple[str, str]]:
    """Every Hermes profile of the workspace (its Co-Founder's, then each member's):
    (profile key, who)."""
    from agos_core.actions import agent_profiles
    from agos_core.actions import team as team_actions

    out = [(workspace_id, "")]
    for agent in team_actions.members(core, workspace_id):
        out.append((agent_profiles.key(workspace_id, agent.name), agent.title or agent.name))
    return out


def _changes(core: Core, key: str, limit: int) -> list[dict[str, Any]]:
    """One profile's skill ledger, as Hermes reads it (engine.skill_changes)."""
    assert core.engine is not None
    try:
        return core.engine.skill_changes(core.engine.profile_home(key), limit)
    except (EngineError, OSError, ValueError) as error:
        log.warning("skill ledger of %s not read: %s", key, error)
        return []


def learned(core: Core, workspace_id: str, limit: int = 200) -> dict[str, Any]:
    """What this workspace's agents taught themselves, in every profile of it (the
    Co-Founder's and each member's): every skill change of Hermes's skill ledger, with
    its SKILL.md text before/after, and the current memory."""
    require_workspace(core, workspace_id)
    engine = core.engine
    if engine is None:
        return {"changes": [], "memory": "", "user": "", "memories": [], "feedback": []}
    from concurrent.futures import ThreadPoolExecutor

    profiles = _profiles(core, workspace_id)
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(lambda p: _changes(core, p[0], limit), profiles))
    changes = []
    for (_key, who), rows in zip(profiles, found, strict=True):
        for e in rows:
            by = (
                "learned by itself"
                if e.get("actor") in ("agent", "curator")
                else str(e.get("actor"))
            )
            changes.append(
                {
                    "id": str(e.get("id") or ""),
                    "at": str(e.get("ts") or ""),
                    "by": f"{by} · {who}" if who else by,
                    "agent": who,
                    "action": str(e.get("action") or ""),
                    "skill": str(e.get("skill") or ""),
                    "source": _source_link(core, workspace_id, str(e.get("session") or "")),
                    "before": e.get("before"),
                    "after": e.get("after"),
                    "files": list(e.get("files") or []),
                    "undone": bool(e.get("undone") or e.get("action") == "rollback"),
                }
            )
    changes.sort(key=lambda c: str(c["at"]), reverse=True)
    from agos_core.actions import learning

    memories = []
    for key, who in profiles:
        folder = engine.profile_home(key) / "memories"
        memories.append(
            {"agent": who, "memory": _read(folder / "MEMORY.md"), "user": _read(folder / "USER.md")}
        )
    return {
        "changes": changes[:limit],
        "memory": memories[0]["memory"],
        "user": memories[0]["user"],
        "memories": [m for m in memories[1:] if m["memory"].strip() or m["user"].strip()],
        "feedback": learning.decisions(core, workspace_id),
    }


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _source_link(core: Core, workspace_id: str, session: str) -> dict[str, str] | None:
    from agos_core.db import chats as chats_repo

    c = core.db.execute(
        "SELECT * FROM chats WHERE workspace_id = ? AND hermes_key = ?",
        (workspace_id, session),
    ).fetchone()
    if c:
        title = chats_repo.chat_title(core.db, c)
        return {"label": f"Chat “{title}”", "href": f"/w/{workspace_id}/messages?c={c['id']}"}
    return None


def undo_change(core: Core, workspace_id: str, entry_id: str) -> None:
    """Puts one learned skill change back (Hermes's own single-entry rollback), in
    the workspace's profile (Co-Founder or member) whose ledger has it."""
    require_workspace(core, workspace_id)
    engine = core.engine
    if engine is None:
        raise ActionError("The engine is off.", 409)
    if not re.fullmatch(r"[0-9a-f]{6,64}", entry_id):
        raise ActionError("Unknown change.")
    key = next(
        (
            k
            for k, _who in _profiles(core, workspace_id)
            if any(str(e.get("id")) == entry_id for e in _changes(core, k, 100_000))
        ),
        None,
    )
    if key is None:
        raise NotFoundError("This change")
    try:
        # Hermes's own CLI, in the profile whose ledger has the change.
        hermes_cli.cli(engine, key, "curator", "rollback", entry_id, "-y", timeout=120)
    except EngineError as error:
        raise ActionError(f"Couldn't put it back: {error}") from error
    add_activity(
        core.db, workspace_id, kind="learning.undone", text=f"Undid a learned change ({entry_id})"
    )


def read_ahead(core: Core) -> None:
    """engine/read_ahead.py: Hermes's skill ledger of every profile of each
    workspace, asked once after a start (one profile after the other), so the
    first Learned page doesn't wait for Hermes."""
    from agos_core.db import workspaces as workspaces_repo

    if core.engine is None:
        return
    for ws in workspaces_repo.list_workspaces(core.db):
        if not (core.engine.profile_home(ws.id) / "config.yaml").is_file():
            continue  # no Hermes root yet: nothing to ask
        for key, _who in _profiles(core, ws.id):
            _changes(core, key, 200)
