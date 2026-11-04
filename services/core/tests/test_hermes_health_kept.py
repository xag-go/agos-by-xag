"""Step 38 B: Settings → Health never waits for `hermes doctor`. Each root's last
two reports (Hermes's own `hermes status --full` and `hermes doctor`) stay in memory
with the time they were taken; the page gets them at once, and Hermes is asked
again behind it when they are older than a few minutes or when the owner asks for
a new check. Step 42: a root with no report yet doesn't make the page wait either
(the first view after a start waited ~10 s for every root's doctor): it shows as
checking, and its reports come as soon as its own run ends (the page asks again
every few seconds)."""

from __future__ import annotations

import itertools
import threading
import time
from typing import Any

from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_health
from agos_core.engine import read_ahead
from agos_core.engine.read_cache import ReadCache

_ANSWER = itertools.count(1)  # every answer of every fake differs


def _hermes(core: Any, *, gate: threading.Event | None = None) -> list[tuple[str, str]]:
    """Hermes's two reports, counted; `gate` holds them until it is set."""
    asked: list[tuple[str, str]] = []

    def hermes_check(workspace_id: str, command: str, *, timeout: float = 180) -> tuple[str, int]:
        if gate is not None:
            gate.wait(10)
        asked.append((workspace_id, command))
        n = next(_ANSWER)
        if command == "doctor":
            return f"◆ Checks {n}\n  ⚠ one warning", 0
        return f"◆ Environment {n}", 0

    core.engine.hermes_check = hermes_check
    return asked


def _kept(client: Any) -> dict[str, Any]:
    """The first root's reports once Hermes gave them (asked behind the first view)."""
    client.get("/preferences/hermes-health")
    assert ReadCache.settle(10)
    root: dict[str, Any] = client.get("/preferences/hermes-health").json()["roots"][0]
    assert root["checkedAt"] and root["checking"] is False
    return root


def test_the_page_answers_from_the_last_report_at_once(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    asked = _hermes(core)
    client.get("/preferences/hermes-health")  # nothing kept yet: asked behind the page
    assert ReadCache.settle(10)
    first = client.get("/preferences/hermes-health").json()
    [root] = first["roots"]
    assert root["workspaceId"] == a and root["doctor"]["warnings"] == 1
    assert root["checkedAt"] and root["checking"] is False
    assert sorted(asked) == [(a, "doctor"), (a, "status")]
    second = client.get("/preferences/hermes-health").json()
    assert len(asked) == 2  # Hermes not asked again
    assert second["roots"][0]["checkedAt"] == root["checkedAt"]
    assert second["roots"][0]["doctor"]["text"] == root["doctor"]["text"]


def test_the_first_view_after_a_start_never_waits_for_hermes(env: Any) -> None:  # noqa: F811
    """Nothing kept yet (the read-ahead hasn't reached Health): the page answers at
    once, each root checking with Hermes's check still running; a root's reports show
    as soon as its own run ends, while the other still runs. Behind the page, at most
    the read-ahead's two low-priority threads run Hermes (never more load at start)."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    b = ws(client, "Beta")
    gates = {a: threading.Event(), b: threading.Event()}
    running, most = [0], [0]
    lock = threading.Lock()

    def hermes_check(workspace_id: str, command: str, *, timeout: float = 180) -> tuple[str, int]:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        gates[workspace_id].wait(10)
        with lock:
            running[0] -= 1
        return f"  ✓ {command} of {workspace_id}", 0

    core.engine.hermes_check = hermes_check

    def view() -> dict[str, Any]:
        started = time.monotonic()
        body = client.get("/preferences/hermes-health").json()
        assert time.monotonic() - started < 2  # never waits for Hermes
        return {r["workspaceId"]: r for r in body["roots"]}

    first = view()
    assert [first[w]["checking"] for w in (a, b)] == [True, True]
    assert first[a]["doctor"]["pending"] is True
    assert first[a]["doctor"]["error"] is None
    assert first[a]["checkedAt"] is None
    gates[a].set()
    deadline = time.monotonic() + 10
    while view()[a]["checking"] and time.monotonic() < deadline:
        time.sleep(0.05)
    shown = view()
    assert shown[a]["checking"] is False and shown[a]["doctor"]["text"] == f"  ✓ doctor of {a}"
    assert shown[b]["checking"] is True and shown[b]["doctor"]["pending"] is True
    gates[b].set()
    assert ReadCache.settle(10)
    done = view()
    assert [done[w]["checking"] for w in (a, b)] == [False, False]
    assert done[b]["status"]["text"] == f"  ✓ status of {b}"
    assert most[0] <= 2


def test_an_old_report_is_checked_again_behind_the_page(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    asked = _hermes(core)
    before = _kept(client)
    monkeypatch.setattr(hermes_health, "MAX_AGE_S", 0.0)  # every report is old now
    gate = threading.Event()
    _hermes(core, gate=gate)
    started = time.monotonic()
    shown = client.get("/preferences/hermes-health").json()["roots"][0]
    assert time.monotonic() - started < 2  # the kept report, at once
    assert shown["checkedAt"] == before["checkedAt"] and shown["checking"] is True
    gate.set()
    assert ReadCache.settle(10)
    monkeypatch.setattr(hermes_health, "MAX_AGE_S", 300.0)
    after = client.get("/preferences/hermes-health").json()["roots"][0]
    assert after["checking"] is False and after["checkedAt"] >= before["checkedAt"]
    assert after["doctor"]["text"] != before["doctor"]["text"]  # Hermes's new report
    assert len(asked) == 2  # the first fake's two reports; the second fake ran behind


def test_check_again_runs_behind_the_page(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    _hermes(core)
    before = _kept(client)
    gate = threading.Event()
    asked = _hermes(core, gate=gate)
    started = time.monotonic()
    body = client.get("/preferences/hermes-health", params={"fresh": "true"}).json()
    assert time.monotonic() - started < 2
    assert body["roots"][0]["checking"] is True
    assert body["roots"][0]["checkedAt"] == before["checkedAt"]
    # Asked again while it runs: still one check (no second Hermes run at once).
    client.get("/preferences/hermes-health", params={"fresh": "true"})
    gate.set()
    assert ReadCache.settle(10)
    after = client.get("/preferences/hermes-health").json()["roots"][0]
    assert after["checking"] is False and after["doctor"]["text"] != before["doctor"]["text"]
    assert len(asked) == 2


def test_the_read_ahead_checks_each_root_once_one_after_the_other(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    ws(client, "Beta")
    running = [0]
    most = [0]
    asked: list[tuple[str, str]] = []
    lock = threading.Lock()

    def hermes_check(workspace_id: str, command: str, *, timeout: float = 180) -> tuple[str, int]:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.02)
        with lock:
            running[0] -= 1
            asked.append((workspace_id, command))
        return "  ✓ fine", 0

    core.engine.hermes_check = hermes_check
    assert "agos_core.actions.hermes_health:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.hermes_health:read_ahead",))
    assert len(asked) == 4 and most[0] == 1  # one Hermes at a time
    asked.clear()
    body = client.get("/preferences/hermes-health").json()
    assert [r["checking"] for r in body["roots"]] == [False, False]
    assert asked == []  # the page asked Hermes nothing


def test_the_cofounders_check_waits_for_new_reports(env: Any) -> None:  # noqa: F811
    """From a chat, the Co-Founder runs Hermes's checks now (the owner asked for them):
    a new report, which the page then shows too."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    asked = _hermes(core)
    _kept(client)
    found = hermes_health.read(core, a, fresh=True, wait=True)
    assert len(asked) == 4
    page = client.get("/preferences/hermes-health").json()["roots"][0]
    assert page["doctor"]["text"] == found["roots"][0]["doctor"]["text"]
