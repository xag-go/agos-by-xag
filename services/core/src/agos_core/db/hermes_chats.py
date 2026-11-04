"""A chat's conversation, read from the workspace's Hermes (its session store).

A chat (one of the classic chats or a DM) is a Hermes conversation: on the agos
platform its sessions are `source = 'agos'` with the AGOS chat id as Hermes's chat
id, in the profile that answers it (the workspace's root, or a team member's
profile); a chat linked to a Telegram place is Hermes's Telegram conversation
there. Hermes keeps everything about it: the words and their order, the steps of
each answer, the session's title and model, and its full-text index. AGOS reads
them here, read-only, and keeps no copy.

Only the chat's own workspace's profiles are ever opened. The reads themselves (the
read-only handles on each profile's state.db) are the Hermes Gateway's
(hermes_gateway/chat_sessions.py); this module holds the shapes they return, the
parsing of Hermes's words and the installed store.

Must not: open a Hermes database or import the engine or the gateway.

Ids the web sees (one integer per message, as before):
- a message of Hermes: Hermes's row id, tagged with the profile it lives in;
- one of AGOS's own lines in that chat (its notices, Hermes's /command answers,
  which Hermes keeps in no transcript): `ROW_BASE` + the AGOS row id;
- a message he just sent, still in the agos platform's queue: `PENDING_BASE` + the
  queue item's id (it becomes Hermes's own message as soon as Hermes has it).
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import zlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

PROFILE_SHIFT = 36
HERMES_MAX = 1 << 48
ROW_BASE = 1 << 49
PENDING_BASE = 1 << 50
PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")

# What the gateway puts around his words (gateway/run_inbound.py), and the
# mid-turn steer marker (agent/prompt_builder.py): shown as he wrote them.
_REPLY = re.compile(
    r'\A(?:\[Triggering message id: [^\n]*\]\n\n)?\[Replying to( your previous message)?: "(.*?)"\]\n\n',
    re.DOTALL,
)
_MODEL_NOTE = re.compile(r"\A\[Note: model was just switched from [^\n]*?\]\n*", re.DOTALL)
_MEDIA_NOTE = re.compile(r"\A\[The user sent [^\n]*?\]\s*", re.DOTALL)
_STEER_OPEN = re.compile(r"\A\s*\[OUT-OF-BAND USER MESSAGE[^\n]*\]\n?")
_STEER_CLOSE = "[/OUT-OF-BAND USER MESSAGE]"
# Hermes's own prompts in the user role (background results, delegations): no
# owner message (hermes_state_timeline._SYNTHETIC_PROMPT).
_SYNTHETIC = re.compile(
    r"^\s*(?:\[IMPORTANT: Background process |\[ASYNC (?:DELEGATION )?(?:BATCH )?COMPLETE\b|"
    r"A background fan-out of \d+ subagent\(s\) you dispatched earlier has finished\.|"
    r"A background subagent you dispatched earlier has finished\.)",
    re.IGNORECASE,
)


def archive_id(workspace_id: str, chat_id: int) -> str:
    """The session AGOS's older words of a chat were written into (by Hermes)."""
    return f"agos-archive-{workspace_id}-c{chat_id}"


def tag(profile: str, own: str) -> int:
    """A profile's place in the ids (0: the workspace's own; a member: a small
    stable number of its own)."""
    if profile == own:
        return 0
    return 1 + zlib.crc32(profile.encode()) % 4095


def hermes_id(profile_tag: int, row_id: int) -> int:
    return (profile_tag << PROFILE_SHIFT) | row_id


@dataclass(frozen=True)
class Where:
    """Which of Hermes's sessions hold a chat (in which profiles)."""

    workspace_id: str
    chat_id: int
    profiles: tuple[str, ...]  # the workspace's own first
    own: str
    keys: tuple[str, ...] = ()  # sessions named outright (API-server era, archive)
    telegram: tuple[tuple[str, str], ...] = ()  # (chat, thread) of its Telegram place


@dataclass(frozen=True)
class Row:
    """One message of Hermes's transcript (never changed: the lists share them)."""

    id: int  # the id the web sees
    profile: str
    row: int
    session: str
    role: str
    content: str
    ts: float
    uid: str = ""
    platform_id: str = ""
    tool_calls: str = ""
    tool_call_id: str = ""
    display_kind: str = ""
    model: str = ""


@dataclass(frozen=True)
class Session:
    id: str
    profile: str
    title: str
    model: str
    started: float
    last: float


@dataclass
class Transcript:
    rows: list[Row] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)


def _epoch(iso: str) -> float:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def iso(ts: float) -> str:
    return datetime.fromtimestamp(float(ts or 0), UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def content_text(content: Any) -> str:
    """A message's words (Hermes keeps some as JSON parts)."""
    if content is None:
        return ""
    text = str(content)
    if text.startswith("[{") or text.startswith('[{"'):
        with contextlib.suppress(ValueError):
            parts = json.loads(text)
            if isinstance(parts, list):
                return "\n".join(
                    str(p.get("text") or "")
                    for p in parts
                    if isinstance(p, dict) and p.get("type") in ("text", "input_text")
                ).strip()
    return text


# ---- what the owner sees -------------------------------------------------------------


@dataclass
class Said:
    """One owner message as Hermes keeps it, shown as he wrote it."""

    body: str
    reply: str | None = None  # the text he replied to
    reply_own: bool = False  # ...the agent's
    voice: str | None = None  # a voice note's words (Hermes's transcript)
    item: int | None = None  # the agos queue item it was written from (its files)


def owner_words(row: Row) -> Said | None:
    """His words in a user row, without what Hermes put around them; None for a
    row that isn't his (Hermes's own prompts)."""
    text = row.content
    if _SYNTHETIC.match(text):
        return None
    if row.display_kind == "steer" or _STEER_OPEN.match(text):
        # A message sent while it answered (Hermes's steer): the words inside the
        # marker are the message as the gateway built it (reply context, files).
        text = _STEER_OPEN.sub("", text.lstrip())
        text = text.split(_STEER_CLOSE, 1)[0].strip()
    elif row.display_kind:
        return None  # a typed bookkeeping row (Hermes's own)
    text = _MODEL_NOTE.sub("", text)
    reply = None
    own = False
    m = _REPLY.match(text)
    if m:
        own = bool(m.group(1))
        reply = m.group(2)
        text = text[m.end() :]
    while True:
        stripped = _MEDIA_NOTE.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    voice = None
    first, _, rest = text.partition("\n\n")
    if len(first) > 1 and first[0] == first[-1] == '"' and first.count('"') == 2:
        voice = first[1:-1]
        text = rest
    # What AGOS wrote into a Telegram conversation with his files: their notes.
    item = None
    for m in _AGOS_FILE.finditer(text):
        found = _AGOS_ITEM.search(m.group(1))
        if found and item is None:
            item = int(found.group(1))
    heard = [m.group(1).strip() for m in _AGOS_VOICE.finditer(text)]
    if heard:
        voice = " ".join(heard)
    text = _AGOS_VOICE.sub("", _AGOS_FILE.sub("", text))
    return Said(body=text.strip(), reply=reply, reply_own=own, voice=voice, item=item)


def without_agos_notes(text: str) -> str:
    """His words without the notes AGOS adds for his files in a Telegram conversation."""
    return _AGOS_VOICE.sub("", _AGOS_FILE.sub("", text)).strip()


_AGOS_FILE = re.compile(r"\[(?:Voice note|File attached), saved at ([^\]\n]+)\]\s*")
_AGOS_VOICE = re.compile(r"\[Voice note, transcribed\] ([^\n]*)\n*")
_AGOS_ITEM = re.compile(r"/\.agos/uploads/chat-\d+/(\d+)-\d+-")


def is_answer(row: Row) -> bool:
    """An answer the owner reads (not a step: a tool call's own words)."""
    if row.role != "assistant" or not row.content.strip():
        return False
    calls = row.tool_calls.strip()
    return not calls or calls in ("[]", "null")


class ChatStore(Protocol):
    """What the chat code reads of Hermes's session stores (hermes_gateway/chat_sessions.py
    Store is the one implementation; agos-core installs it at start)."""

    home_of: Callable[[str], Path | None]
    profile_of: Callable[[str], str]
    own_profiles: Callable[[str], list[str]]

    def forget(self, profile: str | None = None) -> None: ...
    def query(self, profile: str, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]: ...
    def columns(self, profile: str) -> set[str]: ...
    def archive_states(self, workspace_id: str) -> tuple[dict[int, bool], dict[str, bool]]: ...
    def room_names(self, workspace_id: str) -> dict[str, str]: ...
    def forget_archive(self, workspace_id: str) -> None: ...
    def belongs(self, profile: str, workspace_id: str) -> bool: ...
    def sessions(self, where: Where) -> list[Session]: ...
    def transcript(self, where: Where) -> Transcript: ...
    def summary(self, where: Where) -> Transcript: ...
    def title(self, where: Where, sessions: list[Session] | None = None) -> str: ...
    def model_override(self, where: Where, *, kept: bool = False) -> dict[str, str] | None: ...
    def search(
        self, workspace_id: str, query: str, limit: int = 60
    ) -> list[tuple[str, str, Row]]: ...


_STORE: dict[str, ChatStore | None] = {"store": None}


def install(store: ChatStore | None) -> None:
    _STORE["store"] = store


def store() -> ChatStore | None:
    return _STORE["store"]


def now_epoch() -> float:
    return datetime.now(UTC).timestamp()


def epoch(iso_text: str) -> float:
    return _epoch(iso_text)
