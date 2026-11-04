"""General settings → Time limits: every Hermes timeout, written once with Hermes's
own `hermes config set` into Hermes's managed scope every profile reads (its .env
for TERMINAL_MAX_FOREGROUND_TIMEOUT). The scope starts on the owner's values."""

from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_managed
from agos_core.engine import config_file
from agos_core.engine.time_limits import (
    BY_KEY,
    GROUPS,
    HERMES_MAX_SECONDS,
    HOOK_GUARD_SECONDS,
    NO_LIMIT_SECONDS,
    TIME_LIMITS,
    owner_defaults,
)

# The owner's values (set by hand on the live profiles), with the two keys where
# Hermes reads 0 as something other than "no limit" moved to 24 hours:
# timeouts.mcp.tool_call (0 → Hermes's 300 s default) and
# agent.restart_after_turn_timeout (0 → restart at once, cutting running answers).
OWNER = {
    "timeouts.tools.sequential_call": 0,
    "timeouts.tools.concurrent_batch": 0,
    "timeouts.mcp.tool_call": NO_LIMIT_SECONDS,
    "agent.turn_liveness.timeout_s": 0,
    "agent.gateway_timeout": 0,
    "agent.gateway_timeout_warning": 0,
    # Not a wait for him any more: Hermes's hang guard of every plugin hook, at its
    # own cap (his yes under Full access is asked outside it: agos-guard's
    # tool_execution middleware, tests/test_owner_ask_outside_hook.py).
    "plugins.hook_callback_timeout": HOOK_GUARD_SECONDS,
    "agent.clarify_timeout": 0,
    "agent.session_stall_timeout": 0,
    "delegation.child_timeout_seconds": 0,
    "approvals.timeout": HERMES_MAX_SECONDS,
    "terminal.timeout": NO_LIMIT_SECONDS,
    "TERMINAL_MAX_FOREGROUND_TIMEOUT": NO_LIMIT_SECONDS,
    "browser.command_timeout": NO_LIMIT_SECONDS,
    "browser.inactivity_timeout": NO_LIMIT_SECONDS,
    "auxiliary.vision.download_timeout": NO_LIMIT_SECONDS,
    "agent.restart_after_turn_timeout": NO_LIMIT_SECONDS,
    "discord.voice_channel_inactivity_timeout_seconds": 0,
    **{
        f"auxiliary.{task}.timeout": NO_LIMIT_SECONDS
        for task in [
            "vision",
            "video",
            "compression",
            "skills_hub",
            "approval",
            "mcp",
            "title_generation",
            "memory_query_rewrite",
            "tts_audio_tags",
            "voice_chat",
            "background_review",
            "curator",
            "goal_judge",
            "kanban_decomposer",
            "moa_aggregator",
            "moa_reference",
            "monitor",
            "profile_describer",
            "review",
            "triage_specifier",
        ]
    },
}


def _value(core: Any, key: str, setting: str) -> Any:
    """What the profile's Hermes reads: its .env or config.yaml with the managed
    scope's on top."""
    home = core.engine.profile_home(key)
    if setting.isupper():
        managed = config_file.read_env(core.engine.settings.managed_home)
        return managed.get(setting, config_file.read_env(home).get(setting))
    seen = core.engine.as_hermes_reads([home])[str(home)]
    return config_file.get(seen, setting)


def _own(core: Any, key: str, setting: str) -> Any:
    """The profile's own config.yaml copy (none: the scope holds it)."""
    return config_file.get(config_file.read(core.engine.profile_home(key)), setting)


def _sets(runner: Any) -> list[list[str]]:
    return [c for c in runner.calls if "config" in c and "set" in c]


def test_the_card_covers_the_owners_list_with_his_values() -> None:
    assert {limit.key: limit.default for limit in TIME_LIMITS} == OWNER
    assert len(BY_KEY) == len(TIME_LIMITS)
    assert {limit.group for limit in TIME_LIMITS} == set(GROUPS)
    for limit in TIME_LIMITS:
        # "No limit" is what the owner chose, and the card shows it as such.
        if limit.key != "plugins.hook_callback_timeout":
            assert limit.is_no_limit(limit.default), limit.key
        assert limit.is_no_limit(limit.no_limit_value), limit.key
        assert limit.zero_is_no_limit == (limit.no_limit_value == 0)
    seeded = owner_defaults()
    assert seeded["TERMINAL_MAX_FOREGROUND_TIMEOUT"] == str(NO_LIMIT_SECONDS)
    # Only clocks: no helper model, no image mode (Settings → Helper models: Hermes's).
    assert set(seeded) == set(BY_KEY)


def test_a_new_workspace_and_member_start_on_the_owners_values(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    for key in (a, f"{a}--a-writer"):
        for setting, value in OWNER.items():
            assert str(_value(core, key, setting)) == str(value), (key, setting)
        for helper in ("auxiliary.video.model", "auxiliary.vision.provider"):
            assert _value(core, key, helper) is None  # AGOS picks none
        assert _value(core, key, "agent.image_input_mode") is None
        assert _own(core, key, "terminal.timeout") is None  # no copy: the scope's
        home = core.engine.profile_home(key)
        assert "TERMINAL_MAX_FOREGROUND_TIMEOUT" not in config_file.read_env(home)


def test_a_resync_never_resets_what_he_changed(env: Any) -> None:  # noqa: F811
    from agos_core.actions.engine import sync_workspace

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    r = client.put(
        "/preferences/hermes-time-limits",
        json={"values": {"terminal.timeout": 900, "agent.gateway_timeout": 1200}},
    )
    assert r.status_code == 200, r.text
    (core.engine.profile_home(a) / ".agos-applied").unlink()
    sync_workspace(core, a)
    for key in (a, f"{a}--a-writer"):
        assert _value(core, key, "terminal.timeout") == 900
        assert _value(core, key, "agent.gateway_timeout") == 1200


def test_saved_into_every_root_and_member_through_hermes(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    body = {
        "values": {
            "terminal.timeout": 3600,
            "agent.clarify_timeout": 600,
            "TERMINAL_MAX_FOREGROUND_TIMEOUT": 7200,
        },
    }
    got = client.put("/preferences/hermes-time-limits", json=body)
    assert got.status_code == 200, got.text
    for key in (a, f"{a}--a-writer", b):
        assert _value(core, key, "terminal.timeout") == 3600
        assert _value(core, key, "agent.clarify_timeout") == 600
        assert _value(core, key, "TERMINAL_MAX_FOREGROUND_TIMEOUT") == "7200"  # its .env
    assert _own(core, a, "terminal.timeout") is None  # one managed value, no copy
    # Hermes's own command wrote them (an UPPER name goes to its .env writer).
    assert any("TERMINAL_MAX_FOREGROUND_TIMEOUT" in c for c in _sets(runner))
    view = got.json()
    assert view["profiles"] == 3
    rows = {row["key"]: row for row in view["limits"]}
    assert rows["terminal.timeout"]["value"] == 3600 and not rows["terminal.timeout"]["noLimit"]
    assert rows["agent.gateway_timeout"]["noLimit"] and rows["agent.gateway_timeout"]["value"] == 0
    assert rows["approvals.timeout"]["noLimit"]
    assert all(not row["spread"] for row in view["limits"])
    assert "video" not in view and "videoGroup" not in view
    # The same save again: Hermes already has it, nothing is run.
    before = len(_sets(runner))
    assert client.put("/preferences/hermes-time-limits", json=body).status_code == 200
    assert len(_sets(runner)) == before
    assert client.get("/preferences/hermes-time-limits").json() == view


def test_no_profile_can_hold_its_own_value(env: Any) -> None:  # noqa: F811
    """One value for every workspace: Hermes refuses a profile's own (config.yaml
    and .env alike), so the card never shows workspaces that differ."""
    import pytest

    from agos_core.engine.hermes import EngineError

    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    for key, value in (("terminal.timeout", "600"), ("TERMINAL_MAX_FOREGROUND_TIMEOUT", "600")):
        with pytest.raises(EngineError):
            core.engine._hermes(b, "config", "set", key, value)
    view = client.get("/preferences/hermes-time-limits").json()
    assert all(not r["spread"] for r in view["limits"])
    # A key the scope doesn't hold: Hermes's own default is what it uses, read from
    # Hermes's settings list (its DEFAULT_CONFIG), not a copy in AGOS (P3).
    import runpy
    from pathlib import Path

    from agos_core.engine import hermes_schema as hs

    defaults_file = Path.home() / ".hermes/hermes-agent/hermes_cli/config_defaults.py"
    defaults = runpy.run_path(str(defaults_file))["DEFAULT_CONFIG"]
    defaults["browser"]["command_timeout"] = 37  # what this Hermes says
    core.engine.config_schema = lambda: hs.build({}, defaults, "")
    hermes_managed.write(core, {}, ("browser.command_timeout",))
    row = next(
        r
        for r in client.get("/preferences/hermes-time-limits").json()["limits"]
        if r["key"] == "browser.command_timeout"
    )
    assert row["value"] == 37 and row["hermesDefault"] == 37


def test_new_profiles_take_what_the_workspaces_use(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    assert (
        client.put(
            "/preferences/hermes-time-limits",
            json={"values": {"terminal.timeout": 1800, "approvals.timeout": 7200}},
        ).status_code
        == 200
    )
    add_agent(client, a, "writer")  # a new member: its Co-Founder's
    b = ws(client, "Beta")  # a new workspace: the others'
    add_agent(client, b, "editor")
    for key in (f"{a}--a-writer", b, f"{b}--a-editor"):
        assert _value(core, key, "terminal.timeout") == 1800, key
        assert _value(core, key, "approvals.timeout") == 7200, key
        assert _value(core, key, "agent.gateway_timeout") == 0, key


def test_what_hermes_wouldnt_read_as_no_limit_is_refused(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")

    def put(body: dict[str, Any]) -> int:
        return int(client.put("/preferences/hermes-time-limits", json=body).status_code)

    assert put({"values": {"terminal.timeout": 0}}) == 400  # 0 = instant there
    assert put({"values": {"timeouts.mcp.tool_call": 0}}) == 400  # 0 = its 300 s default
    assert put({"values": {"agent.restart_after_turn_timeout": 0}}) == 400  # cuts answers
    assert put({"values": {"agent.not_a_timeout": 5}}) == 400
    assert put({"values": {"approvals.timeout": HERMES_MAX_SECONDS + 1}}) == 400
    assert put({"videoModel": "gemini-3-flash-preview"}) == 422  # not this card's
    assert put({"values": {"agent.clarify_timeout": 0}}) == 200  # Hermes: 0 = unlimited
    assert _value(core, a, "terminal.timeout") == NO_LIMIT_SECONDS  # untouched


def test_the_old_hook_timeout_of_0_moves_to_hermess_cap_once(env: Any) -> None:  # noqa: F811
    """925047d put 0 there (no hang guard for any plugin hook) only because his yes
    waited inside a hook. That 0 moves once to Hermes's cap; his own later choice,
    0 included, then stays."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    key = "plugins.hook_callback_timeout"
    core.engine.managed_write([(key, "0")], [])
    core.db.execute("DELETE FROM app_settings WHERE key = ?", (hermes_managed.HOOK_GUARD_MOVED,))
    assert hermes_managed.move_hook_guard(core) is True
    assert str(_value(core, a, key)) == str(HOOK_GUARD_SECONDS)
    core.engine.managed_write([(key, "0")], [])  # the owner picks No limit himself
    assert hermes_managed.move_hook_guard(core) is False
    assert str(_value(core, a, key)) == "0"


def test_the_live_start_moves_the_hook_guard_too(monkeypatch: Any) -> None:
    """Live starts with the loops on, through _sync_then_serve, not at_start: the
    one move of the hook guard must run there as well (it never ran on live)."""
    import asyncio
    import contextlib

    from agos_core.actions import hermes_managed
    from agos_core.actions.services.system import startup

    called: list[str] = []
    monkeypatch.setattr(hermes_managed, "move_hook_guard", lambda core: called.append("guard"))
    monkeypatch.setattr(hermes_managed, "move_once", lambda core: called.append("move"))

    async def stop(core: Any, **_how: Any) -> None:  # resync_all(core, finish=...)
        raise RuntimeError("stop here")

    monkeypatch.setattr(startup, "resync_all", stop)
    from agos_core.db import ownership

    monkeypatch.setattr(ownership, "unregistered", lambda db: [])
    with contextlib.suppress(RuntimeError):
        asyncio.run(startup.sync_then_serve(type("C", (), {"db": None})()))
    assert called[:2] == ["guard", "move"]
