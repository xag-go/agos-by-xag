"""#13: an agent's memory/skills "Ask me" (Autonomy → Learn) is Hermes's own review
gate in that agent's profile: `memory.write_approval` and `skills.write_approval`
(H: hermes_cli/config_defaults.py; tools/write_approval.py evaluate_gate). Hermes
then holds the write for his review (Workspace → Held-back writes), and the guard
asks no second time (agos_guard.one_gate)."""

from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, hermes_all_settings
from agos_core.engine import config_file

GATES = ("memory.write_approval", "skills.write_approval")


def _gates(home: Any) -> list[Any]:
    cfg = config_file.read(home)
    return [config_file.get(cfg, k) for k in GATES]


def _rule(client: Any, a: str, agent: str, choice: str | None) -> None:
    r = client.put(
        f"/workspaces/{a}/autonomy", json={"agent": agent, "action": "memory", "choice": choice}
    )
    assert r.status_code == 204, r.text


def test_ask_me_on_learning_is_hermess_write_approval_per_profile(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    agent = next(
        x["id"]
        for x in client.get(f"/workspaces/{a}/autonomy").json()["agents"]
        if x["id"] not in ("*", "")
    )
    root = core.engine.profile_home(a)
    member = core.engine.profile_home(agent_profiles.key(a, agent))
    _rule(client, a, "*", "ask")
    assert _gates(root) == [True, True] and _gates(member) == [True, True]
    # The member's own "Do it": its profile's gate is off, the Co-Founder's stays on.
    _rule(client, a, agent, "do")
    assert _gates(member) == [False, False] and _gates(root) == [True, True]
    _rule(client, a, "*", "do")
    assert _gates(root) == [False, False]
    # A new member under everyone's "Ask me" starts with Hermes's gates on.
    _rule(client, a, "*", "ask")
    add_agent(client, a, "editor")
    assert _gates(core.engine.profile_home(agent_profiles.key(a, "editor"))) == [True, True]


def test_the_gates_are_the_autonomy_cards() -> None:
    keys = hermes_all_settings.card_keys()
    assert all(keys.get(k) == "autonomy" for k in GATES)
    assert "autonomy" in hermes_all_settings.CARD_LABELS


def test_the_ask_me_on_learning_lives_only_in_hermes(env: Any) -> None:  # noqa: F811
    """STEP 32 (925047d area2 P2/W1): the memory/skills "Ask me" is read from each
    profile's Hermes write_approval; AGOS's guard file keeps only "never" (Hermes has
    no deny switch) or "allow" (a member's own exception), and the guard never asks
    for these writes itself: Hermes's gate holds them, Full access or not."""
    import json

    from agos_core.hermes_plugin.agos_guard import decide

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    agent = next(
        x["id"]
        for x in client.get(f"/workspaces/{a}/autonomy").json()["agents"]
        if x["id"] not in ("*", "")
    )
    key = agent_profiles.key(a, agent)
    _rule(client, a, "*", "ask")
    policy = json.loads((core.engine.profile_home(a) / "agos-guard.json").read_text())
    stored = {r.get("memory") for r in policy["rules"].values()}
    assert stored <= {None, "never", "allow"}, stored
    assert decide(policy, "", "memory", {"action": "add"}) is None  # Hermes's gate asks
    assert decide(policy, agent, "skill_manage", {"name": "x"}) is None
    view = client.get(f"/workspaces/{a}/autonomy").json()["rules"]
    assert view["*"]["memory"] == "ask" and "memory" not in view.get(agent, {})
    # Set in Hermes from outside AGOS: the card shows Hermes's value, and another
    # rule change doesn't put AGOS's back.
    core.engine._hermes(key, "config", "set", "memory.write_approval", "false")
    core.engine._hermes(key, "config", "set", "skills.write_approval", "false")
    view = client.get(f"/workspaces/{a}/autonomy").json()["rules"]
    assert view[agent]["memory"] == "do" and view["*"]["memory"] == "ask"
    _rule(client, a, "*", "never")
    _rule(client, a, "*", None)  # back to everyone's default: not never
    assert _gates(core.engine.profile_home(key)) == [False, False]
    r = client.put(
        f"/workspaces/{a}/autonomy", json={"agent": "*", "action": "files", "choice": "ask"}
    )
    assert r.status_code == 204
    assert _gates(core.engine.profile_home(key)) == [False, False]


def test_the_guard_keeps_no_second_memory_gate() -> None:
    from agos_core.hermes_plugin import agos_guard

    assert not hasattr(agos_guard, "one_gate") and not hasattr(agos_guard, "hermes_holds")
