"""Repository of AGOS's own lines in a chat (table `message_rows`, read through its
`messages` view): a room's lines, AGOS's notices and /command answers in a Hermes
chat, the owner's edits and deletions of them, and the quotes a reply carries.

Split out of db/chats.py (which re-exports these names and keeps add_chat_message,
which also touches the chat's row).

Owns every read and write of message_rows. Must not: import actions or engine, or
write another table.
"""

import re
import sqlite3

from agos_core.db.chat_turns import answered_up_to
from agos_core.db.rows import now

__all__ = [
    "add_line",
    "delete_message",
    "edit_owner_message",
    "excerpt_in",
    "last_body",
    "last_owner_line",
    "letters_of",
    "lines_of",
    "owner_line",
    "owner_messages",
    "owner_words_in_dm",
    "owner_words_in_workspace",
    "recent_agent_lines",
    "unanswered",
    "with_quote",
]


def add_line(
    db: sqlite3.Connection,
    chat_id: int,
    author: str,
    body: str,
    at: str,
    speaker: str | None = None,
    reply_to: int | None = None,
    reply_excerpt: str | None = None,
) -> int:
    """One of AGOS's own lines in a chat (db/chats.py add_chat_message checks the chat
    and keeps its updated_at). A reply only to a message of this same chat."""
    if (
        reply_to is not None
        and not db.execute(
            "SELECT 1 FROM messages WHERE id = ? AND chat_id = ?", (reply_to, chat_id)
        ).fetchone()
    ):
        reply_to = None  # only a message of this same chat
    excerpt = _excerpt_of(db, reply_to, reply_excerpt)
    cursor = db.execute(
        """INSERT INTO message_rows (chat_id, author, body, created_at, speaker, reply_to,
             reply_excerpt) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (chat_id, author, body, at, speaker, reply_to, excerpt),
    )
    return int(cursor.lastrowid or 0)


def _excerpt_of(db: sqlite3.Connection, reply_to: int | None, excerpt: str | None) -> str | None:
    """The selected part, if it's really in the replied message (whitespace and
    markdown marks aside: a selection in the page loses them)."""
    if reply_to is None or not excerpt or not excerpt.strip():
        return None
    row = db.execute("SELECT body FROM messages WHERE id = ?", (reply_to,)).fetchone()
    if row is None:
        return None
    return excerpt_in(str(row["body"]), excerpt)


def excerpt_in(body: str, excerpt: str | None) -> str | None:
    if not excerpt or not excerpt.strip():
        return None
    # Compare letters and digits only: the page drops markdown marks, list
    # bullets and numbers, so a selection across lines never matches verbatim.
    plain = letters_of(body)
    wanted = letters_of(excerpt)
    if not wanted or wanted == plain or wanted not in plain:
        return None
    return excerpt.strip()[:4000]


_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
# Everything str.isalnum() refuses (\W is "not alnum and not _"): the same
# characters as a per-character isalnum() test, without a Python step per character.
_NOT_ALNUM = re.compile(r"[\W_]+")


def letters_of(text: str) -> str:
    """Letters and digits only, without list bullets and numbers at line starts."""
    return _NOT_ALNUM.sub("", _LIST_MARK.sub("", text).lower())


def edit_owner_message(
    db: sqlite3.Connection, workspace_id: str, chat_id: int, message_id: int, body: str
) -> bool:
    """The owner changes one of his own lines in a room of this workspace."""
    return (
        db.execute(
            """UPDATE message_rows SET body = ?, edited_at = ?, hermes_profile = NULL,
                 hermes_session = NULL, hermes_uid = NULL
               WHERE id = ? AND chat_id = ? AND author = 'owner'
                 AND chat_id IN (SELECT id FROM chats WHERE workspace_id = ?)""",
            (body, now(), message_id, chat_id, workspace_id),
        ).rowcount
        > 0
    )


def delete_message(
    db: sqlite3.Connection, workspace_id: str, chat_id: int, message_id: int
) -> bool:
    """One of AGOS's rows goes (owner's or the agent's). Replies to it keep their own text."""
    found = db.execute(
        """SELECT 1 FROM message_rows WHERE id = ? AND chat_id = ?
             AND chat_id IN (SELECT id FROM chats WHERE workspace_id = ?)""",
        (message_id, chat_id, workspace_id),
    ).fetchone()
    if found is None:
        return False
    db.execute(
        "UPDATE message_rows SET reply_to = NULL, reply_excerpt = NULL WHERE reply_to = ?",
        (message_id,),
    )
    db.execute("DELETE FROM message_rows WHERE id = ?", (message_id,))
    return True


def with_quote(
    body: str,
    author: str | None,
    speaker: str | None,
    quoted: str | None,
    part: str | None = None,
) -> str:
    """The owner's message as a room member reads it: the message he answers
    first, or only the part of it he selected."""
    if quoted is None:
        return body
    who = (
        "his own earlier message" if author == "owner" else f"this message from {speaker or 'you'}"
    )
    if part:
        lines = "\n".join(f"> {line}" for line in part.strip().splitlines())
        return (
            f"(The owner is replying to this part of {who} — only this part, "
            f"not the rest:)\n{lines}\n\n{body}"
        )
    excerpt = quoted.strip()
    if len(excerpt) > 1_500:
        excerpt = excerpt[:1_500] + "…"
    lines = "\n".join(f"> {line}" for line in excerpt.splitlines())
    return f"(The owner is replying to {who}:)\n{lines}\n\n{body}"


def owner_messages(
    db: sqlite3.Connection,
    chat_id: int,
    after: int,
    up_to: int | None = None,
    *,
    quote: bool = True,
) -> list[tuple[int, str]]:
    """The owner's lines of a room in (after, up_to], oldest first, each with the
    message it replies to when it's a reply."""
    return [
        (
            m["id"],
            with_quote(m["body"], m["q_author"], m["q_speaker"], m["q_body"], m["reply_excerpt"])
            if quote
            else m["body"],
        )
        for m in db.execute(
            """SELECT m.id, m.body, m.reply_excerpt, q.body AS q_body, q.author AS q_author,
                      q.speaker AS q_speaker
               FROM messages m LEFT JOIN messages q ON q.id = m.reply_to
               WHERE m.chat_id = ? AND m.author = 'owner' AND m.id > ? AND m.id <= ?
               ORDER BY m.id""",
            (chat_id, after, up_to if up_to is not None else 1 << 62),
        )
    ]


def unanswered(
    db: sqlite3.Connection, chat_id: int, *, quote: bool = True
) -> list[tuple[int, str]]:
    """A room's owner lines not yet handed to its members, oldest first."""
    return owner_messages(db, chat_id, answered_up_to(db, chat_id), quote=quote)


def owner_line(db: sqlite3.Connection, chat_id: int, message_id: int) -> str | None:
    """The body of one of the owner's own lines of AGOS in the chat."""
    row = db.execute(
        "SELECT body FROM messages WHERE id = ? AND chat_id = ? AND author = 'owner'",
        (message_id, chat_id),
    ).fetchone()
    return str(row["body"]) if row is not None else None


def last_owner_line(db: sqlite3.Connection, chat_id: int) -> int:
    """The id of the owner's newest line of AGOS's own in the chat (0: none)."""
    found = db.execute(
        "SELECT max(id) AS id FROM messages WHERE chat_id = ? AND author = 'owner'", (chat_id,)
    ).fetchone()
    return int(found["id"] or 0) if found is not None else 0


def recent_agent_lines(db: sqlite3.Connection, chat_id: int, minutes: int, limit: int) -> list[str]:
    """AGOS's own agent lines of the chat in the last minutes, newest first."""
    return [
        str(r["body"])
        for r in db.execute(
            """SELECT body FROM messages WHERE chat_id = ? AND author = 'agent'
                 AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?)
               ORDER BY id DESC LIMIT ?""",
            (chat_id, f"-{minutes} minutes", limit),
        ).fetchall()
    ]


def lines_of(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """Every line of the chat, oldest first, with the message each replies to."""
    return db.execute(
        """SELECT m.id, m.author, m.body, m.created_at, m.speaker, m.kind, m.reply_to,
                  m.reply_excerpt, m.edited_at,
                  q.body AS q_body, q.author AS q_author, q.speaker AS q_speaker
             FROM messages m LEFT JOIN messages q ON q.id = m.reply_to
            WHERE m.chat_id = ? ORDER BY m.id""",
        (chat_id,),
    ).fetchall()


def last_body(db: sqlite3.Connection, chat_id: int) -> str | None:
    """The chat's newest line (a list's preview)."""
    row = db.execute(
        "SELECT body FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT 1", (chat_id,)
    ).fetchone()
    return str(row["body"]) if row else None


def owner_words_in_dm(
    db: sqlite3.Connection, workspace_id: str, agent: str | None, limit: int
) -> list[str]:
    """The owner's newest lines in his DM with `agent` (None: the Co-Founder)."""
    if agent is None:
        rows = db.execute(
            """SELECT m.body FROM messages m JOIN chats c ON c.id = m.chat_id
                WHERE m.author = 'owner' AND c.workspace_id = ? AND c.agent IS NULL
                  AND c.kind = 'dm'
                ORDER BY m.id DESC LIMIT ?""",
            (workspace_id, limit),
        )
    else:
        rows = db.execute(
            """SELECT m.body FROM messages m JOIN chats c ON c.id = m.chat_id
                WHERE m.author = 'owner' AND c.workspace_id = ? AND c.agent = ?
                  AND c.kind = 'dm'
                ORDER BY m.id DESC LIMIT ?""",
            (workspace_id, agent, limit),
        )
    return [str(r[0]) for r in rows]


def owner_words_in_workspace(db: sqlite3.Connection, workspace_id: str, limit: int) -> list[str]:
    """The owner's newest lines in any chat of the workspace."""
    return [
        str(r[0])
        for r in db.execute(
            """SELECT m.body FROM messages m JOIN chats c ON c.id = m.chat_id
                WHERE m.author = 'owner' AND c.workspace_id = ?
                ORDER BY m.id DESC LIMIT ?""",
            (workspace_id, limit),
        )
    ]
