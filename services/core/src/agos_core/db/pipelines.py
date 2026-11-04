"""Repository of the pipeline tables: `pipeline_rules` (a workspace's "when a card
moves, do this" rules) and `pipeline_seen` (the last move acted on per card, one
compare-and-set write so the same move told twice acts once).

Owns every read and write of pipeline_rules and pipeline_seen (actions/pipelines.py,
the Board service). Must not: import actions or engine, or touch a card.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "delete",
    "enabled",
    "fired",
    "insert",
    "of_workspace",
    "seen_mark",
    "seen_statuses",
    "set_seen",
    "set_seen_statuses",
    "update",
]


def of_workspace(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT * FROM pipeline_rules WHERE workspace_id = ? ORDER BY id", (workspace_id,)
        )
    )


def insert(db: sqlite3.Connection, workspace_id: str, fields: dict[str, Any], at: str) -> int:
    """A new rule (`fields`: its checked columns); its id."""
    cur = db.execute(
        """INSERT INTO pipeline_rules (workspace_id, name, trigger, status, goal_id,
               label, action, member, automation_id, text, enabled, created_at,
               updated_at)
           VALUES (:ws, :name, :trigger, :status, :goal_id, :label, :action, :member,
                   :automation_id, :text, :enabled, :at, :at)""",
        {**fields, "ws": workspace_id, "at": at},
    )
    return int(cur.lastrowid or 0)


def update(
    db: sqlite3.Connection, workspace_id: str, rule_id: int, fields: dict[str, Any], at: str
) -> bool:
    """A changed rule; False when it isn't this workspace's."""
    cur = db.execute(
        """UPDATE pipeline_rules SET name = :name, trigger = :trigger,
               status = :status, goal_id = :goal_id, label = :label,
               action = :action, member = :member, automation_id = :automation_id,
               text = :text, enabled = :enabled, updated_at = :at
             WHERE id = :id AND workspace_id = :ws""",
        {**fields, "ws": workspace_id, "at": at, "id": rule_id},
    )
    return cur.rowcount > 0


def delete(db: sqlite3.Connection, workspace_id: str, rule_id: int) -> bool:
    """False when the rule isn't this workspace's."""
    cur = db.execute(
        "DELETE FROM pipeline_rules WHERE id = ? AND workspace_id = ?",
        (rule_id, workspace_id),
    )
    return cur.rowcount > 0


def enabled(
    db: sqlite3.Connection, workspace_id: str, triggers: tuple[str, ...]
) -> list[sqlite3.Row]:
    """The workspace's rules that are on, for these triggers."""
    return list(
        db.execute(
            sql.text(
                """SELECT * FROM pipeline_rules WHERE workspace_id = ? AND enabled = 1
                  AND trigger IN ({marks}) ORDER BY id""",
                marks=sql.marks(len(triggers)),
            ),
            (workspace_id, *triggers),
        )
    )


def fired(db: sqlite3.Connection, workspace_id: str, rule_id: int, outcome: str) -> None:
    """The rule acted now, with this outcome."""
    db.execute(
        """UPDATE pipeline_rules SET last_fired_at = ?, last_outcome = ?
           WHERE id = ? AND workspace_id = ?""",
        (now(), outcome, rule_id, workspace_id),
    )


def seen_mark(db: sqlite3.Connection, workspace_id: str, card: str, kind: str) -> str | None:
    """The last move acted on for this card and kind; None when none was."""
    row = db.execute(
        "SELECT mark FROM pipeline_seen WHERE workspace_id = ? AND card = ? AND kind = ?",
        (workspace_id, card, kind),
    ).fetchone()
    return None if row is None else str(row["mark"])


def set_seen(
    db: sqlite3.Connection, workspace_id: str, card: str, kind: str, mark: str, at: str
) -> None:
    db.execute(
        """INSERT INTO pipeline_seen (workspace_id, card, kind, mark, seen_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (workspace_id, card, kind) DO UPDATE
             SET mark = excluded.mark, seen_at = excluded.seen_at""",
        (workspace_id, card, kind, mark, at),
    )


def seen_statuses(db: sqlite3.Connection, workspace_id: str) -> dict[str, str]:
    """{card: the last status acted on}."""
    return {
        str(r["card"]): str(r["mark"])
        for r in db.execute(
            "SELECT card, mark FROM pipeline_seen WHERE workspace_id = ? AND kind = 'status'",
            (workspace_id,),
        )
    }


def set_seen_statuses(
    db: sqlite3.Connection, workspace_id: str, statuses: Iterable[tuple[str, str]], at: str
) -> None:
    """Each (card, status) is the last status acted on."""
    for card, status in statuses:
        set_seen(db, workspace_id, card, "status", status, at)
