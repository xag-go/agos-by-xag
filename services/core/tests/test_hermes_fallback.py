"""General settings → Fallback models: Hermes's own `fallback_providers`, one chain
for every workspace in Hermes's managed scope (one config.yaml every Hermes
process AGOS runs reads), written with Hermes's `hermes config set`. No profile
keeps a copy (old ones move in once, then go); AGOS keeps none (its old
app_settings one moves into Hermes)."""

import json
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_fallback, hermes_managed
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine import config_file

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

CHAIN = [
    {"provider": "claude", "mode": "cli", "model": "claude-sonnet-4-6"},
    {"provider": "openrouter", "mode": "api", "model": "anthropic/claude-sonnet-4"},
]
IN_HERMES = [
    {"provider": "anthropic", "model": "claude-sonnet-4-6"},
    {"provider": "openrouter", "model": "anthropic/claude-sonnet-4"},
]


def _chain(core: Any, key: str) -> Any:
    """A profile's own copy (none once the managed scope holds the chain)."""
    return config_file.read(core.engine.profile_home(key)).get("fallback_providers")


def _managed(core: Any) -> Any:
    return core.engine.managed_config().get("fallback_providers")


def _own(core: Any, key: str, name: str, value: Any) -> None:
    """A copy in a profile's own config.yaml (from before the managed scope)."""
    core.engine.unmanaged_hermes(key, "config", "set", name, json.dumps(value))


def _fallback_calls(runner: Any) -> list[list[str]]:
    return [c for c in runner.calls if "fallback_providers" in c or "fallback_model" in c]


def _put(client: Any, chain: list[dict[str, Any]]) -> Any:
    return client.put("/preferences/hermes-fallback", json={"chain": chain})


def test_saved_once_for_every_root_and_member_through_hermes(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    assert client.get("/preferences/hermes-fallback").json() == {
        "profiles": 3,
        "chain": [],
        "spread": [],
    }
    got = _put(client, CHAIN)
    assert got.status_code == 200, got.text
    assert _managed(core) == IN_HERMES
    for key in (a, f"{a}--a-writer", b):
        assert _chain(core, key) is None, key  # no copy: every profile reads the scope
    # Hermes's own command wrote it, once, in the writer home beside the scope.
    calls = _fallback_calls(runner)
    assert len(calls) == 1
    assert calls[0][1:5] == ["config", "set", "--force", "fallback_providers"]
    assert json.loads(calls[0][-1]) == IN_HERMES
    view = got.json()
    assert view["profiles"] == 3 and view["spread"] == []
    assert view["chain"] == [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "baseUrl": "",
            "catalogProvider": "claude",
            "mode": "cli",
        },
        {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4",
            "baseUrl": "",
            "catalogProvider": "openrouter",
            "mode": "api",
        },
    ]
    # The same save again: Hermes already has it, nothing is written.
    before = len(_fallback_calls(runner))
    assert _put(client, CHAIN).status_code == 200
    assert len(_fallback_calls(runner)) == before
    assert client.get("/preferences/hermes-fallback").json() == view
    # Reordered, then cleared: Hermes's empty list.
    assert _put(client, CHAIN[::-1]).json()["chain"][0]["provider"] == "openrouter"
    assert _managed(core) == IN_HERMES[::-1]
    assert _put(client, []).json()["chain"] == []
    assert _managed(core) == []
    # Hermes refuses a profile's own value for a key its scope pins.
    import pytest

    from agos_core.engine.hermes import EngineError

    with pytest.raises(EngineError):
        core.engine._hermes(b, "config", "set", "fallback_providers", "[]")


def test_old_copies_move_in_once_then_go(env: Any) -> None:  # noqa: F811
    """The chain AGOS wrote into every profile before: into the managed scope at the
    next start (the most common one), then the copies (and a legacy
    fallback_model) are removed; nothing moves twice."""
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    for key in (a, f"{a}--a-writer"):
        _own(core, key, "fallback_providers", IN_HERMES[:1])
    _own(core, b, "fallback_providers", [{"provider": "nous", "model": "hermes-4"}])
    _own(core, b, "fallback_model", {"provider": "nous", "model": "m-old"})
    assert "fallback_providers" in hermes_managed.move_once(core)
    assert _managed(core) == IN_HERMES[:1]  # what most had
    hermes_managed.settle(core)
    for key in (a, f"{a}--a-writer", b):
        have = config_file.read(core.engine.profile_home(key))
        assert "fallback_providers" not in have and "fallback_model" not in have, key
    assert "fallback_providers" not in hermes_managed.move_once(core)  # once
    assert _managed(core) == IN_HERMES[:1]


def test_a_gateway_started_before_keeps_equal_copies(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """A root whose running gateway was started before AGOS gave it the scope still
    reads its profiles' own file: its copies follow each save until it restarts."""
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    _own(core, a, "fallback_providers", [{"provider": "nous", "model": "hermes-4"}])
    _own(core, b, "fallback_providers", [{"provider": "nous", "model": "hermes-4"}])
    monkeypatch.setattr(core.engine, "gateway_managed", lambda w: False if w == a else None)
    hermes_managed.at_start(core)
    assert _chain(core, a) == [{"provider": "nous", "model": "hermes-4"}]  # kept
    assert _chain(core, b) is None  # its next start reads the scope
    assert _put(client, CHAIN).status_code == 200
    assert _managed(core) == IN_HERMES and _chain(core, a) == IN_HERMES
    monkeypatch.setattr(core.engine, "gateway_managed", lambda w: True)  # restarted
    hermes_managed.settle(core)
    assert _chain(core, a) is None


def test_hermes_own_extras_and_legacy_key(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    custom = {
        "provider": "custom",
        "model": "llama-3.1-70b",
        "base_url": "http://localhost:8000/v1",
        "key_env": "LOCAL_API_KEY",
    }
    keyed = {**custom, "api_key": "***"}
    _own(core, a, "fallback_providers", [keyed])
    _own(core, a, "fallback_model", {"provider": "nous", "model": "m-old"})
    hermes_managed.at_start(core)
    # Hermes's merge moved in (list, then the legacy entry); no inline key with it.
    assert _managed(core) == [custom, {"provider": "nous", "model": "m-old"}]
    view = client.get("/preferences/hermes-fallback").json()
    assert [e["model"] for e in view["chain"]] == ["llama-3.1-70b", "m-old"]
    assert view["chain"][0]["catalogProvider"] is None
    assert view["chain"][0]["baseUrl"] == "http://localhost:8000/v1"
    assert "***" not in json.dumps(view) and "***" not in json.dumps(_managed(core))
    # Its own inline key stays in its own file (the managed chain wins over it).
    assert _chain(core, a) == [keyed]
    have = config_file.read(core.engine.profile_home(a))
    assert "fallback_model" not in have  # one chain, like `hermes fallback` leaves it
    assert any(c[1:] == ["config", "unset", "fallback_model"] for c in runner.calls)
    # Kept as it was (no mode: Hermes's own provider name) plus a picker choice.
    body = [
        {"provider": "custom", "model": "llama-3.1-70b", "baseUrl": "http://localhost:8000/v1"},
        CHAIN[1],
    ]
    assert _put(client, body).status_code == 200, _put(client, body).text
    assert _managed(core) == [custom, IN_HERMES[1]]  # its key_env kept


def test_new_profiles_read_the_one_chain(env: Any) -> None:  # noqa: F811
    from agos_core.actions.engine import sync_workspace
    from agos_core.actions.library import apply_workspace

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    assert _managed(core) is None  # AGOS never picks a fallback by itself
    assert _put(client, CHAIN).status_code == 200
    add_agent(client, a, "writer")
    b = ws(client, "Beta")
    add_agent(client, b, "editor")
    for key in (a, f"{a}--a-writer", b, f"{b}--a-editor"):
        assert _chain(core, key) is None, key  # nothing copied: the scope is read
        (core.engine.profile_home(key) / ".agos-applied").unlink(missing_ok=True)
        (core.engine.profile_home(key) / ".agos-connectors").unlink(missing_ok=True)
    for key in (a, b):
        sync_workspace(core, key)
        apply_workspace(core, key)
    assert _managed(core) == IN_HERMES  # no sync touches it
    assert not hasattr(hermes_fallback, "give_new_profile")


def test_agos_old_setting_moves_into_hermes_once(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    set_setting(
        core.db,
        hermes_fallback.OLD_SETTING,
        [{"provider": "p-one", "model": "m-one"}, {"provider": "", "model": "dropped"}],
    )
    assert hermes_fallback.move_old_setting(core) is True
    assert _managed(core) == [{"provider": "p-one", "model": "m-one"}]
    assert _chain(core, a) is None
    assert get_setting(core.db, hermes_fallback.OLD_SETTING, None) is None
    assert hermes_fallback.move_old_setting(core) is False  # once
    # Hermes already holding a chain: the old copy only goes.
    set_setting(core.db, hermes_fallback.OLD_SETTING, [{"provider": "p-two", "model": "m"}])
    assert hermes_fallback.move_old_setting(core) is True
    assert _managed(core) == [{"provider": "p-one", "model": "m-one"}]


def test_old_setting_stays_when_hermes_refuses(env: Any) -> None:  # noqa: F811
    from agos_core.engine.hermes import EngineError

    client, core, runner, _home = env
    ws(client, "Alpha")
    set_setting(core.db, hermes_fallback.OLD_SETTING, [{"provider": "p", "model": "m"}])
    real = runner.run

    def refuse(argv: list[str], **kw: Any) -> str:
        if "fallback_providers" in argv:
            raise EngineError("config.yaml is not writable")
        return str(real(argv, **kw))

    runner.run = refuse
    assert hermes_fallback.move_old_setting(core) is False
    assert get_setting(core.db, hermes_fallback.OLD_SETTING, None) is not None


def test_what_hermes_couldnt_use_is_refused(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")

    def put(chain: list[dict[str, Any]]) -> int:
        return int(_put(client, chain).status_code)

    assert put([{"provider": "Open Router", "model": "m"}]) == 400
    assert put([{"provider": "openrouter", "model": "bad\nmodel"}]) == 400
    assert put([{"provider": "custom", "model": "m", "baseUrl": "ftp://x"}]) == 400
    assert put([{"provider": "openrouter", "model": "m"}] * 2) == 200  # one route once
    assert _managed(core) == [{"provider": "openrouter", "model": "m"}]
    assert _chain(core, a) is None
    many = [{"provider": "openrouter", "model": f"m{n}"} for n in range(21)]
    assert put(many) == 400


def test_no_agos_table_or_setting_holds_the_chain(env: Any) -> None:  # noqa: F811
    """Hermes is the only place it lives: after a save, no AGOS row has it."""
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    marker = "guard-only-in-hermes/model-7f3a"
    assert _put(client, [{"provider": "openrouter", "mode": "api", "model": marker}]).status_code
    assert _managed(core) == [{"provider": "openrouter", "model": marker}]
    assert _chain(core, a) is None
    tables = [
        r[0]
        for r in core.db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    ]
    for table in tables:
        for row in core.db.execute(f'SELECT * FROM "{table}"').fetchall():
            assert marker not in json.dumps([str(v) for v in tuple(row)]), table
    keys = [r[0] for r in core.db.execute("SELECT key FROM app_settings").fetchall()]
    assert not [k for k in keys if "fallback" in k.lower()]
    # The code: Hermes's key is named only where it is read/written through Hermes,
    # and no sync passes a chain (profile_config / apply have no such input).
    named = sorted(
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if '"fallback_providers"' in p.read_text() or "'fallback_providers'" in p.read_text()
    )
    assert named == ["engine/fallback.py"], named
    assert not (SRC / "actions" / "model_fallback.py").exists()
    for path in SRC.rglob("*.py"):
        text = path.read_text()
        assert "fallback_pairs" not in text and "model_fallback" not in text, path
        assert "set_setting(core.db, OLD_SETTING" not in text, path
    from agos_core.engine.rules import profile_config

    assert not [k for k in profile_config(image="i:1", mounts=[]) if "fallback" in k]


def test_an_anthropic_route_with_its_own_key_is_an_api_key(env: Any) -> None:  # noqa: F811
    """Hermes calls a route that carries a key (api_key / key_env) with that key
    (hermes_cli/fallback_config.py resolve_entry_api_key): an API key, not the
    Claude subscription."""
    client, core, _runner, _home = env
    ws(client, "Alpha")
    chain = [
        {"provider": "anthropic", "model": "claude-sonnet-4-6", "key_env": "ANTHROPIC_API_KEY"},
        {"provider": "anthropic", "model": "claude-opus-4-6"},
    ]
    core.engine.managed_write([("fallback_providers", json.dumps(chain))], [])
    view = client.get("/preferences/hermes-fallback").json()
    assert [(e["catalogProvider"], e["mode"]) for e in view["chain"]] == [
        ("claude", "api"),
        ("claude", "cli"),
    ]
    assert "ANTHROPIC_API_KEY" not in json.dumps(view)
