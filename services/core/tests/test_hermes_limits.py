"""General settings that reach every workspace's Hermes (loop detector, time limit,
members at once), and the owner's account pause rule."""

from typing import Any

import pytest
from work_env import Env, create_ws, env  # noqa: F401  (fixture)

from agos_core.actions import account_pause


def test_loop_detector_and_time_limit_are_hermess_own_settings(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set once in General settings, written into Hermes's managed scope (loop
    guard, run budget, Kanban's cap): one config.yaml every workspace's Hermes
    reads; read back from Hermes; AGOS keeps no copy, nor does any profile, not
    even of Hermes's defaults: a count he leaves is Hermes's default (unset), and
    members at once is Hermes's own memory-derived cap until he sets one."""
    from agos_core.actions.hermes_managed import has, lookup
    from agos_core.engine import hermes_schema
    from agos_core.engine.hermes_schema import Field

    client, _fake, core, ws = env
    loop = "tool_loop_guardrails.hard_stop_after."
    fields = [
        Field(loop + "exact_failure", "number", "", 6),
        Field(loop + "same_tool_failure", "number", "", 9),
        Field(loop + "idempotent_no_progress", "number", "", 4),
    ]
    monkeypatch.setattr(core.engine, "config_schema", lambda: fields)
    monkeypatch.setattr(hermes_schema, "kanban_auto_cap", lambda: 7)
    other = create_ws(client, "Other")
    runner = core.engine.runner
    got = client.get("/preferences/hermes-limits").json()
    assert got["membersAtOnce"] is None  # unset: Hermes decides, never 2
    assert got["sameToolFailing"] == 9  # Hermes's default, read from Hermes
    assert got["hermesDefaults"] == {
        "sameError": 6,
        "sameToolFailing": 9,
        "noProgress": 4,
        "membersAtOnce": 7,
    }
    r = client.put(
        "/preferences/hermes-limits",
        json={"loopOn": True, "sameError": 3, "sameToolFailing": 9, "timeLimitMinutes": 45},
    )
    assert r.status_code == 200, r.text
    managed = core.engine.managed_config()
    assert not has(managed, "kanban.max_in_progress")  # left to Hermes
    assert not has(managed, loop + "same_tool_failure")  # = Hermes's default
    assert lookup(managed, "tool_loop_guardrails.hard_stop_enabled") is True
    assert lookup(managed, "tool_loop_guardrails.non_interactive_hard_stop_enabled") is True
    assert lookup(managed, loop + "exact_failure") == 3
    assert lookup(managed, "agent.run_budget_seconds") == 2700
    for w in (ws, other):
        cfg = runner.config.get(f"agos-{w}", {})
        assert "kanban.max_in_progress" not in cfg and "agent.run_budget_seconds" not in cfg
    # Written by Hermes's own `config set`, in the scope's folder, without the scope.
    writer = str(core.engine.settings.managed_home)
    assert any(
        e.get("HERMES_HOME") == writer and e["HERMES_MANAGED_DIR"].endswith(".off")
        for e in runner.envs
    )
    got = client.get("/preferences/hermes-limits").json()
    assert {k: v for k, v in got.items() if k != "hermesDefaults"} == {
        "loopOn": True,
        "sameError": 3,
        "sameToolFailing": 9,
        "noProgress": 4,
        "timeLimitMinutes": 45,
        "membersAtOnce": None,
    }
    r = client.put(
        "/preferences/hermes-limits",
        json={"loopOn": True, "sameError": 3, "timeLimitMinutes": 45, "membersAtOnce": 3},
    )
    assert r.status_code == 200, r.text
    assert lookup(core.engine.managed_config(), "kanban.max_in_progress") == 3  # his own cap
    # A new workspace reads the same file: nothing copied into it.
    third = create_ws(client, "Third")
    assert "agent.run_budget_seconds" not in runner.config.get(f"agos-{third}", {})
    client.put("/preferences/hermes-limits", json={"loopOn": False, "timeLimitMinutes": None})
    managed = core.engine.managed_config()
    assert lookup(managed, "tool_loop_guardrails.hard_stop_enabled") is False
    assert not has(managed, "agent.run_budget_seconds")
    assert not has(managed, "kanban.max_in_progress")  # back to Hermes's own cap
    assert client.get("/preferences/hermes-limits").json()["timeLimitMinutes"] is None


def test_the_account_pause_holds_at_the_owners_threshold(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agos_core.engine import limits, models

    client, _fake, core, _ws = env
    full = [limits.Account("anthropic", "Claude", [limits.Window("Current week", 100.0, None)], [])]
    monkeypatch.setattr(limits, "account_limits", lambda *a, **k: full)
    monkeypatch.setattr(models, "hermes_python", lambda s: "/bin/python")
    assert account_pause.reason(core) == "Claude current week at 100%"
    client.put("/preferences/usage", json={"enabled": False, "warnAt": 80, "pauseAt": 100})
    assert account_pause.reason(core) is None  # usage rules off
    client.put("/preferences/usage", json={"enabled": True, "warnAt": 80, "pauseAt": 100})
    half: Any = [limits.Account("anthropic", "Claude", [limits.Window("Week", 50.0, None)], [])]
    monkeypatch.setattr(limits, "account_limits", lambda *a, **k: half)
    assert account_pause.reason(core) is None
