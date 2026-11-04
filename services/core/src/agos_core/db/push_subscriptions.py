"""The push_subscriptions table: browsers that asked for the installed AGOS app's own
notifications (actions/web_push.py is its one caller).

Owns: adding or refreshing a browser's subscription, dropping one, and the list.

Must not: send anything (actions/web_push.py does).
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["drop", "listed", "save"]


def save(
    db: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, label: str, at: str
) -> None:
    """The browser's subscription, new or refreshed (its keys, label and last seen)."""
    db.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, label, created_at, seen_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,
             label = excluded.label, seen_at = excluded.seen_at""",
        (endpoint, p256dh, auth, label, at, at),
    )


def drop(db: sqlite3.Connection, endpoint: str) -> bool:
    """True when there was such a subscription."""
    before = db.total_changes
    db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    return db.total_changes > before


def listed(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in db.execute(
            "SELECT id, endpoint, p256dh, auth, label, created_at, seen_at FROM push_subscriptions ORDER BY id"
        ).fetchall()
    ]
