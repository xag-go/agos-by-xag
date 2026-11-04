"""A new workspace starts on the owner's own General config; he changes it after.
Both live in the workspace's own Hermes: its approvals.mode, and the agos-guard
plugin's file for the Autonomy rules."""

import json
from typing import Any

import channels_rig
from test_library import MODEL

from agos_core.actions import autonomy
from agos_core.hermes_plugin.agos_guard import POLICY_FILE

env, fake_telegram = channels_rig.env, channels_rig.fake_telegram  # with an engine


def test_new_workspace_starts_on_owner_config(env: Any) -> None:
    client, core, _fake, _tg, _ws = env
    ws = client.post("/workspaces", json={"name": "Fresh Team", "defaultModel": MODEL}).json()["id"]

    assert client.get(f"/workspaces/{ws}").json()["chatAccess"] == "full"
    rules = autonomy.shown_rules(core, ws)  # the card (memory: Hermes's write_approval)
    everyone = rules["*"]
    assert everyone["messages"] == "do"
    assert everyone["apps_change"] == everyone["cards"] == "do"
    assert everyone["apps_delete"] == "ask"  # deleting in a connected app asks first
    for k in ("files", "commands", "browser", "desktop", "images", "memory"):
        assert everyone[k] == "do"
    cofounder = {**everyone, **rules[""]}
    assert all(v == "do" for v in cofounder.values())

    # The one copy is the plugin's own file in its Hermes.
    policy = core.engine.profile_home(ws) / POLICY_FILE
    written = json.loads(policy.read_text())["rules"]
    assert written["*"]["messages"] == "do" and written[""]["apps_delete"] == "do"
    assert policy.stat().st_mode & 0o777 == 0o600

    # He changes it himself, and it sticks (in that file).
    autonomy.set_rule(core, ws, "*", "messages", "ask")
    assert autonomy.rules(core, ws)["*"]["messages"] == "ask"
    assert json.loads(policy.read_text())["rules"]["*"]["messages"] == "ask"
    # A later write of the file (the members' menu) keeps his rules.
    autonomy.write_policy(core, ws)
    assert autonomy.rules(core, ws)["*"]["messages"] == "ask"


def test_a_new_workspaces_model_is_the_shared_hermes_homes(env: Any) -> None:
    """The New workspace form starts on the shared Hermes home's own model (the home
    General Settings writes), not on a model written in the web; null while Hermes
    has none there (its default config leaves model.default empty)."""
    import time

    client, core, _fake, _tg, _ws = env
    config = core.engine.settings.hermes_home / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model:\n  default: ''\n  provider: auto\n")
    assert client.get("/models/default").json() is None

    time.sleep(0.01)
    config.write_text(
        "model:\n  default: claude-sonnet-4-6\n  provider: anthropic\n"
        "agent:\n  reasoning_effort: high  # owner\n"
    )
    assert client.get("/models/default").json() == {
        "provider": "claude",
        "mode": "cli",
        "model": "claude-sonnet-4-6",
        "effort": "high",
    }
