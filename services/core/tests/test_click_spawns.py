"""Hermes starts per click, counted on the fake runner: the same click on the old
path (one `hermes config set` CLI per key: what runs when Hermes's runtime can't)
and through engine.config_writes (Hermes's writer for all of a home's keys in one
process, only the keys whose value Hermes doesn't hold already)."""

from typing import Any

import pytest
from conftest import hermes_config_batch
from test_library import env, skill, turn_off, turn_on, ws

__all__ = ["env"]


def _config_clis(runner: Any) -> list[list[str]]:
    return [c for c in runner.calls if c[1:3] in (["config", "set"], ["config", "unset"])]


def test_a_library_switch_writes_one_hermes_process_with_only_what_changed(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1: Library / Capabilities switch of a workspace (no members)."""
    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    sid = skill(client, a)  # made on in its workspace
    assert turn_off(client, a, sid) == 204
    runner.calls.clear()
    assert turn_on(client, a, sid) == 204
    before = _config_clis(runner)  # one CLI per pair, every pair of the workspace
    starts = hermes_config_batch(monkeypatch)
    runner.calls.clear()
    assert client.put(f"/workspaces/{a}/connectors/{sid}", json={"on": False}).status_code == 204
    assert _config_clis(runner) == []
    roots = [s for s in starts if s[0].endswith(f"agos-{a}")]
    assert len(roots) == 1  # the root's keys: one Hermes process
    assert roots[0][1:] == ["skills.disabled"]  # and only the key that changed
    print(f"C1 switch: {len(before)} Hermes CLI before -> {len(starts)} Hermes process after")
    assert len(before) > 10


def test_a_general_card_saved_unchanged_starts_no_hermes_and_a_change_one_process(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5: General settings card through Hermes's managed scope (Time limits)."""
    from agos_core.engine.hermes import HermesEngine

    client, _core, runner, _home = env
    ws(client, "Alpha")
    asked: list[str] = []
    real = HermesEngine.gateway_managed

    def counted(self: Any, root: str) -> Any:
        asked.append(root)
        return real(self, root)

    monkeypatch.setattr(HermesEngine, "gateway_managed", counted)
    body = {"values": {"terminal.timeout": 3600, "agent.clarify_timeout": 600}}
    runner.calls.clear()
    assert client.put("/preferences/hermes-time-limits", json=body).status_code == 200
    before = len(_config_clis(runner))
    # The same save again: nothing to write, no settling, no gateway asked.
    runner.calls.clear()
    asked.clear()
    assert client.put("/preferences/hermes-time-limits", json=body).status_code == 200
    assert _config_clis(runner) == [] and asked == []
    # A change: the managed keys in one Hermes process.
    starts = hermes_config_batch(monkeypatch)
    runner.calls.clear()
    body = {"values": {"terminal.timeout": 1800, "agent.clarify_timeout": 300}}
    assert client.put("/preferences/hermes-time-limits", json=body).status_code == 200
    assert _config_clis(runner) == []
    assert [s[1:] for s in starts] == [["terminal.timeout", "agent.clarify_timeout"]]
    print(f"C5 time limits: {before} Hermes CLI before -> {len(starts)} Hermes process after")


def test_a_provider_key_reaches_every_home_four_at_a_time(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C6: general_sync.sync (provider key save/remove, logins) writes the homes
    side by side, at most 4 at once (each home has its own write lock)."""
    import threading
    import time

    from agos_core.actions import general_sync

    client, core, _runner, _home = env
    for name in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"):
        ws(client, name)
    lock = threading.Lock()
    now = {"in": 0, "most": 0}
    seen: list[str] = []

    def push(home: Any, values: Any, names: Any, save: Any) -> list[str]:
        with lock:
            now["in"] += 1
            now["most"] = max(now["most"], now["in"])
            seen.append(str(home))
        time.sleep(0.2)
        with lock:
            now["in"] -= 1
        return ["KEY"]

    monkeypatch.setattr(general_sync, "push_home", push)
    report = general_sync.sync(core)
    homes = [str(h) for _ws, h in general_sync.homes(core)]
    assert sorted(seen) == sorted(homes) and report["homes"] == len(homes) >= 6
    assert list(report["changed"]) == homes  # reported in the homes' order
    assert 1 < now["most"] <= 4


def test_a_workspace_model_pick_is_one_hermes_process(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C7: Workspace settings -> model (provider, model, base_url, effort)."""
    import types

    from agos_core.actions import engine as engine_actions

    client, core, runner, _home = env
    a = ws(client, "Alpha")
    pick = types.SimpleNamespace(provider="openrouter", mode="api", model="x/one", effort="high")
    runner.calls.clear()
    engine_actions.set_model(core, a, pick)
    before = len(_config_clis(runner))
    starts = hermes_config_batch(monkeypatch)
    runner.calls.clear()
    engine_actions.set_model(core, a, types.SimpleNamespace(**{**vars(pick), "model": "x/two"}))
    assert _config_clis(runner) == [] and len(starts) == 1
    assert starts[0][1:] == ["model.default"]  # only the model changed
    print(f"C7 model pick: {before} Hermes CLI before -> {len(starts)} Hermes process after")
    assert before >= 3


def test_the_members_resync_of_a_switch_is_one_hermes_process_each(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C1/C10: a switch's member re-sync (background live, at once in tests): each
    member's pairs in one Hermes process, only what changed, members side by side."""
    from test_agent_profiles import add_agent

    client, _core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    sid = skill(client, a)  # made on in its workspace
    assert turn_off(client, a, sid) == 204
    runner.calls.clear()
    assert turn_on(client, a, sid) == 204
    clis_before = len(_config_clis(runner))
    starts = hermes_config_batch(monkeypatch)
    runner.calls.clear()
    assert client.put(f"/workspaces/{a}/connectors/{sid}", json={"on": False}).status_code == 204
    assert _config_clis(runner) == []
    members = [s for s in starts if "/profiles/" in s[0] and len(s) > 1]
    assert len(members) == 2 and all(s[1:] == ["skills.disabled"] for s in members)
    # Each member's approvals follow its Co-Founder's, read from the root's config.yaml
    # (C10: it was one `hermes config get` per member).
    asked = [c for c in runner.calls if c[1:4] == ["config", "get", "approvals.mode"]]
    assert asked == []
    print(
        f"C1/C10 switch with 2 members: {clis_before} Hermes CLI before -> "
        f"{len(starts)} Hermes processes after (root + 2 members)"
    )
