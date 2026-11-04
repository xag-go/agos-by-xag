"""The Co-Founder's mode (direct or ask) and the instructions its chat runs with; the team's copies of them.
Must not: run or store an action.

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agos_core.actions import automations as automation_actions
from agos_core.actions import library as library_actions
from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import library as library_repo
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.domain.workspace import workspace_id_from_name
from agos_core.engine import cofounder_actions as rules

__all__ = [
    "MODE_KEY",
    "Mode",
    "instructions",
    "mode",
    "set_mode",
    "write_team_copies",
]

log = logging.getLogger("agos.cofounder_actions")

MODE_KEY = "cofounder.actions"
Mode = Literal["direct", "ask"]


def mode(core: Core) -> Mode:
    return "ask" if get_setting(core.db, MODE_KEY, "direct") == "ask" else "direct"


def set_mode(core: Core, value: Mode) -> None:
    set_setting(core.db, MODE_KEY, value)


def instructions(core: Core, workspace_id: str) -> str:
    write_team_copies(core, workspace_id)
    items = [
        (
            a.name,
            a.schedule,
            a.on,
            automation_actions.who_label(a.agent, [s.model_dump() for s in a.steps]),
            a.hook is not None,
        )
        for a in automation_actions.list_all(core, workspace_id)
    ]
    library = [
        (str(r["kind"]), str(r["name"]), library_actions.title_of(core, r))
        for kind in ("agent", "skill", "mcp")
        for r in _mine(core, workspace_id, kind)
    ]
    from agos_core.actions import hire_kit
    from agos_core.actions import team as team_actions

    team = [
        (
            a.name,
            a.title,
            a.summary
            # Step 62: a member still getting ready (or taking its onboarding test)
            # gets no other work from the Co-Founder.
            + (
                " [NOT READY: no work for it until its Readiness is done]"
                if hire_kit.busy_only_onboarding(core, workspace_id, a.name)
                else ""
            ),
        )
        for a in team_actions.members(core, workspace_id, on_only=True)
    ]
    from agos_core.actions import founder

    return rules.instructions(
        items,
        mode(core) == "direct",
        library,
        team,
        founder.lines(core, workspace_id),
        founder.prompt_name(core, workspace_id),
    )


def _edited(current: str, p: dict[str, Any]) -> str:
    """The new text: whole (instructions), appended (add_instructions), or with
    exact passages swapped (replace). A passage that isn't there is an error,
    so nothing is changed by a guess."""
    if p.get("instructions"):
        return str(p["instructions"])
    text = current
    for r in p.get("replace") or []:
        find = str(r.get("find") or "")
        if find not in text:
            raise ActionError(f"Couldn't find this passage to change: “{find[:120]}”.")
        text = text.replace(find, str(r.get("with") or ""), 1)
    if p.get("add_instructions"):
        text = f"{text.rstrip()}\n\n{str(p['add_instructions']).strip()}".strip()
    if not text.strip():
        raise ActionError("Give it instructions.")
    return text


def _mine(core: Core, workspace_id: str, kind: str) -> list[Any]:
    """The agents/skills/MCP servers of THIS workspace only (added to it, on or off).
    Other workspaces' items are never shown to, read by or changed by its Co-Founder."""
    if kind == "agent":
        from agos_core.actions import team  # the members' own Hermes profiles

        return [a.row() for a in team.members(core, workspace_id)]
    if kind == "mcp":
        return [r for r in library_repo.list_items(core.db, "mcp", workspace_id)]
    from agos_core.actions import workspace_skills  # AGOS's background skills left out

    return workspace_skills.shown(core, workspace_id)


def write_team_copies(core: Core, workspace_id: str) -> None:
    """/workspace/playbooks shows what the team uses (one copy: see team_files)."""
    from agos_core.actions import team_files

    team_files.sync(core, workspace_id)


def _existing(core: Core, workspace_id: str, kind: str, name: str) -> Any:
    """The item of THIS workspace this name points to: its ID or its display name."""
    wanted = name.strip().lower()
    slug = workspace_id_from_name(name)
    for r in _mine(core, workspace_id, kind):
        if slug == str(r["name"]) or wanted in (
            str(r["name"]).lower(),
            library_actions.title_of(core, r).strip().lower(),
        ):
            return r
    return None
