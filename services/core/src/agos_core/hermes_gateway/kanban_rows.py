"""Reads of a workspace's Hermes Kanban board database (kanban.db), read-only (ADR 0024).

Hermes's board is Hermes's: its cards (tasks), their links, comments, events, runs,
attachments and notify subscriptions. The Board service reads it here, one query per
method, on one read-only handle (`opened`); what the rows mean is the caller's.

Owns: every SQL statement AGOS runs on a Kanban board database (the board's own
tables, read as Hermes wrote them; older boards may lack a column or a table).
Must not: write the board (that is Hermes's CLI: actions/services/board/kanban_cli.py),
open another workspace's board, or shape rows for a page.
Errors are sqlite3.Error, as from the database itself.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from agos_core.db import sql
from agos_core.hermes_gateway import hermes_db

__all__ = ["Board", "open_board", "opened"]

# The card's creator columns (older boards may lack them: read as NULL).
_CREATOR = ("created_by", "idempotency_key")
# The columns of the scope read (status cards); older boards may lack some.
SCOPE_COLUMNS = ("id", "title", "body", "status", "assignee", "block_kind", "completed_at")
# The searchable words of a card, and what a card hit shows.
_CARD_TEXT = ("title", "body", "result")
_CARD_HIT = ("id", "title", "body", "result", "status", "created_at")
_TABLES = ("tasks", "task_comments", "task_attachments")
_CHUNK = 500
_ALL_WORDS = "instr(lower({expr}), ?) > 0"


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _all_in(expr: str, words: Sequence[str]) -> sql.Piece:
    """SQL: every word is in `expr` (any case); `expr` is built from checked names."""
    return sql.Piece(" AND ".join(_ALL_WORDS.format(expr=expr) for _ in words))


class Board:
    """One read-only handle on a Hermes board database (the caller closes it)."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def close(self) -> None:
        self.db.close()

    # ---- the board's shape -----------------------------------------------------------

    def columns(self, table: str) -> set[str]:
        """The columns of one of the board's tables; none when it can't be read."""
        try:
            return {
                str(r[1])
                for r in self.db.execute(
                    sql.text("PRAGMA table_info({t})", t=sql.name(table, _TABLES))
                )
            }
        except sqlite3.Error:
            return set()

    def tables(self) -> set[str]:
        return {str(r[0]) for r in self.db.execute("SELECT name FROM sqlite_master")}

    # ---- cards -----------------------------------------------------------------------

    def stamp_rows(self) -> list[Any]:
        """Every field of every card AGOS shows, by id (what the board's stamp hashes)."""
        return self.db.execute(
            """SELECT id, title, body, assignee, status, created_by, created_at,
                      started_at, completed_at, model_override, goal_mode, block_kind
                 FROM tasks ORDER BY id"""
        ).fetchall()

    def extra_rows(self) -> list[Any]:
        """(id, goal_mode, block_kind, status, body, assignee) of every card."""
        return self.db.execute(
            "SELECT id, goal_mode, block_kind, status, body, assignee FROM tasks"
        ).fetchall()

    def statuses(self) -> list[Any]:
        """(id, status) of every card."""
        return self.db.execute("SELECT id, status FROM tasks").fetchall()

    def unarchived(self) -> list[Any]:
        """(id, status, created_at) of every card not archived."""
        return self.db.execute(
            "SELECT id, status, created_at FROM tasks WHERE status != 'archived'"
        ).fetchall()

    def card(self, card_id: str) -> tuple[sqlite3.Row | None, list[str]]:
        """A card (id, title, body, status, created_at, by name) and its comments' words."""
        self.db.row_factory = sqlite3.Row
        task = self.db.execute(
            "SELECT id, title, body, status, created_at FROM tasks WHERE id = ?", (card_id,)
        ).fetchone()
        if task is None:
            return None, []
        comments = [
            str(r["body"] or "")
            for r in self.db.execute(
                "SELECT body FROM task_comments WHERE task_id = ? ORDER BY id", (card_id,)
            )
        ]
        return task, comments

    def facts(self, card_ids: Sequence[str]) -> list[Any]:
        """(id, status, title, result) of these cards."""
        return self.db.execute(
            sql.text(
                "SELECT id, status, title, result FROM tasks WHERE id IN ({m})",
                m=sql.marks(len(card_ids)),
            ),
            tuple(card_ids),
        ).fetchall()

    def keyed(self, prefix: str) -> list[Any]:
        """The cards whose idempotency key starts with `prefix`: (id, status, title,
        result, idempotency_key, created_at, completed_at, assignee)."""
        return self.db.execute(
            """SELECT id, status, title, result, idempotency_key, created_at, completed_at,
                      assignee
               FROM tasks WHERE idempotency_key LIKE ? ESCAPE '\\'""",
            (_like_prefix(prefix),),
        ).fetchall()

    def made_in(self, session_prefix: str) -> list[Any]:
        """(id, title, body, status, created_at) of the cards made in sessions whose id
        starts with `session_prefix`, oldest first."""
        return self.db.execute(
            """SELECT id, title, body, status, created_at FROM tasks
               WHERE session_id LIKE ? ESCAPE '\\' ORDER BY created_at, id""",
            (_like_prefix(session_prefix),),
        ).fetchall()

    def done_since(self, since: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = 'done' AND completed_at >= ?",
            (since,),
        ).fetchone()
        return int(row[0] or 0) if row else 0

    def latest_by(self, profile: str, limit: int) -> list[Any]:
        """(id, title, status, result) of a profile's newest cards."""
        return self.db.execute(
            """SELECT id, title, status, result FROM tasks WHERE assignee = ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (profile, limit),
        ).fetchall()

    def needs_input(self) -> list[Any]:
        """(id, title, assignee, last block payload) of the cards blocked for input."""
        return self.db.execute(
            """SELECT t.id, t.title, t.assignee,
                 (SELECT e.payload FROM task_events e WHERE e.task_id = t.id
                    AND e.kind = 'blocked' ORDER BY e.id DESC LIMIT 1)
               FROM tasks t WHERE t.status = 'blocked' AND t.block_kind = 'needs_input'
               ORDER BY t.id LIMIT 20"""
        ).fetchall()

    def needs_input_of(self, card: str) -> Any:
        """(last block payload, body, assignee) of a card blocked for input; None else."""
        return self.db.execute(
            """SELECT (SELECT e.payload FROM task_events e WHERE e.task_id = t.id
                         AND e.kind = 'blocked' ORDER BY e.id DESC LIMIT 1),
                      t.body, t.assignee
               FROM tasks t WHERE t.id = ? AND t.status = 'blocked'
                 AND t.block_kind = 'needs_input'""",
            (card,),
        ).fetchone()

    def open_with_blocks(self) -> list[Any]:
        """Every card not done or archived: (id, status, block_kind, assignee, title,
        running, last block payload, when it last blocked or waited)."""
        return self.db.execute(
            """SELECT t.id, t.status, t.block_kind, t.assignee, t.title,
                      t.current_run_id IS NOT NULL AND t.status = 'running',
                      (SELECT e.payload FROM task_events e WHERE e.task_id = t.id
                         AND e.kind = 'blocked' ORDER BY e.id DESC LIMIT 1),
                      (SELECT e.created_at FROM task_events e WHERE e.task_id = t.id
                         AND e.kind IN ('blocked', 'dependency_wait')
                         ORDER BY e.id DESC LIMIT 1)
               FROM tasks t WHERE t.status NOT IN ('done', 'archived')"""
        ).fetchall()

    def at_owner(self, owner: str) -> list[Any]:
        """(id, status, assignee, body) of the cards in review at `owner`, or blocked."""
        return self.db.execute(
            """SELECT id, status, assignee, body FROM tasks
               WHERE (status = 'review' AND assignee = ?) OR status = 'blocked'""",
            (owner,),
        ).fetchall()

    def titles_at_owner(self, owner: str) -> list[Any]:
        """(id, title) of the same cards as `at_owner`."""
        return self.db.execute(
            "SELECT id, title FROM tasks WHERE (status = 'review' AND assignee = ?) "
            "OR status = 'blocked'",
            (owner,),
        ).fetchall()

    def scope_tasks(self) -> list[dict[str, Any]]:
        """Every card with SCOPE_COLUMNS (a column the board lacks reads as None)."""
        have = self.columns("tasks")
        picked = sql.or_null(SCOPE_COLUMNS, have, SCOPE_COLUMNS)
        return [
            dict(zip(SCOPE_COLUMNS, r, strict=True))
            for r in self.db.execute(sql.text("SELECT {picked} FROM tasks", picked=picked))
        ]

    def creators(self, task_ids: Sequence[str]) -> dict[str, tuple[str, str]]:
        """{card: (created_by, idempotency_key)}; what was read before an error."""
        found: dict[str, tuple[str, str]] = {}
        with contextlib.suppress(sqlite3.Error):
            have = self.columns("tasks")
            picked = sql.or_null(_CREATOR, have, _CREATOR)
            for chunk in range(0, len(task_ids), _CHUNK):
                names = list(task_ids[chunk : chunk + _CHUNK])
                for i, by, key in self.db.execute(
                    sql.text(
                        "SELECT id, {picked} FROM tasks WHERE id IN ({ids})",
                        picked=picked,
                        ids=sql.marks(len(names)),
                    ),
                    names,
                ):
                    found[str(i)] = (str(by or ""), str(key or ""))
        return found

    # ---- links -----------------------------------------------------------------------

    def links(self) -> list[Any]:
        """(parent_id, child_id) of every link."""
        return self.db.execute("SELECT parent_id, child_id FROM task_links").fetchall()

    def parents_of(self, card_ids: Sequence[str]) -> list[Any]:
        """(parent_id, child_id) of the links into these cards."""
        if not card_ids:
            return []
        return self.db.execute(
            sql.text(
                "SELECT parent_id, child_id FROM task_links WHERE child_id IN ({m})",
                m=sql.marks(len(card_ids)),
            ),
            tuple(card_ids),
        ).fetchall()

    # ---- events and runs -------------------------------------------------------------

    def events(self, kinds: Sequence[str], limit: int) -> list[Any]:
        """The latest events of these kinds, newest first: (id, task_id, kind, payload,
        created_at, card title)."""
        return self.db.execute(
            sql.text(
                """SELECT e.id, e.task_id, e.kind, e.payload, e.created_at, t.title
                FROM task_events e LEFT JOIN tasks t ON t.id = e.task_id
                WHERE e.kind IN ({kinds})
                ORDER BY e.id DESC LIMIT ?""",
                kinds=sql.marks(len(kinds)),
            ),
            (*kinds, limit),
        ).fetchall()

    def events_since(self, since: float, kinds: Sequence[str]) -> list[Any]:
        """Events of these kinds after `since`, oldest first: (task_id, kind, payload,
        created_at, card title)."""
        return self.db.execute(
            sql.text(
                """SELECT e.task_id, e.kind, e.payload, e.created_at, t.title
                  FROM task_events e LEFT JOIN tasks t ON t.id = e.task_id
                 WHERE e.created_at > ? AND e.kind IN ({kinds})
                 ORDER BY e.id""",
                kinds=sql.marks(len(kinds)),
            ),
            (since, *kinds),
        ).fetchall()

    def attempts(self, card_ids: Sequence[str]) -> list[Any]:
        """The runs (attempts) of these cards, oldest first: (task_id, id, profile,
        status, outcome, started_at, ended_at, summary, metadata, error)."""
        if not card_ids:
            return []
        return self.db.execute(
            sql.text(
                """SELECT task_id, id, profile, status, outcome, started_at, ended_at,
                          summary, metadata, error
                     FROM task_runs WHERE task_id IN ({m}) ORDER BY started_at, id""",
                m=sql.marks(len(card_ids)),
            ),
            tuple(card_ids),
        ).fetchall()

    def admissions(self, card_ids: Sequence[str]) -> list[Any]:
        """(task_id, run_id, payload) of these cards' `owner_admitted` events (the
        session a gateway opened for each attempt, and its store)."""
        if not card_ids:
            return []
        return self.db.execute(
            sql.text(
                """SELECT task_id, run_id, payload FROM task_events
                    WHERE kind = 'owner_admitted' AND task_id IN ({m}) ORDER BY id""",
                m=sql.marks(len(card_ids)),
            ),
            tuple(card_ids),
        ).fetchall()

    def run_profiles(self, event_ids: Sequence[int]) -> dict[int, str]:
        """{event: the profile of the run it belongs to}; what was read before an error."""
        found: dict[int, str] = {}
        with contextlib.suppress(sqlite3.Error):
            for chunk in range(0, len(event_ids), _CHUNK):
                part = list(event_ids[chunk : chunk + _CHUNK])
                for event, profile in self.db.execute(
                    sql.text(
                        """SELECT e.id, r.profile FROM task_events e JOIN task_runs r ON r.id = e.run_id
                        WHERE e.id IN ({ids})""",
                        ids=sql.marks(len(part)),
                    ),
                    part,
                ):
                    found[int(event)] = str(profile or "")
        return found

    # ---- comments ----------------------------------------------------------------------

    def review_marks(self) -> list[Any]:
        """(task_id, author, body, created_at) of the review/plan marker comments, oldest
        first."""
        return self.db.execute(
            """SELECT task_id, author, body, created_at FROM task_comments
               WHERE body LIKE '%[agos-review %' OR body LIKE '%[agos-plan %'
               ORDER BY created_at ASC, id ASC"""
        ).fetchall()

    def comment_counts(self) -> list[Any]:
        """(task_id, number of comments)."""
        return self.db.execute(
            "SELECT task_id, COUNT(*) FROM task_comments GROUP BY task_id"
        ).fetchall()

    def for_owner(self) -> list[Any]:
        """Agents' comments at the owner he has not answered on that card since (an
        @owner mention, or a card in Review at him), newest first: (id, task_id, author,
        body, created_at, title, status, assignee)."""
        return self.db.execute(
            """SELECT c.id, c.task_id, c.author, c.body, c.created_at, t.title,
                      t.status, t.assignee
                 FROM task_comments c JOIN tasks t ON t.id = c.task_id
                WHERE (c.body LIKE '%@owner%' OR (t.status = 'review' AND t.assignee = 'owner'))
                  AND c.author NOT IN ('owner', 'user') AND t.status != 'archived'
                  AND NOT EXISTS (SELECT 1 FROM task_comments o WHERE o.task_id = c.task_id
                                    AND o.id > c.id AND o.author IN ('owner', 'user'))
                ORDER BY c.id DESC LIMIT 30"""
        ).fetchall()

    # ---- notify subscriptions ----------------------------------------------------------

    def notify_subs(self, card_id: str) -> list[Any]:
        """(platform, chat_id, thread_id, delivery_mode) of the card's subscriptions."""
        return self.db.execute(
            """SELECT platform, chat_id, thread_id, delivery_mode
                 FROM kanban_notify_subs WHERE task_id = ?""",
            (card_id,),
        ).fetchall()

    # ---- search ------------------------------------------------------------------------

    def card_hits(self, words: Sequence[str], have: set[str]) -> list[Any]:
        """Cards whose title, body or result hold every word: (id, title, body, result,
        status, created_at); `have`: the tasks table's columns."""
        texts = [sql.name(c, _CARD_TEXT) for c in _CARD_TEXT if c in have]
        expr = " || char(10) || ".join(f"coalesce({c}, '')" for c in texts)
        return self.db.execute(
            sql.text(
                "SELECT {picks} FROM tasks WHERE {cond}",
                picks=sql.or_null(_CARD_HIT, have, _CARD_HIT),
                cond=_all_in(expr, words),
            ),
            list(words),
        ).fetchall()

    def comment_hits(self, words: Sequence[str]) -> list[Any]:
        """Comments holding every word: (id, task_id, author, body, created_at, title)."""
        return self.db.execute(
            sql.text(
                """SELECT c.id, c.task_id, c.author, c.body, c.created_at, t.title
                      FROM task_comments c LEFT JOIN tasks t ON t.id = c.task_id
                     WHERE {cond}""",
                cond=_all_in("coalesce(c.body, '')", words),
            ),
            list(words),
        ).fetchall()

    def attachment_hits(self, words: Sequence[str]) -> list[Any]:
        """Attachments whose file name holds every word: (id, task_id, filename,
        created_at, title)."""
        return self.db.execute(
            sql.text(
                """SELECT a.id, a.task_id, a.filename, a.created_at, t.title
                      FROM task_attachments a LEFT JOIN tasks t ON t.id = a.task_id
                     WHERE {cond}""",
                cond=_all_in("coalesce(a.filename, '')", words),
            ),
            list(words),
        ).fetchall()


def open_board(path: Path, *, timeout: float = 2) -> Board:
    """A read-only handle on the board database at `path` (the caller closes it)."""
    return Board(hermes_db.connect_ro(path, timeout=timeout))


@contextlib.contextmanager
def opened(path: Path, *, timeout: float = 2) -> Iterator[Board]:
    """`open_board`, closed at the end of the block."""
    board = open_board(path, timeout=timeout)
    try:
        yield board
    finally:
        board.close()
