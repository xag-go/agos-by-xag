"""The owner's yes before AGOS's own tools fails closed (security audit F4).

The plugin asks the core (tool-check) before agos_action / agos_capability; when that
check can't get an answer the tool is refused, never run without his Allow. And the
core does not trust the plugin alone: the bridge's /actions and /capability refuse an
owner-gated call from an owner's chat that tool-check never asked about."""

from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions, hermes_channel

RULE = {"do": "add_owner_rule", "text": "Answer in Darija", "why": "he said so"}
AUTOMATION = {"do": "create_automation", "name": "Daily ideas", "schedule": "0 9 * * *"}


def _chat(core: Any, ws: str) -> str:
    from agos_core.actions.workers import open_dm

    return f"agos:{int(open_dm(core, ws, None))}"


def _post(client: Any, core: Any, ws: str, path: str, body: dict[str, Any]) -> Any:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _saved(core: Any) -> int:
    return int(core.db.execute("SELECT COUNT(*) FROM cofounder_actions").fetchone()[0])


def test_an_owner_gated_batch_never_asked_about_is_refused(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    chat = _chat(core, ws)
    out = _post(client, core, ws, "actions", {"chat": chat, "actions": [RULE]})
    assert out == {"error": hermes_channel.GATE_NOT_ASKED}
    assert _saved(core) == 0


def test_after_tool_check_asked_the_same_batch_goes_on_once(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    chat = _chat(core, ws)
    args = {"actions": [RULE]}
    check = _post(
        client, core, ws, "tool-check", {"tool": "agos_action", "args": args, "chat": chat}
    )
    assert check["ask"] is True
    # Another batch, or another chat, was not asked about.
    other = {"actions": [{**RULE, "text": "something else"}]}
    assert hermes_channel.gate_refusal(core, ws, chat, "agos_action", other)
    assert hermes_channel.gate_refusal(core, ws, "agos:999999", "agos_action", args)
    # The asked batch passes the core's gate, once (a replay is asked again).
    assert hermes_channel.gate_refusal(core, ws, chat, "agos_action", args) is None
    assert hermes_channel.gate_refusal(core, ws, chat, "agos_action", args)


def test_what_needs_no_yes_is_not_held(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    chat = _chat(core, ws)
    cofounder_actions.set_mode(core, "direct")
    assert (
        hermes_channel.gate_refusal(core, ws, chat, "agos_action", {"actions": [AUTOMATION]})
        is None
    )
    capability = {"kind": "app", "name": "github", "on": True}
    assert hermes_channel.gate_refusal(core, ws, chat, "agos_capability", capability) is None
    # A card's worker or an automation's run: its gated actions wait on their card.
    assert (
        hermes_channel.gate_refusal(core, ws, "kanban:t_x1", "agos_action", {"actions": [RULE]})
        is None
    )


def test_in_ask_mode_a_capability_needs_the_check_first(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    chat = _chat(core, ws)
    cofounder_actions.set_mode(core, "ask")
    try:
        body = {"chat": chat, "kind": "app", "name": "github", "on": True, "why": "x"}
        assert _post(client, core, ws, "capability", body) == {
            "error": hermes_channel.GATE_NOT_ASKED
        }
        args = {"kind": "app", "name": "github", "why": "x"}
        check = _post(
            client, core, ws, "tool-check", {"tool": "agos_capability", "args": args, "chat": chat}
        )
        assert check["ask"] is True
        same = {"kind": "app", "name": "github", "on": True}
        assert hermes_channel.gate_refusal(core, ws, chat, "agos_capability", same) is None
    finally:
        cofounder_actions.set_mode(core, "direct")


# ---- the plugin: no answer from AGOS = refused -------------------------------------


def _bridge(monkeypatch: pytest.MonkeyPatch, answer: dict[str, Any] | None) -> Any:
    from agos_core.hermes_plugin.agos_guard import bridge

    monkeypatch.setattr(
        bridge, "bridge", lambda: {"core": "http://127.0.0.1:8766", "workspace": "w", "key": "k"}
    )
    monkeypatch.setattr(bridge, "post", lambda path, body, timeout=30: answer)
    return bridge


def test_the_plugin_refuses_when_the_check_gets_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(monkeypatch, None)  # unreachable, or the 15 s wait ran out
    said = bridge.owner_decides("agos_action", {"actions": [RULE]}, "s1")
    assert said == {"action": "block", "message": bridge.GATE_UNREACHABLE}


def test_the_plugin_refuses_with_no_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.hermes_plugin.agos_guard import bridge

    monkeypatch.setattr(bridge, "bridge", lambda: None)
    said = bridge.owner_decides("agos_capability", {"name": "github"}, "s1")
    assert said is not None and said["action"] == "block"


def test_the_plugin_asks_or_lets_it_run_as_agos_says(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _bridge(monkeypatch, {"ask": False, "message": ""})
    assert bridge.owner_decides("agos_action", {"actions": [AUTOMATION]}, "s1") is None
    bridge = _bridge(monkeypatch, {"ask": True, "message": "🛠 rule"})
    said = bridge.owner_decides("agos_action", {"actions": [RULE]}, "s1")
    assert said is not None and said["action"] == "approve" and said["message"] == "🛠 rule"
