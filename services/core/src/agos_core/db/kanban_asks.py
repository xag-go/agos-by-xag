"""Repository of `kanban_asks`: what a member working a Kanban card waits on from the
owner (an Autonomy ask: Allow once / Deny) and the proposals and questions kept in
the same table (their kind).

Owns every read and write of kanban_asks: the Board service's (actions/kanban_asks.py,
the Inbox and the Channel service's buttons) and the proposals' (actions/services/
proposals: recording a round, the owner's decision, its Undo). Must not: import
actions or engine.
"""

import sqlite3
from collections.abc import Collection

from agos_core.db import sql
from agos_core.db.rows import now

__all__ = [
    "add_ask",
    "add_proposal",
    "add_question",
    "answered",
    "ask_labels",
    "card_rows",
    "daily_plans",
    "decide",
    "decided",
    "get",
    "goal_proposed",
    "goal_titles_waiting",
    "in_kinds",
    "in_workspace",
    "latest_id",
    "latest_round",
    "of_card",
    "of_kind",
    "status_of",
    "waiting_asks",
    "waiting_count",
    "waiting_in_kinds",
    "waiting_of_kind",
    "waiting_payloads",
    "workspace_of",
]


def add_ask(
    db: sqlite3.Connection,
    workspace_id: str,
    card: str,
    member: str,
    action: str,
    label: str,
    detail: str,
) -> int | None:
    """A new waiting ask; None when the same one waits already."""
    cur = db.execute(
        """INSERT OR IGNORE INTO kanban_asks
             (workspace_id, card, member, action, label, detail, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, card, member, action, label, detail, now()),
    )
    return int(cur.lastrowid or 0) if cur.rowcount else None


def add_question(
    db: sqlite3.Connection,
    workspace_id: str,
    card: str,
    member: str,
    action: str,
    label: str,
    detail: str,
    kind: str,
    payload: str,
) -> int | None:
    """A new waiting question of a card (its first round); None when one waits already."""
    cur = db.execute(
        """INSERT OR IGNORE INTO kanban_asks
             (workspace_id, card, member, action, label, detail, created_at, kind,
              payload, round)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (workspace_id, card, member, action, label, detail, now(), kind, payload, 1),
    )
    return int(cur.lastrowid or 0) if cur.rowcount else None


def latest_id(db: sqlite3.Connection, workspace_id: str, card: str) -> int | None:
    row = db.execute(
        "SELECT id FROM kanban_asks WHERE workspace_id = ? AND card = ? ORDER BY id DESC LIMIT 1",
        (workspace_id, card),
    ).fetchone()
    return int(row["id"]) if row else None


def of_card(db: sqlite3.Connection, workspace_id: str, card: str, kind: str) -> list[sqlite3.Row]:
    """A card's asks of one kind, newest first."""
    return db.execute(
        "SELECT * FROM kanban_asks WHERE workspace_id = ? AND card = ? AND kind = ? "
        "ORDER BY id DESC",
        (workspace_id, card, kind),
    ).fetchall()


def waiting_of_kind(
    db: sqlite3.Connection, workspace_id: str, kind: str, limit: int
) -> list[sqlite3.Row]:
    return db.execute(
        """SELECT * FROM kanban_asks WHERE workspace_id = ? AND status = 'waiting'
             AND kind = ? ORDER BY id LIMIT ?""",
        (workspace_id, kind, limit),
    ).fetchall()


def daily_plans(db: sqlite3.Connection, workspace_id: str, date: str) -> list[sqlite3.Row]:
    """The daily-plan proposals (kind goal, change daily_plan) for `date`, newest first."""
    return list(
        db.execute(
            """SELECT * FROM kanban_asks WHERE workspace_id = ? AND kind = 'goal'
                 AND json_valid(payload) AND json_extract(payload, '$.change') = 'daily_plan'
                 AND json_extract(payload, '$.date') = ? ORDER BY id DESC""",
            (workspace_id, date),
        )
    )


def of_kind(
    db: sqlite3.Connection, workspace_id: str, ask_id: int, kind: str
) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_asks WHERE id = ? AND workspace_id = ? AND kind = ?",
        (ask_id, workspace_id, kind),
    ).fetchone()
    return row


def answered(db: sqlite3.Connection, ask_id: int, result: str, *, only_waiting: bool) -> None:
    """Answered with `result` (JSON); `only_waiting`: unless it was decided meanwhile."""
    if only_waiting:
        db.execute(
            """UPDATE kanban_asks SET status = 'answered', decided_at = ?, result = ?
                 WHERE id = ? AND status = 'waiting'""",
            (now(), result, ask_id),
        )
        return
    db.execute(
        "UPDATE kanban_asks SET status = 'answered', decided_at = ?, result = ? WHERE id = ?",
        (now(), result, ask_id),
    )


def get(db: sqlite3.Connection, ask_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_asks WHERE id = ?", (ask_id,)
    ).fetchone()
    return row


def in_workspace(db: sqlite3.Connection, workspace_id: str, ask_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM kanban_asks WHERE id = ? AND workspace_id = ?", (ask_id, workspace_id)
    ).fetchone()
    return row


def waiting_asks(db: sqlite3.Connection, workspace_id: str, limit: int) -> list[sqlite3.Row]:
    """The Autonomy asks still waiting, oldest first."""
    return db.execute(
        """SELECT * FROM kanban_asks WHERE workspace_id = ? AND status = 'waiting'
             AND kind = 'ask' ORDER BY id LIMIT ?""",
        (workspace_id, limit),
    ).fetchall()


def ask_labels(db: sqlite3.Connection, workspace_id: str, card: str) -> list[sqlite3.Row]:
    """(label, status) of every Autonomy ask of one card."""
    return db.execute(
        """SELECT label, status FROM kanban_asks WHERE workspace_id = ? AND card = ?
             AND kind = 'ask'""",
        (workspace_id, card),
    ).fetchall()


def decide(db: sqlite3.Connection, ask_id: int, status: str) -> None:
    db.execute(
        "UPDATE kanban_asks SET status = ?, decided_at = ? WHERE id = ?",
        (status, now(), ask_id),
    )


def status_of(db: sqlite3.Connection, ask_id: int) -> str | None:
    """Where an ask stands (waiting, allowed, ...); None when it is gone."""
    row = db.execute("SELECT status FROM kanban_asks WHERE id = ?", (ask_id,)).fetchone()
    return str(row["status"]) if row else None


def workspace_of(db: sqlite3.Connection, ask_id: int) -> str | None:
    row = db.execute("SELECT workspace_id FROM kanban_asks WHERE id = ?", (ask_id,)).fetchone()
    return str(row["workspace_id"]) if row else None


# ---- proposals (actions/services/proposals) ---------------------------------------------


def add_proposal(
    db: sqlite3.Connection,
    workspace_id: str,
    card: str,
    member: str,
    kind: str,
    label: str,
    detail: str,
    payload: str,
    round_: int,
) -> int | None:
    """A new waiting proposal round of a card; None when one waits already."""
    cur = db.execute(
        """INSERT OR IGNORE INTO kanban_asks
             (workspace_id, card, member, action, label, detail, created_at, kind,
              payload, round)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            card,
            member,
            f"proposal:{kind}",
            label,
            detail,
            now(),
            kind,
            payload,
            round_,
        ),
    )
    return int(cur.lastrowid or 0) if cur.rowcount else None


def card_rows(db: sqlite3.Connection, workspace_id: str, card: str) -> list[sqlite3.Row]:
    """Every row of one card, any kind, newest first."""
    return db.execute(
        "SELECT * FROM kanban_asks WHERE workspace_id = ? AND card = ? ORDER BY id DESC",
        (workspace_id, card),
    ).fetchall()


def latest_round(db: sqlite3.Connection, workspace_id: str, card: str) -> int | None:
    """The round of a card's newest row; None when the card has none."""
    row = db.execute(
        "SELECT round FROM kanban_asks WHERE workspace_id = ? AND card = ? ORDER BY id DESC LIMIT 1",
        (workspace_id, card),
    ).fetchone()
    return int(row["round"]) if row is not None else None


def waiting_in_kinds(
    db: sqlite3.Connection, workspace_id: str, kinds: Collection[str], limit: int
) -> list[sqlite3.Row]:
    """The waiting rows of any of `kinds`, oldest first."""
    return db.execute(
        sql.text(
            """SELECT * FROM kanban_asks WHERE workspace_id = ? AND status = 'waiting'
             AND kind IN ({kinds}) ORDER BY id LIMIT ?""",
            kinds=sql.marks(len(kinds)),
        ),
        (workspace_id, *kinds, limit),
    ).fetchall()


def in_kinds(
    db: sqlite3.Connection, workspace_id: str, ask_id: int, kinds: Collection[str]
) -> sqlite3.Row | None:
    """One row of this workspace when it is one of `kinds`."""
    row: sqlite3.Row | None = db.execute(
        sql.text(
            "SELECT * FROM kanban_asks WHERE id = ? AND workspace_id = ? AND kind IN ({kinds})",
            kinds=sql.marks(len(kinds)),
        ),
        (ask_id, workspace_id, *kinds),
    ).fetchone()
    return row


def waiting_count(db: sqlite3.Connection, workspace_id: str) -> int:
    """Every waiting row of a workspace (asks, proposals, questions)."""
    row = db.execute(
        "SELECT COUNT(*) AS n FROM kanban_asks WHERE workspace_id = ? AND status = 'waiting'",
        (workspace_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def waiting_payloads(db: sqlite3.Connection, workspace_id: str, kind: str) -> list[sqlite3.Row]:
    """(card, payload JSON text) of every waiting row of one kind, oldest first."""
    return db.execute(
        "SELECT card, payload FROM kanban_asks WHERE workspace_id = ? AND kind = ? "
        "AND status = 'waiting' ORDER BY id",
        (workspace_id, kind),
    ).fetchall()


def goal_titles_waiting(db: sqlite3.Connection, workspace_id: str) -> list[str]:
    """The titles of the add_goal proposals still waiting for the owner."""
    return [
        str(r["title"] or "")
        for r in db.execute(
            """SELECT json_extract(payload, '$.title') AS title FROM kanban_asks
               WHERE workspace_id = ? AND kind = 'goal' AND status = 'waiting'
               AND json_extract(payload, '$.change') = 'add_goal'""",
            (workspace_id,),
        )
    ]


def goal_proposed(db: sqlite3.Connection, workspace_id: str, notes_key: str) -> bool:
    """A goal proposal (any status) was made from this Vision notes key."""
    found = db.execute(
        """SELECT 1 FROM kanban_asks WHERE workspace_id = ? AND kind = 'goal'
           AND json_extract(payload, '$.notes_key') = ? LIMIT 1""",
        (workspace_id, notes_key),
    ).fetchone()
    return found is not None


def decided(
    db: sqlite3.Connection,
    workspace_id: str,
    ask_id: int,
    status: str,
    note: str | None,
    result: str | None,
) -> None:
    """The owner's decision on a waiting proposal (unless it was decided meanwhile)."""
    db.execute(
        """UPDATE kanban_asks SET status = ?, decided_at = ?, note = ?, result = ?
           WHERE id = ? AND workspace_id = ? AND status = 'waiting'""",
        (status, now(), note, result, ask_id, workspace_id),
    )
