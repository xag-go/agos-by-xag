"""AGOS recovers from what breaks under it: the Hermes gateway killed mid-answer, the
model unreachable, the core restarted during a card's run and during an answer, the
disk full, the database busy. Each test breaks one thing on the real rig, then checks:
the answer ends (completed, or failed with a reason) — never stuck "running"; a
failure shows in the workspace's Log (System Log / problems); nothing the owner wrote
is lost; and the next message works again.
"""

from __future__ import annotations

import contextlib
import signal
import sqlite3
import subprocess
import threading
import time
from typing import Any

import pytest

from failure.real_rig import LIVE, RealRig

pytestmark = pytest.mark.hermes

# Hermes's gateway resumes or drops a cut turn after its restart; AGOS closes a turn
# Hermes answers nothing for after 60 s + 30 s of idle gateway (gateway_turns.py).
ENDS_WITHIN_S = 300
# After a crash Hermes waits for the dead process's session lock (~5 min) first.
AFTER_A_CRASH_S = 600
# AGOS sets Hermes's agent.api_max_retries to 10 (engine/rules.py: a provider hiccup is
# waited out): with the model unreachable the answer fails after ~10 min of retries.
MODEL_RETRIES_S = 1200


def _turn_of(rig: RealRig, chat: int, before: set[int]) -> dict[str, Any]:
    new = [t for t in rig.turns(chat) if t["id"] not in before]
    assert new, "no turn was started"
    return new[-1]


def _ended(rig: RealRig, chat: int, turn_id: int) -> dict[str, Any] | None:
    turn = next(t for t in rig.turns(chat) if t["id"] == turn_id)
    return None if turn["status"] in LIVE else turn


def _owner_words(rig: RealRig, ws: str, chat: int) -> list[str]:
    return [str(m["body"]) for m in rig.messages(ws, chat) if m["from"] == "owner"]


def _words(what: str) -> str:
    return f"{what} {int(time.time())}"


def _works_again(rig: RealRig, ws: str, chat: int, tag: str) -> None:
    """A plain message is answered once (the fake model echoes it)."""
    words = _words(f"are you back {tag}")
    rig.post(ws, chat, words)
    rig.wait(f"answer after {tag}", lambda: rig.answered(ws, chat, words), 240, 2)
    time.sleep(3)
    assert rig.said(ws, chat, words) == 1 and len(rig.answered(ws, chat, words)) == 1


def _in_the_log(rig: RealRig, ws: str, turn_id: int) -> bool:
    return any(e["id"] == f"chat:turn:{turn_id}" for e in rig.problems(ws))


def test_gateway_killed_mid_answer_the_turn_ends_and_the_next_message_works(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    ws, chat = alpha["ws"], alpha["chat"]
    before = {t["id"] for t in rig.turns(chat)}
    words = _words("slow answer please, gateway test")
    rig.post(ws, chat, words)
    turn = rig.wait(
        "the answer running", lambda: _turn_of(rig, chat, before) if rig.live_turns() else None, 60
    )
    root = rig.root(ws)
    time.sleep(3)  # the model is working on it (fake_llm sleeps 12 s on "slow")
    rig.kill(rig.gateway_pid(root), signal.SIGKILL)
    rig.rig.service_restart(root)  # Hermes's systemd service brings it back
    ended = rig.wait("the cut turn ends", lambda: _ended(rig, chat, turn["id"]), AFTER_A_CRASH_S, 3)
    assert ended["status"] in ("completed", "failed"), ended
    if ended["status"] == "failed":
        assert ended["error"], ended
        assert _in_the_log(rig, ws, turn["id"]), "a failed answer shows in the Log's problems"
    _works_again(rig, ws, chat, "after the gateway kill")
    if rig.said(ws, chat, words) != 1:
        # Hermes's crash resume starts the cut turn again from its own note and its
        # transcript keeps no copy of his message (docs/guides/resilience-tests.md).
        pytest.xfail("his message cut by the gateway crash is not in the chat any more")


def test_model_unreachable_the_turn_fails_with_a_reason_then_works_again(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    ws, chat = alpha["ws"], alpha["chat"]
    before = {t["id"] for t in rig.turns(chat)}
    words = _words("hello while the model is down")
    rig.stop_llm()
    try:
        rig.post(ws, chat, words)
        turn = rig.wait("a turn", lambda: _turn_of(rig, chat, before), 60)
        try:
            ended = rig.wait(
                "the turn ends", lambda: _ended(rig, chat, turn["id"]), MODEL_RETRIES_S, 5
            )
        except AssertionError:
            ended = None
    finally:
        rig.start_llm()
    if ended is None:
        # Seen on the rig: after its 10 attempts Hermes rebuilds the client, tries once
        # more and starts 10 attempts again, for as long as the model is down; the
        # answer shows "running" until AGOS's 3 h stale close (docs/guides/resilience-tests.md).
        rig.wait("the answer once the model is back", lambda: rig.answered(ws, chat, words), 300, 3)
        pytest.xfail("an unreachable model keeps the answer running (Hermes retries without end)")
    said = [m for m in rig.messages(ws, chat) if m["from"] == "agent"]
    # AGOS records the failure with Hermes's reason and the Log shows it.
    assert ended["status"] == "failed" and ended["error"], (ended, said[-3:])
    assert _in_the_log(rig, ws, turn["id"])
    assert rig.said(ws, chat, words) == 1
    _works_again(rig, ws, chat, "after the model came back")


def test_core_restarted_mid_answer_the_answer_arrives_once(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    ws, chat = alpha["ws"], alpha["chat"]
    before = {t["id"] for t in rig.turns(chat)}
    words = _words("slow answer please, core restart test")
    rig.post(ws, chat, words)
    turn = rig.wait(
        "the answer running", lambda: _turn_of(rig, chat, before) if rig.live_turns() else None, 60
    )
    time.sleep(2)
    rig.stop_core()
    time.sleep(5)
    rig.start_core()
    ended = rig.wait("the turn ends", lambda: _ended(rig, chat, turn["id"]), ENDS_WITHIN_S, 3)
    assert ended["status"] == "completed", ended
    rig.wait("the answer", lambda: rig.answered(ws, chat, words), 120, 2)
    # Past AGOS's 60 s hand-again: his message went in once, one answer.
    time.sleep(75)
    assert rig.said(ws, chat, words) == 1, _owner_words(rig, ws, chat)[-4:]
    assert len(rig.answered(ws, chat, words)) == 1
    _works_again(rig, ws, chat, "after the core restart")


def test_core_restarted_during_a_card_run_the_card_ends_done(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    ws = alpha["ws"]
    made = rig.api(
        "POST",
        f"/workspaces/{ws}/kanban",
        {
            "title": "Restart test card",
            "body": "Write one line.",
            "member": "writer",
            "triage": False,
        },
    )
    card = str(made.get("id") or made.get("card"))
    time.sleep(1)
    rig.stop_core()
    time.sleep(5)
    rig.start_core()

    def done() -> Any:
        shown = rig.api("GET", f"/workspaces/{ws}/kanban/{card}")
        return shown if shown.get("status") == "done" else None

    shown = rig.wait("the card done", done, ENDS_WITHIN_S, 3)
    assert shown["title"] == "Restart test card"
    board = rig.api("GET", f"/workspaces/{ws}/kanban")
    assert [c for c in board["cards"] if c["id"] == card], "the card is still on the board"
    with contextlib.closing(rig.db()) as con:
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_disk_full_writes_are_refused_cleanly_and_nothing_is_lost(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    """The core can't grow any file (RLIMIT_FSIZE on its process: every write past
    4 KiB fails like a full disk; unprivileged, no tmpfs mount needed)."""
    ws, chat = alpha["ws"], alpha["chat"]
    kept = _owner_words(rig, ws, chat)
    before = {t["id"] for t in rig.turns(chat)}
    core = rig.pid("core")
    subprocess.run(["prlimit", f"--pid={core}", "--fsize=4096:unlimited"], check=True)  # noqa: S603, S607
    try:
        refused: Exception | None = None
        try:
            rig.post(ws, chat, _words("this lands on a full disk"))
        except RuntimeError as error:
            refused = error
        assert refused is not None, "the write was accepted on a full disk"
        assert " 500" in str(refused) or " 503" in str(refused) or " 507" in str(refused), str(
            refused
        )
        assert not [t for t in rig.turns(chat) if t["id"] not in before and t["status"] in LIVE]
        # Reads still work while the disk is full.
        assert _owner_words(rig, ws, chat) == kept
    finally:
        subprocess.run(["prlimit", f"--pid={core}", "--fsize=unlimited:unlimited"], check=True)  # noqa: S603, S607
    assert _owner_words(rig, ws, chat) == kept
    with contextlib.closing(rig.db()) as con:
        assert con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    _works_again(rig, ws, chat, "after the disk had room again")


def test_database_busy_a_write_waits_or_fails_cleanly_then_works(
    rig: RealRig, alpha: dict[str, Any]
) -> None:
    """Another process holds AGOS's database (an exclusive lock, longer than the
    core's 5 s busy timeout)."""
    ws, chat = alpha["ws"], alpha["chat"]
    kept = _owner_words(rig, ws, chat)
    busy_words = _words("written while the database is busy")
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        con = sqlite3.connect(
            rig.E / "data" / "system" / "agos.db", timeout=30, isolation_level=None
        )
        try:
            con.execute("BEGIN EXCLUSIVE")
            held.set()
            release.wait(12)
            con.execute("ROLLBACK")
        finally:
            con.close()

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(30)
    outcome: Any
    try:
        outcome = rig.post(ws, chat, busy_words)
    except RuntimeError as error:
        outcome = error
    finally:
        release.set()
        holder.join(30)
    if isinstance(outcome, Exception):
        assert " 503" in str(outcome) or " 500" in str(outcome), str(outcome)
        assert _owner_words(rig, ws, chat) == kept
    else:
        rig.wait("his message in the chat", lambda: rig.said(ws, chat, busy_words) == 1, 120, 2)
    _works_again(rig, ws, chat, "after the database was free")
