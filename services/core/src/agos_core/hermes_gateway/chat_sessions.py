"""Reads of a chat's conversation in the workspace's Hermes (each profile's session
store, state.db), read-only and through one handle per profile (ADR 0024).

Owns: the read-only handles on Hermes's state.db of the workspace's own profiles, the
reads of a chat's sessions, transcript, title, /model, archive marks, hosted room
names and full-text search, and the caches kept while those files are unchanged.
The shapes it returns and the parsing of Hermes's words are db/hermes_chats.py's.

Must not: write a Hermes store, open another workspace's profile, or keep rows once
the store changed.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

from agos_core.db import hermes_chats as hc
from agos_core.engine import read_cache
from agos_core.hermes_gateway import hermes_db

__all__ = ["Store"]

T = TypeVar("T")


class _Unkept(Exception):
    """A read that met an error of Hermes's store: its answer is used this once."""

    def __init__(self, value: Any) -> None:
        super().__init__("Hermes's store did not answer every read")
        self.value = value


class Store:
    """Reads Hermes's session store of each profile (read-only, one handle each)."""

    def __init__(
        self,
        home_of: Callable[[str], Path | None],
        profile_of: Callable[[str], str],
        own_profiles: Callable[[str], list[str]],
    ) -> None:
        self.home_of = home_of
        self.profile_of = profile_of
        self.own_profiles = own_profiles
        self._dbs: dict[str, tuple[sqlite3.Connection, set[str]]] = {}
        self._lock = threading.RLock()
        self._archive: dict[str, tuple[tuple[Any, ...], dict[int, bool], dict[str, bool]]] = {}
        self._rooms: dict[str, tuple[tuple[Any, ...], dict[str, str]]] = {}
        # What the lists show of each chat (`summary`, its /model), kept while the
        # state.db of every profile it is read from is unchanged (`_kept`).
        self._summaries: read_cache.ReadCache[hc.Transcript] = read_cache.ReadCache(
            "hermes-chat-summaries", retry_after=0.0, max_entries=4096
        )
        self._overrides: read_cache.ReadCache[dict[str, str] | None] = read_cache.ReadCache(
            "hermes-chat-models", retry_after=0.0, max_entries=4096
        )
        self._reading = threading.local()

    # ---- handles -------------------------------------------------------------

    def _open(self, profile: str) -> tuple[sqlite3.Connection, set[str]] | None:
        found = self._dbs.get(profile)
        if found is not None:
            return found
        home = self.home_of(profile)
        if home is None or not hc.PROFILE_NAME.match(profile):
            return None
        path = home / "state.db"
        if not path.is_file():
            return None
        try:
            db = hermes_db.connect_ro(path, timeout=3, check_same_thread=False)
            db.row_factory = sqlite3.Row
            columns = {str(r[1]) for r in db.execute("PRAGMA table_info(messages)")}
        except sqlite3.Error:
            self._reading.failed = True
            return None
        self._dbs[profile] = (db, columns)
        return self._dbs[profile]

    def forget(self, profile: str | None = None) -> None:
        with self._lock:
            for name in [p for p in self._dbs if profile is None or p == profile]:
                with contextlib.suppress(sqlite3.Error):
                    self._dbs.pop(name)[0].close()

    def query(self, profile: str, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            found = self._open(profile)
            if found is None:
                return []
            try:
                return list(found[0].execute(sql, tuple(args)))
            except sqlite3.Error:
                self._reading.failed = True
                self.forget(profile)
                return []

    def columns(self, profile: str) -> set[str]:
        with self._lock:
            found = self._open(profile)
            return set(found[1]) if found else set()

    # ---- Hermes's per-session archive (a chat hidden in AGOS) ------------------

    def _stamp(self, workspace_id: str) -> tuple[Any, ...]:
        out: list[Any] = []
        for profile in self.own_profiles(workspace_id):
            home = self.home_of(profile)
            for name in ("state.db", "state.db-wal"):
                try:
                    out.append((profile, name, (home / name).stat().st_mtime_ns) if home else None)
                except OSError:
                    out.append((profile, name, None))
        return tuple(out)

    def archive_states(self, workspace_id: str) -> tuple[dict[int, bool], dict[str, bool]]:
        """Whether Hermes archived every session of each AGOS chat (H:
        hermes_state_sessions.py set_session_archived, column sessions.archived):
        ({agos chat id: all archived}, {session id: archived}) over the workspace's own
        profiles. Cached on the state files' times."""
        stamp = self._stamp(workspace_id)
        with self._lock:
            held = self._archive.get(workspace_id)
            if held is not None and held[0] == stamp:
                return held[1], held[2]
            chats: dict[int, bool] = {}
            ids: dict[str, bool] = {}
            prefix = hc.archive_id(workspace_id, 0)[:-1]  # "agos-archive-<ws>-c"
            for profile in self.own_profiles(workspace_id):
                for r in self.query(
                    profile,
                    # Only Hermes's DELIBERATE archive (set_session_archived clears
                    # auto_archived); its idle sweep's and its accidental ones
                    # (H: hermes_state_common.py:189 _RECOVERABLE_END_REASONS) never
                    # hide a chat the owner didn't delete.
                    """SELECT id, source, chat_id,
                              (COALESCE(archived, 0) != 0 AND COALESCE(auto_archived, 0) = 0
                               AND COALESCE(end_reason, '') NOT IN
                                 ('agent_close', 'ws_orphan_reap', 'superseded_by_resume',
                                  'startup_orphan_reap')) AS archived
                         FROM sessions WHERE source = 'agos' OR id LIKE 'agos-archive-%'""",
                ):
                    sid, gone = str(r["id"]), bool(r["archived"])
                    ids[sid] = gone
                    chat = str(r["chat_id"] or "") if r["source"] == "agos" else ""
                    if not chat and sid.startswith(prefix) and sid[len(prefix) :].isdigit():
                        chat = sid[len(prefix) :]
                    if chat.isdigit():
                        chats[int(chat)] = chats.get(int(chat), True) and gone
            self._archive[workspace_id] = (stamp, chats, ids)
            return chats, ids

    # ---- a group's name: its Hermes room's own (H: gateway/hosted_rooms.py:88-91) --

    def room_names(self, workspace_id: str) -> dict[str, str]:
        """{room id: name} of the hosted rooms in the workspace's root (Hermes keeps
        them in the root's shared-state.db: H: gateway/hosted_rooms.py:398-412
        default_db_path; a disbanded room keeps its row until Hermes prunes it).
        Cached on the file's times; {} when Hermes has none."""
        home = self.home_of(self.profile_of(workspace_id))
        if home is None:
            return {}
        path = home / "shared-state.db"
        stamp: list[Any] = []
        for name in ("shared-state.db", "shared-state.db-wal"):
            try:
                stamp.append((home / name).stat().st_mtime_ns)
            except OSError:
                stamp.append(None)
        key = "rooms:" + workspace_id
        with self._lock:
            held = self._rooms.get(key)
            if held is not None and held[0] == tuple(stamp):
                return held[1]
            names: dict[str, str] = {}
            if path.is_file():
                try:
                    with contextlib.closing(hermes_db.connect_ro(path, timeout=3)) as db:
                        for r in db.execute("SELECT room_id, name FROM hosted_rooms"):
                            names[str(r[0])] = str(r[1] or "")
                except sqlite3.Error:
                    names = {}
            self._rooms[key] = (tuple(stamp), names)
            return names

    def forget_archive(self, workspace_id: str) -> None:
        with self._lock:
            self._archive.pop(workspace_id, None)

    def belongs(self, profile: str, workspace_id: str) -> bool:
        own = self.profile_of(workspace_id)
        return profile == own or profile.startswith(own + "--")

    # ---- a chat's sessions ---------------------------------------------------

    def _session_filter(self, where: hc.Where) -> tuple[str, list[Any]]:
        parts = ["(source = 'agos' AND chat_id = ?)"]
        args: list[Any] = [str(where.chat_id)]
        if where.keys:
            parts.append(f"id IN ({','.join('?' * len(where.keys))})")
            args += list(where.keys)
        # The chat's Telegram place, in each of its own profiles: the root's (the
        # Co-Founder's chats) or the member's (its topic, which Hermes routes there:
        # gateway.profile_routes). Only the chat's own profiles are read (sessions).
        for chat, thread in where.telegram:
            if thread in ("", "0"):
                # No topic; a forum's General topic is Hermes's thread "1".
                general = "1" if chat.startswith("-") else ""
                parts.append(
                    "(source = 'telegram' AND chat_id = ? AND COALESCE(thread_id, '') IN ('', '0', ?))"
                )
                args += [chat, general]
            else:
                parts.append("(source = 'telegram' AND chat_id = ? AND thread_id = ?)")
                args += [chat, thread]
        return " OR ".join(parts), args

    def sessions(self, where: hc.Where) -> list[hc.Session]:
        out: list[hc.Session] = []
        for profile in where.profiles:
            if not self.belongs(profile, where.workspace_id):
                continue
            cond, args = self._session_filter(where)
            for r in self.query(
                profile,
                f"""SELECT s.id, s.title, s.model, s.started_at,
                           (SELECT MAX(m.timestamp) FROM messages m WHERE m.session_id = s.id)
                             AS last
                      FROM sessions s WHERE {cond}""",
                args,
            ):
                out.append(
                    hc.Session(
                        id=str(r["id"]),
                        profile=profile,
                        title=str(r["title"] or ""),
                        model=str(r["model"] or ""),
                        started=float(r["started_at"] or 0),
                        last=float(r["last"] or r["started_at"] or 0),
                    )
                )
        out.sort(key=lambda s: (s.started, s.id))
        return out

    def transcript(self, where: hc.Where) -> hc.Transcript:
        """Every message of the chat's sessions, in order (by time), as Hermes keeps
        them: what an /undo or /retry took back is gone, what a compaction folded
        away is still shown, and a message copied forward by a compaction is shown
        once."""
        sessions = self.sessions(where)
        found = hc.Transcript(sessions=sessions)
        by_profile: dict[str, list[hc.Session]] = {}
        for s in sessions:
            by_profile.setdefault(s.profile, []).append(s)
        seen: set[str] = set()
        for profile, mine in by_profile.items():
            have = self.columns(profile)

            def col(name: str, have: set[str] = have) -> str:
                return name if name in have else f"NULL AS {name}"

            visible = []
            if "active" in have:
                visible.append(
                    "(active = 1 OR compacted = 1)" if "compacted" in have else "active = 1"
                )
            if "_compressed_summary" in have:
                visible.append("_compressed_summary = 0")
            models = {s.id: s.model for s in mine}
            marks = ",".join("?" * len(mine))
            sql = f"""SELECT id, session_id, role, content, timestamp, {col("message_uid")},
                             {col("platform_message_id")}, {col("tool_calls")},
                             {col("tool_call_id")}, {col("display_kind")}
                        FROM messages WHERE session_id IN ({marks})
                        {"AND " + " AND ".join(visible) if visible else ""}
                       ORDER BY id"""
            profile_tag = hc.tag(profile, where.own)
            for r in self.query(profile, sql, [s.id for s in mine]):
                uid = str(r["message_uid"] or "")
                if uid and uid in seen:
                    continue  # a compaction's copy of a message already shown
                if uid:
                    seen.add(uid)
                found.rows.append(
                    hc.Row(
                        id=hc.hermes_id(profile_tag, int(r["id"])),
                        profile=profile,
                        row=int(r["id"]),
                        session=str(r["session_id"]),
                        role=str(r["role"]),
                        content=hc.content_text(r["content"]),
                        ts=float(r["timestamp"] or 0),
                        uid=uid,
                        platform_id=str(r["platform_message_id"] or ""),
                        tool_calls=str(r["tool_calls"] or ""),
                        tool_call_id=str(r["tool_call_id"] or ""),
                        display_kind=str(r["display_kind"] or ""),
                        model=models.get(str(r["session_id"]), ""),
                    )
                )
        found.rows.sort(key=lambda m: (m.ts, m.profile != where.own, m.row))
        return found

    def _kept(self, cache: read_cache.ReadCache[T], where: hc.Where, read: Callable[[], T]) -> T:
        """`read()` kept while the state.db (with its WAL, where Hermes writes first)
        of each of the chat's profiles is unchanged, stamped before the read: a
        message Hermes writes meanwhile is read on the next call. A read that met an
        error of Hermes's store (busy, changed under it) is used once, never kept."""
        stamp = tuple(
            (profile, read_cache.sqlite_stamp(home / "state.db") if home else None)
            for profile in where.profiles
            for home in (self.home_of(profile),)
        )

        def run() -> T:
            self._reading.failed = False
            value = read()
            if self._reading.failed:
                raise _Unkept(value)
            return value

        try:
            return cache.get(where, stamp, run)
        except _Unkept as unkept:
            found: T = unkept.value
            return found

    def summary(self, where: hc.Where) -> hc.Transcript:
        """What a list shows of the chat (its last words, title and time): the
        chat's sessions with his messages and the answers only (no steps), kept
        while Hermes's store is unchanged (`_kept`): each Team, Office or Dashboard
        call shows every chat's last words. Each caller gets its own lists."""

        def read() -> hc.Transcript:
            whole = self.transcript(where)
            return hc.Transcript(
                rows=[r for r in whole.rows if r.role == "user" or hc.is_answer(r)],
                sessions=whole.sessions,
            )

        kept = self._kept(self._summaries, where, read)
        return hc.Transcript(rows=list(kept.rows), sessions=list(kept.sessions))

    def title(self, where: hc.Where, sessions: list[hc.Session] | None = None) -> str:
        """The conversation's title: its newest session that has one (of
        `sessions` when the caller has read them already)."""
        titled = [s for s in (self.sessions(where) if sessions is None else sessions) if s.title]
        return titled[-1].title if titled else ""

    def model_override(self, where: hc.Where, *, kept: bool = False) -> dict[str, str] | None:
        """Hermes's own /model for this conversation (`--session`), as its gateway
        keeps it across restarts (its routing table, in state.db). `kept`: for a
        list, kept while Hermes's store is unchanged (`_kept`)."""
        if kept:
            found = self._kept(self._overrides, where, lambda: self._model_override(where))
            return dict(found) if found is not None else None
        return self._model_override(where)

    def _model_override(self, where: hc.Where) -> dict[str, str] | None:
        for profile in reversed(where.profiles):
            for r in self.query(
                profile,
                "SELECT entry_json FROM gateway_routing WHERE session_key LIKE ? ORDER BY updated_at DESC",
                [f"%:agos:%:{where.chat_id}"],
            ):
                try:
                    entry = json.loads(r["entry_json"] or "{}")
                except ValueError:
                    continue
                key = str(entry.get("session_key") or "")
                if not key.endswith(f":agos:dm:{where.chat_id}"):
                    continue
                override = entry.get("model_override")
                if isinstance(override, dict) and override.get("model"):
                    return {str(k): str(v) for k, v in override.items()}
                return None
        return None

    def search(
        self, workspace_id: str, query: str, limit: int = 60
    ) -> list[tuple[str, str, hc.Row]]:
        """Hermes's own full-text index (FTS5) over the workspace's conversations:
        (session's chat id, session id, the message), newest first."""
        words = [w for w in re.findall(r"\w+", query.lower()) if w][:6]
        if not words:
            return []
        match = " ".join('"' + w.replace('"', '""') + '"*' for w in words)
        own = self.profile_of(workspace_id)
        out: list[tuple[str, str, hc.Row]] = []
        for profile in self.own_profiles(workspace_id):
            for r in self.query(
                profile,
                """SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
                          s.chat_id, s.source
                     FROM messages_fts f JOIN messages m ON m.id = f.rowid
                     JOIN sessions s ON s.id = m.session_id
                    WHERE messages_fts MATCH ? AND m.role IN ('user', 'assistant')
                      AND COALESCE(m.content, '') != ''
                    ORDER BY m.id DESC LIMIT ?""",
                [match, limit],
            ):
                out.append(
                    (
                        str(r["chat_id"] or ""),
                        str(r["session_id"]),
                        hc.Row(
                            id=hc.hermes_id(hc.tag(profile, own), int(r["id"])),
                            profile=profile,
                            row=int(r["id"]),
                            session=str(r["session_id"]),
                            role=str(r["role"]),
                            content=hc.content_text(r["content"]),
                            ts=float(r["timestamp"] or 0),
                        ),
                    )
                )
        out.sort(key=lambda x: -x[2].ts)
        return out[:limit]
