"""Repository of `card_services`: the servers Hermes started for a card (an agent's
dev server), with its process, port and when it stopped.

Owns every read and write of card_services (actions/card_services.py, the Board
service). Must not: import actions or engine, or start or stop a process.
"""

from __future__ import annotations

import sqlite3
from typing import Any

__all__ = ["add", "get", "of_card", "stop_on_port", "stop_process", "stopped"]


def of_card(db: sqlite3.Connection, workspace_id: str, card_id: str) -> list[sqlite3.Row]:
    """The card's services, newest first."""
    return list(
        db.execute(
            "SELECT * FROM card_services WHERE workspace_id = ? AND card = ? ORDER BY id DESC",
            (workspace_id, card_id),
        )
    )


def get(db: sqlite3.Connection, workspace_id: str, service_id: int) -> sqlite3.Row | None:
    """One service, only when it is this workspace's."""
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM card_services WHERE id = ? AND workspace_id = ?",
        (service_id, workspace_id),
    ).fetchone()
    return row


def stopped(db: sqlite3.Connection, workspace_id: str, service_id: int, at: str) -> None:
    """The service ended at `at` (unless it was marked already)."""
    db.execute(
        """UPDATE card_services SET stopped_at = ?
           WHERE id = ? AND workspace_id = ? AND stopped_at IS NULL""",
        (at, service_id, workspace_id),
    )


def stop_process(
    db: sqlite3.Connection, workspace_id: str, card_id: str, process_id: str, at: str
) -> None:
    """The card's services of Hermes's process `process_id` ended at `at`."""
    db.execute(
        """UPDATE card_services SET stopped_at = ?
             WHERE workspace_id = ? AND card = ? AND process_id = ?
               AND stopped_at IS NULL""",
        (at, workspace_id, card_id, process_id),
    )


def stop_on_port(
    db: sqlite3.Connection, workspace_id: str, card_id: str, port: int, at: str
) -> None:
    """The card's services on `port` ended at `at` (a new one took the port)."""
    db.execute(
        """UPDATE card_services SET stopped_at = ?
             WHERE workspace_id = ? AND card = ? AND port = ? AND stopped_at IS NULL""",
        (at, workspace_id, card_id, port),
    )


def add(db: sqlite3.Connection, workspace_id: str, card_id: str, row: dict[str, Any]) -> None:
    """A service Hermes started (`row`: profile, process_id, pid, pid_scope,
    started_mark, command, port, label, started_at)."""
    db.execute(
        """INSERT INTO card_services (workspace_id, card, profile, process_id, pid,
               pid_scope, started_mark, command, port, label, started_at)
           VALUES (:ws, :card, :profile, :process_id, :pid, :pid_scope, :started_mark,
                   :command, :port, :label, :started_at)""",
        {**row, "ws": workspace_id, "card": card_id},
    )
