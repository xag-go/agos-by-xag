"""Workspaces and the folders the owner added to them."""

import sqlite3
from collections.abc import Callable
from typing import Literal

from agos_core.db.records import AddedFolder, Workspace
from agos_core.db.rows import now
from agos_core.domain.models import ModelSelection
from agos_core.domain.workspace import is_workspace_id, require_workspace_id

# The workspace's model lives in its Hermes profile (actions/engine.workspace_model):
# agos-core sets this reader when it opens. Before the profile has a model (or
# without an engine) the placeholder says so plainly.
model_reader: Callable[[str], ModelSelection | None] | None = None
NO_MODEL = ModelSelection(provider="claude", mode="cli", model="not-set", effort="medium")


def model_of(workspace_id: str) -> ModelSelection:
    found = model_reader(workspace_id) if model_reader is not None else None
    return found or NO_MODEL


# The workspace's access switch is its Hermes profile's approvals.mode
# (actions/access.py): agos-core sets this reader when it opens.
access_reader: Callable[[str], bool] | None = None


def access_of(workspace_id: str) -> Literal["ask", "full"]:
    return "full" if access_reader is not None and access_reader(workspace_id) else "ask"


# The workspace's one-line description is its Co-Founder's (the root profile's)
# Hermes description, profile.yaml `description` (hermes_cli/profiles.py
# read_profile_meta; `hermes profile describe`): agos-core sets this reader when it
# opens. A description Hermes hasn't taken yet (engine off, or an old row moved by
# the step-27 migration) waits under `workspace.description.move.<ws>`
# (actions/engine.move_description puts it into Hermes, then deletes it).
description_reader: Callable[[str], str] | None = None
MOVE_DESCRIPTION = "workspace.description.move."  # + workspace id


def pending_description(db: sqlite3.Connection, workspace_id: str) -> str | None:
    from agos_core.db.app_settings import get_setting

    found = get_setting(db, MOVE_DESCRIPTION + workspace_id, None)
    return found if isinstance(found, str) else None


def set_pending_description(db: sqlite3.Connection, workspace_id: str, text: str) -> None:
    from agos_core.db.app_settings import set_setting

    set_setting(db, MOVE_DESCRIPTION + workspace_id, text)


def drop_pending_description(db: sqlite3.Connection, workspace_id: str, text: str) -> None:
    """Hermes holds `text` now: the waiting copy goes (unless he changed it meanwhile)."""
    if pending_description(db, workspace_id) == text:
        db.execute("DELETE FROM app_settings WHERE key = ?", (MOVE_DESCRIPTION + workspace_id,))
        db.execute("DELETE FROM app_settings WHERE key = ?", (MOVE_NAME + workspace_id,))


# The workspace's name is its Co-Founder's (the root profile's) Hermes display name,
# profile.yaml `display_name` (hermes_cli/profiles.py read_profile_meta; what
# `hermes profile rename default <name>` sets for a root's own profile). A name
# Hermes hasn't taken yet waits under `workspace.name.move.<ws>` (as the
# description does; actions/engine.move_name puts it into Hermes, then deletes it).
name_reader: Callable[[str], str] | None = None
MOVE_NAME = "workspace.name.move."  # + workspace id
NAME_MAX = 64  # hermes_cli/profiles.py set_profile_display_name


def pending_name(db: sqlite3.Connection, workspace_id: str) -> str | None:
    from agos_core.db.app_settings import get_setting

    found = get_setting(db, MOVE_NAME + workspace_id, None)
    return found if isinstance(found, str) else None


def set_pending_name(db: sqlite3.Connection, workspace_id: str, name: str) -> None:
    from agos_core.db.app_settings import set_setting

    set_setting(db, MOVE_NAME + workspace_id, name)


def drop_pending_name(db: sqlite3.Connection, workspace_id: str, name: str) -> None:
    """Hermes holds `name` now: the waiting copy goes (unless he changed it meanwhile)."""
    if pending_name(db, workspace_id) == name:
        db.execute("DELETE FROM app_settings WHERE key = ?", (MOVE_NAME + workspace_id,))


def name_of(db: sqlite3.Connection, workspace_id: str) -> str:
    waiting = pending_name(db, workspace_id)
    if waiting is not None:
        return waiting
    found = name_reader(workspace_id) if name_reader is not None else ""
    return found or workspace_id


def description_of(db: sqlite3.Connection, workspace_id: str) -> str:
    waiting = pending_description(db, workspace_id)
    if waiting is not None:
        return waiting
    return description_reader(workspace_id) if description_reader is not None else ""


# The workspace's icon is a file in its own folder (storage/workspace_icon.py):
# agos-core sets this reader when it opens. One stat per workspace, no read.
icon_reader: Callable[[str], str | None] | None = None


def icon_of(workspace_id: str) -> str | None:
    return icon_reader(workspace_id) if icon_reader is not None else None


def _workspace(db: sqlite3.Connection, row: sqlite3.Row) -> Workspace:
    return Workspace(
        id=require_workspace_id(row["id"]),
        name=name_of(db, str(row["id"])),
        description=description_of(db, str(row["id"])),
        default_model=model_of(str(row["id"])),
        chat_access=access_of(str(row["id"])),
        archived=row["archived_at"] is not None,
        created_at=row["created_at"],
        icon=icon_of(str(row["id"])),
    )


# The owner's order of the workspaces (dragged on the rail): app_settings key.
ORDER_KEY = "workspace_order"


def saved_order(db: sqlite3.Connection) -> list[str]:
    from agos_core.db.app_settings import get_setting

    saved = get_setting(db, ORDER_KEY, [])
    return [str(i) for i in saved] if isinstance(saved, list) else []


def list_workspaces(db: sqlite3.Connection, *, include_archived: bool = False) -> list[Workspace]:
    """Workspaces not in the trash, in the owner's order (the sidebar order): the
    ones he placed first, as he placed them, then the others oldest first."""
    sql = "SELECT * FROM workspaces WHERE deleted_at IS NULL"
    if not include_archived:
        sql += " AND archived_at IS NULL"
    rows = list(db.execute(sql + " ORDER BY created_at"))
    place = {wid: n for n, wid in enumerate(saved_order(db))}
    rows.sort(key=lambda r: place.get(str(r["id"]), len(place)))  # stable: oldest first
    return [_workspace(db, r) for r in rows]


def save_order(db: sqlite3.Connection, ids: list[str]) -> list[str]:
    """Keeps the order of the ids that are workspaces (each once); the rest follow."""
    from agos_core.db.app_settings import set_setting

    known = {str(r["id"]) for r in db.execute("SELECT id FROM workspaces WHERE deleted_at IS NULL")}
    order = list(dict.fromkeys(i for i in ids if i in known))
    set_setting(db, ORDER_KEY, order)
    return order


def get_workspace(db: sqlite3.Connection, workspace_id: str) -> Workspace | None:
    if not is_workspace_id(workspace_id):
        return None
    row = db.execute(
        "SELECT * FROM workspaces WHERE id = ? AND deleted_at IS NULL", (workspace_id,)
    ).fetchone()
    return _workspace(db, row) if row else None


_IDS = {
    (True, True): "SELECT id FROM workspaces ORDER BY id",
    (False, True): "SELECT id FROM workspaces WHERE deleted_at IS NULL ORDER BY id",
    (True, False): "SELECT id FROM workspaces WHERE archived_at IS NULL ORDER BY id",
    (False, False): (
        "SELECT id FROM workspaces WHERE deleted_at IS NULL AND archived_at IS NULL ORDER BY id"
    ),
}


def ids(db: sqlite3.Connection, *, trashed: bool = True, archived: bool = True) -> list[str]:
    """Every workspace id, in id order; `trashed` / `archived`: those included too."""
    return [str(r["id"]) for r in db.execute(_IDS[(trashed, archived)])]


def workspace_id_taken(db: sqlite3.Connection, workspace_id: str) -> bool:
    """Including workspaces in the trash: their ids stay reserved."""
    return (
        db.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone() is not None
    )


def live_ids(db: sqlite3.Connection) -> list[str]:
    """The ids of the workspaces not in the trash (archived ones too), in no order."""
    return [str(r["id"]) for r in db.execute("SELECT id FROM workspaces WHERE deleted_at IS NULL")]


def is_live(db: sqlite3.Connection, workspace_id: str) -> bool:
    """The workspace exists and is not in the trash."""
    return (
        db.execute(
            "SELECT 1 FROM workspaces WHERE id = ? AND deleted_at IS NULL", (workspace_id,)
        ).fetchone()
        is not None
    )


def other_ids(db: sqlite3.Connection, workspace_id: str) -> list[str]:
    """The ids of every other workspace, the trash's included."""
    return [
        str(r["id"]) for r in db.execute("SELECT id FROM workspaces WHERE id != ?", (workspace_id,))
    ]


def insert_workspace(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    name: str,
    description: str,
) -> None:
    """`name` and `description` wait for their Hermes (the Co-Founder's profile.yaml)
    until the workspace's first sync has made the profile (actions/engine.py
    move_name, move_description)."""
    at = now()
    db.execute(
        """INSERT INTO workspaces (id, created_at, updated_at)
           VALUES (?, ?, ?)""",
        (require_workspace_id(workspace_id), at, at),
    )
    set_pending_name(db, workspace_id, name.strip())
    if description.strip():
        set_pending_description(db, workspace_id, description.strip())


def update_workspace(
    db: sqlite3.Connection,
    workspace_id: str,
    *,
    name: str,
) -> bool:
    """A new name waits for its Hermes (set_pending_name; actions/engine.move_name)."""
    found = (
        db.execute(
            """UPDATE workspaces SET updated_at = ?
               WHERE id = ? AND deleted_at IS NULL""",
            (now(), workspace_id),
        ).rowcount
        > 0
    )
    if found:
        set_pending_name(db, workspace_id, name.strip())
    return found


def set_archived(db: sqlite3.Connection, workspace_id: str, archived: bool) -> None:
    db.execute(
        "UPDATE workspaces SET archived_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now() if archived else None, now(), workspace_id),
    )


def mark_deleted(db: sqlite3.Connection, workspace_id: str, trash_name: str) -> None:
    """In the trash: rows stay until the trash is purged."""
    db.execute(
        "UPDATE workspaces SET deleted_at = ?, trash_name = ?, updated_at = ? WHERE id = ?",
        (now(), trash_name, now(), workspace_id),
    )


def list_trashed(db: sqlite3.Connection) -> list[dict[str, str]]:
    return [
        {
            "id": r["id"],
            "name": name_of(db, str(r["id"])),
            "trashName": r["trash_name"],
            "deletedAt": r["deleted_at"],
        }
        for r in db.execute(
            "SELECT id, trash_name, deleted_at FROM workspaces WHERE deleted_at IS NOT NULL"
            " ORDER BY deleted_at DESC"
        )
    ]


def restore_deleted(db: sqlite3.Connection, workspace_id: str) -> None:
    db.execute(
        "UPDATE workspaces SET deleted_at = NULL, trash_name = NULL, updated_at = ? WHERE id = ?",
        (now(), workspace_id),
    )


def purge_deleted(db: sqlite3.Connection, workspace_id: str) -> None:
    gone = db.execute(
        "SELECT 1 FROM workspaces WHERE id = ? AND deleted_at IS NOT NULL", (workspace_id,)
    ).fetchone()
    if gone:
        # Not tied by a foreign key: its row ids come back in other chats.
        db.execute("DELETE FROM hermes_inbox WHERE workspace_id = ?", (workspace_id,))
        _purge_keys(db, workspace_id)
    db.execute("DELETE FROM workspaces WHERE id = ? AND deleted_at IS NOT NULL", (workspace_id,))


def _purge_keys(db: sqlite3.Connection, workspace_id: str) -> None:
    """Every app_settings key of the workspace and of its chats goes with it
    (ownership.WILDCARD_IDS says what each `*` key's id is), read before the
    workspaces row's delete cascades the chats away. Keys an older purge left
    behind are swept at start (db/orphan_keys.sweep)."""
    from agos_core.db.ownership import WILDCARD_IDS

    chats = {
        str(row["id"])
        for row in db.execute(
            "SELECT id FROM chats WHERE workspace_id = ?", (workspace_id,)
        ).fetchall()
    }
    mine: list[sqlite3.Row] = []
    for row in db.execute("SELECT key FROM app_settings").fetchall():
        key = str(row["key"])
        wildcard = next((w for w in WILDCARD_IDS if key.startswith(w[:-1])), None)
        if wildcard is None or WILDCARD_IDS[wildcard] == "global":
            continue
        rest = key[len(wildcard) - 1 :]
        if rest.startswith("agos:"):
            rest = rest[len("agos:") :]
        ids = {workspace_id} if WILDCARD_IDS[wildcard] == "workspace" else chats
        if rest in ids:
            mine.append(row)
    for row in mine:
        db.execute("DELETE FROM app_settings WHERE key = ?", (row["key"],))


MOVE_FOLDERS = "folders.move."  # + workspace id: old rows waiting for their Hermes


def legacy_folders(db: sqlite3.Connection, workspace_id: str) -> list[AddedFolder]:
    """AGOS's old list of a workspace's added folders (the dropped workspace_folders
    table, kept by the step-26 migration under `folders.move.<ws>`), before Hermes's
    `terminal.docker_volumes` became the one list (actions/engine.py folders).
    Read only until the workspace's next sync puts them into its Hermes; never
    written again."""
    from agos_core.db.app_settings import get_setting

    saved = get_setting(db, MOVE_FOLDERS + workspace_id, [])
    return [
        AddedFolder(name=r["name"], host_path=r["host_path"], access=r["access"])
        for r in (saved if isinstance(saved, list) else [])
        if isinstance(r, dict)
    ]


def drop_legacy_folders(db: sqlite3.Connection, workspace_id: str) -> int:
    """The old rows go once the workspace's Hermes holds its folders."""
    gone = len(legacy_folders(db, workspace_id))
    db.execute("DELETE FROM app_settings WHERE key = ?", (MOVE_FOLDERS + workspace_id,))
    return gone
