"""Reading a bundle before import: the zip, its parsed tree, whether its scripts are trusted, what already exists.
Must not: write anything.

Split out of agos_core.actions.portability (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.engine import bundle as fmt

__all__ = [
    "DEFAULTS",
    "KINDS",
    "SCRIPTS",
    "parsed",
    "preview",
    "read_zip",
    "trust",
]

KINDS = ("agents", "skills", "automations", "vision")
DEFAULTS = {"agents": "rename", "skills": "skip", "automations": "rename", "vision": "skip"}
SCRIPTS = (".sh", ".py", ".js", ".ts", ".rb", ".pl", ".ps1", ".bash")


# ---- preview ---------------------------------------------------------------------------


def read_zip(data: bytes) -> dict[str, str]:
    try:
        return fmt.from_zip(data)
    except fmt.BundleError as error:
        raise ActionError(str(error)) from error


def parsed(files: dict[str, str]) -> fmt.Parsed:
    try:
        return fmt.parse(files)
    except fmt.BundleError as error:
        raise ActionError(str(error)) from error


def trust(files: dict[str, str]) -> str:
    """Paperclip's trust level, in AGOS's words: markdown_only, or scripts (a skill
    carries a script the team's sandbox may run)."""
    scripts = any(
        p.startswith("skills/") and (p.endswith(SCRIPTS) or "/scripts/" in p) for p in files
    )
    return "scripts" if scripts else "markdown_only"


def _existing(core: Core, workspace_id: str | None) -> dict[str, set[str]]:
    from agos_core.actions import automations, goals, team, workspace_skills

    if workspace_id is None:
        return {k: set() for k in KINDS}
    return {
        "agents": {a.name for a in team.members(core, workspace_id)},
        "skills": workspace_skills.names(core, workspace_id),
        "automations": {a.name.strip().lower() for a in automations.list_all(core, workspace_id)},
        "vision": {"vision"} if goals.top(core, workspace_id) is not None else set(),
    }


def preview(core: Core, files: dict[str, str], workspace_id: str | None) -> dict[str, Any]:
    """What the bundle holds and what of it is in the target workspace already."""
    if workspace_id is not None:
        require_workspace(core, workspace_id)
    found = parsed(files)
    have = _existing(core, workspace_id)
    return {
        "name": found.name,
        "slug": found.slug,
        "kind": str(found.meta.get("kind") or "team"),
        "description": str(found.meta.get("description") or ""),
        "hash": fmt.content_hash(files),
        "trust": trust(files),
        "agents": [
            {
                "name": a.name,
                "title": a.title,
                "reportsTo": a.reports_to,
                "exists": a.name in have["agents"],
            }
            for a in fmt.leads_first(found.agents)
        ],
        "skills": [{"name": s.name, "exists": s.name in have["skills"]} for s in found.skills],
        "automations": [
            {
                "name": str(a["name"]),
                "agent": str(a.get("agent") or ""),
                "exists": str(a["name"]).strip().lower() in have["automations"],
            }
            for a in found.automations
        ],
        "vision": found.vision is not None,
        "visionExists": bool(have["vision"]) and found.vision is not None,
        "inputs": found.inputs,
        "notCarried": list(fmt.NOT_CARRIED),
    }
