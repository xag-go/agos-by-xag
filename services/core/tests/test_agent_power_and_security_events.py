"""Rogue-agent alert and security events (wave 2, read vs act lane).

- An agent working alone (a card's worker, an automation's run) that creates an
  automation, MCP server, skill or key, or any burst of power actions, is told to the
  owner as his Notifications setting says (event `agos.agent_power`).
- Refused requests (a wrong internal token, a wrong bridge key, a Host or Origin the
  web refused) land in the System Log with source `security`, rate-limited, never
  with the value that was given.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture

from agos_core.actions import agent_power, cofounder_actions, hermes_channel, security_events
from agos_core.actions.notification_rules import save_notifications

AUTOMATION = {
    "do": "create_automation",
    "name": "Nightly",
    "schedule": "0 3 * * *",
    "instructions": "a",
}


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    agent_power._recent.clear()
    agent_power._told_burst.clear()
    security_events.reset()
    yield
    agent_power._recent.clear()
    agent_power._told_burst.clear()
    security_events.reset()


def _told(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    from agos_core.actions import digest
    from agos_core.actions.services.channel import owner_needs

    seen: dict[str, list[str]] = {"chat": [], "push": [], "digest": []}
    monkeypatch.setattr(
        owner_needs, "tell_owner", lambda core, ws, text, chat_id=None: seen["chat"].append(text)
    )
    monkeypatch.setattr(
        owner_needs, "push", lambda core, ws, text, source, **k: seen["push"].append(text)
    )
    monkeypatch.setattr(digest, "hold", lambda core, ws, event, text: seen["digest"].append(text))
    return seen


def _cofounder(core: Any, ws: str) -> None:
    from agos_core.actions.workers import open_dm

    open_dm(core, ws, None)


def _activity(core: Any) -> list[str]:
    rows = core.db.execute("SELECT text FROM activity WHERE kind = 'agent.power' ORDER BY id")
    return [str(r["text"]) for r in rows]


# ---- the rogue-agent alert -------------------------------------------------------------


def test_an_automation_made_by_a_run_is_told_to_the_owner(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    cofounder_actions.set_mode(core, "direct")
    _cofounder(core, ws)
    seen = _told(monkeypatch)
    said = hermes_channel.run_actions(core, ws, "kanban:t_rogue1", [AUTOMATION])
    assert said["results"][0]["status"] == "done", said
    [text] = _activity(core)
    assert "an automation" in text and "board card" in text
    assert seen["chat"] == [text] and seen["push"] == [text]


def test_the_owners_notification_setting_is_respected(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    seen = _told(monkeypatch)
    save_notifications(core, {agent_power.EVENT: "silent"})
    agent_power.tell(core, ws, "An agent made an automation by itself.")
    assert seen == {"chat": [], "push": [], "digest": []}
    assert _activity(core) == ["An agent made an automation by itself."]  # still in the log
    save_notifications(core, {agent_power.EVENT: "batched"})
    agent_power.tell(core, ws, "again")
    assert seen["digest"] == ["again"] and seen["push"] == []


def test_a_clean_owner_chat_creation_is_not_an_alert(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    seen = _told(monkeypatch)
    agent_power.noted(core, ws, "agos:1", ["create_automation", "create_mcp"])
    assert seen["chat"] == [] and _activity(core) == []


def test_a_burst_of_power_actions_is_told_once(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env
    seen = _told(monkeypatch)
    agent_power.noted(core, ws, "agos:1", ["update_skill"] * agent_power.BURST)
    assert seen["chat"] == []
    agent_power.noted(core, ws, "agos:1", ["update_skill"])  # the 11th within 5 minutes
    assert len(seen["chat"]) == 1 and "11 changes" in seen["chat"][0]
    agent_power.noted(core, ws, "agos:1", ["update_skill"] * 5)
    assert len(seen["chat"]) == 1  # told once per window
    agent_power.noted(core, ws, "agos:1", ["create_label"] * 50)  # work, not power
    assert len(seen["chat"]) == 1


def test_a_failing_alert_never_changes_what_was_done(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _client, core, _cron, ws = env

    def broken(*a: Any, **k: Any) -> None:
        raise RuntimeError("phone down")

    monkeypatch.setattr(agent_power, "tell", broken)
    agent_power.noted(core, ws, "cron:job", ["create_automation"])  # no raise


# ---- security events -------------------------------------------------------------------


def _security_rows(core: Any) -> list[str]:
    rows = core.db.execute("SELECT text FROM system_log WHERE source = 'security' ORDER BY id")
    return [str(r["text"]) for r in rows]


def test_a_wrong_internal_token_is_logged_without_the_token(env: Any) -> None:  # noqa: F811
    client, core, _cron, _ws = env
    r = client.get("/workspaces", headers={"x-agos-internal": "guess-1234567890-abcdef"})
    assert r.status_code == 401
    [text] = _security_rows(core)
    assert "internal token" in text and "/workspaces" in text and "wrong" in text
    assert "guess-1234567890" not in text


def test_a_wrong_bridge_key_is_logged_without_the_key(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    r = client.post(
        f"/hermes-bridge/{ws}/tool-check",
        json={"tool": "agos_action", "args": {}},
        headers={"authorization": "Bearer stolen-key-0123456789"},
    )
    assert r.status_code == 401
    [text] = _security_rows(core)
    assert "bridge" in text and "stolen-key" not in text


def test_security_events_are_rate_limited(env: Any) -> None:  # noqa: F811
    client, core, _cron, _ws = env
    for _ in range(security_events.PER_WINDOW + 10):
        client.get("/workspaces", headers={"x-agos-internal": "nope"})
    assert len(_security_rows(core)) == security_events.PER_WINDOW


def test_the_web_tells_a_refused_host(env: Any) -> None:  # noqa: F811
    client, core, _cron, _ws = env
    r = client.post(
        "/security/events",
        json={"kind": "host", "where": "/w/x?token=abc", "detail": "evil.example:3000"},
    )
    assert r.status_code == 204
    [text] = _security_rows(core)
    assert "Host" in text and "evil.example:3000" in text and "token=abc" not in text
    # Only the web's own kinds come this way.
    bad = client.post("/security/events", json={"kind": "bridge_key"})
    assert bad.status_code == 422
