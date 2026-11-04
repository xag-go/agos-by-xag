"""The owner's trusted apps (read vs act, owner decision 2026-11-03 b): an app or MCP
server's answer counts as untrusted unless he put that app on the workspace's list.
Empty by default; he sets it in Settings → Autonomy, and the Co-Founder can propose
it (an owner-only power: its card waits for his yes, then Undo)."""

import json
from typing import Any

from test_library import env, ws  # noqa: F401  (fixture + helper)
from test_proactive import _policy

from agos_core.actions import cofounder_actions, trusted_apps
from agos_core.engine import cofounder_actions as action_rules
from agos_core.engine import power


def test_no_app_is_trusted_until_he_says_so(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    assert trusted_apps.listed(core, a) == []
    assert client.get(f"/workspaces/{a}/autonomy").json()["trustedApps"] == []


def test_he_sets_the_list_and_the_plugin_reads_it(env: Any) -> None:  # noqa: F811
    client, _core, _runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    r = client.put(f"/workspaces/{a}/trusted-apps", json={"apps": ["Linear", "notion", "linear"]})
    assert r.status_code == 204, r.text
    assert _policy(home, a)["trustedApps"] == ["linear", "notion"]
    assert "trustedApps" not in _policy(home, b) or _policy(home, b)["trustedApps"] == []
    assert client.get(f"/workspaces/{a}/autonomy").json()["trustedApps"] == ["linear", "notion"]
    # His Autonomy rules are kept beside it.
    client.put(f"/workspaces/{a}/autonomy", json={"agent": "*", "action": "files", "choice": "ask"})
    assert _policy(home, a)["trustedApps"] == ["linear", "notion"]
    bad = client.put(f"/workspaces/{a}/trusted-apps", json={"apps": ["../etc"]})
    assert bad.status_code == 400


def test_the_cofounder_proposes_it_and_he_says_yes_then_undo(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    kind = action_rules.Action("set_trusted_apps", {"apps": ["github"]})
    assert power.is_power("set_trusted_apps")
    assert action_rules.needs_owner(kind)  # never on the agent's word alone
    cofounder_actions.set_mode(core, "direct")
    from agos_core.actions.workers import open_dm
    from agos_core.db import chats as chats_repo

    chat = int(open_dm(core, a, None))
    turn = chats_repo.insert_turn(
        core.db, chat_id=chat, workspace_id=a, asked_up_to=0, speaker=None
    )
    [action_id] = cofounder_actions.save(core, a, chat, turn, [kind])
    assert trusted_apps.listed(core, a) == []  # waits for his yes
    r = client.post(f"/workspaces/{a}/cofounder-actions/{action_id}", json={"choice": "approve"})
    assert r.status_code == 200 and r.json()["status"] == "done", r.text
    assert trusted_apps.listed(core, a) == ["github"]
    r = client.post(f"/workspaces/{a}/cofounder-actions/{action_id}", json={"choice": "undo"})
    assert r.status_code == 200, r.text
    assert trusted_apps.listed(core, a) == []


def test_a_members_policy_copy_carries_the_list(env: Any) -> None:  # noqa: F811
    client, core, _runner, home = env
    a = ws(client, "Alpha")
    trusted_apps.save(core, a, ["linear"])
    from agos_core.actions import agent_profiles

    member = home / "member"
    member.mkdir()
    agent_profiles._write_policy(core, a, "writer", member)
    target = member / "agos-guard.json"
    assert json.loads(target.read_text())["trustedApps"] == ["linear"]
