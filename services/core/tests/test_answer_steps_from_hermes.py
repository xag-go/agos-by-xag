"""An answer's thoughts, notes and helpers are Hermes's (its session's rows); AGOS's
turn record keeps only the approvals asked (step 26, audit B-1)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from split_parts import whole_text

from agos_core.actions.services.chat.answer_steps import steps_between
from agos_core.actions.turn_steps import join, kept
from agos_core.db import hermes_chats as hc
from agos_core.db.connection import open_database
from agos_core.db.migrations import MIGRATIONS
from agos_core.engine.chat import LiveTurn

_STRIP = next(m for m in MIGRATIONS if "-- agos: chat_turns.activity keeps only" in m)
SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"


@pytest.fixture(autouse=True)
def _plain_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.engine import hermes_redact

    monkeypatch.setattr(hermes_redact, "mask_many", lambda texts: list(texts))


def _row(n: int, role: str, content: str = "", **kw: Any) -> hc.Row:
    return hc.Row(id=n, profile="p", row=n, session="s", role=role, content=content, ts=n, **kw)


def _call(call_id: str, name: str, args: dict[str, Any]) -> str:
    return json.dumps([{"id": call_id, "function": {"name": name, "arguments": json.dumps(args)}}])


def test_thoughts_and_helpers_are_read_from_hermess_rows() -> None:
    rows = [
        _row(1, "user", "do it"),
        _row(
            2,
            "assistant",
            "<think>Let me look first.</think>",
            tool_calls=_call("a", "read_file", {"path": "x"}),
        ),
        _row(3, "tool", "file text", tool_call_id="a"),
        _row(
            4, "assistant", "", tool_calls=_call("b", "delegate_task", {"goal": "check the docs"})
        ),
        _row(
            5,
            "tool",
            json.dumps({"results": [{"status": "completed", "summary": "docs are fine"}]}),
            tool_call_id="b",
        ),
        _row(6, "assistant", "All done."),
    ]
    steps = steps_between(rows)
    assert [(s["kind"], s["title"]) for s in steps] == [
        ("thinking", "Thought"),
        ("tool", "Read a file"),
        ("tool", "Asked a helper"),
        ("subagent", "Started a helper"),
        ("subagent", "A helper finished"),
    ]
    assert steps[0]["detail"] == "Let me look first."
    assert steps[3]["detail"] == "check the docs"
    assert steps[4]["detail"] == "docs are fine" and steps[4]["status"] == "done"


def test_a_failed_helper_shows_failed() -> None:
    rows = [
        _row(
            1,
            "assistant",
            "",
            tool_calls=_call("b", "delegate_task", {"tasks": [{"goal": "g1"}, {"goal": "g2"}]}),
        ),
        _row(
            2,
            "tool",
            json.dumps(
                {
                    "results": [
                        {"status": "completed", "summary": "ok"},
                        {"status": "timeout", "error": "slow"},
                    ]
                }
            ),
            tool_call_id="b",
        ),
    ]
    helpers = [s for s in steps_between(rows) if s["kind"] == "subagent"]
    assert [(h["title"], h["detail"], h.get("status", "done")) for h in helpers] == [
        ("Started a helper", "g1", "done"),
        ("Started a helper", "g2", "done"),
        ("A helper finished", "ok", "done"),
        ("A helper finished", "slow", "failed"),
    ]


def test_the_record_keeps_only_the_approvals_in_place() -> None:
    live = LiveTurn(turn_id=7)
    for event in (
        {"event": "reasoning.available", "text": "thinking it over"},
        {"event": "tool.started", "tool": "terminal", "preview": "ls"},
        {"event": "tool.completed", "tool": "terminal"},
        {"event": "message.interim", "text": "a note"},
        {"event": "subagent.start", "goal": "g"},
        {"event": "approval.request", "command": "rm -rf x", "description": "delete"},
        {"event": "approval.responded", "choice": "once"},
        {"event": "subagent.complete", "summary": "s"},
    ):
        live.apply(event)
    record = kept(live.activity)
    assert [(k["kind"], k["at"]) for k in record] == [("approval", 1)]
    # Shown back between Hermes's own steps: after the first tool, before the next.
    hermes = [
        {"kind": "thinking", "title": "Thought", "detail": "t"},
        {"kind": "tool", "title": "Ran a command", "detail": "ls"},
        {"kind": "thinking", "title": "Thought", "detail": "u"},
        {"kind": "tool", "title": "Ran a command", "detail": "rm"},
    ]
    shown = join(7, hermes, record)
    assert [s["kind"] for s in shown] == ["thinking", "tool", "thinking", "approval", "tool"]
    assert [s["id"] for s in shown] == [f"7-{i}" for i in range(1, 6)]


def _turn(db: sqlite3.Connection, activity: Any) -> int:
    cursor = db.execute(
        """INSERT INTO chat_turns (chat_id, workspace_id, status, asked_up_to, activity, started_at)
           VALUES (1, 'w', 'completed', 0, ?, '2026-01-01T00:00:00.000Z')""",
        (json.dumps(activity),),
    )
    return int(cursor.lastrowid or 0)


def test_the_old_copies_go_and_the_approvals_stay(tmp_path: Path) -> None:
    db = open_database(tmp_path / "agos.db")
    db.execute("PRAGMA foreign_keys = OFF")
    approval = {"kind": "approval", "title": "Allowed once", "detail": "rm", "at": 2}
    mixed = _turn(
        db,
        {
            "kept": [
                {"kind": "thinking", "title": "Thought", "detail": "t", "at": 0},
                {"kind": "note", "title": "Note", "detail": "n", "at": 1},
                approval,
                {"kind": "subagent", "title": "A helper finished", "detail": "s", "at": 3},
            ]
        },
    )
    room = _turn(db, [{"kind": "thinking", "title": "Thought", "detail": "room"}])
    for _ in range(2):  # once, and again: nothing more changes
        db.executescript(_STRIP)
        got = json.loads(
            db.execute("SELECT activity FROM chat_turns WHERE id = ?", (mixed,)).fetchone()[0]
        )
        assert got == {"kept": [approval]}
    untouched = db.execute("SELECT activity FROM chat_turns WHERE id = ?", (room,)).fetchone()[0]
    assert json.loads(untouched) == [{"kind": "thinking", "title": "Thought", "detail": "room"}]


def test_no_copy_of_hermess_steps_comes_back() -> None:
    """Guard: a turn record's `kept` is written from turn_steps.kept (approvals alone),
    and nothing outside the step reader builds thoughts or helpers for a record."""
    chat = whole_text("actions/chat.py")  # the facade and its parts (services/chat/)
    writes = re.findall(r"activity=\{\"kept\": (\w+)\}", chat)
    assert writes and set(writes) == {"kept"}, writes
    assert chat.count("approvals_of(") == 2
    assert "kept.append" not in chat
    steps = (SRC / "actions" / "turn_steps.py").read_text()
    assert 'item.kind == "approval"' in steps
    # Read back from Hermes: what an answer did between its tool calls.
    reader = (SRC / "actions" / "services" / "chat" / "answer_steps.py").read_text()
    assert '"kind": "thinking"' in reader and '"kind": "subagent"' in reader
