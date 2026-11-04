"""AGOS Brain: ways of working the whole team learned, shared by every workspace,
with nothing of a project in them; each workspace can turn one off ("Not here")."""

from pathlib import Path
from typing import Any

from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run

from agos_core.actions import brain, cofounder_actions


def soul(core: Any, ws: str) -> str:
    """What this workspace's Hermes has of the Brain: the shared skills it reads
    (skills.external_dirs) minus the ones turned off here (skills.disabled)."""
    import json

    config = core.engine.runner.config.get(core.engine.profile(ws), {})
    folders = json.loads(config.get("skills.external_dirs", "[]"))
    off = set(json.loads(config.get("skills.disabled", "[]")))
    texts = []
    for folder in folders:
        for skill in sorted(Path(folder).glob("agos-brain-*/SKILL.md")):
            if skill.parent.name not in off:
                texts.append(skill.read_text())
    assert "Way of working" not in (core.engine.profile_home(ws) / "SOUL.md").read_text()
    return "\n".join(texts)


def second(client: Any, ws: str) -> str:
    model = client.get(f"/workspaces/{ws}").json()["defaultModel"]
    made = client.post("/workspaces", json={"name": "Second", "defaultModel": model})
    return str(made.json()["id"])


def test_a_method_reaches_every_workspace(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    other = second(client, ws)
    r = client.post("/brain", json={"text": "Read the whole error before trying again."})
    assert r.status_code == 201
    mid = r.json()["id"]
    for w in (ws, other):
        assert "Read the whole error before trying again." in soul(core, w)
    # The same method twice is one method.
    again = client.post("/brain", json={"text": "read the whole error before trying again."})
    assert again.json()["id"] == mid
    assert client.put(f"/brain/{mid}", json={"text": "Read errors fully."}).status_code == 204
    assert [m["text"] for m in client.get("/brain").json()] == ["Read errors fully."]
    assert client.delete(f"/brain/{mid}").status_code == 204
    assert "Read errors fully." not in soul(core, other)


def test_not_here_turns_it_off_in_one_workspace_only(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    other = second(client, ws)
    mid = client.post("/brain", json={"text": "Check numbers twice."}).json()["id"]
    r = client.put(f"/workspaces/{ws}/brain/{mid}", json={"used": False})
    assert r.status_code == 204
    assert "Check numbers twice." not in soul(core, ws)
    assert "Check numbers twice." in soul(core, other)
    listed = {m["id"]: m["usedHere"] for m in client.get(f"/workspaces/{ws}/brain").json()}
    assert listed == {mid: False}
    client.put(f"/workspaces/{ws}/brain/{mid}", json={"used": True})
    assert "Check numbers twice." in soul(core, ws)
    assert client.put(f"/workspaces/{ws}/brain/9999", json={"used": False}).status_code == 404


def test_no_length_limit(env: Any) -> None:  # noqa: F811
    """The owner wants no character limit anywhere."""
    client, core, _cron, ws = env
    long = "Step. " * 2_000
    assert client.post("/brain", json={"text": long}).status_code == 201
    assert long.strip() in soul(core, ws)
    assert client.post("/owner-rules", json={"text": long}).status_code == 201


def test_the_cofounder_proposes_one_and_it_waits_for_the_owner(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    text = " ".join(cofounder_actions.instructions(core, ws).split())
    assert "add_method" in text and "no project" in text
    from agos_core.actions import hermes_channel

    item = {"do": "add_method", "text": "Try the cheapest check first.", "why": "worked twice"}
    # Even in direct mode Hermes asks him first (its Allow / Deny before the tool runs).
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [item]})["ask"] is True
    assert brain.list_methods(core) == []
    [card] = _run(core, ws, item)  # he said Allow
    assert card["status"] == "done"
    [m] = brain.list_methods(core)
    assert m["text"] == "Try the cheapest check first." and m["fromWorkspace"] == ws
    cofounder_actions.decide(core, ws, card["id"], "undo")
    assert brain.list_methods(core) == []


def test_purge_forgets_the_workspaces_choices(env: Any) -> None:  # noqa: F811
    client, _core, _cron, ws = env
    other = second(client, ws)
    mid = client.post("/brain", json={"text": "Keep notes short."}).json()["id"]
    client.put(f"/workspaces/{other}/brain/{mid}", json={"used": False})
    client.post(f"/workspaces/{other}/delete", json={"confirm": other})
    client.delete(f"/trash/{other}")
    assert [m["text"] for m in client.get("/brain").json()] == ["Keep notes short."]


def test_agents_cant_change_a_brain_method() -> None:
    """Only the owner changes the Brain (in AGOS): Hermes's skill_manage is refused."""
    from agos_core.hermes_plugin import agos_guard

    hooks: dict[str, Any] = {}

    class Ctx:
        def register_hook(self, name: str, fn: Any) -> None:
            hooks.setdefault(name, fn)  # the guard's own comes first

        def __getattr__(self, _: str) -> Any:
            return lambda *a, **k: None

    agos_guard.register(Ctx())
    verdict = hooks["pre_tool_call"](tool_name="skill_manage", args={"name": "agos-brain-3"})
    assert verdict and verdict["action"] == "block"
    assert hooks["pre_tool_call"](tool_name="skill_manage", args={"name": "my-skill"}) is None


def test_a_method_holds_nothing_of_the_workspace_that_proposed_it(env: Any) -> None:  # noqa: F811
    """Workspaces stay closed: which workspace proposed a method is kept beside the
    shared folder, never in the skill the other workspaces' agents read."""
    _client, core, _cron, ws = env
    mid = brain.add(core, "Check the cheapest thing first.", from_workspace=ws)
    skill = (brain.skills_dir(core) / brain.skill_name(mid) / "SKILL.md").read_text()
    assert ws not in skill
    assert [m["fromWorkspace"] for m in brain.list_methods(core)] == [ws]
    assert not (brain.skills_dir(core) / "origins.json").exists()


def test_a_deleted_methods_number_is_never_reused(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    first = brain.add(core, "One.")
    brain.set_used_here(core, ws, first, False)
    brain.delete(core, first)
    assert brain.skill_name(first) not in brain._disabled(core, ws)
    second = brain.add(core, "Two.")
    assert second != first
    assert [m["usedHere"] for m in brain.list_methods(core, ws)] == [True]
    assert client.get("/brain").json()[0]["text"] == "Two."


def test_agents_cant_change_a_shared_library_skill(tmp_path: Path, monkeypatch: Any) -> None:
    """A skill Hermes reads from skills.external_dirs (the AGOS library, shared by
    every workspace) can't be changed by one workspace's agents; their own local
    skills can, and making a new one is always allowed."""
    import sys
    import types

    from agos_core.hermes_plugin import agos_guard

    local, shared = tmp_path / "home" / "skills", tmp_path / "library"
    (local / "mine").mkdir(parents=True)
    (shared / "invoice-check").mkdir(parents=True)
    found = {"mine": local / "mine", "invoice-check": shared / "invoice-check"}
    utils = types.ModuleType("agent.skill_utils")
    # Hermes's own ownership test (agent/skill_utils.py is_external_skill_path:
    # under skills.external_dirs or a trusted project dir).
    utils.is_external_skill_path = lambda p: Path(p).resolve().is_relative_to(shared.resolve())  # type: ignore[attr-defined]
    fake_tool = types.ModuleType("tools.skill_manager_tool")
    fake_tool._find_skill = lambda n: {"path": found[n]} if n in found else None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.skill_utils", utils)
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", fake_tool)
    assert agos_guard.shared_skill("invoice-check", {"action": "patch"})
    assert not agos_guard.shared_skill("mine", {"action": "patch"})
    assert not agos_guard.shared_skill("invoice-check", {"action": "create"})
    assert not agos_guard.shared_skill("unknown", {"action": "edit"})
