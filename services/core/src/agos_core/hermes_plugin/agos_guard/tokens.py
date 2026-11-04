"""Token watch, inside Hermes: a Kanban card using far more tokens than usual.

Hermes counts each model call of the card's run (bridge.api_call_done). Here the
count is kept in Hermes's own Kanban, as events on the card (kind "agos_tokens",
one running total per run), and the mark is set by the board's own history: the
cards that finished there give a typical size, and a card past ~3x that (at least
3M tokens) is told once; again at twice the mark, 4x, 8x... ("agos_tokens_told").
Nothing is paused or stopped: the owner hears it (through AGOS, his screen) and
decides.
"""

from __future__ import annotations

import statistics
from typing import Any

MIN_MARK = 3_000_000  # below this, never "a lot"
FACTOR = 3  # x the board's typical finished card
HISTORY = 30  # finished cards looked at
COUNT = "agos_tokens"
TOLD = "agos_tokens_told"


def level_for(tokens: int, limit: int) -> int:
    """0 under the mark, then 1 (past it), 2 (2x), 3 (4x), 4 (8x)..."""
    if tokens < limit:
        return 0
    level, edge = 1, limit * 2
    while tokens >= edge:
        level += 1
        edge *= 2
    return level


def card_total(conn: Any, card: str) -> int:
    """A card's tokens: each run's latest total, added up."""
    rows = conn.execute(
        f"""SELECT MAX(CAST(json_extract(payload, '$.tokens') AS INTEGER))
              FROM task_events WHERE task_id = ? AND kind = '{COUNT}'
             GROUP BY COALESCE(run_id, -1)""",
        (card,),
    ).fetchall()
    return sum(int(r[0] or 0) for r in rows)


def mark(conn: Any, card: str = "") -> int:
    """How many tokens is "far more than usual" for a card on this board."""
    rows = conn.execute(
        f"""SELECT e.task_id, MAX(e.created_at) AS seen FROM task_events e
              JOIN tasks t ON t.id = e.task_id
             WHERE e.kind = '{COUNT}' AND t.status = 'done' AND e.task_id != ?
             GROUP BY e.task_id ORDER BY seen DESC LIMIT ?""",
        (card, HISTORY),
    ).fetchall()
    sizes = [n for n in (card_total(conn, str(r[0])) for r in rows) if n > 0]
    if len(sizes) < 3:
        return MIN_MARK * 2  # not enough history yet: a safe, high mark
    return max(MIN_MARK, int(statistics.median(sizes) * FACTOR))


def told_level(conn: Any, card: str) -> int:
    row = conn.execute(
        f"""SELECT MAX(CAST(json_extract(payload, '$.level') AS INTEGER))
              FROM task_events WHERE task_id = ? AND kind = '{TOLD}'""",
        (card,),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def record(conn: Any, append: Any, card: str, run: str, tokens: int) -> dict[str, int] | None:
    """The run's total so far, kept on the card in Hermes's Kanban. Returns what to
    tell the owner when the card just crossed a level (else None)."""
    run_id = int(run) if str(run).isdigit() else None
    append(conn, card, COUNT, {"tokens": int(tokens)}, run_id=run_id)
    total = card_total(conn, card)
    limit = mark(conn, card)
    level = level_for(total, limit)
    if level <= told_level(conn, card):
        return None
    usual = max(limit // FACTOR, 1)
    append(conn, card, TOLD, {"level": level, "tokens": total, "usual": usual}, run_id=run_id)
    return {"level": level, "tokens": total, "usual": usual}


def record_in_hermes(card: str, run: str, tokens: int) -> dict[str, int] | None:
    """`record` on this profile's board, through Hermes's own Kanban database code."""
    from hermes_cli import kanban_db  # type: ignore[import-not-found]
    from hermes_cli.kanban_db_connect import connect_closing  # type: ignore[import-not-found]

    with connect_closing() as conn, conn:
        return record(conn, kanban_db._append_event, card, run, tokens)
