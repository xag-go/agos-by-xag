"""Where a workspace's own skills live (one folder of its Hermes root), which are shown or hidden, and reading one.
Must not: write a skill.

Split out of agos_core.actions.workspace_skills (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.engine import library as lib
from agos_core.engine.library import LibraryError

__all__ = [
    "FOLDER",
    "agos_owned",
    "definition",
    "existing_dir",
    "external_dirs",
    "folder",
    "head",
    "hidden",
    "names",
    "never_written",
    "pairs",
    "shared_dirs",
    "shown",
    "skill_dir",
    "stored",
]

log = logging.getLogger("agos.workspace_skills")

FOLDER = lib.SKILLS_DIR_NAME  # <root>/skills/agos-library


# ---- where they are ------------------------------------------------------------------


def folder(core: Core, workspace_id: str) -> Path | None:
    """The workspace's skill folder (in its root), or None without Hermes."""
    if core.engine is None:
        return None
    return lib.copies_dir(core.engine.profile_home(workspace_id))


def skill_dir(core: Core, workspace_id: str, name: str) -> Path | None:
    base = folder(core, workspace_id)
    return base / name if base is not None else None


def existing_dir(core: Core, workspace_id: str, name: str) -> Path | None:
    """The skill's folder when Hermes has it written (its SKILL.md is there)."""
    found = skill_dir(core, workspace_id, name)
    return found if found is not None and (found / "SKILL.md").is_file() else None


def shared_dirs(core: Core) -> list[Path]:
    """The skill folders EVERY workspace's profiles read where they are: AGOS's own
    skills (/task, written by AGOS) and the Brain's. Both are in AGOS's data dir,
    which no sandbox grant can mount (engine/rules.py); Hermes mounts them
    read-only itself, and the guard keeps agents from changing them."""
    from agos_core.actions import agos_skills, brain

    dirs = [agos_skills.ensure(core), brain.skills_dir(core)]
    for found in dirs:
        found.mkdir(parents=True, exist_ok=True)
    return dirs


def external_dirs(core: Core, workspace_id: str, *, member: bool) -> list[str]:
    """A profile's `skills.external_dirs`. A member reads its workspace's skill
    folder there too; the Co-Founder has it as its own local skills (never listed:
    Hermes would then take its own skills for someone else's)."""
    dirs = [str(d) for d in shared_dirs(core)]
    own = folder(core, workspace_id)
    if member and own is not None:
        own.mkdir(parents=True, exist_ok=True)  # Hermes skips a folder that isn't there
        dirs.append(str(own))
    return dirs


def names(core: Core, workspace_id: str) -> set[str]:
    return {str(r["name"]) for r in repo.workspace_skills(core.db, workspace_id)}


def agos_owned() -> frozenset[str]:
    """The skills AGOS keeps in every workspace in the background (the Co-Founder's
    team-design, every agent's find-skills): Hermes loads them like any other, the
    owner never sees them."""
    from agos_core.actions import skill_requests, team_design

    return frozenset({team_design.NAME, skill_requests.NAME})


def hidden(row: Any) -> bool:
    """A skill row the owner never sees (nor gives, copies or exports): one of AGOS's
    background skills, as AGOS made it."""
    return str(row["source"] or "") == "agos" and str(row["name"]) in agos_owned()


def shown(core: Core, workspace_id: str) -> list[Any]:
    """The workspace's skills as the owner (and the Co-Founder's catalog) sees them:
    every one but AGOS's background skills, which stay on disk and in Hermes's index."""
    return [r for r in repo.workspace_skills(core.db, workspace_id) if not hidden(r)]


def pairs(
    core: Core, workspace_id: str, skills_on: list[str] | set[str], *, member: bool
) -> tuple[list[str], list[str]]:
    """(skills.external_dirs, skills.disabled) of one of the workspace's profiles:
    its folders, and what is off here (its skills not turned on, plus Hermes's
    own entries: the Brain's "Not here", what Hermes turned off itself)."""
    from agos_core.actions import brain

    mine = names(core, workspace_id)
    off = [n for n in brain.off_here(core, workspace_id) if n not in mine]
    off += sorted(mine - set(skills_on))
    return external_dirs(core, workspace_id, member=member), sorted(set(off))


# ---- reading one ----------------------------------------------------------------------


def _folder_of(core: Core, row: Any) -> Path | None:
    ws = str(row["workspace_id"] or "")
    return skill_dir(core, ws, str(row["name"])) if ws else None


def head(core: Core, row: Any) -> dict[str, str]:
    """A skill's SKILL.md frontmatter, read from its folder each time with Hermes's
    own reader (agent/skill_utils.py parse_frontmatter)."""
    found = _folder_of(core, row)
    if found is None:
        return {}
    try:
        text = (found / "SKILL.md").read_text(errors="replace")
        frontmatter, _body = lib.parse_skill(text)
    except (OSError, LibraryError):
        return {}
    return frontmatter


# The skill lives ONCE: its Hermes skill folder (SKILL.md, references, scripts).
# The database keeps only what isn't in it (where it came from).
_IN_FOLDER = ("text", "files")


def stored(definition: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in definition.items() if k not in _IN_FOLDER}


def definition(core: Core, row: Any) -> dict[str, Any]:
    """The skill as it is: its folder's text and files, plus the stored extras."""
    from agos_core.actions.team_files import skill_files

    kept = repo.definition(row)
    found = _folder_of(core, row)
    text = ""
    files: dict[str, str] = {}
    if found is not None:
        with contextlib.suppress(OSError):
            text = (found / "SKILL.md").read_text()
        files = skill_files(found)
    return {**stored(kept), "text": text, "files": files}


def never_written(core: Core, row: Any) -> bool:
    """A skill AGOS made whose SKILL.md Hermes never wrote: the empty card of an
    earlier create Hermes refused (AGOS removes those itself now)."""
    if str(row["kind"]) != "skill" or str(row["source"] or "") != "created":
        return False
    found = _folder_of(core, row)
    return found is None or not (found / "SKILL.md").is_file()


def _row(core: Core, workspace_id: str, item_id: int) -> Any:
    require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This skill")  # another workspace's: out of reach
    if hidden(row):
        raise NotFoundError("This skill")  # AGOS's own, in the background
    return row


def _home(core: Core, workspace_id: str) -> Path:
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    return core.engine.profile_home(workspace_id)
