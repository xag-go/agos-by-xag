"""The owner's / Co-Founder's skill writes and "What I learned", run against the
installed Hermes: its skill_manage (atomic batch, past the write_approval gate the
way /skills approve replays), its skill ledger, rollback_entry and read_blob.
Skipped on a machine without Hermes. (One home: a fresh Hermes home's first start
is slow.)"""

from pathlib import Path

import pytest
from test_hermes_writes_live import engine  # noqa: F401 - fixture

from agos_core.engine.hermes import HermesEngine

SKILL = "---\nname: demo\ndescription: A demo skill.\n---\n\n{body}\n"


def test_hermess_own_check_of_a_new_skill_says_what_its_create_says(
    engine: HermesEngine,  # noqa: F811
    tmp_path: Path,
) -> None:
    """The check AGOS runs before it writes a new skill is Hermes's create's own:
    the same refusal (the skill index's description budget), and nothing written."""
    home = tmp_path / "lib"
    home.mkdir()
    long = "---\nname: demo\ndescription: Use when " + "x" * 80 + ".\n---\n\nBody.\n"
    try:
        said = engine.skill_check(home, "demo", long)
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    assert said["ok"] is False and "60-char" in said["error"], said
    assert not (home / "skills" / "demo").exists()
    made = engine.skill_manage(home, "demo", [{"action": "create", "content": long}])
    assert made["ok"] is False and said["error"] in made["error"], (said, made)
    assert engine.skill_check(home, "demo", SKILL.format(body="v1")) == {"ok": True, "error": ""}
    assert not (home / "skills" / "demo").exists()


def _files(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


def test_skill_writes_are_hermess_skill_manage_and_ledger(
    engine: HermesEngine,  # noqa: F811
    tmp_path: Path,
) -> None:
    home = tmp_path / "lib"
    home.mkdir()
    # The agents' gate is on: the owner's own write still goes in (not held).
    (home / "config.yaml").write_text("skills:\n  write_approval: true\n")
    try:
        made = engine.skill_manage(
            home,
            "demo",
            [
                {"action": "create", "content": SKILL.format(body="v1")},
                {"action": "write_file", "file_path": "references/a.md", "file_content": "A"},
            ],
        )
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    assert made["ok"] and len(made["entries"]) == 2, made
    folder = home / "skills" / "demo"
    big = bytes(range(256)) * 4_000  # 1 MB binary, a hidden file, a LICENSE before SKILL.md
    (folder / "assets").mkdir()
    (folder / "assets" / "big.bin").write_bytes(big)
    (folder / ".hidden").write_text("h")
    (folder / "Assets").mkdir()
    (folder / "Assets" / "LICENSE").write_text("MIT")
    edit = engine.skill_manage(
        home,
        "demo",
        [
            {"action": "patch", "content": SKILL.format(body="v2")},
            {"action": "remove_file", "file_path": "references/a.md"},
        ],
        actor="agent",
    )
    assert edit["ok"] and len(edit["entries"]) == 2, edit
    assert _files(folder) == {"SKILL.md", "assets/big.bin", ".hidden", "Assets/LICENSE"}
    # What I learned: Hermes's ledger with the SKILL.md text of each change.
    changes = engine.skill_changes(home)
    patch = next(c for c in changes if c["action"] == "patch")
    assert "v1" in patch["before"] and "v2" in patch["after"] and patch["actor"] == "agent"
    # Undo: Hermes's rollback_entry, newest first; nothing else moves.
    back = engine.skill_rollback(home, ["demo"], edit["entries"])
    assert back["ok"], back
    assert "v1" in (folder / "SKILL.md").read_text()
    assert (folder / "references" / "a.md").read_text() == "A"
    assert (folder / "assets" / "big.bin").read_bytes() == big
    assert {c["id"] for c in engine.skill_changes(home) if c["undone"]} == set(edit["entries"])
    # A file Hermes's tool doesn't write (outside its four folders): refused, nothing changed.
    bad = engine.skill_manage(
        home, "demo", [{"action": "write_file", "file_path": "notes.md", "file_content": "x"}]
    )
    assert not bad["ok"] and "references" in bad["error"] and not (folder / "notes.md").exists()
    # Delete: its ledger keeps the whole package, so the rollback brings all back.
    gone = engine.skill_manage(home, "demo", delete=True)
    assert gone["ok"] and not folder.exists()
    assert engine.skill_rollback(home, ["demo"], gone["entries"])["ok"]
    assert (folder / "assets" / "big.bin").read_bytes() == big


def test_a_skills_history_comes_from_hermess_ledger_with_each_files_content(
    engine: HermesEngine,  # noqa: F811
    tmp_path: Path,
) -> None:
    """Skill versions (engine/hermes.py _SKILL_HISTORY + engine/skill_versions.py):
    the real ledger's entries for ONE skill, oldest first, with the changed files'
    content for the entries not known yet; the versions derived from them are the
    folder's states, a restore plan brings an old one back through skill_manage."""
    import base64

    from agos_core.engine import skill_versions as sv

    home = tmp_path / "lib"
    home.mkdir()
    folder = home / "skills" / "agos-library" / "demo"
    try:
        made = engine.skill_manage(
            home,
            "demo",
            [
                {
                    "action": "create",
                    "content": SKILL.format(body="v1"),
                    "category": "agos-library",
                },
                {"action": "write_file", "file_path": "references/a.md", "file_content": "A"},
            ],
        )
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    assert made["ok"], made
    other = engine.skill_manage(
        home, "other", [{"action": "create", "content": SKILL.format(body="o")}]
    )
    assert other["ok"], other
    edit = engine.skill_manage(
        home,
        "demo",
        [
            {"action": "patch", "content": SKILL.format(body="v2")},
            {"action": "remove_file", "file_path": "references/a.md"},
        ],
        actor="agent",
    )
    assert edit["ok"], edit
    history = engine.skill_history(home, folder, "demo", known=made["entries"])
    assert [e["id"] for e in history] == [*reversed(made["entries"]), *reversed(edit["entries"])]
    assert all("after" not in e for e in history[:2])  # known: no content carried
    patch = next(e for e in history if e["action"] == "patch")
    assert base64.b64decode(patch["before"]["SKILL.md"]).decode() == SKILL.format(body="v1")
    assert base64.b64decode(patch["after"]["SKILL.md"]).decode() == SKILL.format(body="v2")
    removed = next(e for e in history if e["action"] == "remove_file")
    assert removed["before"] == {"references/a.md": base64.b64encode(b"A").decode()}
    assert removed["after"] == {} and removed["paths"] == ["references/a.md"]
    assert {e["actor"] for e in history} == {"user", "agent"}
    # Derived from the whole ledger: v1 = the create (two entries, one write), v2 =
    # the edit; the folder now is v2 (no observed version).
    full = engine.skill_history(home, folder, "demo", known=[])
    versions = sv.derive(
        [],
        full,
        sv.read_folder(folder),
        now="now",
        observed_author="outside",
        observed_action="observed",
    )
    assert [(v.number, v.author, v.action) for v in versions] == [
        (1, "owner", "create"),
        (2, "cofounder", "edit"),
    ]
    assert versions[0].files == {
        "SKILL.md": SKILL.format(body="v1").encode(),
        "references/a.md": b"A",
    }
    assert versions[1].files == {"SKILL.md": SKILL.format(body="v2").encode()}
    assert sorted(versions[0].entries) == sorted(made["entries"])
    # The restore plan for v1, applied as ONE skill_manage batch, is what the folder was.
    text, files, skipped = sv.restore_plan(
        versions[0], sv.read_folder(folder), ("references", "templates", "scripts", "assets")
    )
    assert text == SKILL.format(body="v1") and files == {"references/a.md": "A"} and skipped == []
    from agos_core.actions.skill_writes import ops_for

    back = engine.skill_manage(home, "demo", ops_for(folder, text, files, create=False))
    assert back["ok"] and len(back["entries"]) == 2, back
    assert sv.read_folder(folder) == versions[0].files


_GATE = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import approval
from tools import write_approval as wa
approval.enable_session_yolo("s1")
out = {"yolo": approval.is_approval_bypass_active(), "memory": None, "skills": None}
for sub in (wa.MEMORY, wa.SKILLS):
    d = wa.evaluate_gate(sub)
    out[sub] = "allow" if d.allow else ("stage" if d.stage else "blocked")
print("AGOS-GATE " + json.dumps(out))
"""


def test_hermess_write_gate_holds_under_full_access(
    engine: HermesEngine,  # noqa: F811
    tmp_path: Path,
) -> None:
    """925047d area2 W1: Hermes's memory/skills write_approval has no YOLO bypass
    (H: tools/write_approval.py evaluate_gate), so AGOS's guard needs no Ask of its
    own for these writes under Full access."""
    import json

    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text(
        "memory:\n  write_approval: true\nskills:\n  write_approval: true\n"
    )
    try:
        said = engine._in_runtime(home, _GATE, "AGOS-GATE", extra={"HERMES_YOLO_MODE": "1"})
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    got = json.loads(said)
    assert got["yolo"] is True, got
    assert got["memory"] == "stage" and got["skills"] == "stage", got
