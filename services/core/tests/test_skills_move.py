"""The one-time move of the old shared skill library into each workspace's own
skills (actions/skills_move.py), on data shaped like live's."""

import json
from pathlib import Path
from typing import Any

from test_agent_profiles import add_agent
from test_engine_sync import profile_dir
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import skills_move, workspace_skills
from agos_core.db.rows import dump_json, now


def _text(name: str, extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: Use when doing {name}.\n---\n\n1. Do {name}.\n{extra}"


SHARED = "make-interfaces-feel-better"
CONTENT_ON = [
    "brand-voice-expansion",
    "learning-topic-cycle",
    "hook-writing",
    "script-polish",
    "caption-style",
    "thumbnail-brief",
    "shorts-cutdown",
    "trend-scan",
    "ideas-bank",
    "weekly-report",
]
CONTENT_OWN = ["brand-voice-expansion", "learning-topic-cycle", "hook-writing", "script-polish"]
LAB_ON = [SHARED, *[f"lab-step-{n}" for n in range(1, 12)]]
SAM_OWN = ["inbox-sweep", "calendar-brief"]
RAP_ON = [SHARED]
EVERY = sorted({*CONTENT_ON, *LAB_ON, *SAM_OWN, *RAP_ON, "never-used"})


def _old_library(core: Any, root: Path) -> dict[str, int]:
    """The old shared rows (no workspace) and their folders, one in a hub category."""
    ids = {}
    for name in EVERY:
        folder = root / ("creative" if name == SHARED else "") / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(_text(name, "Library version.\n"))
        web = name == SHARED
        ids[name] = int(
            core.db.execute(
                """INSERT INTO library_items (kind, name, title, summary, definition, source,
                     created_at, updated_at, workspace_id)
                   VALUES ('skill', ?, '', '', ?, ?, ?, ?, NULL)""",
                (
                    name,
                    dump_json({"identifier": "official/creative/" + name} if web else {}),
                    "web" if web else "created",
                    now(),
                    now(),
                ),
            ).lastrowid
            or 0
        )
    # Files only the library's copy has (the owner's Co-Founder asked to keep them).
    (root / "brand-voice-expansion" / "scripts").mkdir()
    (root / "brand-voice-expansion" / "scripts" / "guide_tool.py").write_text("print('guide')\n")
    (root / "learning-topic-cycle" / "references").mkdir()
    (root / "learning-topic-cycle" / "references" / "topics.md").write_text("theirs topics\n")
    (root / "learning-topic-cycle" / "references" / "cycle.md").write_text("theirs cycle\n")
    # Hermes's hub lock of the old library home knows the web skill.
    (root / ".hub").mkdir()
    entry = {"source": "official", "identifier": f"official/creative/{SHARED}"}
    (root / ".hub" / "lock.json").write_text(
        json.dumps(
            {"version": 1, "installed": {SHARED: {**entry, "install_path": f"creative/{SHARED}"}}}
        )
    )
    return ids


def _own_version(home: Path, w: str, name: str, **files: str) -> Path:
    folder = profile_dir(home, f"agos-{w}") / "skills" / "agos-library" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(_text(name, f"Changed in {w}.\n"))
    for rel, body in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(body)
    (folder.parent / ".agos-sources.json").write_text(json.dumps({name: "base-hash"}))
    return folder


def _set_on(core: Any, w: str, on: list[str]) -> None:
    off = [n for n in EVERY if n not in on]
    core.engine._hermes(w, "config", "set", "skills.disabled", json.dumps(off))


def _rows(core: Any) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in core.db.execute(
        "SELECT name, workspace_id FROM library_items WHERE kind = 'skill' ORDER BY name"
    ):
        out.setdefault(str(r["workspace_id"]), []).append(str(r["name"]))
    return out


def _tree(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()
    }


def test_the_old_library_moves_into_each_workspace_once(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    content, lab = ws(client, "marketing"), ws(client, "lab-builder")
    sam, rap = ws(client, "personal-assistant"), ws(client, "rap-production")
    add_agent(client, content, "script-writer")
    add_agent(client, content, "editor")
    library = core.layout.global_dir / "skills"
    ids = _old_library(core, library)
    core.db.execute(
        "INSERT INTO connector_notes (workspace_id, item_id, notes, updated_at) VALUES (?, ?, ?, ?)",
        (lab, ids[SHARED], "Use it on every page.", now()),
    )
    for w, on in ((content, CONTENT_ON), (lab, LAB_ON), (sam, SAM_OWN), (rap, RAP_ON)):
        _set_on(core, w, on)
    for name in CONTENT_OWN:
        _own_version(home, content, name)
    # Its own copy has a file of the same name: it stays the workspace's.
    _own_version(home, content, "learning-topic-cycle", **{"references/topics.md": "mine\n"})
    for name in SAM_OWN:
        _own_version(home, sam, name)

    moved = skills_move.move_old_shared_skills(core)

    assert sorted(moved[content]) == sorted(CONTENT_ON)
    assert sorted(moved[lab]) == sorted(LAB_ON)
    assert sorted(moved[sam]) == sorted(SAM_OWN) and moved[rap] == [SHARED]
    rows = _rows(core)
    assert "None" not in rows  # the shared rows are gone
    assert {w: sorted(n) for w, n in rows.items()} == {
        content: sorted(CONTENT_ON),
        lab: sorted(LAB_ON),
        sam: sorted(SAM_OWN),
        rap: [SHARED],
    }
    folder = {w: profile_dir(home, f"agos-{w}") / "skills" / "agos-library" for w in rows}
    # An own version stays as it was; the library-only files join it.
    brand = folder[content] / "brand-voice-expansion"
    assert "Changed in" in (brand / "SKILL.md").read_text()
    assert (brand / "scripts" / "guide_tool.py").read_text() == "print('guide')\n"
    cycle = folder[content] / "learning-topic-cycle"
    assert (cycle / "references" / "topics.md").read_text() == "mine\n"  # never overwritten
    assert (cycle / "references" / "cycle.md").read_text() == "theirs cycle\n"
    assert "Library version." in (folder[content] / "trend-scan" / "SKILL.md").read_text()
    assert not (folder[content] / ".agos-sources.json").exists()
    assert not (folder[sam] / ".agos-sources.json").exists()
    # One skill on in two workspaces: two independent copies, each with its row.
    for w in (lab, rap):
        assert (folder[w] / SHARED / "SKILL.md").is_file()
    (folder[lab] / SHARED / "SKILL.md").write_text(_text(SHARED, "Lab only.\n"))
    assert "Lab only." not in (folder[rap] / SHARED / "SKILL.md").read_text()
    shared_rows = core.db.execute(
        "SELECT * FROM library_items WHERE kind = 'skill' AND name = ?", (SHARED,)
    ).fetchall()
    assert len({r["id"] for r in shared_rows}) == 2
    assert {r["source"] for r in shared_rows} == {"web"}
    assert {json.loads(r["definition"])["identifier"] for r in shared_rows} == {
        f"official/creative/{SHARED}"
    }
    # Each workspace's own hub lock now knows its copy (Hermes's check/update work there).
    for w in (lab, rap):
        lock = json.loads((folder[w].parent / ".hub" / "lock.json").read_text())
        assert lock["installed"][SHARED]["install_path"] == f"agos-library/{SHARED}"
        assert lock["installed"][SHARED]["identifier"] == f"official/creative/{SHARED}"
    assert not (folder[content].parent / ".hub" / "lock.json").exists()
    lab_row = next(r for r in shared_rows if r["workspace_id"] == lab)
    notes = core.db.execute(
        "SELECT notes FROM connector_notes WHERE workspace_id = ? AND item_id = ?",
        (lab, lab_row["id"]),
    ).fetchone()
    assert notes["notes"] == "Use it on every page."
    # The old folder is moved aside, never deleted (a skill on nowhere is kept there).
    assert not library.exists()
    [retired] = list(core.layout.global_dir.glob("skills.retired-*"))
    assert (retired / "never-used" / "SKILL.md").is_file()
    assert (retired / "creative" / SHARED / "SKILL.md").is_file()
    # Every profile is written again: the members read their workspace's folder.
    for member in ("script-writer", "editor"):
        dirs = json.loads(runner.config[f"agos-{content}--a-{member}"]["skills.external_dirs"])
        assert str(folder[content]) in dirs and str(library) not in dirs
    for w in rows:
        dirs = json.loads(runner.config[f"agos-{w}"]["skills.external_dirs"])
        assert str(library) not in dirs and str(folder[w]) not in dirs
    turned_on = {
        c["name"] for c in client.get(f"/workspaces/{content}/connectors").json() if c["on"]
    }
    assert set(CONTENT_ON) <= turned_on
    assert {i["name"] for i in client.get(f"/workspaces/{rap}/skills").json()} == {SHARED}

    # Idempotent: a second start finds the move done and changes nothing.
    trees = {w: _tree(folder[w]) for w in rows}
    assert skills_move.move_old_shared_skills(core) == {}
    assert _rows(core) == rows
    assert {w: _tree(folder[w]) for w in rows} == trees
    assert len(list(core.layout.global_dir.glob("skills.retired-*"))) == 1


def test_an_off_skill_with_an_own_version_stays_off_and_a_half_done_move_finishes(
    env: Any,  # noqa: F811
) -> None:
    client, core, runner, home = env
    w = ws(client, "Alpha")
    library = core.layout.global_dir / "skills"
    ids = _old_library(core, library)
    _set_on(core, w, ["hook-writing"])
    _own_version(home, w, "script-polish")  # changed here once, then turned off
    skills_move.move_old_shared_skills(core)
    rows = _rows(core)
    assert sorted(rows[w]) == ["hook-writing", "script-polish"]
    off = json.loads(runner.config[f"agos-{w}"]["skills.disabled"])
    assert "script-polish" in off and "hook-writing" not in off
    assert workspace_skills.existing_dir(core, w, "script-polish") is not None
    gone = "SELECT 1 FROM library_items WHERE id = ?"
    assert all(core.db.execute(gone, (i,)).fetchone() is None for i in ids.values())
    # The folder left behind by a crash after the rows went: moved aside on the next start.
    library.mkdir()
    (library / "late").mkdir()
    (library / "late" / "SKILL.md").write_text(_text("late"))
    assert skills_move.move_old_shared_skills(core) == {}
    assert not library.exists()
    assert len(list(core.layout.global_dir.glob("skills.retired-*"))) == 2
    assert _rows(core) == rows
    # The empty skills/ Hermes makes in the global home stays where it is.
    library.mkdir()
    assert skills_move.move_old_shared_skills(core) == {}
    assert library.is_dir()
    assert len(list(core.layout.global_dir.glob("skills.retired-*"))) == 2
