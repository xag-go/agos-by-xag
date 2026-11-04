"""Step 38 B: a workspace's Skills never waits for Hermes's update check, and the
Composio app picker never waits for Composio's app list. Hermes's `hermes skills
check` (a network check of every hub skill, ~20 s on live) and Composio's list are
kept in memory: the page gets the last answer at once and they are asked again
behind it (every few hours / once a day, and right after AGOS changed the hub's
skills), and the read-ahead after start makes the first ask."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from test_library import ws
from test_library_sources import env  # noqa: F401 - fixture (a Hermes checkout for _sources)

from agos_core.actions import composio, workspace_skills
from agos_core.actions.services.library import github_token, skills_hub
from agos_core.engine import composio as cz
from agos_core.engine import read_ahead, sources
from agos_core.engine.read_cache import ReadCache

SKILL = "replica-launch"


def _hub(env: Any, monkeypatch: Any) -> tuple[list[list[str]], dict[str, str]]:  # noqa: F811
    """Hermes's hub as far as these pages go; `state` is what its check says."""
    _client, core, _fake, _tmp = env
    calls: list[list[str]] = []
    state = {"status": "update_available"}

    def hermes(self: Any, args: list[str], **kw: Any) -> str:
        calls.append(args)
        home = kw.get("home")
        folder = (home or core.layout.global_dir) / "skills" / "agos-library" / SKILL
        if args[:2] == ["skills", "inspect"]:
            return f"Name: {SKILL}\nDescription: Writes the launch.\n"
        if args[:2] in (["skills", "install"], ["skills", "update"]):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(
                f"---\nname: {SKILL}\ndescription: Writes the launch.\n---\n\nSteps.\n"
            )
            return "Decision: ALLOWED\nUpdated\n"
        if args[:2] == ["skills", "check"]:
            return f"│ Name │ Source │ Status │\n│ {SKILL} │ github │ {state['status']} │\n"
        return ""

    monkeypatch.setattr(sources.Sources, "_hermes", hermes)
    return calls, state


def _checks(calls: list[list[str]]) -> int:
    return sum(1 for a in calls if a[:2] == ["skills", "check"])


def _install(client: Any) -> tuple[str, int]:
    """A workspace with one skill from the web: (its updates' address, the skill's id)."""
    w = ws(client, "Alpha")
    body = {"identifier": f"Jakeschincariol/replica-skill/{SKILL}"}
    assert client.post(f"/workspaces/{w}/skills/web/install", json=body).status_code == 201
    [item] = [i for i in client.get(f"/workspaces/{w}/skills").json() if i["name"] == SKILL]
    return f"/workspaces/{w}/skills", int(item["id"])


def test_the_update_check_is_kept_and_asked_again_behind_the_page(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, _core, _fake, _tmp = env
    calls, state = _hub(env, monkeypatch)
    base, _item = _install(client)
    assert client.get(f"{base}/updates").json() == []  # Hermes's first check: behind
    assert ReadCache.settle(10)
    first = client.get(f"{base}/updates").json()
    assert [u["hasUpdate"] for u in first] == [True]
    client.get(f"{base}/updates")
    assert _checks(calls) == 1  # kept
    # Hours later: the last answer at once, Hermes checks again behind the page.
    monkeypatch.setattr(skills_hub, "_HUB_CHECK_S", 0.001)
    state["status"] = "up_to_date"
    gate = time.monotonic()
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [True]
    assert time.monotonic() - gate < 2
    assert ReadCache.settle(10)
    monkeypatch.setattr(skills_hub, "_HUB_CHECK_S", 6 * 3600)
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [False]
    assert ReadCache.settle(10)


def test_an_update_shows_at_once_and_hermes_checks_again_behind_it(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, _core, _fake, _tmp = env
    calls, state = _hub(env, monkeypatch)
    base, item = _install(client)
    client.get(f"{base}/updates")  # Hermes's first check, behind the page
    assert ReadCache.settle(10)
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [True]
    assert client.post(f"{base}/{item}/update").status_code in (200, 204)
    state["status"] = "up_to_date"
    before = _checks(calls)
    # Hermes's update ran: not offered again while its next check runs behind.
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [False]
    assert ReadCache.settle(10)
    assert _checks(calls) == before + 1


def test_the_read_ahead_makes_the_first_update_check(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _fake, _tmp = env
    calls, _state = _hub(env, monkeypatch)
    base, _item = _install(client)
    core.engine.tool_services_in = lambda home: {}
    monkeypatch.setattr(github_token, "_token_status", lambda core, kept: None)
    workspace_skills._HUB.drop()
    read_ahead.run(core, ("agos_core.actions.library:read_ahead",))
    seen = _checks(calls)
    assert seen == 1
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [True]
    assert _checks(calls) == seen


def test_the_first_update_check_never_makes_the_page_wait(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """Step 41: right after a start, before the read-ahead got there, Settings →
    Skills waited for Hermes's whole `hermes skills check` (the network, ~20 s on
    live). Now the page answers at once without the hub's skills (no Update mark,
    as when the check fails) and Hermes's check runs behind it; the next view shows
    Hermes's answer."""
    client, _core, _fake, _tmp = env
    calls, _state = _hub(env, monkeypatch)
    base, _item = _install(client)
    workspace_skills._HUB.drop()
    gate = threading.Event()
    real = sources.Sources._hermes

    def slow(self: Any, args: list[str], **kw: Any) -> str:
        if args[:2] == ["skills", "check"]:
            assert gate.wait(10), "the hub never answered"
        return str(real(self, args, **kw))

    monkeypatch.setattr(sources.Sources, "_hermes", slow)
    started = time.monotonic()
    assert client.get(f"{base}/updates").json() == []
    assert client.get(f"{base}/updates").json() == []  # one check, not one per view
    assert time.monotonic() - started < 2
    gate.set()
    assert ReadCache.settle(10)
    assert [u["hasUpdate"] for u in client.get(f"{base}/updates").json()] == [True]
    assert _checks(calls) == 1


@pytest.fixture
def _catalog(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    fetched: list[str] = []
    gate = threading.Event()
    gate.set()

    def toolkits(value: str) -> list[cz.Toolkit]:
        gate.wait(5)
        fetched.append(value)
        return [cz.Toolkit(f"app{len(fetched)}", "App", "", "", (), False)]

    monkeypatch.setattr(composio, "fetch_toolkits", toolkits)
    composio._catalog.clear()
    return fetched


def test_composios_list_is_fetched_once_for_callers_together(
    _catalog: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(value: str) -> list[cz.Toolkit]:
        time.sleep(0.2)  # every caller arrives while it runs
        _catalog.append(value)
        return [cz.Toolkit("app", "App", "", "", (), False)]

    monkeypatch.setattr(composio, "fetch_toolkits", slow)
    got: list[Any] = []
    threads = [threading.Thread(target=lambda: got.append(composio._all("k"))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(got) == 4 and _catalog == ["k"]


def test_a_day_old_list_shows_at_once_while_composio_is_asked_again(_catalog: list[str]) -> None:
    first = composio._all("k")
    stamp, items = composio._catalog["all"]
    composio._catalog["all"] = (stamp - composio.CATALOG_TTL_S - 1, items)
    assert composio._all("k") == first  # the last list, at once
    assert ReadCache.settle(10)
    assert [t.slug for t in composio._all("k")] == ["app2"]


def test_the_read_ahead_fetches_composios_list(
    env: Any,  # noqa: F811
    _catalog: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _fake, _tmp = env
    a = ws(client, "Alpha")
    monkeypatch.setattr(
        composio, "key", lambda core, workspace_id: "ak_x" if workspace_id == a else None
    )
    assert "agos_core.actions.composio:read_ahead" in read_ahead.WARMERS
    read_ahead.run(core, ("agos_core.actions.composio:read_ahead",))
    assert _catalog == ["ak_x"]
