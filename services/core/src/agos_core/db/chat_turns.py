"""Repository of `chat_turns`: one record per answer a chat gives (the turn
working now, AGOS's part of each: its status, Hermes run, reply, activity, error).

Split out of db/chats.py (which re-exports these names). The doorbell rings that tell
the send round and the open live views about a new or ended turn are the Chat
service's (actions/services/chat/chat_writes.py), never this repository's.

Owns: every read and write of chat_turns. Must not: import actions or engine, or
touch another table.
"""

import sqlite3
from dataclasses import dataclass
from typing import Any, Literal

from agos_core.db import sql
from agos_core.db.rows import dump_json, now

__all__ = [
    "LIVE",
    "LIVE_SQL",
    "TurnRow",
    "TurnStatus",
    "all_of",
    "answered_before",
    "answered_up_to",
    "ended",
    "ended_by",
    "fail_unreported",
    "get_turn",
    "ids_of",
    "insert_turn",
    "last_settled",
    "last_two",
    "live_records",
    "live_turn",
    "live_turns",
    "raise_asked_up_to",
    "ran_on_hermes",
    "run_turn_since",
    "run_via",
    "set_speaker",
    "set_turn",
    "started_at",
    "workspace_busy",
]

TurnStatus = Literal["starting", "running", "stopping", "completed", "failed", "stopped"]
LIVE: tuple[TurnStatus, ...] = ("starting", "running", "stopping")
LIVE_SQL = sql.marks(len(LIVE))


@dataclass(frozen=True)
class TurnRow:
    id: int
    chat_id: int
    workspace_id: str
    hermes_run_id: str | None
    status: TurnStatus
    asked_up_to: int
    speaker: str | None = None
    # 'hermes': answered by the workspace's Hermes gateway, which reports to AGOS
    # itself, so AGOS never follows, restarts or re-asks it. 'room': a Hermes room.
    via: str | None = None


def _turn_row(r: sqlite3.Row) -> TurnRow:
    return TurnRow(
        id=r["id"],
        chat_id=r["chat_id"],
        workspace_id=r["workspace_id"],
        hermes_run_id=r["hermes_run_id"],
        status=r["status"],
        asked_up_to=r["asked_up_to"],
        speaker=r["speaker"],
        via=r["via"] if "via" in r.keys() else None,  # noqa: SIM118 — sqlite3.Row
    )


def live_turn(db: sqlite3.Connection, chat_id: int) -> TurnRow | None:
    r = db.execute(
        sql.text(
            "SELECT * FROM chat_turns WHERE chat_id = ? AND status IN ({live})", live=LIVE_SQL
        ),
        (chat_id, *LIVE),
    ).fetchone()
    return _turn_row(r) if r else None


def live_turns(db: sqlite3.Connection) -> list[TurnRow]:
    return [
        _turn_row(r)
        for r in db.execute(
            sql.text(
                "SELECT * FROM chat_turns WHERE status IN ({live}) ORDER BY id", live=LIVE_SQL
            ),
            LIVE,
        )
    ]


def get_turn(db: sqlite3.Connection, turn_id: int) -> TurnRow | None:
    r = db.execute("SELECT * FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    return _turn_row(r) if r else None


def answered_up_to(db: sqlite3.Connection, chat_id: int) -> int:
    """The owner's messages up to this id got (or are getting) an answer (a room)."""
    r = db.execute(
        "SELECT MAX(asked_up_to) FROM chat_turns WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    return int(r[0] or 0)


def insert_turn(
    db: sqlite3.Connection,
    *,
    chat_id: int,
    workspace_id: str,
    asked_up_to: int,
    speaker: str | None = None,
    status: str = "starting",
) -> int:
    """A new turn record. `status` 'completed' makes a record that is never live (a
    card's or an automation's run in the Co-Founder chat): the one-live-turn-per-chat
    rule (chat_turns_one_live) only holds live ones, so it never collides with the
    answer the chat is giving right now."""
    cursor = db.execute(
        """INSERT INTO chat_turns (chat_id, workspace_id, status, asked_up_to, started_at,
                                   speaker)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (chat_id, workspace_id, status, asked_up_to, now(), speaker),
    )
    return int(cursor.lastrowid or 0)


# What AGOS writes on a turn record. Never its model, provider or tokens: those
# are Hermes's (its sessions, session_model_usage).
_TURN_FIELDS = {
    "hermes_run_id",
    "status",
    "reply_id",
    "activity",
    "error",
    "ended_at",
}


def set_turn(db: sqlite3.Connection, turn_id: int, **fields: Any) -> None:
    unknown = set(fields) - _TURN_FIELDS
    if unknown:
        raise ValueError(f"unknown turn fields: {sorted(unknown)}")
    values = [dump_json(v) if k == "activity" else v for k, v in fields.items()]
    db.execute(
        sql.text(
            "UPDATE chat_turns SET {sets} WHERE id = ?",
            sets=sql.assignments(fields, _TURN_FIELDS),
        ),
        (*values, turn_id),
    )


def workspace_busy(db: sqlite3.Connection, workspace_id: str) -> bool:
    """A chat answer of the workspace is live now."""
    return (
        db.execute(
            sql.text(
                "SELECT 1 FROM chat_turns WHERE workspace_id = ? AND status IN ({live}) LIMIT 1",
                live=LIVE_SQL,
            ),
            (workspace_id, *LIVE),
        ).fetchone()
        is not None
    )


def ran_on_hermes(db: sqlite3.Connection, chat_id: int) -> bool:
    """One of the chat's answers was a Hermes run (not an AGOS row)."""
    return (
        db.execute(
            """SELECT 1 FROM chat_turns WHERE chat_id = ? AND hermes_run_id IS NOT NULL
                 AND hermes_run_id NOT LIKE 'row:%' LIMIT 1""",
            (chat_id,),
        ).fetchone()
        is not None
    )


def ended_by(db: sqlite3.Connection, turn_id: int, via: str) -> None:
    """A record made already ended, answered by `via` (a room's command line Hermes
    answered itself)."""
    db.execute(
        "UPDATE chat_turns SET status = 'completed', via = ?, ended_at = ? WHERE id = ?",
        (via, now(), turn_id),
    )


def last_settled(db: sqlite3.Connection, chat_id: int, settle_s: int) -> sqlite3.Row | None:
    """The chat's last turn record, with `settled`: it ended over `settle_s` ago."""
    row: sqlite3.Row | None = db.execute(
        """SELECT id, status, reply_id, started_at, ended_at,
                  ended_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?) AS settled
             FROM chat_turns WHERE chat_id = ? ORDER BY id DESC LIMIT 1""",
        (f"-{settle_s} seconds", chat_id),
    ).fetchone()
    return row


def raise_asked_up_to(db: sqlite3.Connection, turn_id: int, asked_up_to: int) -> None:
    db.execute(
        "UPDATE chat_turns SET asked_up_to = MAX(asked_up_to, ?) WHERE id = ?",
        (asked_up_to, turn_id),
    )


def run_via(db: sqlite3.Connection, turn_id: int, via: str) -> None:
    """A new record is running now, answered by `via` (the workspace's Hermes gateway)."""
    db.execute("UPDATE chat_turns SET status = 'running', via = ? WHERE id = ?", (via, turn_id))


def live_records(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """(id, workspace_id, started_at, via, chat) of every live turn."""
    return db.execute(
        "SELECT t.id, t.workspace_id, t.started_at, t.via, c.id AS chat FROM chat_turns t"
        " JOIN chats c ON c.id = t.chat_id"
        " WHERE t.status IN ('starting', 'running', 'stopping')"
    ).fetchall()


def fail_unreported(db: sqlite3.Connection, via: str, started_before: str, error: str) -> int:
    """Live turns answered by `via` (or a room) started before a time: failed now."""
    return db.execute(
        """UPDATE chat_turns SET status = 'failed', ended_at = ?,
             error = ?
           WHERE via IN (?, 'room') AND status IN ('starting','running','stopping')
             AND started_at < ?""",
        (now(), error, via, started_before),
    ).rowcount


def set_speaker(db: sqlite3.Connection, turn_id: int, speaker: str | None) -> None:
    """Who answers in a room's turn now (no ring: the live view's version moves)."""
    db.execute("UPDATE chat_turns SET speaker = ? WHERE id = ?", (speaker, turn_id))


def last_two(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """(id, status, asked_up_to) of the chat's two newest turn records."""
    return db.execute(
        "SELECT id, status, asked_up_to FROM chat_turns WHERE chat_id = ? ORDER BY id DESC LIMIT 2",
        (chat_id,),
    ).fetchall()


def answered_before(db: sqlite3.Connection, chat_id: int, turn_id: int) -> int:
    """How far the last answer before this turn that didn't fail or stop got (0: none)."""
    row = db.execute(
        """SELECT asked_up_to FROM chat_turns WHERE chat_id = ? AND id < ?
             AND status NOT IN ('failed', 'stopped') ORDER BY id DESC LIMIT 1""",
        (chat_id, turn_id),
    ).fetchone()
    return int(row["asked_up_to"]) if row else 0


def ids_of(db: sqlite3.Connection, chat_id: int) -> list[int]:
    return [
        int(r["id"]) for r in db.execute("SELECT id FROM chat_turns WHERE chat_id = ?", (chat_id,))
    ]


def started_at(db: sqlite3.Connection, turn_id: int) -> str | None:
    row = db.execute("SELECT started_at FROM chat_turns WHERE id = ?", (turn_id,)).fetchone()
    return str(row["started_at"]) if row else None


def ended(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """The chat's finished turn records, oldest first."""
    return db.execute(
        sql.text(
            "SELECT * FROM chat_turns WHERE chat_id = ? AND status NOT IN ({live}) ORDER BY id",
            live=LIVE_SQL,
        ),
        (chat_id, *LIVE),
    ).fetchall()


def all_of(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """Every turn record of the chat, oldest first."""
    return db.execute(
        "SELECT * FROM chat_turns WHERE chat_id = ? ORDER BY id", (chat_id,)
    ).fetchall()


def run_turn_since(
    db: sqlite3.Connection, workspace_id: str, chat_id: int, run_id: str, since: str
) -> int | None:
    """The newest turn of a chat carrying this Hermes run id, started at `since` or later."""
    row = db.execute(
        """SELECT id FROM chat_turns WHERE workspace_id = ? AND chat_id = ?
             AND hermes_run_id = ? AND started_at >= ? ORDER BY id DESC LIMIT 1""",
        (workspace_id, chat_id, run_id, since),
    ).fetchone()
    return int(row["id"]) if row is not None else None
