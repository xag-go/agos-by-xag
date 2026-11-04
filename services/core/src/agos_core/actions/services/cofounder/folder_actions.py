"""The Co-Founder's actions for folders (the Automations, Skills and Projects lists).
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.cofounder.action_args import Fields, Result, text_arg
from agos_core.context import Core
from agos_core.db import goals as goals_repo

__all__ = [
    "do_create_folder",
    "do_delete_folder",
    "do_move_to_folder",
    "do_rename_folder_of",
    "undo_create_folder",
    "undo_delete_folder",
    "undo_move_to_folder",
    "undo_rename_folder_of",
]

# ---- the table --------------------------------------------------------------------------


# ---- folders (the Automations, Skills and Projects lists) ------------------------------


def _folder_item(core: Core, ws: str, kind: str, ref: Any) -> tuple[int, str]:
    """(id, name) of one of this workspace's automations, skills or projects."""
    from agos_core.actions import automations
    from agos_core.db import library as library_repo

    wanted = " ".join(str(ref or "").split()).lower().lstrip("#")
    found: list[tuple[int, str, str]]  # id, name, title
    if kind == "automation":
        found = [(a.id, a.name, a.name) for a in automations.list_all(core, ws)]
    elif kind == "skill":
        found = [
            (int(r["id"]), str(r["name"]), str(r["title"]))
            for r in library_repo.workspace_skills(core.db, ws)
        ]
    else:
        found = [(i, title, title) for i, title in goals_repo.projects(core.db, ws)]
    for item_id, name, title in found:
        if wanted in (str(item_id), name.strip().lower(), title.strip().lower()):
            return item_id, name
    raise ActionError(f"There is no {kind} “{ref}” in this workspace.", 404)


def do_create_folder(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import folders

    made = folders.create(core, ws, folders.kind_of(p.get("kind")), text_arg(p, "name"))
    return {"folder": int(made["id"])}


def undo_create_folder(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import folders

    folders.remove(core, ws, int(r["folder"]))


def do_rename_folder_of(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import folders

    found = folders.find(core, ws, folders.kind_of(p.get("kind")), p.get("folder"))
    folders.rename(core, ws, int(found["id"]), text_arg(p, "new"))
    return {"folder": int(found["id"]), "before": str(found["name"])}


def undo_rename_folder_of(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import folders

    folders.rename(core, ws, int(r["folder"]), str(r["before"]))


def do_delete_folder(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import folders

    found = folders.find(core, ws, folders.kind_of(p.get("kind")), p.get("folder"))
    return {"gone": folders.remove(core, ws, int(found["id"]))}


def undo_delete_folder(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import folders

    folders.restore(core, ws, dict(r["gone"]))


def do_move_to_folder(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import folders

    kind = folders.kind_of(p.get("kind"))
    item_id, _name = _folder_item(core, ws, kind, p.get("item"))
    target = text_arg(p, "folder")
    folder_id = int(folders.find(core, ws, kind, target)["id"]) if target else None
    before = folders.move(core, ws, kind, item_id, folder_id)
    return {"kind": kind, "item": item_id, "before": before}


def undo_move_to_folder(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import folders

    before = r.get("before")
    try:
        folder_id = None if before is None else int(folders.one(core, ws, int(before))["id"])
    except NotFoundError:
        folder_id = None  # that folder was deleted since: back to No folder
    folders.move(core, ws, folders.kind_of(r["kind"]), int(r["item"]), folder_id)
