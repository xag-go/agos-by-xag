"""Running a turn with Hermes: start, the stored attachments, finish, stop, retry, approvals, closing, the tick.
Must not: post the owner's message (messages does).

Split out of agos_core.actions.chat (which re-exports it); behaviour unchanged.
"""

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from agos_core.actions import chat_store, idle, slis
from agos_core.actions.errors import ActionError
from agos_core.actions.services.chat import chat_writes
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.services.chat.history import edits_note
from agos_core.actions.services.chat.live_turns import _STATES, _Live, _registry, _spawn
from agos_core.actions.services.chat.lookup import _chat, log
from agos_core.config import EngineConfig
from agos_core.context import Core
from agos_core.db import chat_attachments, chat_turns, hermes_inbox
from agos_core.db import chats as repo
from agos_core.db import hermes_chats as hc
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.engine import attachments as files
from agos_core.engine import doorbell
from agos_core.engine.models import hermes_python
from agos_core.storage.layout import workspace_paths

__all__ = [
    "answer_approval",
    "close_pre_hermes",
    "delete_chat",
    "retry",
    "shutdown",
    "start_turn",
    "stop_turn",
    "tick",
]


def stop_turn(core: Core, workspace_id: str, chat_id: int) -> bool:
    turn = repo.live_turn(core.db, chat_id)
    if turn is None or turn.workspace_id != workspace_id:
        return False
    live = _registry(core).get(turn.id)
    from agos_core.actions import rooms

    if turn.via == rooms.VIA:
        return rooms.stop(core, workspace_id, chat_id)  # Hermes's own stop_room
    if turn.via == "hermes":
        # Hermes's own /stop in the chat's conversation (the gateway interrupts it).
        from agos_core.actions import hermes_channel

        where = hermes_channel.chat_on_hermes(core, chat_id)
        address = str(where["address"]) if where else ""
        if address.startswith(hermes_channel.AGOS_PREFIX):
            hermes_inbox.put(core.db, workspace_id, address, "/stop", "command")
            doorbell.ring(doorbell.INBOX, workspace_id)
    # The owner pressed Stop: the answer ends now, whatever Hermes does next
    # (a follower that is still alive sees `stop` and leaves it closed).
    if live:
        live.stop = True
    _close(core, turn.id, "stopped", reply=None, error=None)
    return True


def answer_approval(core: Core, workspace_id: str, chat_id: int, choice: str) -> None:
    if choice not in ("once", "deny"):  # a chat never widens what the agent may do
        raise ActionError("Choose allow once or deny.")
    from agos_core.actions import rooms

    if rooms.answer(core, workspace_id, chat_id, choice):
        return  # a room member's command (Hermes's approve_room_task)
    turn = repo.live_turn(core.db, chat_id)
    if turn is not None and turn.workspace_id == workspace_id and turn.via == "hermes":
        from agos_core.actions import hermes_channel

        where = hermes_channel.chat_on_hermes(core, chat_id)
        if where is None:
            raise ActionError("Nothing is waiting for an answer.", status=409)
        hermes_channel.answer_approval(core, workspace_id, str(where["address"]), choice)
        return
    raise ActionError("Nothing is waiting for an answer.", status=409)


def retry(core: Core, workspace_id: str, chat_id: int) -> None:
    """Asks again the last message, when its answer failed or was stopped: Hermes's
    own /retry (it asks its last message again itself)."""
    row = _chat(core, workspace_id, chat_id)
    if repo.live_turn(core.db, chat_id) is not None:
        raise ActionError("The agent is already answering.", status=409)
    if not repo.is_hermes(row):
        _retry_room(core, workspace_id, chat_id)
        return
    chat = chat_view.get_chat(core.db, workspace_id, chat_id)
    last = chat.turns[-1] if chat and chat.turns else None
    if last is None or last.status not in ("failed", "stopped") or not last.asked_up_to:
        raise ActionError("There is nothing to try again.", status=409)
    from agos_core.actions import hermes_channel

    with transaction(core.db):
        if hermes_channel.own_command(core, workspace_id, chat_id, "/retry"):
            hermes_channel.open_turn(core, workspace_id, chat_id)
            return
    # A conversation Hermes's /retry can't take from AGOS (a group's members each
    # have their own): his last message is asked again.
    asked = next((m for m in chat.messages if m.id == last.asked_up_to), None) if chat else None
    if asked is None or not asked.body.strip():
        raise ActionError("There is nothing to try again.", status=409)
    with transaction(core.db):
        hermes_channel.hand_over(core, workspace_id, chat_id, asked.body)


def _retry_room(core: Core, workspace_id: str, chat_id: int) -> None:
    rows = chat_turns.last_two(core.db, chat_id)
    if not rows or rows[0]["status"] not in ("failed", "stopped"):
        raise ActionError("There is nothing to try again.", status=409)
    since = chat_turns.answered_before(core.db, chat_id, int(rows[0]["id"]))
    messages = repo.owner_messages(core.db, chat_id, since, rows[0]["asked_up_to"])
    if not messages:
        raise ActionError("There is nothing to try again.", status=409)
    _spawn(core, _start(core, workspace_id, chat_id, messages))


def delete_chat(core: Core, workspace_id: str, chat_id: int) -> None:
    _chat(core, workspace_id, chat_id)
    stop_turn(core, workspace_id, chat_id)
    for turn_id in chat_turns.ids_of(core.db, chat_id):
        live = _registry(core).get(turn_id)
        if live is not None:
            live.stop = True
    # Only hidden from the list: the files in the workspace, the Hermes session and
    # the workspace's memory stay, so the project keeps what it learned in this
    # chat (ADR 0011). Hidden is Hermes's own archive of its sessions where Hermes
    # has them; AGOS's mark only where it has nothing to archive (chat_store.hide).
    chat_store.hide(core, _chat(core, workspace_id, chat_id))


# ---- a room's turn ------------------------------------------------------------------


async def start_turn(core: Core, workspace_id: str, chat_id: int) -> None:
    await _start(core, workspace_id, chat_id, None)


async def _start(
    core: Core,
    workspace_id: str,
    chat_id: int,
    messages: list[tuple[int, str]] | None,
) -> None:
    """A room's new lines go to its members: a group chat is a Hermes room (ADR
    0020), run exactly as Hermes runs it: his words (voice notes heard, files as
    their paths) go in, as he wrote them."""
    chat = repo.chat_row(core.db, workspace_id, chat_id)
    if chat is None or core.engine is None or repo.is_hermes(chat):
        return
    pending = messages if messages is not None else repo.unanswered(core.db, chat_id)
    if not pending:
        return
    from agos_core.actions import rooms

    live = repo.live_turn(core.db, chat_id)
    if (
        live is not None
        and live.via == rooms.VIA
        and live.asked_up_to >= max(i for i, _ in pending)
    ):
        return  # already handed over (two rounds raced to it)
    with transaction(core.db):
        changed = edits_note(core, chat_id)
    text = await _for_hermes(core, workspace_id, pending)
    if changed:
        first_id, first_text = text[0]
        text = [(first_id, f"{changed}\n\n{first_text}"), *text[1:]]
    await asyncio.to_thread(rooms.hand_over, core, workspace_id, chat_id, text)


async def _stored(
    core: Core,
    workspace_id: str,
    ids: list[int],
    live: _Live | None,
    *,
    with_images: bool = True,
) -> list[files.Stored]:
    """The owner's attachments on these lines; voice notes transcribed once, with
    the speech-to-text Hermes is set up with."""
    rows = chat_attachments.attachments_of(core.db, ids)
    folder = workspace_paths(core.layout, workspace_id).files
    stored: list[files.Stored] = []
    for row in rows:
        path = files.resolve(folder, row["path"])
        transcript = row["transcript"]
        if row["kind"] == "audio" and transcript is None and path is not None and core.engine:
            if live is not None:
                live.turn.note_phase("Listening to the voice note")
            try:
                transcript = await asyncio.to_thread(_transcribe, core.engine.settings, path)
            except (RuntimeError, OSError, ValueError) as error:
                log.warning("voice note %s: %s", row["id"], error)
                transcript = ""
            with transaction(core.db):
                chat_attachments.set_transcript(core.db, row["id"], transcript)
            if live is not None:
                live.turn.end_phase()
        data = (
            path.read_bytes()
            if with_images and row["kind"] == "image" and path is not None
            else None
        )
        stored.append(
            files.Stored(
                kind=row["kind"],
                name=row["name"],
                mime=row["mime"],
                relative=row["path"],
                transcript=transcript,
                data=data,
            )
        )
    return stored


def _transcribe(settings: EngineConfig, path: Path) -> str:
    """A voice note's words, in a thread: finding Hermes's Python may start Hermes
    (its runtime command, asked once), which never runs on the event loop."""
    return files.transcribe(settings, hermes_python(settings), path)


def _gateway_up(core: Core, workspace_id: str) -> None:
    """Hermes's own service keeps the gateway up (systemd `Restart=always`, written
    by `hermes gateway install`: H: hermes_cli/gateway.py systemd unit), so a
    message never starts it. Only the test-only "spawn" supervisor has no such
    service: there the gateway AGOS spawned is brought back (actions/idle.py)."""
    idle.spawned_up(core, workspace_id)


async def _for_hermes(
    core: Core, workspace_id: str, pending: list[tuple[int, str]]
) -> list[tuple[int, str]]:
    """What he wrote in AGOS, as a Hermes room takes it (text only): a voice note's
    words, and where a screenshot or file is saved (Hermes's own tools open them
    there, as with what he sends in Telegram)."""
    out: list[tuple[int, str]] = []
    for message_id, text in pending:
        stored = await _stored(core, workspace_id, [message_id], None, with_images=False)
        body = files.turn_content([text], stored) if stored else text
        out.append((message_id, body if isinstance(body, str) else text))
    return out


# ---- the end of a Hermes answer -------------------------------------------------------


def _finish(core: Core, workspace_id: str, chat_id: int, turn_id: int, live: _Live) -> None:
    """Hermes reported the end of its answer. Hermes keeps the answer: the reply,
    its steps, its model and tokens (its sessions, messages.token_count,
    session_model_usage) and how it ended (agent.log "Turn ended", read by
    db/chats.py). AGOS's record only closes ("completed" = Hermes reported back)
    and keeps what Hermes has no place for: the approvals asked (each with its
    place among Hermes's tool steps, actions/turn_steps.py) and which Hermes
    message it answered. Thoughts, notes and helpers are read back from Hermes.
    The installed app on his phone hears the answer came (actions/web_push.py)."""
    turn = live.turn
    row = repo.get_turn(core.db, turn_id)
    from agos_core.actions.turn_steps import kept as approvals_of

    kept = approvals_of(turn.activity)
    with transaction(core.db):
        if row is None or repo.get_turn(core.db, turn_id) is None:
            _registry(core).pop(turn_id, None)
            return
        chat_writes.set_turn(
            core.db,
            turn_id,
            status="completed",
            reply_id=None,
            activity={"kept": kept},
            error=None,
            ended_at=now(),
            hermes_run_id=_answered(core, chat_id, row),
        )
    _registry(core).pop(turn_id, None)
    slis.turn_ended(core, workspace_id, turn_id, turn.first_output_at)  # the S2 SLI
    from agos_core.actions import web_push

    with contextlib.suppress(Exception):
        web_push.answered(core, workspace_id, chat_id, turn.final_text())


def _answered(core: Core, chat_id: int, turn: repo.TurnRow) -> str | None:
    """Which of Hermes's messages this answer answered (\"row:<id>\"): his newest
    message in the conversation once it started."""
    chat = repo.any_row(core.db, chat_id)
    store = hc.store()
    where = repo.where_of(core.db, chat) if chat is not None else None
    if store is None or where is None:
        return None
    started = chat_turns.started_at(core.db, turn.id)
    since = hc.epoch(started) - 5 if started else 0.0
    users = [
        r
        for r in store.transcript(where).rows
        if r.role == "user" and r.display_kind != "steer" and r.ts >= since
    ]
    return f"row:{users[0].id}" if users else None


def _close(core: Core, turn_id: int, status: str, *, reply: int | None, error: str | None) -> None:
    live = _registry(core).pop(turn_id, None)
    from agos_core.actions.turn_steps import kept as approvals_of

    kept = approvals_of(live.turn.activity if live else [])
    with transaction(core.db):
        found = repo.get_turn(core.db, turn_id)
        if found is not None:
            from agos_core.actions import rooms

            activity: Any = (
                ([a.as_json() for a in live.turn.activity] if live else [])
                if found.via == rooms.VIA
                else {"kept": kept}
            )
            chat_writes.set_turn(
                core.db,
                turn_id,
                status=status,
                reply_id=reply,
                activity=activity,
                error=error[:1_000] if error else None,
                ended_at=now(),
            )


async def shutdown(core: Core) -> None:
    """Stops following answers before the database closes. Hermes keeps running
    them; the next start picks them up again (`tick`)."""
    from agos_core.actions import rooms

    rooms.forget(core)
    state = _STATES.pop(id(core.db), None)
    if state is None:
        return
    for live in list(state.live.values()):  # a worker thread may still add one
        live.stop = True
    for task in state.tasks:
        task.cancel()
    if state.tasks:
        await asyncio.wait(state.tasks, timeout=5)


# ---- background: a room's lines not handed over yet ----------------------------------


def close_pre_hermes(core: Core) -> int:
    """Once, at the core's start: turns still open from before everything ran on
    Hermes (no `via`) can never end, so they close as failed. How many."""
    closed = 0
    for turn in repo.live_turns(core.db):
        if turn.via not in ("hermes", "room"):
            _close(core, turn.id, "failed", reply=None, error="the answer did not finish")
            closed += 1
    return closed


async def tick(core: Core) -> None:
    if core.engine is None:
        return
    # Every answer is Hermes's (its gateway answers and reports back itself, and
    # resumes a turn a crash cut: gateway/run_startup.py recover_interrupted_turns),
    # so AGOS guesses no dead turn here. What waits is only a room's line written
    # while nothing could take it.
    for chat in repo.chats_waiting(core.db):
        _spawn(core, start_turn(core, chat["workspace_id"], chat["id"]))
