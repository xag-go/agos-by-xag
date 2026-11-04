"""General settings → Voice notes: who hears the owner's voice notes is ONE
provider + model for every workspace, in Hermes's managed scope (`stt.provider`,
`stt.<provider>.model`), written with Hermes's own `hermes config set`. No
profile keeps a copy; the old copies (Fuel Machine's `stt.provider: local`) move
in once to the most common value (gemini / gemini-3-flash-preview), then go. A
fresh install starts with voice notes off (`stt.enabled: false`) until the owner
picks a provider.
"""

from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import hermes_managed
from agos_core.engine import config_file
from agos_core.engine.hermes import EngineError

GEMINI = "gemini-3-flash-preview"


@pytest.fixture(autouse=True)
def _hermes_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hermes's settings schema's speech-to-text rows (hermes_stt_rig.py: from its source)."""
    from hermes_stt_rig import hermes_stt_fields

    from agos_core.engine.hermes import HermesEngine

    fields = hermes_stt_fields()
    monkeypatch.setattr(HermesEngine, "config_schema", lambda self: list(fields))


def _managed(core: Any) -> dict[str, Any]:
    stt = core.engine.managed_config().get("stt")
    return stt if isinstance(stt, dict) else {}


def _own(core: Any, key: str) -> dict[str, Any]:
    stt = config_file.read(core.engine.profile_home(key)).get("stt")
    return stt if isinstance(stt, dict) else {}


def _put(client: Any, provider: str, model: str) -> Any:
    return client.put("/preferences/hermes-voice", json={"provider": provider, "model": model})


def test_one_provider_and_model_for_every_profile(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    add_agent(client, a, "writer")
    # The core's start: no profile had a choice, so voice notes start off.
    assert _managed(core) == {"enabled": False}
    for key in (a, f"{a}--a-writer", b):
        assert "provider" not in _own(core, key) and "gemini" not in _own(core, key), key
    got = client.get("/preferences/hermes-voice").json()
    assert got["profiles"] == 3
    assert (got["provider"], got["model"]) == ("off", "")
    options = {o["name"]: o for o in got["options"]}
    assert got["options"][0]["name"] == "off"
    assert {
        "off",
        "gemini",
        "local",
        "groq",
        "openai",
        "mistral",
        "xai",
        "elevenlabs",
        "deepinfra",
    } <= set(options)
    assert options["groq"]["models"][0] == "whisper-large-v3-turbo"
    assert options["gemini"]["models"] == [GEMINI]

    # Picking Gemini turns them on: the switch leaves the scope (Hermes's default: on).
    r = _put(client, "gemini", GEMINI)
    assert r.status_code == 200, r.text
    assert (r.json()["provider"], r.json()["model"]) == ("gemini", GEMINI)
    assert _managed(core) == {"provider": "gemini", "gemini": {"model": GEMINI}}

    r = _put(client, "groq", "whisper-large-v3")
    assert r.status_code == 200, r.text
    assert (r.json()["provider"], r.json()["model"]) == ("groq", "whisper-large-v3")
    # One provider + its model: the other provider's model leaves the scope.
    assert _managed(core) == {"provider": "groq", "groq": {"model": "whisper-large-v3"}}
    for key in (a, f"{a}--a-writer", b):
        assert _own(core, key) == {} or "provider" not in _own(core, key), key
    # ElevenLabs keeps its model under model_id (Hermes's name).
    assert _put(client, "elevenlabs", "scribe_v1").status_code == 200
    assert _managed(core) == {"provider": "elevenlabs", "elevenlabs": {"model_id": "scribe_v1"}}
    # No model: Hermes's default for that provider.
    r = _put(client, "openai", "")
    assert r.status_code == 200 and r.json()["model"] == ""
    assert _managed(core) == {"provider": "openai"}
    # The same save again writes nothing.
    before = len(runner.calls)
    assert _put(client, "openai", "").status_code == 200
    assert not [c for c in runner.calls[before:] if "config" in c and "set" in c]
    # Hermes refuses a profile's own provider while the scope pins it.
    with pytest.raises(EngineError):
        core.engine._hermes(b, "config", "set", "stt.provider", "local")
    # Off again: the switch, no provider, no model.
    r = _put(client, "off", "whatever")
    assert r.status_code == 200 and (r.json()["provider"], r.json()["model"]) == ("off", "")
    assert _managed(core) == {"enabled": False}


def test_wrong_choices_are_refused(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    ws(client, "Alpha")
    assert _put(client, "whisperx", "base").status_code == 400
    assert _put(client, "local_command", "").status_code == 400  # not offered
    assert _put(client, "groq", "bad model; rm -rf").status_code == 400
    assert _managed(core) == {"enabled": False}  # still off


def test_old_copies_move_in_once_to_the_most_common_then_go(env: Any) -> None:  # noqa: F811
    """Before the card every profile held its own stt.* (AGOS's start values,
    Fuel Machine on Hermes's legacy `local`). The move takes the most common
    provider and its model, and the copies go: Fuel Machine hears with Gemini."""
    client, core, _runner, _home = env
    a, b, fuel = ws(client, "Alpha"), ws(client, "Beta"), ws(client, "Fuel Machine")
    add_agent(client, a, "writer")
    core.engine.managed_write([], ["stt.enabled", "stt.provider", "stt.gemini.model"])
    assert _managed(core) == {}
    for key in (a, f"{a}--a-writer", b):
        core.engine.unmanaged_hermes(key, "config", "set", "stt.provider", "gemini")
        core.engine.unmanaged_hermes(key, "config", "set", "stt.gemini.model", GEMINI)
    core.engine.unmanaged_hermes(fuel, "config", "set", "stt.provider", "local")
    core.engine.unmanaged_hermes(fuel, "config", "set", "stt.local.model", "base")
    moved = hermes_managed.move_once(core)
    assert set(moved) == {"stt.provider", "stt.gemini.model"}  # never local's model
    assert _managed(core) == {"provider": "gemini", "gemini": {"model": GEMINI}}
    hermes_managed.settle(core)
    for key in (a, f"{a}--a-writer", b, fuel):
        own = _own(core, key)
        assert "provider" not in own, key
        assert "model" not in (own.get("gemini") or {}), key
    assert hermes_managed.move_once(core) == []  # once
    view = client.get("/preferences/hermes-voice").json()
    assert (view["provider"], view["model"]) == ("gemini", GEMINI)


def test_the_most_common_provider_brings_its_own_model(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b, c = ws(client, "Alpha"), ws(client, "Beta"), ws(client, "Cedar")
    core.engine.managed_write([], ["stt.enabled", "stt.provider", "stt.gemini.model"])
    for key in (a, b):
        core.engine.unmanaged_hermes(key, "config", "set", "stt.provider", "groq")
        core.engine.unmanaged_hermes(key, "config", "set", "stt.groq.model", "whisper-large-v3")
    core.engine.unmanaged_hermes(c, "config", "set", "stt.provider", "gemini")
    core.engine.unmanaged_hermes(c, "config", "set", "stt.gemini.model", "gemini-x")
    hermes_managed.move_once(core)
    assert _managed(core) == {"provider": "groq", "groq": {"model": "whisper-large-v3"}}


def test_no_agos_writer_sets_stt_per_profile_and_the_settings_page_shows_the_card(
    env: Any,  # noqa: F811
) -> None:
    from agos_core.actions import hermes_all_settings
    from agos_core.engine import owner_choices, rules

    assert "stt.provider" in hermes_managed.by_card()
    assert hermes_managed.by_card()["stt.gemini.model"] == "voice"
    config = rules.profile_config(image="i:1", mounts=[])
    assert "stt.provider" not in config and "stt.gemini.model" not in config
    assert "stt.provider" not in owner_choices.WHY
    assert hermes_all_settings.card_keys()["stt.provider"] == "voice"
    assert "Voice notes" in hermes_all_settings.CARD_LABELS["voice"]
    client, core, _runner, _home = env
    ws(client, "Alpha")
    core.engine.config_schema = lambda: []
    rows = {r["key"]: r for r in hermes_all_settings.read(core)["settings"]}
    row = rows["stt.enabled"]
    assert not row["editable"] and row["rule"]["card"] == "voice"
