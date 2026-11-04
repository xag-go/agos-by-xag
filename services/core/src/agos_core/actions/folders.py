"""Folders: the owner's own grouping of a workspace's automations, skills and projects.

A folder is AGOS-only metadata (the `folders` / `folder_items` rows). It never changes
how Hermes runs anything: no Hermes file, cron job or skill moves, nothing is written
outside AGOS's database. One level only (no folder in a folder), one folder per item,
and each kind has its own folders. Deleting a folder sends its items back to "No
folder"; an item deleted elsewhere drops out of its folder by itself (the rows' foreign
keys cascade). Everything stays inside its own workspace.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Literal, cast

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.connection import transaction
from agos_core.db.rows import now

FolderKind = Literal["automation", "skill", "project"]
KINDS: tuple[FolderKind, ...] = ("automation", "skill", "project")
MAX_FOLDERS = 100
_NAME = re.compile(r"[^\x00-\x1f]{1,40}")
# The item's own row, its column in folder_items, and the check that it is one of
# this workspace's items of that kind.
_ITEM: dict[str, tuple[str, str]] = {
    "automation": ("automation_id", "SELECT id FROM automations WHERE id = ? AND workspace_id = ?"),
    "skill": (
        "skill_id",
        "SELECT id FROM library_items WHERE id = ? AND workspace_id = ? AND kind = 'skill'",
    ),
    "project": (
        "project_id",
        "SELECT id FROM goals WHERE id = ? AND workspace_id = ? AND level = 'project'",
    ),
}
_NOUN = {"automation": "automation", "skill": "skill", "project": "project"}


def kind_of(value: Any) -> FolderKind:
    text = str(value or "").strip().lower().rstrip("s")
    for kind in KINDS:
        if kind == text:
            return kind
    raise ActionError("Folders hold automations, skills or projects.")


def _clean_name(name: str) -> str:
    name = " ".join(str(name or "").split())
    if not _NAME.fullmatch(name):
        raise ActionError("Give the folder a name (40 characters at most).")
    return name


def listing(core: Core, workspace_id: str, kind: FolderKind) -> list[dict[str, Any]]:
    """This workspace's folders of one kind (by name), each with its items' ids."""
    column = _ITEM[kind][0]
    rows = list(
        core.db.execute(
            "SELECT id, name FROM folders WHERE workspace_id = ? AND kind = ?"
            " ORDER BY name COLLATE NOCASE",
            (workspace_id, kind),
        )
    )
    by_id: dict[int, list[int]] = {int(r["id"]): [] for r in rows}
    folders: list[dict[str, Any]] = [
        {"id": int(r["id"]), "kind": kind, "name": str(r["name"]), "items": by_id[int(r["id"])]}
        for r in rows
    ]
    if by_id:
        marks = ",".join("?" * len(by_id))
        for r in core.db.execute(
            f"SELECT folder_id, {column} AS item FROM folder_items"
            f" WHERE folder_id IN ({marks}) AND {column} IS NOT NULL ORDER BY {column}",
            tuple(by_id),
        ):
            by_id[int(r["folder_id"])].append(int(r["item"]))
    return folders


def one(core: Core, workspace_id: str, folder_id: int) -> dict[str, Any]:
    row = core.db.execute(
        "SELECT kind FROM folders WHERE id = ? AND workspace_id = ?", (folder_id, workspace_id)
    ).fetchone()
    if row is None:
        raise NotFoundError("This folder")
    kind = cast(FolderKind, str(row["kind"]))
    return next(f for f in listing(core, workspace_id, kind) if f["id"] == folder_id)


def find(core: Core, workspace_id: str, kind: FolderKind, ref: Any) -> dict[str, Any]:
    """A folder by its number or its name (any case)."""
    wanted = " ".join(str(ref or "").split()).lower().lstrip("#")
    for folder in listing(core, workspace_id, kind):
        if str(folder["id"]) == wanted or str(folder["name"]).lower() == wanted:
            return folder
    raise ActionError(f"There is no {_NOUN[kind]} folder “{ref}” in this workspace.", 404)


def create(core: Core, workspace_id: str, kind: FolderKind, name: str) -> dict[str, Any]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    name = _clean_name(name)
    existing = listing(core, workspace_id, kind)
    if any(str(f["name"]).lower() == name.lower() for f in existing):
        raise ActionError("A folder with this name exists already.")
    if len(existing) >= MAX_FOLDERS:
        raise ActionError(f"{MAX_FOLDERS} folders at most.")
    with transaction(core.db):
        new = core.db.execute(
            "INSERT INTO folders (workspace_id, kind, name, created_at) VALUES (?, ?, ?, ?)",
            (workspace_id, kind, name, now()),
        ).lastrowid
    return one(core, workspace_id, int(new or 0))


def rename(core: Core, workspace_id: str, folder_id: int, name: str) -> dict[str, Any]:
    old = one(core, workspace_id, folder_id)
    name = _clean_name(name)
    if name.lower() != str(old["name"]).lower() and any(
        str(f["name"]).lower() == name.lower()
        for f in listing(core, workspace_id, cast(FolderKind, old["kind"]))
    ):
        raise ActionError("A folder with this name exists already.")
    with transaction(core.db):
        core.db.execute(
            "UPDATE folders SET name = ? WHERE id = ? AND workspace_id = ?",
            (name, folder_id, workspace_id),
        )
    return one(core, workspace_id, folder_id)


def remove(core: Core, workspace_id: str, folder_id: int) -> dict[str, Any]:
    """The folder goes; its items stay, back in "No folder". Returns what it was."""
    gone = one(core, workspace_id, folder_id)
    with transaction(core.db):
        core.db.execute(
            "DELETE FROM folders WHERE id = ? AND workspace_id = ?", (folder_id, workspace_id)
        )
    return gone


def _require_item(core: Core, workspace_id: str, kind: FolderKind, item_id: int) -> str:
    column, check = _ITEM[kind]
    if core.db.execute(check, (item_id, workspace_id)).fetchone() is None:
        raise NotFoundError(f"This {_NOUN[kind]}")
    return column


def folder_of(core: Core, workspace_id: str, kind: FolderKind, item_id: int) -> int | None:
    column = _ITEM[kind][0]
    row = core.db.execute(
        f"SELECT fi.folder_id FROM folder_items fi JOIN folders f ON f.id = fi.folder_id"
        f" WHERE fi.{column} = ? AND f.workspace_id = ?",
        (item_id, workspace_id),
    ).fetchone()
    return None if row is None else int(row["folder_id"])


def move(
    core: Core, workspace_id: str, kind: FolderKind, item_id: int, folder_id: int | None
) -> int | None:
    """Puts the item in the folder (None = "No folder"). Returns the folder it was in."""
    column = _require_item(core, workspace_id, kind, item_id)
    if folder_id is not None:
        target = one(core, workspace_id, folder_id)
        if target["kind"] != kind:
            raise ActionError(f"That folder holds {target['kind']}s, not {_NOUN[kind]}s.")
    before = folder_of(core, workspace_id, kind, item_id)
    with transaction(core.db):
        core.db.execute(f"DELETE FROM folder_items WHERE {column} = ?", (item_id,))
        if folder_id is not None:
            core.db.execute(
                f"INSERT INTO folder_items (folder_id, {column}) VALUES (?, ?)",
                (folder_id, item_id),
            )
    return before


def restore(core: Core, workspace_id: str, gone: dict[str, Any]) -> dict[str, Any]:
    """A deleted folder back (its name and the items of it that still exist)."""
    kind = kind_of(gone["kind"])
    made = create(core, workspace_id, kind, str(gone["name"]))
    for item in gone.get("items") or []:
        try:
            move(core, workspace_id, kind, int(item), int(made["id"]))
        except NotFoundError:
            continue  # deleted since
    return one(core, workspace_id, int(made["id"]))


# ---- a workspace's export / import (actions/portability.py) ------------------------------


def export(core: Core, workspace_id: str, names: dict[str, dict[int, str]]) -> dict[str, Any]:
    """The folders as the bundle carries them: per kind, each folder's name and its
    items' names (`names`: kind -> item id -> the name the bundle knows it by)."""
    out: dict[str, Any] = {}
    for kind in KINDS:
        shown = names.get(kind, {})
        folders = [
            {
                "name": f["name"],
                "items": [shown[i] for i in f["items"] if i in shown],
            }
            for f in listing(core, workspace_id, kind)
        ]
        if folders:
            out[kind] = folders
    return out


def apply_import(
    core: Core, workspace_id: str, given: Any, found: dict[str, dict[str, int]]
) -> None:
    """The bundle's folders into the workspace: a folder of the same name is reused,
    and only the items this import wrote (`found`: kind -> name -> id) move into it."""
    if not isinstance(given, dict):
        return
    for kind in KINDS:
        entries = given.get(kind)
        if not isinstance(entries, list):
            continue
        ids = found.get(kind, {})
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            try:
                name = _clean_name(str(entry.get("name") or ""))
            except ActionError:
                continue
            try:
                folder = find(core, workspace_id, kind, name)
            except ActionError:
                try:
                    folder = create(core, workspace_id, kind, name)
                except ActionError:
                    continue
            for item in entry.get("items") or []:
                item_id = ids.get(str(item))
                if item_id is not None:
                    try:
                        move(core, workspace_id, kind, item_id, int(folder["id"]))
                    except (ActionError, sqlite3.Error):
                        continue
