"""A stand-in for a Hermes profile's session store (state.db), as Hermes writes it.

The tests' fake gateway writes here what the real Hermes keeps of a conversation:
his messages (with the platform's message id), the answers, the tool steps, the
/undo that takes an exchange back, a session's title and the /model override (its
routing table). AGOS reads it read-only (db/hermes_chats.py), like the real one.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, chat_id TEXT, thread_id TEXT, chat_type TEXT,
  user_id TEXT, model TEXT, title TEXT, title_source TEXT, started_at REAL NOT NULL,
  ended_at REAL, end_reason TEXT, pinned INTEGER NOT NULL DEFAULT 0, parent_session_id TEXT,
  message_count INTEGER DEFAULT 0, display_name TEXT,
  archived INTEGER NOT NULL DEFAULT 0, auto_archived INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_title_unique ON sessions(title)
  WHERE title IS NOT NULL;
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,
  content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL NOT NULL,
  reasoning TEXT, platform_message_id TEXT, active INTEGER NOT NULL DEFAULT 1,
  compacted INTEGER NOT NULL DEFAULT 0, _compressed_summary INTEGER NOT NULL DEFAULT 0,
  display_kind TEXT, message_uid TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  content, tool_name, tool_calls, content='messages', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content, tool_name, tool_calls)
  VALUES (new.id, new.content, new.tool_name, new.tool_calls);
END;
CREATE TABLE IF NOT EXISTS gateway_routing (
  scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL, entry_json TEXT NOT NULL,
  updated_at REAL NOT NULL, PRIMARY KEY (scope, session_key)
);
"""

_CLOCK = {"last": 0.0}


def _now() -> float:
    """Strictly increasing, so the order of what a test writes is kept."""
    at = max(time.time(), _CLOCK["last"] + 0.001)
    _CLOCK["last"] = at
    return at


def _db(home: Path) -> sqlite3.Connection:
    home.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(home / "state.db", isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def session(
    home: Path, source: str, chat: str, thread: str | None = None, *, model: str = "fake-model"
) -> str:
    """The conversation's open session (made on first use, like Hermes's gateway)."""
    with contextlib.closing(_db(home)) as db:
        found = db.execute(
            """SELECT id FROM sessions WHERE source = ? AND chat_id = ?
                 AND COALESCE(thread_id, '') = ? AND ended_at IS NULL
               ORDER BY started_at DESC LIMIT 1""",
            (source, chat, thread or ""),
        ).fetchone()
        if found:
            return str(found["id"])
        sid = f"s_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO sessions (id, source, chat_id, thread_id, chat_type, model, started_at)
               VALUES (?, ?, ?, ?, 'dm', ?, ?)""",
            (sid, source, chat, thread, model, _now()),
        )
        return sid


def say(
    home: Path,
    chat: str,
    role: str,
    content: str,
    *,
    source: str = "agos",
    thread: str | None = None,
    platform_id: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
    display_kind: str | None = None,
) -> int:
    """One message Hermes keeps in the conversation's session."""
    sid = session(home, source, chat, thread)
    with contextlib.closing(_db(home)) as db:
        cursor = db.execute(
            """INSERT INTO messages (session_id, role, content, timestamp, platform_message_id,
                 tool_calls, tool_call_id, display_kind, message_uid)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                role,
                content,
                _now(),
                platform_id,
                json.dumps(tool_calls) if tool_calls else None,
                tool_call_id,
                display_kind,
                uuid.uuid4().hex,
            ),
        )
        return int(cursor.lastrowid or 0)


def tool(home: Path, chat: str, name: str, args: str, result: str, *, source: str = "agos") -> None:
    """A tool step of the answer: the call and its result."""
    call = f"call_{uuid.uuid4().hex[:8]}"
    say(
        home,
        chat,
        "assistant",
        "",
        source=source,
        tool_calls=[{"id": call, "function": {"name": name, "arguments": args}}],
    )
    say(home, chat, "tool", result, source=source, tool_call_id=call)


def undo(home: Path, chat: str, *, source: str = "agos") -> bool:
    """Hermes's /undo: his last message and what came after it are taken back."""
    sid = session(home, source, chat)
    with contextlib.closing(_db(home)) as db:
        last = db.execute(
            """SELECT MAX(id) FROM messages WHERE session_id = ? AND role = 'user' AND active = 1
                 AND COALESCE(display_kind, '') != 'steer'""",
            (sid,),
        ).fetchone()[0]
        if last is None:
            return False
        db.execute("UPDATE messages SET active = 0 WHERE session_id = ? AND id >= ?", (sid, last))
        return True


def last_user(home: Path, chat: str, *, source: str = "agos") -> str:
    sid = session(home, source, chat)
    with contextlib.closing(_db(home)) as db:
        row = db.execute(
            """SELECT content FROM messages WHERE session_id = ? AND role = 'user' AND active = 1
               ORDER BY id DESC LIMIT 1""",
            (sid,),
        ).fetchone()
        return str(row["content"]) if row else ""


def title(home: Path, chat: str, text: str, *, source: str = "agos") -> bool:
    """Hermes's /title (one session per title, as Hermes keeps them)."""
    sid = session(home, source, chat)
    with contextlib.closing(_db(home)) as db:
        try:
            db.execute("UPDATE sessions SET title = ? WHERE id = ?", (text, sid))
        except sqlite3.IntegrityError:
            return False
        return True


def model(home: Path, profile: str, chat: str, override: dict[str, str]) -> None:
    """Hermes's /model --session: kept in its routing table across restarts."""
    key = f"agent:{profile}:agos:dm:{chat}"
    entry = {"session_key": key, "platform": "agos", "model_override": override}
    with contextlib.closing(_db(home)) as db:
        db.execute(
            """INSERT INTO gateway_routing (scope, session_key, entry_json, updated_at)
               VALUES ('', ?, ?, ?) ON CONFLICT (scope, session_key)
               DO UPDATE SET entry_json = excluded.entry_json, updated_at = excluded.updated_at""",
            (key, json.dumps(entry), _now()),
        )


def bridge_keeps(core: Any, ws: str, path: str, body: dict[str, Any], answer: Any) -> None:
    """What the workspace's Hermes keeps of its Telegram conversation (its session
    store): his message once Hermes takes it in, its answer once sent."""
    from agos_core.actions import agent_profiles, hermes_channel
    from agos_core.db import chats as chats_repo

    if answer.status_code != 200 or not core.engine:
        return
    home = core.engine.profile_home(ws)
    if path == "incoming" and not answer.json().get("handled") and body.get("authorized", True):
        address = str(body.get("chat") or "")
        if address.startswith("agos:"):
            return
        home = routed_home(core, ws, address)
        chat, _, thread = address.partition(":")
        text = str(body.get("text") or "")
        say(
            home,
            chat,
            "user",
            text,
            source="telegram",
            thread=None if thread in ("", "0") else thread,
            platform_id=str(body.get("messageId") or "") or None,
        )
    elif path in ("platform-next", "member-next"):
        # Hermes takes his messages into the conversation (with the platform's id).
        for item in answer.json().get("items") or []:
            if item.get("kind") != "message":
                continue
            split = hermes_channel.split_agos(str(item["chat"]))
            if split is None:
                continue
            member = hermes_channel.owner_member(core, ws, str(item["chat"]))
            where = core.engine.profile_home(agent_profiles.key(ws, member)) if member else home
            say(
                where,
                str(item["chat"]).split(":", 1)[1],
                "user",
                str(item.get("text") or ""),
                platform_id=f"agos-{item['id']}",
            )
    elif path == "turn-start" and body.get("said") and not str(body["chat"]).startswith("agos:"):
        # What Hermes read: a voice note's words (in place of the note), or the
        # request a /command became.
        chat, _, thread = str(body["chat"]).partition(":")
        sid = session(home, "telegram", chat, None if thread in ("", "0") else thread)
        said = str(body["said"])
        with contextlib.closing(sqlite3.connect(home / "state.db", isolation_level=None)) as db:
            if body.get("how") == "replace":
                db.execute(
                    """UPDATE messages SET content = ? WHERE id = (SELECT MAX(id) FROM messages
                         WHERE session_id = ? AND role = 'user')""",
                    (said, sid),
                )
            else:
                say(
                    home,
                    chat,
                    "user",
                    said,
                    source="telegram",
                    thread=None if thread in ("", "0") else thread,
                )
    elif path == "turn-finish":
        turn = core.db.execute(
            "SELECT chat_id FROM chat_turns WHERE id = ?", (body.get("turnId"),)
        ).fetchone()
        text = str(answer.json().get("text") or body.get("text") or "")
        if turn is None:
            return
        row = core.db.execute("SELECT * FROM chats WHERE id = ?", (turn["chat_id"],)).fetchone()
        where = chats_repo.where_of(core.db, row)
        if where is None:
            return
        # A test's "failed": Hermes ended the turn without an answer (its
        # on_session_end says so, after the answer's turn-finish).
        failed = bool(body.get("failed"))
        if not where.telegram:
            member = str(row["agent"] or "") if row["kind"] == "dm" else ""
            own = core.engine.profile_home(agent_profiles.key(ws, member)) if member else home
            if text and not failed:
                say(own, str(row["id"]), "assistant", text)
            _hook_turn_end(core, ws, body, failed)
            return
        chat, thread = where.telegram[0]
        topic = None if thread in ("", "0") else thread
        home = routed_home(core, ws, f"{chat}:{thread}")
        if text and not failed:
            say(home, chat, "assistant", text, source="telegram", thread=topic)
        _hook_turn_end(core, ws, body, failed)


def _hook_turn_end(core: Any, ws: str, body: dict[str, Any], failed: bool) -> None:
    """After its answer Hermes says how the turn ended (on_session_end → the
    plugin's turn-end)."""
    from agos_core.actions import hermes_channel

    hermes_channel.turn_ended(core, ws, int(body["turnId"]), reason(failed))


def routed_home(core: Any, ws: str, address: str) -> Path:
    """The profile Hermes answers a Telegram place in: a member's topic is routed to
    the member's own profile (gateway.profile_routes), anything else is the root's."""
    from agos_core.actions import member_topics

    for link in member_topics.linked(core, ws):
        if link["address"] == address:
            from agos_core.actions import agent_profiles

            return Path(core.engine.profile_home(agent_profiles.key(ws, link["agent"])))
    return Path(core.engine.profile_home(ws))


FAILED_REASON = "all_retries_exhausted_no_response"


OK_REASON = "text_response(finish_reason=stop)"


def reason(failed: bool) -> str:
    """Hermes's turn_exit_reason (its on_session_end hook)."""
    return FAILED_REASON if failed else OK_REASON
