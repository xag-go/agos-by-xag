"""Account-wide owner settings stored as JSON values."""

import sqlite3
from typing import Any

from agos_core.db.rows import dump_json, load_json, now


def get_setting(db: sqlite3.Connection, key: str, default: Any) -> Any:
    row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return load_json(row["value"]) if row else default


def set_setting(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute(
        """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        (key, dump_json(value), now()),
    )


def delete_setting(db: sqlite3.Connection, key: str) -> None:
    db.execute("DELETE FROM app_settings WHERE key = ?", (key,))


def with_prefix(db: sqlite3.Connection, prefix: str) -> list[tuple[str, str]]:
    """(key, its JSON text) of every setting whose key starts with `prefix`."""
    return [
        (str(r["key"]), str(r["value"]))
        for r in db.execute(
            "SELECT key, value FROM app_settings WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
        ).fetchall()
    ]
