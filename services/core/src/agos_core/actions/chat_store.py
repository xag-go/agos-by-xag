"""Hermes keeps the chats' sessions: every session holding a chat's words is pinned,
and a chat hidden in AGOS is Hermes's own archive of its sessions.

A chat or DM is its Hermes conversation (db/hermes_chats.py). Every session holding
a chat's words is pinned (`hermes sessions pin`): Hermes never prunes a pinned
session. A chat the owner deletes stays (ADR 0011) and is hidden: on the agos
platform, Hermes archives its sessions (its per-session archive, read back by
db/hermes_switches.hidden); AGOS marks `deleted_at` only where Hermes has nothing to
archive (a group, a chat with no session yet, one linked to a Telegram place, whose
conversation is the owner's live Telegram chat), or until Hermes took the archive.
Only the chat's own workspace's profiles are read or written.

When: Hermes says when a chat's session moved on. Its `on_session_end` hook (the
agos-guard plugin's `/turn-end`) pins that chat's sessions (`keep_chat`, in the
background), a compression's new session included. One pass over every chat runs
at AGOS's start (`tick`), for what happened while AGOS was down. No AGOS loop
re-reads every chat's sessions any more.
"""

from __future__ import annotations

import logging
import sqlite3

from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.db import hermes_chats as hc
from agos_core.db.connection import transaction
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.chat_store")


def keep(core: Core, workspace_id: str, chat_id: int | None = None) -> int:
    """Every session holding a chat's words (one chat's, with `chat_id`) is pinned
    (Hermes's own `sessions pin`), so Hermes's retention never prunes a chat's
    history; a plain chat's name AGOS held goes once its session has a title."""
    store = hc.store()
    engine = core.engine
    if engine is None or store is None:
        return 0
    wanted: dict[str, set[str]] = {}
    for chat in repo.of_workspace(core.db, workspace_id, chat_id):
        try:  # one bad chat never keeps the workspace's other chats unpinned
            where = repo.where_of(core.db, chat)
            if where is None:
                continue
            for s in store.sessions(where):
                wanted.setdefault(s.profile, set()).add(s.id)
            _drop_title(core, chat, store.title(where))
        except Exception:
            log.exception("chat %s of %s not kept in Hermes", chat["id"], workspace_id)
    pinned = 0
    for profile, ids in wanted.items():
        if not ids or not store.belongs(profile, workspace_id):
            continue
        marks = ",".join("?" * len(ids))
        have = {
            str(r["id"])
            for r in store.query(
                profile,
                f"SELECT id FROM sessions WHERE pinned = 1 AND id IN ({marks})",
                sorted(ids),
            )
        }
        todo = sorted(ids - have)
        if not todo:
            continue
        home = engine.home_of(profile)
        if home is None:
            continue
        try:  # Hermes's own `hermes sessions pin`
            engine.pin_sessions(home, todo[:200])
        except Exception as error:  # noqa: BLE001 — tried again next round
            log.info("sessions of %s not pinned: %s", profile, error)
            continue
        pinned += len(todo[:200])
    return pinned


def _drop_title(core: Core, chat: sqlite3.Row, hermes_title: str) -> None:
    """A plain chat's name AGOS held until its Hermes session had one: once Hermes's
    session has a title (its own /title, or the one Hermes gave it), AGOS's copy
    goes (db/chats.py title_from reads Hermes's first)."""
    if chat["kind"] != "chat" or not str(chat["title"] or "") or not hermes_title:
        return
    with transaction(core.db):
        repo.drop_title_copy(core.db, int(chat["id"]), chat["title"])


def keep_chat(core: Core, workspace_id: str, chat_id: int) -> None:
    """Hermes ended a turn in this chat (its on_session_end): its sessions are
    pinned, off the request."""
    import threading

    def run() -> None:
        try:
            keep(core, workspace_id, chat_id)
        except Exception:
            log.exception("chat %s not kept in Hermes", chat_id)

    threading.Thread(target=run, name=f"keep-chat-{chat_id}", daemon=True).start()


def tick(core: Core) -> dict[str, dict[str, int]]:
    """Every live workspace: the sessions holding its chats are kept (pinned), and
    names Hermes's sessions hold leave AGOS."""
    if core.engine is None or hc.store() is None:
        return {}
    from agos_core.db.workspaces import list_workspaces

    out: dict[str, dict[str, int]] = {}
    for workspace in list_workspaces(core.db):
        try:
            out[workspace.id] = {"pinned": keep(core, workspace.id)}
        except Exception:
            log.exception("chats of %s not kept in Hermes", workspace.id)
    return out


def _archive(core: Core, row: sqlite3.Row, archived: bool) -> bool:
    """Hermes archives (or brings back) every session of the chat. False when Hermes
    has nothing of it to archive or didn't take it (AGOS's mark then holds it)."""
    engine, store = core.engine, hc.store()
    if engine is None or store is None or str(row["kind"]) == "group":
        return False
    workspace_id = str(row["workspace_id"])
    where = repo.where_of(core.db, row)
    if where is None or where.telegram:
        return False  # its Hermes conversation is his live Telegram chat
    if int(row["id"]) not in store.archive_states(workspace_id)[0]:
        return False  # no session of it on the agos platform yet
    by_profile: dict[str, list[str]] = {}
    for s in store.sessions(where):
        by_profile.setdefault(s.profile, []).append(s.id)
    try:
        for profile, ids in by_profile.items():
            home = engine.home_of(profile)
            if home is not None and store.belongs(profile, workspace_id):
                engine.archive_sessions(home, ids, archived)
    except (EngineError, OSError) as error:
        log.warning("chat %s not archived in Hermes: %s", row["id"], error)
        return False
    finally:
        store.forget_archive(workspace_id)
    return True


def hide(core: Core, row: sqlite3.Row) -> None:
    """The owner deleted the chat: hidden, kept (Hermes's archive, else AGOS's mark)."""
    if _archive(core, row, True):
        return
    with transaction(core.db):
        repo.delete_chat(core.db, str(row["workspace_id"]), int(row["id"]))


def unhide(core: Core, row: sqlite3.Row) -> None:
    """A hidden DM opened again: back with its whole history."""
    _archive(core, row, False)
    with transaction(core.db):
        repo.unhide(core.db, int(row["id"]))


def move_hidden(core: Core) -> int:
    """Chats AGOS hid itself before (its deleted_at) whose sessions Hermes can archive:
    Hermes's archive holds them now, AGOS's mark goes. Safe to run again."""
    moved = 0
    for row in repo.hidden_by_agos(core.db):
        if _archive(core, row, True):
            with transaction(core.db):
                repo.unhide(core.db, int(row["id"]))
            moved += 1
    return moved
