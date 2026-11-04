"""A turn Hermes answered without its agent (no AI login: none of the hooks that report
back fire) is closed once Hermes's own runtime status says it answers nothing
(gateway_state.json `active_agents` 0, gateway running, heartbeat fresh) at two rounds
in a row; never while Hermes runs something, starts up, hasn't taken the message,
or can't tell."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture

from agos_core.actions import hermes_channel
from agos_core.actions.services.chat import gateway_turns
from agos_core.db import chats as chats_repo
from agos_core.db.rows import now as iso_now
from agos_core.engine.hermes import HermesEngine

ROUND = 60.0  # AGOS's idle round


def _iso(seconds_ago: float) -> str:
    from datetime import UTC, datetime

    when = datetime.fromtimestamp(time.time() - seconds_ago, UTC)
    return when.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _open_turn(
    core: Any, ws: str, seconds_ago: float = 600, via: str = "hermes", status: str = "running"
) -> tuple[int, int]:
    chat = chats_repo.insert_chat(core.db, workspace_id=ws, title="Ads", channel="web")
    turn = chats_repo.insert_turn(
        core.db, chat_id=chat, workspace_id=ws, asked_up_to=0, speaker=None
    )
    core.db.execute(
        "UPDATE chat_turns SET status = ?, started_at = ?, via = ? WHERE id = ?",
        (status, _iso(seconds_ago), via, turn),
    )
    return int(turn), int(chat)


def _status(**said: Any) -> dict[str, Any]:
    return {
        "pid": said.pop("pid", 4242),
        "live": said.pop("live", True),
        "stale": said.pop("stale", False),
        "record": {"gateway_state": "running", "active_agents": 0, **said},
    }


def _hermes_says(
    monkeypatch: pytest.MonkeyPatch,
    by_home: Callable[[Path], dict[str, Any]] | None = None,
    **said: Any,
) -> None:
    def gateway_status(self: Any, home: Path, fresh: bool = False) -> dict[str, Any]:
        if by_home is not None:
            return by_home(Path(home))
        return _status(**dict(said))

    monkeypatch.setattr(HermesEngine, "gateway_status", gateway_status)


def _rounds(core: Any, n: int = 2) -> list[int]:
    """`n` idle rounds, a minute apart: what got closed."""
    start = time.time()
    closed: list[int] = []
    for i in range(n):
        closed += hermes_channel.close_unanswered(core, now=start + i * ROUND)
    return closed


def _turn(core: Any, turn: int) -> tuple[str, str | None]:
    row = core.db.execute("SELECT status, error FROM chat_turns WHERE id = ?", (turn,)).fetchone()
    return str(row["status"]), row["error"]


def test_a_turn_hermes_answers_nothing_for_is_closed_with_why(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)
    _hermes_says(monkeypatch)
    start = time.time()
    assert hermes_channel.close_unanswered(core, now=start) == []  # seen idle once
    assert _turn(core, turn)[0] == "running"
    assert hermes_channel.close_unanswered(core, now=start + ROUND) == [turn]
    assert _turn(core, turn) == ("failed", hermes_channel.NO_AGENT)
    assert _rounds(core) == []  # once


def test_an_answer_hermes_kept_closes_it_as_answered(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The end got lost on the way (a crash, a restart): Hermes's transcript has it."""
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)
    _hermes_says(monkeypatch)
    monkeypatch.setattr(gateway_turns, "_answer_kept", lambda core, chat_id, since: True)
    assert _rounds(core) == [turn]
    assert _turn(core, turn) == ("completed", None)


def test_a_stop_he_asked_for_closes_as_stopped(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws, status="stopping")
    _hermes_says(monkeypatch)
    assert _rounds(core) == [turn]
    assert _turn(core, turn) == ("stopped", None)


@pytest.mark.parametrize(
    "said",
    [
        {"active_agents": 1},  # Hermes is answering (or starting an agent): it reports back
        {"gateway_state": "starting"},  # it resumes the turns a crash cut by itself
        {"gateway_state": "draining"},
        {"live": False},  # not running: nothing to read
        {"pid": None},
        {"stale": True},  # no heartbeat: its record can't be trusted
        {"active_agents": None},
        {"active_agents": "0"},
        {"active_agents": True},
    ],
)
def test_nothing_is_closed_unless_hermes_says_it_answers_nothing(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    said: dict[str, Any],
) -> None:
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)
    _hermes_says(monkeypatch, **said)
    assert _rounds(core, 3) == []
    assert _turn(core, turn) == ("running", None)


def test_idle_once_then_busy_starts_over(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A follow-up Hermes starts right after the turn before it: one idle look is not
    enough, and a busy round in between starts the count again."""
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)
    start = time.time()
    _hermes_says(monkeypatch)
    assert hermes_channel.close_unanswered(core, now=start) == []
    _hermes_says(monkeypatch, active_agents=1)
    assert hermes_channel.close_unanswered(core, now=start + ROUND) == []
    _hermes_says(monkeypatch)
    assert hermes_channel.close_unanswered(core, now=start + 2 * ROUND) == []
    assert hermes_channel.close_unanswered(core, now=start + 3 * ROUND) == [turn]


def test_a_message_hermes_has_not_taken_is_left(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    turn, chat = _open_turn(core, ws)
    item = core.db.execute(
        "INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)"
        " VALUES (?, ?, 'salam', 'message', ?)",
        (ws, f"agos:{chat}", iso_now()),
    ).lastrowid
    _hermes_says(monkeypatch)
    assert _rounds(core) == []
    core.db.execute("UPDATE hermes_inbox SET done_at = ? WHERE id = ?", (iso_now(), item))
    assert _rounds(core) == [turn]


def test_a_new_turn_and_a_rooms_turn_are_left_to_hermes(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agos_core.actions import rooms

    _client, core, _cron, ws = env
    fresh, _ = _open_turn(core, ws, seconds_ago=5)  # Hermes picks a message up at once
    room, _ = _open_turn(core, ws, via=rooms.VIA)  # the room driver's own
    _hermes_says(monkeypatch)
    start = time.time()
    assert hermes_channel.close_unanswered(core, now=start) == []
    assert hermes_channel.close_unanswered(core, now=start + 30) == []
    assert _turn(core, fresh)[0] == "running" and _turn(core, room)[0] == "running"


def test_a_members_own_gateway_at_work_keeps_it_open(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)
    member = core.engine.root(ws) / "profiles" / "a-writer"
    member.mkdir(parents=True)
    (member / "gateway_state.json").write_text("{}")
    root = core.engine.root(ws)
    _hermes_says(
        monkeypatch,
        by_home=lambda home: _status() if home == root else _status(active_agents=1),
    )
    assert _rounds(core) == []
    # Its own gateway stopped: the Co-Founder's serves it, and says nothing is in flight.
    _hermes_says(
        monkeypatch,
        by_home=lambda home: _status() if home == root else _status(live=False, pid=None),
    )
    assert _rounds(core) == [turn]


def test_hermes_unreadable_closes_nothing(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    turn, _chat = _open_turn(core, ws)

    def broken(self: Any, home: Any, fresh: bool = False) -> Any:
        raise RuntimeError("hermes did not answer")

    monkeypatch.setattr(HermesEngine, "gateway_status", broken)
    assert _rounds(core) == []
    assert _turn(core, turn)[0] == "running"


def test_the_idle_round_runs_it() -> None:
    import inspect

    from agos_core.actions import idle

    assert "close_unanswered" in inspect.getsource(idle.chores)
