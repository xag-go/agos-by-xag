"""Hermes's own settings shown in AGOS: read from and written to the workspace's
Hermes profile, never kept in AGOS."""

from typing import Any

from chat_rig import Env, env  # noqa: F401 — fixture


def test_goal_turns_live_in_hermes(env: Env, monkeypatch: Any) -> None:  # noqa: F811
    client, _fake, core, ws = env
    config: dict[str, str] = {}
    calls: list[tuple[str, ...]] = []

    def hermes(workspace_id: str, *args: str, timeout: float = 60) -> str:
        assert workspace_id == ws
        calls.append(args)
        if args[:2] == ("config", "set"):
            config[args[2]] = args[3]
        if args[:2] == ("config", "unset"):
            config.pop(args[2], None)
        return ""

    from agos_core.engine import config_file, hermes_schema

    def read(home: Any) -> dict[str, Any]:
        return {"goals": {"max_turns": int(config["goals.max_turns"])}} if config else {}

    monkeypatch.setattr(core.engine, "_hermes", hermes)
    monkeypatch.setattr(config_file, "read", read)
    # Hermes's own default, from Hermes's settings list (no copy in AGOS).
    fields = hermes_schema.build({}, {"goals": {"max_turns": 20}}, "")
    monkeypatch.setattr(core.engine, "config_schema", lambda: fields)
    url = f"/workspaces/{ws}/hermes-settings"
    # Unset: no value, Hermes's default beside it (the field's placeholder).
    assert client.get(url).json() == {
        "values": {"goals.max_turns": ""},
        "defaults": {"goals.max_turns": "20"},
    }
    # Saving the form unchanged, or with Hermes's own default, writes nothing.
    for same in ("", "20"):
        assert client.put(url, json={"values": {"goals.max_turns": same}}).status_code == 200
    assert calls == [] and config == {}
    r = client.put(url, json={"values": {"goals.max_turns": "35"}})
    assert r.status_code == 200, r.text
    assert config == {"goals.max_turns": "35"}  # in Hermes, not AGOS
    assert client.get(url).json()["values"]["goals.max_turns"] == "35"
    calls.clear()
    client.put(url, json={"values": {"goals.max_turns": "35"}})
    assert calls == []  # the same value is not written again
    # Back to Hermes's default (or empty): unset, never 20 frozen into the profile.
    client.put(url, json={"values": {"goals.max_turns": "20"}})
    assert config == {} and calls == [("config", "unset", "goals.max_turns")]
    assert client.put(url, json={"values": {"goals.max_turns": "0"}}).status_code == 400
    assert client.put(url, json={"values": {"model.default": "x"}}).status_code == 400
