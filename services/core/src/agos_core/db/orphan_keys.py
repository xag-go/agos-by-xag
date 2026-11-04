"""App-settings keys whose workspace or chat no longer exists, moved out at start.

`db/workspaces.purge_deleted` takes a purged workspace's keys with it since Step
33, but older purges left keys behind (`playbooks.written.<gone>`, a dead chat's
`hermes.effort.agos:<id>` …), and `ownership.unregistered` can't see them: their
prefixes are registered. Every start, each registered `*` key's id
(ownership.WILDCARD_IDS) is checked against its table — the trash keeps its rows,
so a trashed workspace's keys stay. Keys of ids that are gone are written, with
their values, into the backups folder (old-copies convention, db/old_copies.py)
and deleted; nothing is lost.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from agos_core.db.old_copies import backups_folder
from agos_core.db.ownership import WILDCARD_IDS

log = logging.getLogger(__name__)

_SESSION_PREFIX = "agos:"  # a chat key's id as the conversation's session key


def _ids(db: sqlite3.Connection, table: str) -> set[str]:
    assert table in ("workspaces", "chats")  # fixed names, never input
    return {str(row["id"]) for row in db.execute(f"SELECT id FROM {table}").fetchall()}


def sweep(db: sqlite3.Connection, data_root: Path) -> int:
    """Move every orphan key into the backups folder, then delete it. Returns how
    many moved. The write comes first: a failed write leaves everything in place."""
    workspaces = _ids(db, "workspaces")
    chats = _ids(db, "chats")
    orphans: list[sqlite3.Row] = []
    for row in db.execute("SELECT key, value FROM app_settings").fetchall():
        key = str(row["key"])
        wildcard = next((w for w in WILDCARD_IDS if key.startswith(w[:-1])), None)
        if wildcard is None or WILDCARD_IDS[wildcard] == "global":
            continue
        rest = key[len(wildcard) - 1 :]
        if rest.startswith(_SESSION_PREFIX):
            rest = rest[len(_SESSION_PREFIX) :]
        alive = workspaces if WILDCARD_IDS[wildcard] == "workspace" else chats
        if rest and rest not in alive:
            orphans.append(row)
    if not orphans:
        return 0
    now = datetime.now(UTC)
    folder = backups_folder(data_root) / f"old-copies-{now.strftime('%Y-%m-%d')}"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"app-settings-orphans-{now.strftime('%H%M%S')}.json"
    out.write_text(
        json.dumps(
            {str(row["key"]): str(row["value"]) for row in orphans},
            indent=1,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    for row in orphans:
        db.execute("DELETE FROM app_settings WHERE key = ?", (row["key"],))
    log.info("settings keys of gone workspaces/chats moved to %s: %d", out, len(orphans))
    return len(orphans)
