"""A Hermes gateway turn in the AGOS chat: opened, finished, stopped, ended, and the
turns closed when no agent answered.

Owns: the turn lifecycle of Hermes-served chats.
Must not: send anything to Hermes or Telegram (gateway_mirror, gateway_commands).

Part of the Chat service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers). The bot's live state is the Channel service's
(services/channel/connections.py), where a chat lives in Hermes is hermes_addresses."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from typing import Any

from agos_core.actions.services.channel import gateway_platform, hermes_addresses
from agos_core.actions.services.chat import chat_writes
from agos_core.context import Core
from agos_core.db import chat_turns
from agos_core.db import chats as repo
from agos_core.db.connection import transaction
from agos_core.engine import doorbell

__all__ = [
    "ANSWERED",
    "NO_AGENT",
    "SETTLED_S",
    "STOPPED",
    "STOPPED_BY_HIM",
    "UNANSWERED_S",
    "WHY",
    "close_stale",
    "close_unanswered",
    "exit_status",
    "open_turn",
    "turn_ended",
    "turn_finish",
    "turn_start",
    "turn_stopped",
]

log = logging.getLogger("agos.hermes_channel")


def _open_turn(
    core: Core,
    workspace_id: str,
    chat_id: int,
    asked_up_to: int,
    *,
    speaker: str | None = None,
) -> int | None:
    """The chat's Hermes turn: the live one (his new message is now part of it) or a
    new one. None while an answer AGOS runs itself is still working in the chat."""
    from agos_core.actions import chat as chat_actions
    from agos_core.engine.chat import LiveTurn

    live = repo.live_turn(core.db, chat_id)
    if live is not None:
        if live.via != gateway_platform.ENGINE_HERMES:
            return None
        chat_turns.raise_asked_up_to(core.db, live.id, asked_up_to)
        return live.id
    turn_id = chat_writes.insert_turn(
        core.db,
        chat_id=chat_id,
        workspace_id=workspace_id,
        asked_up_to=asked_up_to,
        speaker=speaker,
    )
    chat_turns.run_via(core.db, turn_id, gateway_platform.ENGINE_HERMES)
    chat_actions._registry(core)[turn_id] = chat_actions._Live(
        turn=LiveTurn(turn_id=turn_id), speaker=speaker
    )
    return turn_id


def _asked_up_to(core: Core, chat_id: int, how: str) -> int:
    """A room's lines a starting answer answers (a Hermes chat keeps no lines: 0).
    Hermes starting on its own (a Kanban card's wake, a job's delivery) answers none
    of his lines, so one he just sent is still handed over after it."""
    row = repo.any_row(core.db, chat_id)
    if row is None or row["kind"] != "group":
        return 0
    last = repo.last_owner_line(core.db, chat_id)
    if how in ("store", "replace") or repo.live_turn(core.db, chat_id) is not None:
        return last
    return min(last, repo.answered_up_to(core.db, chat_id))


def open_turn(core: Core, workspace_id: str, chat_id: int) -> int | None:
    """The chat shows Hermes working on it now (its answer reports back itself)."""
    return _open_turn(core, workspace_id, chat_id, 0, speaker=_dm_speaker(core, chat_id))


def _dm_speaker(core: Core, chat_id: int) -> str | None:
    """A chat with a member (its DM, or a Session given to it): its answers are that
    agent's (its name on them)."""
    row = repo.any_row(core.db, chat_id)
    return (
        str(row["agent"]) if row is not None and row["kind"] != "group" and row["agent"] else None
    )


def turn_start(
    core: Core,
    workspace_id: str,
    address: str,
    session_id: str,
    said: str = "",
    how: str = "",
    sender: str = "",
) -> dict[str, Any]:
    """Hermes starts answering: the chat's turn (opened when his message came in),
    which the AGOS chat mirrors. AGOS adds nothing to what the agent reads: who it
    is and how it works are in the answering profile's SOUL.md, a conversation's
    own note (a member's chat, the learning conversation) is Hermes's channel
    prompt, given with the message (`take_inbox`)."""
    from agos_core.actions import learning, read_vs_act

    # Read vs act: a stranger's Telegram message marks its session; `untrusted` tells the plugin.
    read_vs_act.telegram_turn(core, workspace_id, address, sender, session_id)
    seen = {"untrusted": read_vs_act.source_of(core, workspace_id, address, session_id)}
    if address == learning.ADDRESS:  # the owner's decisions, for Hermes to learn from
        return learning.started(core, workspace_id)
    found = hermes_addresses.chat_at(core, workspace_id, address)
    if found is None:
        return {"turnId": None, **seen}
    chat_id = found
    del said  # what Hermes read is in its own transcript (what the chat shows)
    with transaction(core.db):
        turn_id = _open_turn(core, workspace_id, chat_id, _asked_up_to(core, chat_id, how))
    found_member = hermes_addresses.split_agos(address)
    speaker = found_member[1] if found_member else None
    if speaker is None:  # a chat with a member: it answers as that agent (its own Hermes)
        dm = repo.any_row(core.db, chat_id)
        speaker = dm["agent"] if dm is not None and dm["kind"] != "group" and dm["agent"] else None
    if speaker is None:
        # The Co-Founder's view in its SOUL.md stays current for its next conversation.
        # Not before this answer starts: Hermes built this turn's system prompt before
        # it asked (H: agent/turn_context.py, the prompt before the pre_llm_call hooks).
        _refresh_view_soon(core, workspace_id)
    return {
        "turnId": turn_id,
        "chatId": chat_id,
        # Who answers ("" = the Co-Founder): his Autonomy rules for that agent apply.
        "agent": speaker or "",
        **seen,
    }


def turn_finish(core: Core, workspace_id: str, turn_id: int, text: str) -> None:
    """Hermes reported the end of its answer: the AGOS chat shows Hermes's own
    transcript (AGOS changes nothing in it). How it ended comes after it
    (`turn_ended`); its model and tokens are Hermes's (its sessions, read by
    Hermes's usage analytics: engine.hermes_usage)."""
    from agos_core.actions import chat as chat_actions
    from agos_core.actions import learning
    from agos_core.engine.chat import LiveTurn

    if turn_id == learning.TURN_ID or turn_id < 0:
        return  # Hermes learned (or not) by itself / no AGOS turn: nothing to show
    turn = repo.get_turn(core.db, turn_id)
    if turn is None or turn.workspace_id != workspace_id:
        return
    if turn.status in ("starting", "running", "stopping"):
        live = chat_actions._registry(core).get(turn_id) or chat_actions._Live(
            turn=LiveTurn(turn_id=turn_id)
        )
        live.turn.output = text
        chat_actions._finish(core, workspace_id, turn.chat_id, turn_id, live)


# Hermes's interrupts the owner asked for (H: gateway/run.py _INTERRUPT_REASON_STOP,
# _INTERRUPT_REASON_RESET); any other reason is a failure.
STOPPED_BY_HIM = ("Stop requested", "Session reset requested")


def turn_stopped(core: Core, workspace_id: str, turn_id: int, reason: str) -> None:
    """Hermes interrupted the answer (its agent_loop_stopped hook: /stop, /new while
    it works) and sends no answer: the AGOS turn closes now, stopped (or failed),
    with Hermes's reason."""
    from agos_core.actions import chat as chat_actions

    turn = repo.get_turn(core.db, turn_id)
    if turn is None or turn.workspace_id != workspace_id:
        return
    if turn.status in ("starting", "running", "stopping"):
        status = "stopped" if reason in STOPPED_BY_HIM else "failed"
        chat_actions._close(core, turn_id, status, reply=None, error=reason or None)


# Hermes's turn_exit_reason (H: agent/turn_finalizer.py, its on_session_end hook):
# an answer, a stop, or a failure (in plain words).
ANSWERED = "text_response("
STOPPED = ("interrupted_by_user", "interrupted_by_system")
WHY = {
    "budget_exhausted": "It used up its run budget",
    "max_iterations_reached": "It reached its step limit",
    "all_retries_exhausted_no_response": "The model gave no answer, even after retries",
    "empty_response_exhausted": "The model kept giving empty answers",
    "pending_tool_result": "It stopped after a tool, without an answer",
    "context_compression_timeout": "Making the conversation shorter took too long",
    "session_persistence_failed": "The engine couldn't save the conversation",
}


# Workspaces whose Co-Founder view is being rebuilt: True = asked again meanwhile.
_views: dict[str, bool] = {}
_views_lock = threading.Lock()


def _refresh_view_soon(core: Core, workspace_id: str) -> None:
    """The Co-Founder view rebuilt on its own thread (one per workspace at a time; asks
    that come meanwhile make one more round)."""
    with _views_lock:
        if workspace_id in _views:
            _views[workspace_id] = True
            return
        _views[workspace_id] = False

    def run() -> None:
        from agos_core.actions import engine as engine_actions

        while True:
            try:
                engine_actions.refresh_cofounder_view(core, workspace_id)
            except Exception:
                log.exception("Co-Founder view of %s not refreshed", workspace_id)
            with _views_lock:
                if not _views.get(workspace_id):
                    _views.pop(workspace_id, None)
                    return
                _views[workspace_id] = False

    threading.Thread(target=run, name="agos-cofounder-view", daemon=True).start()


def exit_status(reason: str) -> tuple[str, str | None]:
    """(completed | stopped | failed, why) for Hermes's turn_exit_reason."""
    if not reason or reason.startswith(ANSWERED):
        return "completed", None
    if reason.startswith(STOPPED):
        return "stopped", None
    return "failed", WHY.get(reason.split("(", 1)[0], reason)


def turn_ended(core: Core, workspace_id: str, turn_id: int, reason: str) -> None:
    """Hermes ended the turn (its on_session_end hook, after the answer if there was
    one): a turn still open closes with Hermes's status; a failure is kept on the
    turn record with Hermes's reason (the chat and the Log show it)."""
    from agos_core.actions import chat as chat_actions

    turn = repo.get_turn(core.db, turn_id)
    if turn is None or turn.workspace_id != workspace_id:
        return
    status, why = exit_status(reason)
    if turn.status in ("starting", "running", "stopping"):
        chat_actions._close(core, turn_id, status, reply=None, error=why)
    elif status == "failed" and turn.status != "failed":
        with transaction(core.db):
            chat_writes.set_turn(core.db, turn_id, status="failed", error=(why or "")[:1_000])
    # Hermes's session moved on (a compression may have made a new one): kept.
    from agos_core.actions import chat_store

    chat_store.keep_chat(core, workspace_id, turn.chat_id)


# Hermes answers a message without starting its agent when it can't (no AI login: H:
# gateway/run_turn_runner.py returns its error before any agent exists). None of the
# hooks that report a turn back fire then (pre_llm_call, post_llm_call,
# on_session_end), so the AGOS turn would stay "working" with nothing coming.
# Hermes's own runtime status says when it answers nothing: the in-flight work it
# persists at every turn boundary, counted from the moment it takes a message in
# (gateway_state.json `active_agents` = H: gateway/run_shutdown.py _active_work_count:
# its running turns incl. ones whose agent is still starting, cron jobs, API runs),
# read with Hermes's own status functions (engine.gateway_status). Its turn lease
# can't tell: it exists only once an agent runs (H: agent/turn_facade_lease.py).
# A turn is closed only when Hermes has it (nothing of its chat waits in the inbox)
# and every live gateway of the workspace (the Co-Founder's, which serves the members,
# and a member's own) says "running", heartbeat fresh, nothing in flight, at two
# rounds in a row (a follow-up starts right after the turn before it). It closes with
# what Hermes kept: its answer when the transcript has one (an end lost on the way),
# else stopped (he asked to stop) or failed with why. Hermes's own words (its error)
# are already in the chat (`platform_said`) or his Telegram.
UNANSWERED_S = 60
SETTLED_S = 30
NO_AGENT = (
    "The engine answered without starting an agent (for example, this workspace has no "
    "AI login), so this message gets no answer."
)
_IDLE_SEEN: dict[int, dict[int, float]] = {}


def close_unanswered(core: Core, now: float | None = None) -> list[int]:
    """The AGOS turns Hermes no longer answers, closed (their ids)."""
    from agos_core.actions import rooms
    from agos_core.db import hermes_chats

    seen = _IDLE_SEEN.setdefault(id(core.db), {})
    if core.engine is None:
        return []
    at = time.time() if now is None else now
    waiting: dict[str, list[tuple[int, float]]] = {}
    for r in chat_turns.live_records(core.db):
        started = hermes_chats.epoch(str(r["started_at"]))
        if r["via"] == rooms.VIA or started > at - UNANSWERED_S:
            continue  # a room's turn is AGOS's room driver's; a new one Hermes picks up
        chat = repo.any_row(core.db, int(r["chat"]))
        if chat is not None and not repo.queued(core.db, chat):
            waiting.setdefault(str(r["workspace_id"]), []).append((int(r["id"]), started))
    for gone in set(seen) - {t for turns in waiting.values() for t, _ in turns}:
        seen.pop(gone, None)
    closed: list[int] = []
    for workspace_id, turns in waiting.items():
        if not _answers_nothing(core, workspace_id):
            for turn_id, _ in turns:
                seen.pop(turn_id, None)
            continue
        for turn_id, started in turns:
            first = seen.setdefault(turn_id, at)
            if at - first < SETTLED_S:
                continue  # Hermes seen idle once: closed if it still is next round
            seen.pop(turn_id, None)
            if _close_unanswered(core, workspace_id, turn_id, started):
                closed.append(turn_id)
    return closed


def _close_unanswered(core: Core, workspace_id: str, turn_id: int, started: float) -> bool:
    from agos_core.actions import chat as chat_actions
    from agos_core.engine.chat import LiveTurn

    turn = repo.get_turn(core.db, turn_id)
    if turn is None or turn.status not in ("starting", "running", "stopping"):
        return False
    if _answer_kept(core, turn.chat_id, started):
        live = chat_actions._registry(core).get(turn_id) or chat_actions._Live(
            turn=LiveTurn(turn_id=turn_id)
        )
        chat_actions._finish(core, workspace_id, turn.chat_id, turn_id, live)
    elif turn.status == "stopping":
        chat_actions._close(core, turn_id, "stopped", reply=None, error=None)
    else:
        chat_actions._close(core, turn_id, "failed", reply=None, error=NO_AGENT)
    log.info("turn %s closed: Hermes answers nothing in %s", turn_id, workspace_id)
    return True


def _answers_nothing(core: Core, workspace_id: str) -> bool:
    """Hermes's own word that nothing is in flight for this workspace now: its
    gateway runs (fresh heartbeat) with no work, and so does any member's own."""
    assert core.engine is not None
    root = core.engine.root(workspace_id)
    homes = [root]
    with contextlib.suppress(OSError):
        homes += sorted(
            p.parent for p in (root / "profiles").glob("*/gateway_state.json") if p.is_file()
        )
    for home in homes:
        try:
            gateway = core.engine.gateway_status(home, fresh=True)
        except Exception:  # noqa: BLE001 — Hermes can't tell: nothing is closed on a guess
            return False
        live = bool(gateway.get("live")) and gateway.get("pid") is not None
        if home != root and not live:
            continue  # a member without its own gateway: the Co-Founder's serves it
        record = gateway.get("record")
        if not live or gateway.get("stale") or not isinstance(record, dict):
            return False
        if record.get("gateway_state") != "running":
            return False  # starting (it resumes cut turns itself), draining, stopped
        in_flight = record.get("active_agents")
        if not isinstance(in_flight, int) or isinstance(in_flight, bool) or in_flight != 0:
            return False
    return True


def _answer_kept(core: Core, chat_id: int, since: float) -> bool:
    """Hermes's transcript of the chat has an answer written after `since`."""
    from agos_core.db import hermes_chats

    chat = repo.any_row(core.db, chat_id)
    store = hermes_chats.store()
    where = repo.where_of(core.db, chat) if chat is not None else None
    if store is None or where is None:
        return False
    return any(r.role == "assistant" and r.ts >= since for r in store.transcript(where).rows)


def close_stale(core: Core) -> int:
    """Hermes turns that never reported their end are closed as failed."""
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(seconds=gateway_platform.STALE_AFTER_S)).isoformat(
        timespec="milliseconds"
    )
    closed = chat_turns.fail_unreported(
        core.db,
        gateway_platform.ENGINE_HERMES,
        cutoff.replace("+00:00", "Z"),
        "The answer in Telegram never reported back.",
    )
    if closed:  # rare: every open live view looks once
        doorbell.ring(doorbell.LIVE)
    return closed
