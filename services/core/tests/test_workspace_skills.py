"""Each workspace owns its skills: ONE folder in its root that its Co-Founder and every
member read, so a Co-Founder's change reaches the whole team and no other workspace."""

import json
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_cofounder_actions import _run
from test_engine_sync import profile_dir
from test_library import SKILL, env, skill, ws  # noqa: F401 - fixture

from agos_core.actions import workspace_skills


def _folder(home: Path, w: str) -> Path:
    return profile_dir(home, f"agos-{w}") / "skills" / "agos-library"


def test_every_member_reads_its_workspace_folder_and_the_cofounder_has_it_as_its_own(
    env: Any,  # noqa: F811
) -> None:
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    skill(client, a)
    add_agent(client, a, "script-writer")
    add_agent(client, b, "editor")
    own_a, own_b = str(_folder(home, a)), str(_folder(home, b))
    member = json.loads(runner.config[f"agos-{a}--a-script-writer"]["skills.external_dirs"])
    cofounder = json.loads(runner.config[f"agos-{a}"]["skills.external_dirs"])
    assert own_a in member and own_b not in member
    assert own_a not in cofounder  # the Co-Founder's local skills, never "someone else's"
    shared = [str(d) for d in workspace_skills.shared_dirs(core)]
    assert cofounder == shared and member == [*shared, own_a]
    old = str(core.layout.global_dir / "skills")
    assert old not in member and old not in cofounder
    other = json.loads(runner.config[f"agos-{b}--a-editor"]["skills.external_dirs"])
    assert own_b in other and own_a not in other
    # The same skills off for the member as for its Co-Founder.
    sid = client.get(f"/workspaces/{a}/skills").json()[0]["id"]
    assert client.put(f"/workspaces/{a}/connectors/{sid}", json={"on": False}).status_code == 204
    off = json.loads(runner.config[f"agos-{a}--a-script-writer"]["skills.disabled"])
    assert "invoice-check" in off


def test_a_cofounders_edit_is_what_every_member_reads(env: Any) -> None:  # noqa: F811
    """update_skill writes the workspace's one folder (Hermes's skill_manage in the
    root): the member's external folder IS that folder, so it reads the new text.
    Undo is Hermes's ledger rollback of that same file."""
    client, core, runner, home = env
    a = ws(client, "Alpha")
    skill(client, a)
    add_agent(client, a, "script-writer")
    [card] = _run(
        core, a, {"do": "update_skill", "name": "invoice-check", "add_instructions": "2. Fix it."}
    )
    assert card["status"] == "done", card
    member = json.loads(runner.config[f"agos-{a}--a-script-writer"]["skills.external_dirs"])
    read = Path(member[-1]) / "invoice-check" / "SKILL.md"
    assert "2. Fix it." in read.read_text()
    assert read == _folder(home, a) / "invoice-check" / "SKILL.md"
    assert not (
        profile_dir(home, f"agos-{a}--a-script-writer") / "skills" / "agos-library"
    ).exists()
    client.post(f"/workspaces/{a}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert "2. Fix it." not in read.read_text() and "1. Read it." in read.read_text()


def test_creating_a_skill_touches_no_other_workspace(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    before = len(runner.calls)
    b_config = dict(runner.config[f"agos-{b}"])
    [card] = _run(
        core,
        a,
        {
            "do": "create_skill",
            "name": "hook-writer",
            "description": "Use when writing video hooks.",
            "instructions": "Write 3 hooks.",
        },
    )
    assert card["status"] == "done", card
    assert not [c for c in runner.calls[before:] if any(f"agos-{b}" in str(x) for x in c)]
    assert runner.config[f"agos-{b}"] == b_config
    assert (_folder(home, a) / "hook-writer" / "SKILL.md").is_file()
    assert not (_folder(home, b) / "hook-writer").exists()
    on = {c["name"] for c in client.get(f"/workspaces/{a}/connectors").json() if c["on"]}
    assert "hook-writer" in on


def test_a_copy_from_another_workspace_is_independent(env: Any) -> None:  # noqa: F811
    client, _core, _runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    sid = skill(client, a)
    picture = _folder(home, a) / "invoice-check" / "assets" / "logo.png"
    picture.parent.mkdir(parents=True)
    picture.write_bytes(b"\x89PNG\x00\xff")
    copyable = client.get(f"/workspaces/{b}/skills/copyable").json()
    assert [(c["id"], c["workspace"]) for c in copyable] == [(sid, "Alpha")]
    assert client.get(f"/workspaces/{a}/skills/copyable").json() == []
    r = client.post(f"/workspaces/{b}/skills/copy", json={"itemId": sid})
    assert r.status_code == 201, r.text
    mine = r.json()["id"]
    assert mine != sid
    copied = _folder(home, b) / "invoice-check"
    assert (copied / "SKILL.md").read_text() == SKILL
    assert (copied / "assets" / "logo.png").read_bytes() == b"\x89PNG\x00\xff"
    # Each changes alone.
    changed = SKILL + "\n2. Only in Beta.\n"
    r = client.put(
        f"/workspaces/{b}/skills/{mine}",
        json={"name": "invoice-check", "definition": {"text": changed}},
    )
    assert r.status_code == 204, r.text
    assert "Only in Beta" in (copied / "SKILL.md").read_text()
    assert (_folder(home, a) / "invoice-check" / "SKILL.md").read_text() == SKILL
    assert client.delete(f"/workspaces/{a}/skills/{sid}").status_code == 204
    assert (copied / "SKILL.md").is_file()
    assert [i["name"] for i in client.get(f"/workspaces/{b}/skills").json()] == ["invoice-check"]


def test_a_member_cannot_change_its_workspace_skills_but_the_cofounder_can(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    """agos-guard asks Hermes's own ownership test (is_external_skill_path): the
    workspace folder is external for a member (refused), local for its Co-Founder."""
    import sys
    import types

    from agos_core.hermes_plugin import agos_guard

    client, _core, _runner, home = env
    a = ws(client, "Alpha")
    skill(client, a)
    found = _folder(home, a) / "invoice-check"
    external: list[Path] = []
    skill_utils = types.ModuleType("agent.skill_utils")
    skill_utils.is_external_skill_path = lambda p: any(  # type: ignore[attr-defined]
        Path(p).is_relative_to(d) for d in external
    )
    tool = types.ModuleType("tools.skill_manager_tool")
    tool._find_skill = lambda name: {"path": found} if name == "invoice-check" else None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "agent.skill_utils", skill_utils)
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", tool)
    args = {"action": "patch", "name": "invoice-check"}
    assert agos_guard.shared_skill("invoice-check", args) is False  # the Co-Founder
    external.append(_folder(home, a))  # a member: its skills.external_dirs
    assert agos_guard.shared_skill("invoice-check", args) is True
