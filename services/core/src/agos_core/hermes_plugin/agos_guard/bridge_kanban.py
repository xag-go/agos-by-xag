"""Kanban card runs in this gateway: a card's run joined to its AGOS chat, its
claim and its completion told to AGOS, and a run that did nothing said so.

Owns: Hermes's kanban hooks on AGOS's side.
Must not: change the board (Hermes's kanban does).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import Any

__all__ = [
    "AUTOMATION_KEY",
    "NOTHING_DONE",
    "RUN_MARK",
    "kanban_claimed",
    "kanban_completed",
]

try:
    from . import bridge_core
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]


log = logging.getLogger("agos.bridge")


# An automation's run: its cards carry Hermes idempotency keys
# `agos-automation:<automation>:<run>:<source>:<step>` (engine/automation_run.py).
AUTOMATION_KEY = "agos-automation:"
# Our mark on a run card's subscription (Hermes keeps it in delivery_metadata):
# "last" = a last card of its run, "step" = any other card of it.
RUN_MARK = "agos_run"
# A handoff that says the run had nothing to do (the owner's "WALO", Hermes's [SILENT],
# a step its "Only if" lines skipped: step_gate.py).
NOTHING_DONE = ("WALO", "[SILENT]", "AGOS-SKIPPED:")


def _run_card(conn: Any, task_id: str) -> str:
    """'last' / 'step' for a card of an automation's run, '' for any other card.
    A last card = no card of the SAME run waits on it (the next run's first cards
    wait on this run's last ones, so they don't count)."""
    from hermes_cli import kanban_db as kb  # type: ignore[import-not-found]

    task = kb.get_task(conn, task_id)
    key = str(getattr(task, "idempotency_key", "") or "")
    if not key.startswith(AUTOMATION_KEY):
        return ""
    run = ":".join(key.split(":")[:3]) + ":"
    for child in kb.child_ids(conn, task_id):
        other = kb.get_task(conn, child)
        if str(getattr(other, "idempotency_key", "") or "").startswith(run):
            return "step"
    return "last"


def _quiet(conn: Any, kbn: Any, task_id: str) -> bool:
    """The card's `notify+wake` subscriptions become `wake` only: no passive line, the
    woken Co-Founder's turn is the one message. True when any chat follows the card."""
    subs = kbn.list_notify_subs(conn, task_id)
    for sub in subs:
        if (sub.get("delivery_mode") or "notify") != "notify+wake":
            continue
        kbn.add_notify_sub(
            conn,
            task_id=task_id,
            platform=str(sub["platform"]),
            chat_id=str(sub["chat_id"]),
            thread_id=sub.get("thread_id") or None,
            delivery_mode="wake",
        )
    return bool(subs)


def kanban_claimed(task_id: str = "", board: Any = None, profile_name: str = "", **_: Any) -> None:
    """A card starts (Hermes's dispatcher claimed it). Hermes's own Kanban notifier
    tells the owner what becomes of it: a card no chat follows yet (made on the board,
    by AGOS, by an automation) gets the Co-Founder's conversation as its subscriber, the
    same way Hermes subscribes the chat a card was made in (`notify+wake`: the passive
    line, then the Co-Founder's own turn about it). AGOS's bridge file says where that
    conversation is; no destination there = nothing is subscribed.

    An automation's run speaks once (owner, 2026-10-19): its cards are subscribed with
    `wake` only (no passive line: the Co-Founder's one turn is the message), and
    kanban_completed below drops the subscription of every card that ends well except
    a last card with real work. So the owner hears the run's end when it did something,
    and any card of it that blocks, gives up, crashes or times out.

    Every card speaks once (owner, 2026-10-19): Hermes's own `notify+wake` (a card
    made in a chat) sends its plain "✔ Kanban t_... done" line AND wakes the Co-Founder,
    two messages for one card. The owner hears only the Co-Founder: those subscriptions
    become `wake` here (and again when the card ends, see _quiet)."""
    found: Any = (bridge_core.bridge() or {}).get("notify")
    if not task_id or not isinstance(found, dict) or not found.get("chatId"):
        return
    try:
        from hermes_cli import kanban_db_connect as kbc
        from hermes_cli import kanban_db_notify as kbn

        conn = kbc.connect(board=board)
        try:
            if _quiet(conn, kbn, str(task_id)):
                return  # a chat already follows it (Hermes's own subscription wins)
            run = ""
            with contextlib.suppress(Exception):  # unreadable = an ordinary card
                run = _run_card(conn, str(task_id))
            extra: dict[str, Any] = {"delivery_mode": "wake"}
            if run:
                extra["delivery_metadata"] = {RUN_MARK: run}
            kbn.add_notify_sub(
                conn,
                task_id=str(task_id),
                platform=str(found.get("platform") or "agos"),
                chat_id=str(found["chatId"]),
                thread_id=str(found.get("threadId") or "") or None,
                user_id=str(found.get("userId") or "") or None,
                chat_type=str(found.get("chatType") or "dm"),
                # This gateway's own profile delivers it (Hermes's hook says which).
                notifier_profile=str(profile_name or "default"),
                **extra,
            )
        finally:
            conn.close()
    except Exception as error:  # noqa: BLE001 — never in the dispatcher's way
        log.warning("AGOS bridge: card %s not subscribed: %s", task_id, error)
        bridge_core._broken(
            bridge_core._name_of(error, "hermes_cli.kanban_db_notify.add_notify_sub"), error
        )


def _nothing_done(summary: Any) -> bool:
    text = str(summary or "").lstrip(" \t\n*_`>#-").upper()
    return text.startswith(NOTHING_DONE)


def kanban_completed(task_id: str = "", board: Any = None, summary: Any = "", **_: Any) -> None:
    """A card is done (Hermes's hook, in the process that completed it). A card of an
    automation's run that we subscribed stops being followed when its end needs no
    word: any step but the last, and a last card whose handoff says nothing was done.
    Hermes's notifier then has no subscriber to tell, so the Co-Founder isn't woken."""
    if not task_id:
        return
    try:
        from hermes_cli import kanban_db_connect as kbc
        from hermes_cli import kanban_db_notify as kbn

        conn = kbc.connect(board=board)
        try:
            _quiet(conn, kbn, str(task_id))  # a card claimed before this rule
            for sub in kbn.list_notify_subs(conn, str(task_id)):
                mark = (sub.get("delivery_metadata") or {}).get(RUN_MARK)
                if mark == "step" or (mark == "last" and _nothing_done(summary)):
                    kbn.remove_notify_sub(
                        conn,
                        task_id=str(task_id),
                        platform=str(sub["platform"]),
                        chat_id=str(sub["chat_id"]),
                        thread_id=sub.get("thread_id") or None,
                    )
        finally:
            conn.close()
    except Exception as error:  # noqa: BLE001 — never in the worker's way
        log.warning("AGOS bridge: card %s still followed: %s", task_id, error)
        bridge_core._broken(
            bridge_core._name_of(error, "hermes_cli.kanban_db_notify.remove_notify_sub"), error
        )
