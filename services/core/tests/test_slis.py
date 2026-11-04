"""The measured SLIs of docs/compliance/sre.md, stored in `slo_samples` (migration
147, actions/slis.py) for scripts/slo.py's monthly report: the page probe (S1), a
chat's first visible output (S2), the core's health probe (S3) and a scheduled
run's due-vs-start delay (S4, from Hermes's own dispatch stamp)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agos_core.actions import slis
from agos_core.db.connection import open_database
from agos_core.db.workspaces import insert_workspace

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


@pytest.fixture
def core(tmp_path: Path) -> Any:
    db = open_database(":memory:")
    insert_workspace(db, workspace_id="w", name="W", description="")
    return SimpleNamespace(db=db, engine=None, settings=SimpleNamespace())


def _samples(core: Any, sli: str) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in core.db.execute(
            "SELECT subject, value_ms, ok, workspace_id FROM slo_samples WHERE sli = ? ORDER BY id",
            (sli,),
        )
    ]


def test_a_turns_first_output_is_recorded_once(core: Any) -> None:
    started = T0
    assert slis.first_output(core, "w", 7, started, started + timedelta(seconds=2.5))
    assert not slis.first_output(core, "w", 7, started, started + timedelta(seconds=9))
    assert _samples(core, "first_output") == [("turn:7", 2500, 1, "w")]


def test_a_turn_with_no_output_records_nothing(core: Any) -> None:
    assert not slis.first_output(core, "w", 8, T0, None)
    assert _samples(core, "first_output") == []


def test_a_scheduled_runs_delay_comes_from_hermess_dispatch_stamp(core: Any) -> None:
    jobs: list[dict[str, Any]] = [
        {
            "id": "j1",
            "name": "Monday ideas",
            "dispatched_for": "2026-11-03T09:00:00+00:00",
            "dispatched_at": "2026-11-03T09:00:40.500000+00:00",
        },
        {"id": "j2", "name": "never ran", "dispatched_for": None, "dispatched_at": None},
        {
            "id": "j3",
            "name": "late",
            "dispatched_for": "2026-11-03T08:00:00+00:00",
            "dispatched_at": "2026-11-03T08:05:00+00:00",
        },
    ]
    assert slis.automation_delays(core, "w", jobs) == 2
    assert slis.automation_delays(core, "w", jobs) == 0  # each run once
    assert _samples(core, "automation_delay") == [
        ("Monday ideas", 40500, 1, "w"),
        ("late", 300000, 0, "w"),  # beyond 2 min: not on time
    ]


def test_the_health_probe_records_up_and_down(core: Any) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.url.path == "/health" else 500)

    client = httpx.Client(transport=httpx.MockTransport(answer))
    slis.probe(core, "health", "http://core/health", client=client)
    slis.probe(core, "health", "http://core/broken", client=client)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    slis.probe(
        core,
        "health",
        "http://core/health",
        client=httpx.Client(transport=httpx.MockTransport(down)),
    )
    assert [(s[0], s[2]) for s in _samples(core, "health")] == [
        ("/health", 1),
        ("/broken", 0),
        ("/health", 0),
    ]


def test_the_page_probe_records_the_time_to_first_byte(core: Any) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(307)))
    slis.probe(core, "page", "http://web/", client=client)
    [(subject, value, ok, _ws)] = _samples(core, "page")
    assert subject == "/" and ok == 1 and value is not None and value >= 0


def test_probes_are_off_unless_the_install_names_where(core: Any) -> None:
    assert slis.probe_targets(SimpleNamespace(slo_core_url=None, slo_web_url=None)) == []
    assert slis.probe_targets(
        SimpleNamespace(slo_core_url="http://127.0.0.1:8766", slo_web_url="http://127.0.0.1:3000")
    ) == [("health", "http://127.0.0.1:8766/health"), ("page", "http://127.0.0.1:3000/")]


def test_a_live_turn_knows_when_the_owner_first_saw_something() -> None:
    from agos_core.engine.chat import LiveTurn

    turn = LiveTurn(turn_id=1)
    turn.version += 1  # a bump with nothing shown yet
    assert turn.first_output_at is None
    turn.apply({"event": "message.delta", "delta": "Hi"})
    turn.version += 1
    first = turn.first_output_at
    assert first is not None
    turn.apply({"event": "message.delta", "delta": " there"})
    turn.version += 1
    assert turn.first_output_at == first  # the first one stays


def test_a_turns_end_measures_from_its_start(core: Any) -> None:
    from agos_core.db.chats import insert_chat

    chat = insert_chat(core.db, workspace_id="w", title="c", channel="web")
    core.db.execute(
        "INSERT INTO chat_turns (id, chat_id, workspace_id, status, asked_up_to, started_at)"
        " VALUES (5, ?, 'w', 'running', 0, ?)",
        (chat, slis._stamp(T0)),
    )
    assert slis.turn_ended(core, "w", 5, T0 + timedelta(seconds=4))
    assert _samples(core, "first_output") == [("turn:5", 4000, 1, "w")]


def test_the_probe_addresses_are_typed_config(tmp_path: Path) -> None:
    from agos_core.config import ConfigError, load_settings

    base = {"AGOS_DATA_DIR": str(tmp_path), "HOME": str(tmp_path)}
    plain = load_settings(base)
    assert (plain.slo_core_url, plain.slo_web_url) == (None, None)  # no Hermes: a rig
    named = load_settings({**base, "AGOS_SLO_WEB_URL": "http://127.0.0.1:3100/"})
    assert named.slo_web_url == "http://127.0.0.1:3100"
    assert load_settings({**base, "AGOS_SLO_CORE_URL": "off"}).slo_core_url is None
    with pytest.raises(ConfigError):
        load_settings({**base, "AGOS_SLO_CORE_URL": "file:///etc/passwd"})


def test_the_probes_are_jobs_of_the_queue(core: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.background import schedule
    from agos_core.jobs import recurring, runner

    monkeypatch.setattr(recurring, "EVERY", {})
    monkeypatch.setattr(runner, "HANDLERS", {})
    schedule.register()
    assert recurring.EVERY[schedule.HEALTH].interval == timedelta(minutes=1)
    assert recurring.EVERY[schedule.PROBES].interval == timedelta(minutes=5)
    asked: list[str] = []

    def probe(core: Any, sli: str, url: str, **_: Any) -> bool:
        asked.append(url)
        return True

    monkeypatch.setattr(slis, "probe", probe)
    core.settings = SimpleNamespace(slo_core_url="http://c", slo_web_url="http://w")
    runner.HANDLERS[schedule.HEALTH](core, {})
    runner.HANDLERS[schedule.PROBES](core, {})  # no engine: no automation to read
    assert asked == ["http://c/health", "http://w/"]
