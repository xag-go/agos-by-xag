"""Copying skills in: a duplicate, another workspace's skill, one found on this machine.
Must not: talk to Hermes's Skills Hub (skills_hub does).

Split out of agos_core.actions.workspace_skills (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.skill_folders import (
    _folder_of,
    _row,
    existing_dir,
    hidden,
    shown,
    stored,
)
from agos_core.actions.services.library.skill_writes import create
from agos_core.actions.skill_text_files import text_files
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.records import Record
from agos_core.engine import library as lib
from agos_core.engine import sources
from agos_core.engine.library import LibraryError

__all__ = [
    "CopyableSkill",
    "add_missing_files",
    "copy_from",
    "copyable",
    "duplicate",
    "import_from_machine",
    "on_this_machine",
]

# ---- copies: duplicate here, copy from another workspace -------------------------------


def add_missing_files(source: Path, target: Path) -> list[str]:
    """Copies every file of `source` that `target` doesn't have (nothing of
    `target` is ever overwritten or removed; no link, nothing secret-looking)."""
    added = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_symlink() or not path.is_file() or len(rel.parts) > 6:
            continue
        if any(sources._SKIP_FILES.search(part) for part in rel.parts):
            continue
        dest = target / rel
        if dest.exists() or dest.is_symlink():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        added.append(rel.as_posix())
    return added


def _renamed(text: str, name: str) -> str:
    frontmatter, body = lib.parse_skill(text)
    return lib.skill_template(name, frontmatter.get("description", ""), body)


def _copy(
    core: Core,
    workspace_id: str,
    row: Any,
    new_name: str,
    *,
    title: str,
    source: str,
    extra: dict[str, Any],
) -> int:

    found = _folder_of(core, row)
    if found is None or not (found / "SKILL.md").is_file():
        raise ActionError("That skill has nothing in it yet.", 409)
    text = (found / "SKILL.md").read_text()
    if new_name != str(row["name"]):
        text = _renamed(text, new_name)
    new_id = create(
        core,
        workspace_id,
        new_name,
        title=title,
        given={"text": text, "files": text_files(found)},
        source=source,
        extra=extra,
    )
    # What Hermes's text files left out (pictures, big files): copied beside them.
    copied = existing_dir(core, workspace_id, new_name)
    if copied is not None:
        add_missing_files(found, copied)
    return new_id


def duplicate(core: Core, workspace_id: str, item_id: int, new_name: str) -> int:
    row = _row(core, workspace_id, item_id)
    title = str(row["title"] or "")
    return _copy(
        core,
        workspace_id,
        row,
        new_name.strip(),
        title=f"{title} (copy)" if title else "",
        source="created",
        extra={},
    )


class CopyableSkill(Record):
    id: int
    title: str
    name: str
    workspace: str


def copyable(core: Core, workspace_id: str) -> list[CopyableSkill]:
    """The other workspaces' skills, for the owner's "Copy from another workspace"
    only (never shown to a Co-Founder)."""
    from agos_core.actions.library import title_of
    from agos_core.db.workspaces import list_workspaces

    require_workspace(core, workspace_id)
    out = []
    for w in sorted(list_workspaces(core.db, include_archived=True), key=lambda w: w.name):
        if w.id == workspace_id:
            continue
        for r in shown(core, w.id):
            if existing_dir(core, w.id, str(r["name"])) is not None:
                out.append(
                    CopyableSkill(
                        id=int(r["id"]),
                        title=title_of(core, r),
                        name=str(r["name"]),
                        workspace=w.name,
                    )
                )
    return out


def copy_from(core: Core, workspace_id: str, item_id: int, name: str | None = None) -> int:
    """The owner copies another workspace's skill into this one: a full, independent
    copy (its own folder and row; the original is never touched again)."""
    require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or not row["workspace_id"] or hidden(row):
        raise NotFoundError("This skill")
    return _copy(
        core,
        workspace_id,
        row,
        (name or str(row["name"])).strip(),
        title=str(row["title"] or ""),
        source=str(row["source"] or "created"),
        extra=stored(repo.definition(row)),
    )


def on_this_machine(core: Core, workspace_id: str) -> list[Any]:
    from agos_core.actions.library import _found, _sources

    require_workspace(core, workspace_id)
    return _found(core, _sources(core).machine_skills(), workspace_id)


def import_from_machine(core: Core, workspace_id: str, origin: str) -> int:
    """One click: the skill of this machine's Hermes becomes this workspace's own
    (its text through Hermes's skill_manage, the rest of its files beside it)."""
    from agos_core.actions.library import _sources

    try:
        text, found = _sources(core).read_machine_skill(origin)
        name, _description = lib.check_skill(text)
    except (sources.SourceError, LibraryError) as error:
        raise ActionError(str(error)) from error
    item_id = create(
        core,
        workspace_id,
        name,
        title=name,
        given={"text": text, "files": text_files(found)},
        source="machine",
        extra={"hash": sources.text_hash(text)},
    )
    written = existing_dir(core, workspace_id, name)
    if written is not None:
        add_missing_files(found, written)
    return item_id
