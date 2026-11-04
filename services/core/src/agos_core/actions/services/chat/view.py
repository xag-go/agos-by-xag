"""The Chat service's read model: what the owner sees of a chat.

A chat's messages, answers (turns), title and preview are built here from the
chat's Hermes conversation (db/hermes_chats.py) plus AGOS's own part of it
(db/chats.py: its lines, its turn records, its attachments index): the open chat
(get_chat), the lists (list_chats), and each turn's steps, approvals and
Co-Founder actions.

Owns: assembling that view. Must not: write a row (db/chats.py does) or talk to
Hermes other than through db/hermes_chats.py.
"""

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from agos_core.actions import capabilities, cofounder_actions, turn_steps
from agos_core.actions.services.channel.gateway_models import chat_model
from agos_core.actions.services.chat.answer_steps import steps_between
from agos_core.db import (
    chat_attachments,
    chat_edits,
    chat_lines,
    chat_turns,
    feedback_votes,
    hermes_inbox,
)
from agos_core.db import chats as chats_repo
from agos_core.db import hermes_chats as hc
from agos_core.db.chats import (
    ChatKind,
    addresses,
    chat_row,
    command_mark,
    is_hermes,
    live_turn,
    title_from,
    where_of,
)
from agos_core.db.records import Attachment, Chat, ChatActivity, ChatMessage, ChatTurn
from agos_core.db.rows import load_json
from agos_core.db.workspaces import access_of

__all__ = ["View", "get_chat", "list_chats", "room_turns", "turns_of"]


@dataclass
class _Line:
    """A message on its way to the web, with its time and links."""

    msg: ChatMessage
    ts: float
    reply_text: str | None = None
    reply_own: bool = False


@dataclass
class _Group:
    """One answer of Hermes: his message(s) and what came after."""

    start: float
    owner_ids: list[int] = field(default_factory=list)
    first_id: int = 0
    rows: list[hc.Row] = field(default_factory=list)
    answers: list[hc.Row] = field(default_factory=list)
    sessions: set[str] = field(default_factory=set)  # Hermes's sessions it is in


def _attachment(a: sqlite3.Row, heard: str | None = None) -> Attachment:
    """A file as the web shows it. A voice note's words: on a room line (AGOS's own
    line) the ones AGOS heard for the room; in a Hermes chat Hermes's own, read from
    the message it is in (`heard`), never an AGOS copy."""
    return Attachment(
        id=a["id"],
        kind=a["kind"],
        name=a["name"],
        mime=a["mime"],
        size=a["size"],
        duration=a["duration"],
        transcript=a["transcript"] if a["message_id"] is not None else heard,
    )


def _agos_lines(db: sqlite3.Connection, chat_id: int, offset: int) -> list[_Line]:
    """AGOS's own rows of a chat (a room's lines; in a Hermes chat, AGOS's notices)."""
    files: dict[int, list[Any]] = {}
    for a in chat_attachments.of_lines(db, chat_id):
        files.setdefault(int(a["k"]), []).append(a)
    lines = []
    rows = chat_lines.lines_of(db, chat_id)
    for r in rows:
        lines.append(
            _Line(
                msg=ChatMessage(
                    id=offset + int(r["id"]),
                    at=r["created_at"],
                    from_=r["author"],
                    body=r["body"],
                    attachments=[_attachment(a) for a in files.get(int(r["id"]), [])],
                    speaker=r["speaker"],
                    kind=r["kind"],
                    reply_to=(offset + int(r["reply_to"])) if r["reply_to"] else None,
                    reply_preview=(
                        (r["reply_excerpt"] or r["q_body"] or "")[:200] if r["reply_to"] else None
                    ),
                    reply_excerpt=r["reply_excerpt"],
                    edited_at=r["edited_at"],
                    reply_from=(
                        ("owner" if r["q_author"] == "owner" else (r["q_speaker"] or "agent"))
                        if r["reply_to"]
                        else None
                    ),
                ),
                ts=hc.epoch(str(r["created_at"])),
            )
        )
    return lines


def _pending_lines(
    db: sqlite3.Connection, row: sqlite3.Row, transcript: hc.Transcript
) -> list[_Line]:
    """What he sent that Hermes hasn't got in its conversation yet (the agos platform's
    queue): shown until Hermes has it."""
    names = addresses(db, row)
    taken = {r.platform_id for r in transcript.rows if r.role == "user" and r.platform_id}
    newest_user = max((r.ts for r in transcript.rows if r.role == "user"), default=0.0)
    lines = []
    items = hermes_inbox.queued_messages(db, str(row["workspace_id"]), names)
    if not items:
        return []
    files: dict[int, list[Any]] = {}
    for a in chat_attachments.of_items(db, [int(i["id"]) for i in items]):
        files.setdefault(int(a["inbox_id"]), []).append(a)
    for item in items:
        created = hc.epoch(str(item["created_at"]))
        if f"agos-{item['id']}" in taken:
            continue
        if item["done_at"] is not None and newest_user >= created - 1:
            continue  # Hermes has it (one message of its batch carries the batch's id)
        text, reply = str(item["text"]), None
        if item["kind"] == "reply":
            found = load_json(item["text"]) or {}
            text, reply = str(found.get("text") or ""), str(found.get("replyTo") or "") or None
        text = hc.without_agos_notes(text)
        lines.append(
            _Line(
                msg=ChatMessage(
                    id=hc.PENDING_BASE + int(item["id"]),
                    at=item["created_at"],
                    from_="owner",
                    body=text,
                    attachments=[_attachment(a) for a in files.get(int(item["id"]), [])],
                ),
                ts=created,
                reply_text=reply,
            )
        )
    return lines


def _speaker(row: sqlite3.Row, line: hc.Row, own: str) -> str | None:
    """A member's own Hermes answered (its profile): its name on the answer."""
    return str(row["agent"]) if row["agent"] and line.profile != own else None


def _turn_extras(db: sqlite3.Connection, chat_id: int) -> list[sqlite3.Row]:
    """AGOS's part of each finished answer (oldest first)."""
    return chat_turns.ended(db, chat_id)


# A board card's or an automation's own record in the Co-Founder chat (its cards
# from AGOS's tools; actions/hermes_channel.py _run_turn): shown on its own.
RUN_MARK = "run:"


def _match_extras(groups: list[_Group], extras: list[sqlite3.Row]) -> dict[int, list[sqlite3.Row]]:
    """Which of AGOS's turn records goes with which of Hermes's answers: by the
    Hermes message AGOS noted at its end, else by time."""
    by_first: dict[int, list[sqlite3.Row]] = {}
    ids = {g.first_id: g for g in groups}
    starts = sorted((g.start, g.first_id) for g in groups)
    for r in extras:
        link = str(r["hermes_run_id"] or "")
        if link.startswith("row:"):
            try:
                wanted = int(link[4:])
            except ValueError:
                wanted = -1
            if wanted in ids:
                by_first.setdefault(wanted, []).append(r)
                continue
        if command_mark(r) or link.startswith(RUN_MARK):
            continue  # a /command's mark (it had no answer); a card's or a run's own
        at = hc.epoch(str(r["started_at"]))
        later = [first for start, first in starts if start >= at - 5]
        earlier = [first for start, first in starts if start <= at]
        pick = later[0] if later else (earlier[-1] if earlier else None)
        if pick is not None:
            by_first.setdefault(pick, []).append(r)
    return by_first


def _kept(raw: Any) -> tuple[list[dict[str, Any]], bool]:
    """AGOS's own items of an answer (approvals, notes…), and whether that is all of
    them (an answer from before its steps were Hermes's)."""
    data = load_json(raw) if isinstance(raw, str) else raw
    if isinstance(data, list):
        return data, True
    if isinstance(data, dict):
        if "own" in data:
            return list(data["own"] or []), True
        # Only the approvals: the rest of an answer is read from Hermes (turn_steps.kept).
        items = [k for k in data.get("kept") or [] if isinstance(k, dict)]
        return [k for k in items if k.get("kind") == "approval"], False
    return [], False


def _activity(
    turn_id: int, hermes: list[dict[str, Any]], extras: list[sqlite3.Row]
) -> list[ChatActivity]:
    kept: list[dict[str, Any]] = []
    whole: list[dict[str, Any]] | None = None
    for r in extras:
        items, complete = _kept(r["activity"])
        if complete:
            whole = (whole or []) + items
        else:
            kept += items
    if whole is not None and not hermes:
        steps = [{**a, "id": f"{turn_id}-{i}"} for i, a in enumerate(whole, start=1)]
    else:
        steps = turn_steps.join(turn_id, hermes, kept)
    out = []
    for a in steps:
        a.setdefault("status", "done")
        a.setdefault("choices", [])
        a.setdefault("detail", "")
        try:
            out.append(ChatActivity.model_validate(a))
        except ValueError:
            continue
    return out


@dataclass
class View:
    messages: list[ChatMessage]
    turns: list[ChatTurn]
    title: str
    last: float


def _loose_files(
    db: sqlite3.Connection, chat_id: int
) -> tuple[dict[int, list[Any]], dict[str, list[Any]], dict[int, list[Any]]]:
    """The chat's files on no AGOS message, by queue item, by Hermes uid, and by the
    queue item's sent time (ms) for lines Hermes stored without either."""
    by_inbox: dict[int, list[Any]] = {}
    by_uid: dict[str, list[Any]] = {}
    for a in chat_attachments.unplaced(db, chat_id):
        if a["inbox_id"] is not None:
            by_inbox.setdefault(int(a["inbox_id"]), []).append(a)
        if a["hermes_uid"]:
            by_uid.setdefault(str(a["hermes_uid"]), []).append(a)
    by_sent: dict[int, list[Any]] = {}
    if by_inbox:
        for item in hermes_inbox.sent_at(db, list(by_inbox)):
            sent = round(hc.epoch(str(item["created_at"])) * 1000)
            by_sent[sent] = by_inbox[int(item["id"])]
    return by_inbox, by_uid, by_sent


def _view(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    with_turns: bool = True,
    with_replies: bool = True,
) -> View:
    """A Hermes chat as the owner sees it (`with_replies=False`: without linking
    each reply to the message it answers, for the lists: they show none)."""
    where = where_of(db, row)
    store = hc.store()
    transcript = hc.Transcript()
    if store and where:
        # The lists (no turns) need his messages and the answers only, kept while
        # Hermes's state.db files are unchanged; an open chat reads them all.
        transcript = store.transcript(where) if with_turns else store.summary(where)
    own = where.own if where else ""
    chat_id = int(row["id"])
    lines: list[_Line] = _agos_lines(db, chat_id, hc.ROW_BASE)
    # Files: by the queue item his message was (its Hermes id), its Hermes uid, or
    # (in Telegram, where his message has no id of AGOS's) the time he sent it,
    # which is Hermes's own time of that message (the event's timestamp).
    by_inbox, by_uid, by_sent = _loose_files(db, chat_id)
    groups: list[_Group] = []
    current: _Group | None = None
    for r in transcript.rows:
        if r.role == "user":
            said = hc.owner_words(r)
            steer = r.display_kind == "steer" or (
                said is not None and r.content.lstrip().startswith("[OUT-OF-BAND")
            )
            if current is None or not steer:
                current = _Group(start=r.ts, first_id=r.id)
                groups.append(current)
            current.sessions.add(r.session)
            if said is None:
                continue
            files = []
            if r.platform_id.startswith("agos-") and r.platform_id[5:].isdigit():
                files = by_inbox.get(int(r.platform_id[5:]), [])
            if not files and said.item is not None:
                files = by_inbox.get(said.item, [])
            if not files and r.uid:
                files = by_uid.get(r.uid, [])
            if not files and by_sent:
                sent = round(r.ts * 1000)
                files = next((by_sent[t] for t in (sent, sent - 1, sent + 1) if t in by_sent), [])
            voice = said.voice if any(a["kind"] == "audio" for a in files) else None
            body = said.body
            if said.voice and not voice:
                body = f"🎤 {said.voice}" + (f"\n\n{body}" if body else "")
            lines.append(
                _Line(
                    msg=ChatMessage(
                        id=r.id,
                        at=hc.iso(r.ts),
                        from_="owner",
                        body=body,
                        attachments=[_attachment(a, voice) for a in files],
                    ),
                    ts=r.ts,
                    reply_text=said.reply,
                    reply_own=said.reply_own,
                )
            )
            current.owner_ids.append(r.id)
            continue
        if current is None:
            current = _Group(start=r.ts, first_id=r.id)
            groups.append(current)
        current.rows.append(r)
        current.sessions.add(r.session)
        if hc.is_answer(r):
            current.answers.append(r)
            lines.append(
                _Line(
                    msg=ChatMessage(
                        id=r.id,
                        at=hc.iso(r.ts),
                        from_="agent",
                        body=r.content,
                        speaker=_speaker(row, r, own),
                    ),
                    ts=r.ts,
                )
            )
    lines += _pending_lines(db, row, transcript)
    lines.sort(key=lambda line: line.ts)
    # His edits and deletions of older messages (Hermes keeps no edit in the middle
    # of a conversation): what he sees, and what the agent was told.
    edits = {int(e["message_id"]): e for e in chat_edits.hermes_edits(db, chat_id)}
    shown: list[_Line] = []
    for line in lines:
        edit = edits.get(line.msg.id)
        if edit is not None:
            if not edit["after"]:
                continue
            line.msg = line.msg.model_copy(
                update={"body": edit["after"], "edited_at": edit["created_at"]}
            )
        shown.append(line)
    # A reply: Hermes keeps the words he replied to; the message they are from.
    # Each message's letters are worked out once (a long chat with many replies
    # compared every reply against every earlier message again: the lists' 0.2 s).
    # The lists show no reply, so they skip this.
    letters: dict[int, str] = {}
    for i, line in enumerate(shown if with_replies else ()):
        if not line.reply_text:
            continue
        wanted = chats_repo.letters_of(line.reply_text)
        for j in range(i - 1, -1, -1):
            earlier = shown[j]
            if j not in letters:
                letters[j] = chats_repo.letters_of(earlier.msg.body)
            body = letters[j]
            if wanted and wanted in body:
                whole = wanted == body
                line.msg = line.msg.model_copy(
                    update={
                        "reply_to": earlier.msg.id,
                        "reply_preview": line.reply_text[:200],
                        "reply_excerpt": None if whole else line.reply_text,
                        "reply_from": (
                            "owner"
                            if earlier.msg.from_ == "owner"
                            else (earlier.msg.speaker or "agent")
                        ),
                    }
                )
                break
    messages = [line.msg for line in shown]
    turns: list[ChatTurn] = []
    if with_turns:
        models = {x.id: x.model for x in transcript.sessions if x.model}
        turns = _turns(db, row, groups, own, models)
    title = title_from(db, row, where, None if with_turns else transcript.sessions)
    last = max([line.ts for line in shown] + [hc.epoch(str(row["created_at"]))])
    return View(messages=messages, turns=turns, title=title, last=last)


def _turns(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    groups: list[_Group],
    own: str,
    models: dict[str, str] | None = None,
) -> list[ChatTurn]:
    """Each answer as Hermes keeps it: its reply, steps and model; with AGOS's part
    of it (approvals, notes, cards) and how it ended (stopped or failed and why)
    as Hermes's on_session_end hook told it (actions/hermes_channel.py
    turn_ended), or that Hermes never reported its end (close_stale)."""
    chat_id = int(row["id"])
    extras = _turn_extras(db, chat_id)
    matched = _match_extras(groups, extras)
    used = {int(x["id"]) for mine in matched.values() for x in mine}
    live = live_turn(db, chat_id)

    dated: list[tuple[float, ChatTurn]] = []
    for n, g in enumerate(groups):
        mine = matched.get(g.first_id, [])
        newest = n == len(groups) - 1
        error: str | None = None
        if g.answers:
            status: str = "completed"
        elif newest and live is not None:
            status = "running"
        else:
            ended = [x for x in mine if x["status"] in ("failed", "stopped")]
            status = str(ended[-1]["status"]) if ended else "completed"
            last = ended[-1:] or list(reversed(mine))
            error = next((str(x["error"]) for x in last if x["error"]), None)
        if not g.answers and status == "completed" and not mine:
            continue
        turn_id = g.first_id
        speaker = next((_speaker(row, a, own) for a in g.answers), None) or next(
            (x["speaker"] for x in mine if x["speaker"]), None
        )
        if speaker is None and row["agent"] and any(h.profile != own for h in g.rows):
            speaker = str(row["agent"])
        requests, actions = [], []
        for x in mine:
            requests += capabilities.of_turn(db, int(x["id"]))
            actions += cofounder_actions.of_turn(db, int(x["id"]))
        # Hermes's model: its session's (the turn record keeps none).
        model = next((h.model for h in g.rows if h.model), None) or next(
            (m for sid in sorted(g.sessions) if (m := (models or {}).get(sid))), None
        )
        dated.append(
            (
                g.start,
                ChatTurn(
                    id=turn_id,
                    status=status,  # type: ignore[arg-type]
                    asked_up_to=g.owner_ids[-1] if g.owner_ids else 0,
                    reply_id=g.answers[-1].id if g.answers else None,
                    activity=_activity(turn_id, steps_between(g.rows), mine),
                    model=model,
                    error=error,
                    requests=requests,
                    actions=actions,
                    speaker=speaker,
                ),
            )
        )
    for x in extras:
        if int(x["id"]) in used or command_mark(x):
            continue
        turn_id = hc.ROW_BASE + int(x["id"])
        dated.append(
            (
                hc.epoch(str(x["started_at"])),
                ChatTurn(
                    id=turn_id,
                    status=x["status"],
                    asked_up_to=0,
                    reply_id=None,
                    activity=_activity(turn_id, [], [x]),
                    model=None,
                    error=x["error"],
                    requests=capabilities.of_turn(db, int(x["id"])),
                    actions=cofounder_actions.of_turn(db, int(x["id"])),
                    speaker=x["speaker"],
                ),
            )
        )
    dated.sort(key=lambda d: d[0])
    return [t for _at, t in dated]


def _summary(db: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, str, float]:
    """(title, preview, last activity) for the lists."""
    if not is_hermes(row):
        last = chat_lines.last_body(db, int(row["id"]))
        return (
            title_from(db, row, None) if row["kind"] != "chat" else str(row["title"]),
            " ".join(last.split())[:140] if last else "",
            hc.epoch(str(row["updated_at"])),
        )
    view = _view(db, row, with_turns=False, with_replies=False)
    preview = next((m.body for m in reversed(view.messages) if m.body.strip()), "")
    return view.title, " ".join(preview.split())[:140], view.last


def _with_votes(
    db: sqlite3.Connection, row: sqlite3.Row, messages: list[ChatMessage]
) -> list[ChatMessage]:
    """The owner's 👍 / 👎 on the agent's replies (actions/feedback.py, one query)."""
    prefix = f"{row['id']}:"
    votes = {
        ref[len(prefix) :]: vote
        for ref, vote in feedback_votes.with_prefix(
            db, str(row["workspace_id"]), "reply", prefix
        ).items()
    }
    if not votes:
        return messages
    return [
        m.model_copy(update={"vote": votes[str(m.id)]})
        if m.from_ == "agent" and str(m.id) in votes
        else m
        for m in messages
    ]


def _chat(db: sqlite3.Connection, row: sqlite3.Row, *, with_messages: bool) -> Chat:
    live = live_turn(db, int(row["id"]))
    if is_hermes(row) and with_messages:
        view = _view(db, row)
        title, messages, turns, last = view.title, view.messages, view.turns, view.last
        messages = _with_votes(db, row, messages)
        preview = next((m.body for m in reversed(messages) if m.body.strip()), "")
        preview = " ".join(preview.split())[:140]
    elif is_hermes(row):
        title, preview, last = _summary(db, row)
        messages, turns = [], []
    else:
        title, preview, last = _summary(db, row)
        messages = (
            [line.msg for line in _agos_lines(db, int(row["id"]), 0)] if with_messages else []
        )
        turns = room_turns(db, int(row["id"])) if with_messages else []
    return Chat(
        id=row["id"],
        workspace_id=row["workspace_id"],
        title=title,
        channel=row["channel"],
        model=chat_model(db, row, kept=not with_messages),
        # Hermes's own switches (actions/access.py): read for an open chat only.
        access="full"
        if with_messages
        and chats_repo.access_reader is not None
        and chats_repo.access_reader(row["workspace_id"], row["id"])
        else "ask",
        workspace_full=access_of(str(row["workspace_id"])) == "full",
        agent=row["agent"],
        kind=row["kind"],
        members=load_json(row["members"]),
        messages=messages,
        turns=turns,
        updated_at=hc.iso(last) if is_hermes(row) else row["updated_at"],
        preview=preview,
        working=live is not None,
    )


def list_chats(
    db: sqlite3.Connection,
    workspace_id: str,
    kinds: tuple[ChatKind, ...] = ("chat",),
) -> list[Chat]:
    """Most recently active first (the classic Chats page by default)."""
    chats = [_chat(db, r, with_messages=False) for r in chats_repo.listed(db, workspace_id, kinds)]
    chats.sort(key=lambda c: (c.updated_at, c.id), reverse=True)
    return chats


def get_chat(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> Chat | None:
    row = chat_row(db, workspace_id, chat_id)
    return _chat(db, row, with_messages=True) if row else None


def room_turns(db: sqlite3.Connection, chat_id: int) -> list[ChatTurn]:
    """A room's turns (AGOS's room bridge keeps them)."""
    out = []
    for r in chat_turns.all_of(db, chat_id):
        items, _complete = _kept(r["activity"])
        out.append(
            ChatTurn(
                id=r["id"],
                status=r["status"],
                asked_up_to=r["asked_up_to"],
                reply_id=r["reply_id"],
                activity=[ChatActivity.model_validate(a) for a in items],
                model=None,
                error=r["error"],
                requests=_requests_of_turn(db, r["id"]),
                actions=_actions_of_turn(db, r["id"]),
                speaker=r["speaker"],
            )
        )
    return out


def turns_of(db: sqlite3.Connection, workspace_id: str, chat_id: int) -> list[ChatTurn]:
    """The chat's turns, when it is this workspace's (hidden or not)."""
    row = chats_repo.in_workspace(db, workspace_id, chat_id)
    if row is None:
        return []
    if is_hermes(row):
        return _view(db, row).turns
    return room_turns(db, chat_id)


def _requests_of_turn(db: sqlite3.Connection, turn_id: int) -> Any:
    return capabilities.of_turn(db, turn_id)


def _actions_of_turn(db: sqlite3.Connection, turn_id: int) -> Any:
    return cofounder_actions.of_turn(db, turn_id)
