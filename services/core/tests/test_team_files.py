"""One copy of the team's texts: playbooks/{agents,automations} show what the team
uses (a view), cards change it, old masters adopted. Skills are not copied there:
agents read them natively (Hermes's skills, from the shared library folder)."""

from pathlib import Path
from typing import Any

from test_automations import MODEL, env  # noqa: F401 - fixture
from test_cofounder_actions import _member, _run

from agos_core.actions import team_files
from agos_core.db import library as library_repo
from agos_core.storage.layout import workspace_paths

SKILL = "---\nname: {n}\ndescription: Use when testing. Does a test.\n---\n\n# {n}\n\n{body}\n"


def _books(core: Any, ws: str) -> Path:
    return workspace_paths(core.layout, ws).files / "playbooks"


def test_skill_cards_change_hermes_skills_not_a_playbooks_copy(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    [card] = _run(
        core,
        ws,
        {
            "do": "create_skill",
            "name": "fact-checking",
            "description": "Use when checking facts. Checks them.",
            "instructions": "Step 1.\n```bash\nls\n```",
            "files": {"references/sources.md": "Source A", "scripts/check.py": "print(1)"},
        },
    )
    assert card["status"] == "done", card
    team_files.sync(core, ws)
    assert not (_books(core, ws) / "skills").exists()
    own = core.engine.profile_home(ws) / "skills" / "agos-library" / "fact-checking"
    assert "Step 1." in (own / "SKILL.md").read_text()
    assert (own / "references" / "sources.md").read_text() == "Source A"
    # A change made by the Co-Founder is the workspace's one copy (its whole team reads it).
    [edit] = _run(
        core,
        ws,
        {
            "do": "update_skill",
            "name": "fact-checking",
            "add_instructions": "Step 2.",
            "files": {"scripts/check.py": "", "references/more.md": "B"},
        },
    )
    assert edit["status"] == "done", edit
    assert "Step 2." in (own / "SKILL.md").read_text()
    assert (own / "references" / "sources.md").read_text() == "Source A"
    assert (own / "references" / "more.md").read_text() == "B"
    assert not (own / "scripts" / "check.py").exists()
    # Undo: Hermes's rollback of that change.
    from agos_core.actions import cofounder_actions

    cofounder_actions.decide(core, ws, edit["id"], "undo")
    assert "Step 2." not in (own / "SKILL.md").read_text()
    assert (own / "scripts" / "check.py").read_text() == "print(1)"
    assert not (_books(core, ws) / "skills").exists()


def test_an_agent_and_an_automation_show_and_go_away(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    _member(_client, ws, "writer", instructions="Write.")
    _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Monday Ideas",
            "instructions": "Go.",
            "schedule": "0 9 * * 1",
        },
    )
    team_files.sync(core, ws)
    agent = _books(core, ws) / "agents" / "writer.md"
    auto = _books(core, ws) / "automations" / "monday-ideas.md"
    assert "Write." in agent.read_text() and "Go." in auto.read_text()
    core.db.execute("DELETE FROM automations WHERE workspace_id = ?", (ws,))
    team_files.sync(core, ws)
    assert not auto.exists()


def test_the_view_follows_and_outside_edits_are_not_a_second_copy(
    env: Any,  # noqa: F811
) -> None:
    """One editable copy: the agent in AGOS. playbooks/ only shows it: a file
    changed there by hand is put back."""
    _client, core, _cron, ws = env
    _member(_client, ws, "writer", instructions="Write.")
    team_files.sync(core, ws)
    agent = _books(core, ws) / "agents" / "writer.md"
    agent.write_text(agent.read_text().replace("Write.", "Write in Darija."))
    team_files.sync(core, ws)
    from agos_core.actions import team

    writer = team.get(core, ws, "writer")
    assert writer is not None and writer.instructions == "Write."  # its Hermes profile
    assert "Write." in agent.read_text() and "Darija" not in agent.read_text()
    assert not hasattr(team_files, "take_in")
    team_files.refresh_all(core)
    assert not list(_books(core, ws).rglob(team_files.MANIFEST))


def test_the_view_is_rewritten_only_when_a_source_changed(env: Any) -> None:  # noqa: F811
    """No timer rewrite: refresh_all writes a view only when Hermes's files, AGOS's
    rows or the view's own files changed since it last wrote it."""
    _client, core, _cron, ws = env
    _member(_client, ws, "writer", instructions="Write.")
    team_files._written_from.clear()
    assert team_files.refresh_all(core) == 1  # first pass after a start
    assert team_files.refresh_all(core) == 0  # nothing changed: nothing written
    agent = _books(core, ws) / "agents" / "writer.md"
    written = agent.stat().st_mtime_ns
    assert team_files.refresh_all(core) == 0 and agent.stat().st_mtime_ns == written
    from agos_core.actions import team

    soul = team.home(core, ws, "writer") / "SOUL.md"  # type: ignore[operator]
    soul.write_text(soul.read_text().replace("Write.", "Write short."))  # edited in Hermes
    assert team_files.refresh_all(core) == 1
    assert "Write short." in agent.read_text()
    agent.write_text("hand edit")  # from outside the sandbox: put back
    assert team_files.refresh_all(core) == 1
    assert "Write short." in agent.read_text()
    assert team_files.refresh_all(core) == 0


def test_the_old_skills_view_goes_once(env: Any) -> None:  # noqa: F811
    """playbooks/skills from before: only what AGOS wrote there (as it wrote it)
    is removed; anything else is left alone. Safe to repeat."""
    _client, core, _cron, ws = env
    from agos_core.db.app_settings import set_setting

    base = _books(core, ws)
    team_files.sync(core, ws)
    old = base / "skills" / "notes"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("as AGOS wrote it")
    (base / "skills" / "other.md").write_text("not AGOS's")
    written = team_files._manifest(core, ws) | {
        "skills/notes/SKILL.md": team_files._hash(b"as AGOS wrote it")
    }
    set_setting(core.db, team_files.WRITTEN_KEY.format(ws), written)
    for _ in range(2):
        team_files.sync(core, ws)
        assert not old.exists()
        assert (base / "skills" / "other.md").read_text() == "not AGOS's"
    assert not any(k.startswith("skills/") for k in team_files._manifest(core, ws))


def test_docs_cant_be_written_into_the_team_folders(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    [card] = _run(
        core,
        ws,
        {"do": "update_doc", "path": "skills/x/SKILL.md", "why": "w", "text": "hack"},
    )
    assert card["status"] == "failed" and "update_skill" in card["error"]
    [card] = _run(
        core,
        ws,
        {"do": "update_doc", "path": "agents/x.md", "why": "w", "text": "hack"},
    )
    assert card["status"] == "failed" and "update_agent" in card["error"]


def test_old_masters_are_adopted_once(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    _run(
        core,
        ws,
        {
            "do": "create_skill",
            "name": "notes",
            "description": "Use when x. Y.",
            "instructions": "A",
        },
    )
    notes = library_repo.find_item(core.db, "skill", "notes", ws)
    assert notes is not None
    skill = core.engine.profile_home(ws) / "skills" / "agos-library" / "notes"
    used = (skill / "SKILL.md").read_text()
    base = _books(core, ws)
    core.db.execute(
        "DELETE FROM app_settings WHERE key = ?", (team_files.WRITTEN_KEY.format(ws),)
    )  # a workspace from before: never adopted
    old = base / "skills" / "notes"
    old.mkdir(parents=True, exist_ok=True)
    (old / "SKILL.md").write_text(used)
    (old / "references").mkdir(exist_ok=True)
    (old / "references" / "study.md").write_text("only in the master")
    (base / "agents" / "final").mkdir(parents=True, exist_ok=True)
    (base / "agents" / "final" / "writer.txt").write_text("old master")
    team = base.parent / ".agos" / "team"
    team.mkdir(parents=True, exist_ok=True)
    (team / "skill-notes.md").write_text("copy")
    report = team_files.adopt(core, ws)
    assert report["files_added"] == ["notes/references/study.md"]
    archived = base.parent / report["archived"]
    assert (archived / "agents" / "final" / "writer.txt").read_text() == "old master"
    assert not team.exists()
    # The extra file joined the skill, in the workspace's folder Hermes reads.
    assert (skill / "references" / "study.md").read_text() == "only in the master"
    assert not (base / "skills").exists()
    assert not (base / "agents" / "final").exists()
    # Once only.
    assert team_files.adopt(core, ws)["archived"] is None


def test_the_cofounder_is_told_where_the_team_lives(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    from agos_core.actions import cofounder_actions

    text = cofounder_actions.instructions(core, ws)
    assert "skill_view" in text and "agents/<ID>.md" in text and ".agos/team" not in text
    assert "skills/<ID>/" not in text
    assert MODEL
