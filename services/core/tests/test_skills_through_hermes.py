"""STEP 32 A: the owner's and the Co-Founder's skill writes are Hermes's own skill tool
(skill_manage) and skill ledger (record_mutation / rollback_entry). No file of a
skill is lost (binary, over 400 KB, hidden, past 200 files), and a Co-Founder's card
keeps only the ledger ids, never a copy of the skill (audit 925047d area1 B3/M3,
area2 B1/C1/M1)."""

import json
from pathlib import Path
from typing import Any

import hermes_skills
from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run

from agos_core.actions import cofounder_actions
from agos_core.actions import library as library_actions
from agos_core.db import library as library_repo

BIG = bytes(range(256)) * 2_000  # 512 KB, binary


def _skill(name: str, body: str) -> dict[str, Any]:
    return {
        "do": "create_skill",
        "name": name,
        "description": "Use when testing. Does a test.",
        "instructions": body,
        "files": {"references/sources.md": "Source A", "scripts/check.py": "print(1)"},
    }


def _odd_files(folder: Path) -> dict[str, bytes]:
    """What AGOS's old writer deleted: binary, big, hidden, and past 200 files."""
    out = {
        "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\xff",
        "assets/big.bin": BIG,
        ".hidden-notes": b"kept",
        "Assets/LICENSE": b"MIT",
    }
    for i in range(205):
        out[f"references/many/{i:03}.md"] = f"n{i}".encode()
    for rel, data in out.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    return out


def _files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def _result(core: Any, action_id: int) -> dict[str, Any]:
    row = core.db.execute(
        "SELECT result FROM cofounder_actions WHERE id = ?", (action_id,)
    ).fetchone()
    found: dict[str, Any] = json.loads(row["result"])
    return found


def test_a_cofounder_skill_edit_keeps_every_file_and_undo_is_hermess_rollback(
    env: Any,  # noqa: F811
) -> None:
    _client, core, _cron, ws = env
    [made] = _run(core, ws, _skill("fact-checking", "Step 1."))
    assert made["status"] == "done", made
    # Hermes's ledger of the workspace's root has the create (its own skills).
    home = core.engine.profile_home(ws)
    assert [e["action"] for e in hermes_skills.entries(home)][-1:] == ["create"]
    [first] = _run(
        core, ws, {"do": "update_skill", "name": "fact-checking", "add_instructions": "Step 2."}
    )
    assert first["status"] == "done", first
    own = home / "skills" / "agos-library" / "fact-checking"
    odd = _odd_files(own)
    [edit] = _run(
        core,
        ws,
        {
            "do": "update_skill",
            "name": "fact-checking",
            "add_instructions": "Step 3.",
            "files": {"scripts/check.py": "", "references/more.md": "B"},
        },
    )
    assert edit["status"] == "done", edit
    assert "Step 3." in (own / "SKILL.md").read_text()
    for rel, data in odd.items():  # nothing it can't read as text is gone
        assert (own / rel).read_bytes() == data, rel
    assert not (own / "scripts" / "check.py").exists()
    assert (own / "references" / "more.md").read_text() == "B"
    # The card keeps Hermes's ledger ids, no copy of the skill.
    kept = _result(core, edit["id"])
    assert "Step 2." not in json.dumps(kept) and "Source A" not in json.dumps(kept)
    ids = {e["id"] for e in hermes_skills.entries(home)}
    assert kept["ledger"]["entries"] and set(kept["ledger"]["entries"]) <= ids
    # Undo: Hermes's rollback_entry, newest first.
    cofounder_actions.decide(core, ws, edit["id"], "undo")
    text = (own / "SKILL.md").read_text()
    assert "Step 2." in text and "Step 3." not in text
    assert (own / "scripts" / "check.py").read_text() == "print(1)"
    assert not (own / "references" / "more.md").exists()
    assert _files(own) >= set(odd)
    assert "rollback" in [e["action"] for e in hermes_skills.entries(home)]


def test_undo_refuses_when_the_skill_changed_since(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    _run(core, ws, _skill("notes", "A."))
    _run(core, ws, {"do": "update_skill", "name": "notes", "add_instructions": "B."})
    [edit] = _run(core, ws, {"do": "update_skill", "name": "notes", "add_instructions": "C."})
    [later] = _run(core, ws, {"do": "update_skill", "name": "notes", "add_instructions": "D."})
    assert later["status"] == "done"
    import pytest

    from agos_core.actions.errors import ActionError

    with pytest.raises(ActionError, match="changed since"):
        cofounder_actions.decide(core, ws, edit["id"], "undo")
    own = core.engine.profile_home(ws) / "skills" / "agos-library" / "notes"
    assert "D." in (own / "SKILL.md").read_text()


def test_the_owners_edit_and_delete_are_hermess_own_tools(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    _run(core, ws, _skill("writing", "v1"))
    row = library_repo.find_item(core.db, "skill", "writing", ws)
    assert row is not None
    folder = core.engine.profile_home(ws) / "skills" / "agos-library" / "writing"
    odd = _odd_files(folder)
    library_actions.save_item(
        core,
        int(row["id"]),
        kind="skill",
        name="writing",
        title="",
        summary="",
        definition={
            "text": "---\nname: writing\ndescription: Use when writing. Writes.\n---\n\nv2\n",
            "files": {"references/sources.md": "Source B"},
        },
        workspace_id=ws,
    )
    assert "v2" in (folder / "SKILL.md").read_text()
    assert (folder / "references" / "sources.md").read_text() == "Source B"
    assert (folder / "scripts" / "check.py").read_text() == "print(1)"  # not named: kept
    for rel, data in odd.items():
        assert (folder / rel).read_bytes() == data, rel
    home = core.engine.profile_home(ws)
    actions = [e["action"] for e in hermes_skills.entries(home)]
    assert actions[:2] == ["write_file", "patch"] and all(
        e["actor"] == "user" for e in hermes_skills.entries(home)[:2]
    )
    library_actions.delete_item(core, int(row["id"]), ws)
    assert not folder.exists()
    # Hermes's curator archive: recoverable, every file kept.
    archived = core.engine.profile_home(ws) / "skills" / ".archive" / "writing"
    for rel, data in odd.items():
        assert (archived / rel).read_bytes() == data, rel


def test_no_agos_skill_folder_writer_is_left() -> None:
    from agos_core.actions import team_files

    assert not hasattr(team_files, "write_skill_folder")
