"""Reads of the token and cost counts Hermes keeps per session, in a profile's
session store (state.db, Hermes's `sessions` table, hermes_state_common.py), read
only (ADR 0024).

Hermes counts each session's tokens (input, output, prompt-cache reads and writes)
and prices them itself (`estimated_cost_usd` / `actual_cost_usd`, `cost_status`:
actual | estimated | included | unknown). AGOS only reads those numbers.

Owns: those SQL statements (which sessions worked a Kanban card, a cron job's
sessions, a session's children). Must not: write a Hermes store, open a store
outside the path it is given, price anything, or decide what a row means.
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

__all__ = ["COLUMNS", "Sessions", "opened"]

# What a usage row holds (an older store may lack a column: read as NULL).
COLUMNS = (
    "id",
    "source",
    "parent_session_id",
    "started_at",
    "ended_at",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "estimated_cost_usd",
    "actual_cost_usd",
    "cost_status",
)
_WORKED = sql.Piece(
    """source = 'kanban' AND EXISTS (SELECT 1 FROM messages m
         WHERE m.session_id = sessions.id AND m.role = 'user' AND m.content = ?)"""
)
_PREFIXED = sql.Piece("id LIKE ? ESCAPE '\\' AND started_at >= ? AND started_at < ?")
_CHUNK = 400
_DEPTH = 4  # children of children...: a worker's subagents and its compressed continuations


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Sessions:
    """One read-only handle on a profile's state.db (the caller closes it)."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db
        have = {str(r[1]) for r in db.execute("PRAGMA table_info(sessions)")}
        if "id" not in have:
            raise sqlite3.OperationalError("no sessions table")
        self._picked = sql.or_null(COLUMNS, have, COLUMNS)

    def close(self) -> None:
        self.db.close()

    def _rows(self, where: sql.Piece, args: Sequence[Any]) -> list[dict[str, Any]]:
        query = sql.text(
            "SELECT {picked} FROM sessions WHERE {where}", picked=self._picked, where=where
        )
        return [dict(zip(COLUMNS, r, strict=True)) for r in self.db.execute(query, tuple(args))]

    def by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        """These sessions (the ones the store has)."""
        out: list[dict[str, Any]] = []
        names = list(dict.fromkeys(ids))
        for start in range(0, len(names), _CHUNK):
            part = names[start : start + _CHUNK]
            out += self._rows(sql.Piece(sql.text("id IN ({m})", m=sql.marks(len(part)))), part)
        return out

    def worked_card(self, card_id: str) -> list[dict[str, Any]]:
        """The Kanban work sessions on this card: Hermes opens each with the prompt
        `work kanban task <card>` (the same mark card_todos reads)."""
        return self._rows(
            _WORKED,
            (f"work kanban task {card_id}",),
        )

    def with_prefix(self, prefix: str, since: float, until: float) -> list[dict[str, Any]]:
        """Sessions whose id starts with `prefix` (a cron job's `cron_<job>_`), started
        in [since, until)."""
        return self._rows(
            _PREFIXED,
            (_like_prefix(prefix), since, until),
        )

    def with_children(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """`rows` and every session started from them (subagents, continuations)."""
        seen = {str(r["id"]) for r in rows}
        out = list(rows)
        level = list(seen)
        for _ in range(_DEPTH):
            if not level:
                break
            found: list[dict[str, Any]] = []
            for start in range(0, len(level), _CHUNK):
                part = level[start : start + _CHUNK]
                found += self._rows(
                    sql.Piece(sql.text("parent_session_id IN ({m})", m=sql.marks(len(part)))), part
                )
            fresh = {str(r["id"]): r for r in found if str(r["id"]) not in seen}
            seen.update(fresh)
            out += fresh.values()
            level = list(fresh)
        return out


@contextlib.contextmanager
def opened(path: Path, *, timeout: float = 2) -> Iterator[Sessions]:
    """A read-only handle on the state.db at `path`, closed at the end of the block."""
    db = hermes_db.connect_ro(path, timeout=timeout)
    try:
        yield Sessions(db)
    finally:
        db.close()
