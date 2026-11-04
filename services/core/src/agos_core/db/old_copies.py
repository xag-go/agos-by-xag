"""Step 32: the last old copies of Hermes data in AGOS's data folder, moved once.

Found on the live install (audit 925047d area 2, C2/C5/C6 and the unregistered
app_settings keys), none written by any code any more:
- `chat_turns.activity` in the old `{"own": [...]}` form (a whole answer's tool
  calls and results, which the conversation's Hermes session holds:
  hermes_state_common.py messages) for a plain chat or a DM. It is reduced to its
  approvals (`{"kept": [...]}`, what AGOS keeps: Hermes doesn't persist them). A
  group chat's rows stay as they are: a hosted room's log is pruned by Hermes
  (gateway/hosted_rooms.py:38 DISBANDED_ROOM_RETENTION_SECONDS, :567
  _prune_disbanded_rooms_locked), so AGOS's may be the only copy;
- app_settings keys no code names: `chats.words_in_hermes`, `telegram.menus`,
  `tools.default_on`, `kanban.seen.*`, `kanban.asked.*` (ownership.unregistered
  lists them on a live database);
- hand-made copies beside the database: `system/MEMORY.*.bak-*` (a Hermes
  MEMORY.md), `system/before-one-copy-*/` (old skill folders, playbooks, xag.db)
  and the stray empty `agos.db` at the top of the data folder.

Nothing is deleted: the files are moved, and the old rows written as JSON, into
the backups folder (`AGOS_BACKUP_DIR`, else `agos-backups` beside the data folder:
actions/backups.py backup_dir), under `old-copies-<date>/`. Migration 122 (marked
MARK, db/migrations.py) runs `move` first, then its SQL drops the rows (so a failed move leaves
everything in place). When nothing is left it writes nothing (idempotent).
`automations.enabled` of a webhook-only automation (on/off is its Hermes route's)
is set back to 0 by the SQL alone (no data: AGOS never reads it there).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MARK = "-- agos: old copies (step 32)"

# The keys the migration drops (SQL GLOB patterns), written to the file first.
KEYS = (
    "chats.words_in_hermes",
    "telegram.menus",  # Hermes's own menu holds the commands (since 6e53716)
    "tools.default_on",  # Hermes's own toolset list (since 04263c6)
    "kanban.seen.*",
    "kanban.asked.*",
)
_OWN = """SELECT t.id, t.chat_id, t.workspace_id, t.activity FROM chat_turns t
            JOIN chats c ON c.id = t.chat_id
           WHERE c.kind IN ('chat', 'dm') AND json_valid(t.activity)
             AND json_type(t.activity, '$.own') IS NOT NULL ORDER BY t.id"""


def backups_folder(data_root: Path) -> Path:
    """Where AGOS's backups go (actions/backups.py backup_dir, without a Core)."""
    configured = os.environ.get("AGOS_BACKUP_DIR")
    return Path(configured) if configured else data_root.parent / "agos-backups"


def files(data_root: Path) -> list[Path]:
    """The hand-made copies still in the data folder."""
    system = data_root / "system"
    found = sorted(system.glob("MEMORY.*.bak-*")) + sorted(system.glob("before-one-copy-*"))
    stray = data_root / "agos.db"
    if stray.is_file() and stray.stat().st_size == 0:
        found.append(stray)
    return found


def rows(db: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    keys = [
        {"key": str(r[0]), "value": r[1], "updated_at": r[2]}
        for pattern in KEYS
        for r in db.execute(
            "SELECT key, value, updated_at FROM app_settings WHERE key GLOB ? ORDER BY key",
            (pattern,),
        )
    ]
    own = [
        {"id": r[0], "chat_id": r[1], "workspace_id": r[2], "activity": r[3]}
        for r in db.execute(_OWN)
    ]
    return {"app_settings": keys, "chat_turns": own}


def _free(target: Path) -> Path:
    n = 2
    out = target
    while out.exists():
        out = target.with_name(f"{target.name}-{n}")
        n += 1
    return out


def move(db: sqlite3.Connection, data_root: Path | None) -> list[Path]:
    """Moves the files and writes the rows into the backups folder; returns what it
    wrote there (none when nothing is left). Raises OSError when it can't: the
    migration then stops and nothing is dropped."""
    found = rows(db)
    paths = files(data_root) if data_root is not None else []
    if not paths and not any(found.values()):
        return []
    if data_root is None:
        raise OSError("no data folder: no backups folder to move the old copies into")
    folder = backups_folder(data_root) / f"old-copies-{datetime.now(UTC).strftime('%Y-%m-%d')}"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    written: list[Path] = []
    if any(found.values()):
        target = _free(folder / "rows.json")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(
                {
                    "about": (
                        "Old AGOS copies of Hermes data (step 32): app_settings keys no "
                        "code reads, and chat answers' whole tool steps (Hermes's "
                        "sessions hold them; AGOS kept only their approvals)."
                    ),
                    **found,
                },
                handle,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        written.append(target)
    for path in paths:
        target = _free(folder / path.relative_to(data_root))
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        written.append(target)
    return written
