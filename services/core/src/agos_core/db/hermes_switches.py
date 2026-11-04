"""Hermes's own on/off switches, read in AGOS's SQL as functions.

`agos_hidden(chat_id, workspace_id, kind, deleted_at)`: whether a chat is hidden
("deleted" in AGOS, ADR 0011: kept, never shown). A chat whose conversation is
Hermes's own on the agos platform is hidden when Hermes archived its sessions (its
per-session archive, H: hermes_state_sessions.py:992 set_session_archived; the
session and its words stay, session_search still finds them); AGOS's `deleted_at`
holds it only where Hermes has nothing to archive (a group: a Hermes room has no
archive; a chat with no session yet; one linked to a Telegram place, whose Hermes
conversation is the owner's live Telegram chat) or until Hermes took the archive.

`agos_bot_on(workspace_id)`: whether the workspace's Telegram bot is on, which is
Hermes's `platforms.telegram.enabled` in the workspace's root profile (an explicit
`false` beats the token in .env: gateway/config_env.py `_enable_from_env`). AGOS
keeps no copy; agos-core sets the reader when it opens (actions/hermes_channel.py
bot_on). Without a reader (no engine) a bot is on, as Hermes starts one whose token
it has.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

bot_reader: Callable[[str], bool] | None = None


def bot_on(workspace_id: str | None) -> int:
    if workspace_id is None or bot_reader is None:
        return 1
    try:
        return int(bool(bot_reader(str(workspace_id))))
    except Exception:  # noqa: BLE001 — a SQL function must not raise; Hermes's default is on
        return 1


# Hermes's archive of each workspace as the running statement read it (statement()):
# the SQL function runs once per row, and checking Hermes's state files for every
# row made a list of a few hundred chats stat each profile's state.db hundreds of
# times (the Team, Office and Dashboard lists).
_statement = threading.local()


@contextmanager
def statement() -> Iterator[None]:
    """One SQL statement on this thread (db/connection.py SharedConnection.execute):
    hidden() reads Hermes's archive of a workspace once for all its rows, as of
    the moment the statement runs; the next statement reads it again."""
    before = getattr(_statement, "archive", None)
    _statement.archive = {}
    try:
        yield
    finally:
        _statement.archive = before


def hidden(chat_id: int, workspace_id: str | None, kind: str, deleted_at: str | None) -> int:
    if deleted_at is not None:
        return 1
    if workspace_id is None or kind == "group":
        return 0
    from agos_core.db import hermes_chats as hc

    store = hc.store()
    if store is None:
        return 0
    held: dict[str, dict[int, bool]] | None = getattr(_statement, "archive", None)
    chats = held.get(str(workspace_id)) if held is not None else None
    if chats is None:
        try:
            chats, _ = store.archive_states(str(workspace_id))
        except Exception:  # noqa: BLE001 — a SQL function must not raise; unread = shown
            return 0
        if held is not None:
            held[str(workspace_id)] = chats
    return int(chats.get(int(chat_id), False))


def install(db: sqlite3.Connection) -> None:
    db.create_function("agos_bot_on", 1, bot_on)
    db.create_function("agos_hidden", 4, hidden)
