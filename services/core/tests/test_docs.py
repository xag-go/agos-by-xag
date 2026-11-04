"""Documentation: one home per rule, versions, CHANGES.md, checks, and the rules
each agent reads given to it on every job."""

import io
import os
from pathlib import Path
from typing import Any

import pytest
from work_env import Env, env  # noqa: F401  (fixture)

from agos_core.actions import docs, library
from agos_core.engine import docs as rules
from agos_core.storage.layout import workspace_paths


def test_sections_changes_and_log() -> None:
    text = "# Flow\n\n## 1. Where\nSheets.\n\n## 4. Tracker statuses\nmodification -> Script vN.\n"
    assert [s.number for s in rules.sections(text)] == ["1", "4"]
    assert "Script vN" in (rules.section_text(text, "4") or "")
    after = text.replace("Script vN", "Script vN, back to review")
    assert rules.changed_sections(text, after) == ["4. Tracker statuses"]
    log = rules.add_to_log(
        "# Rule changes\n\n## 2026-01-01 - old\n",
        rules.log_entry("flow.md", "Owner", "Sam asked", ["4. Tracker statuses"]),
    )
    assert log.index("flow.md: 4. Tracker statuses") < log.index("2026-01-01 - old")


def test_checks_find_duplicates_bad_pointers_orphans_and_language() -> None:
    rule = "only Sam moves a task to done in the tracker and nobody else ever does it"
    src = rules.Sources(
        docs={
            "README.md": "map",
            "team.md": f"## 1. Team\n{rule}\n",
            "flow.md": f"## 1. Where\nSheets. See team.md section 1 and team.md section 9.\n{rule}\n",
            "lonely.md": "## 1. X\nnobody reads me\n",
            "CHANGES.md": "## 2026-09-28\n- moved out of flow.md section 7 (history)\n",
        },
        agents={"Script Writer": "Read flow.md section 1. عربية"},
        reads={"Script Writer": ["team.md", "flow.md"]},
        latin_only=True,
    )
    found = rules.check(src)
    kinds = {(f.kind, f.where) for f in found}
    assert ("duplicate", "flow.md") in kinds or ("duplicate", "team.md") in kinds
    assert any(f.kind == "pointer" and "section 9" in f.detail for f in found)
    assert not any(f.kind == "pointer" and "team.md section 1:" in f.detail for f in found)
    assert ("orphan", "lonely.md") in kinds
    # The history may cite a section that moved since: not a broken pointer.
    assert not any(f.kind == "pointer" and f.where == "CHANGES.md" for f in found)
    assert ("language", "agent Script Writer") in kinds


def test_the_check_splits_each_text_once(monkeypatch: Any) -> None:
    """Each agent/skill/automation is compared with the rule files: the rule files
    are split into words once per check, not again for each of them (that was most
    of the Documentation page's 0.2 s)."""
    rule = "only Sam moves a task to done in the tracker and nobody else ever does it"
    split: list[str] = []
    real = rules._words

    def counted(text: str) -> list[str]:
        split.append(text)
        return real(text)

    monkeypatch.setattr(rules, "_words", counted)
    src = rules.Sources(
        docs={"team.md": f"## 1. Team\n{rule}\n", "flow.md": "## 1. Where\nSheets.\n"},
        agents={f"Agent {n}": f"Agent {n} writes scripts. {rule}" for n in range(4)},
        skills={"Hooks": "How a hook is written, step by step."},
        reads={},
    )
    found = rules.check(src)
    assert len(split) == len(set(split))  # every text split once
    assert {f.where for f in found if f.kind == "duplicate"} >= {"agent Agent 0", "agent Agent 3"}


def test_a_workspace_gets_documentation_and_every_change_is_logged(env: Env) -> None:  # noqa: F811
    client, _, _core, ws = env
    listing = client.get(f"/workspaces/{ws}/docs").json()
    paths = [f["path"] for f in listing["files"]]
    assert paths[:3] == ["README.md", "team.md", "flow.md"] and "CHANGES.md" in paths
    flow = client.get(f"/workspaces/{ws}/docs/file", params={"path": "flow.md"}).json()
    new = flow["text"] + "\n## 4. Modification\nA new Script vN, then back to review.\n"
    # No "why": refused.
    assert (
        client.put(
            f"/workspaces/{ws}/docs/file", params={"path": "flow.md"}, json={"text": new, "why": ""}
        ).status_code
        == 422
    )
    saved = client.put(
        f"/workspaces/{ws}/docs/file",
        params={"path": "flow.md"},
        json={"text": new, "why": "Sam explained modification", "base_hash": flow["hash"]},
    ).json()
    assert saved["saved"] is True
    log = client.get(f"/workspaces/{ws}/docs/file", params={"path": "CHANGES.md"}).json()["text"]
    assert "flow.md: 4. Modification" in log and "Why: Sam explained modification" in log
    # Opened before someone else saved: refused, nothing lost.
    stale = client.put(
        f"/workspaces/{ws}/docs/file",
        params={"path": "flow.md"},
        json={"text": "x", "why": "y", "base_hash": flow["hash"]},
    )
    assert stale.status_code == 409
    # Versions, diff and restore.
    versions = client.get(f"/workspaces/{ws}/docs/file", params={"path": "flow.md"}).json()[
        "versions"
    ]
    assert versions[0]["why"] == "Sam explained modification"
    diff = client.get(f"/workspaces/{ws}/docs/versions/{versions[0]['id']}").json()["diff"]
    assert "+## 4. Modification" in diff
    client.post(f"/workspaces/{ws}/docs/versions/{versions[-1]['id']}/restore", json={"why": ""})
    back = client.get(f"/workspaces/{ws}/docs/file", params={"path": "flow.md"}).json()["text"]
    assert "Modification" not in back
    # Never outside the playbooks folder.
    assert (
        client.get(f"/workspaces/{ws}/docs/file", params={"path": "../secret.md"}).status_code
        == 400
    )
    # CHANGES.md is AGOS's.
    assert (
        client.put(
            f"/workspaces/{ws}/docs/file",
            params={"path": "CHANGES.md"},
            json={"text": "x", "why": "y"},
        ).status_code
        == 400
    )


def _agent(core: Any, ws: str, reads: list[dict[str, str]]) -> int:
    return library.save_item(
        core,
        None,
        kind="agent",
        name="script-writer",
        title="Script Writer",
        summary="",
        definition={
            "instructions": "You write scripts. Rules: see flow.md section 1.",
            "reads": reads,
        },
        workspace_id=ws,
    )


def test_a_rule_change_reaches_the_next_job_with_no_agent_text_edited(env: Env) -> None:  # noqa: F811
    _, _, core, ws = env
    docs.ensure(core, ws)
    folder = docs.folder(core, ws)
    (folder / "script-scaffold.md").write_text("# Scaffold\n\n## 1. Template\nThree versions.\n")
    _agent(
        core,
        ws,
        [{"path": "flow.md", "section": "1"}, {"path": "script-scaffold.md", "mode": "demand"}],
    )
    text = library.agent_text(core, ws, "script-writer") or ""
    assert "flow.md section 1" in text and "/workspace/playbooks/script-scaffold.md" in text
    flow = (
        (folder / "flow.md")
        .read_text()
        .replace("Sheets, Drive, boards, apps.", "The Sheet is 'Ideas 2026'.")
    )
    docs.save_doc(core, ws, "flow.md", flow, "Sam gave the sheet")
    assert "The Sheet is 'Ideas 2026'." in (library.agent_text(core, ws, "script-writer") or "")


def test_a_deleted_agent_comes_back_the_same(env: Env) -> None:  # noqa: F811
    client, _, core, ws = env
    docs.ensure(core, ws)
    item = _agent(core, ws, [{"path": "team.md"}])
    library.delete_item(core, item)
    gone = client.get(f"/workspaces/{ws}/docs").json()["deletedAgents"]
    assert [g["name"] for g in gone] == ["script-writer"]
    new_id = client.post(f"/workspaces/{ws}/agents/versions/{gone[0]['id']}/restore").json()["id"]
    from agos_core.actions import team

    back = team.by_id(core, new_id)  # its Hermes profile again
    assert back is not None and back.name == "script-writer" and back.title == "Script Writer"
    assert back.reads == [{"path": "team.md", "section": "", "mode": "always"}]
    assert "flow.md section 1" in back.instructions


def test_the_cofounder_changes_a_rule_file_with_undo(env: Env) -> None:  # noqa: F811
    from agos_core.actions import cofounder_actions

    _, _, core, ws = env
    docs.ensure(core, ws)
    result = cofounder_actions._do(
        core,
        ws,
        "update_doc",
        {"path": "team.md", "why": "Sam: reports in Darija", "add": "## 6. Reports\nIn Darija."},
    )
    assert "## 6. Reports" in (docs.folder(core, ws) / "team.md").read_text()
    cofounder_actions._undo(core, ws, "update_doc", result)
    assert "## 6. Reports" not in (docs.folder(core, ws) / "team.md").read_text()
    log = (docs.folder(core, ws) / "CHANGES.md").read_text()
    assert "Who: Co-Founder" in log and "undo of the Co-Founder's change" in log


def test_existing_documentation_is_never_overwritten(env: Env, tmp_path: Path) -> None:  # noqa: F811
    _, _, core, ws = env
    folder = docs.folder(core, ws)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "flow.md").write_text("# mine\n")
    assert docs.ensure(core, ws) is False
    assert (folder / "flow.md").read_text() == "# mine\n"


# ---- the page answers from what it read last while nothing changed ---------------------


def _workspace_with_notes(core: Any, ws: str) -> Path:
    """A workspace folder with notes in nested folders, and a rule file pointing to
    one that is nowhere (google-sync.md) and one outside playbooks/ (deep.md)."""
    docs.ensure(core, ws)
    files = workspace_paths(core.layout, ws).files
    deep = files / "research" / "2026" / "october"
    deep.mkdir(parents=True)
    (deep / "deep.md").write_text("# Deep\n\n## 1. Notes\nx\n")
    (files / "research" / "sources.txt").write_text("not a note")
    flow = docs.folder(core, ws) / "flow.md"
    flow.write_text(
        flow.read_text() + "\n## 4. Sync\nSee google-sync.md section 4 and deep.md section 1.\n"
    )
    return files


def _pointers(page: dict[str, Any]) -> list[str]:
    return [f["detail"] for f in page["findings"] if f["kind"] == "pointer"]


def test_the_page_twice_lists_the_workspace_and_checks_once(
    env: Env,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing changed between two views: the second lists no folder of the workspace
    again (their stamps only), splits no text again, and opens no file twice; the same
    answer, field by field."""
    client, _, core, ws = env
    files = _workspace_with_notes(core, ws)
    playbooks = docs.folder(core, ws)
    listed: list[str] = []
    real_scandir = os.scandir

    def scandir(path: Any = ".") -> Any:
        listed.append(os.fspath(path))
        return real_scandir(path)

    split: list[str] = []
    real_words = rules._words

    def words(text: str) -> list[str]:
        split.append(text)
        return real_words(text)

    opened: list[str] = []
    real_open = io.open

    def counted_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(file, (str, os.PathLike)):
            opened.append(os.fspath(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(rules, "_words", words)
    monkeypatch.setattr(io, "open", counted_open)

    def workspace_listings() -> list[str]:
        return [p for p in listed if p.startswith(str(files)) and not p.startswith(str(playbooks))]

    first = client.get(f"/workspaces/{ws}/docs").json()
    assert "Points to google-sync.md section 4: no such file." in _pointers(first)
    assert not any("deep.md" in p for p in _pointers(first))  # found outside playbooks/
    assert workspace_listings() and split
    assert len(opened) == len(set(opened)), "a file was opened twice in one view"
    listed.clear()
    split.clear()
    opened.clear()
    second = client.get(f"/workspaces/{ws}/docs").json()
    assert second == first
    assert workspace_listings() == []
    assert split == []
    assert len(opened) == len(set(opened)), "a file was opened twice in one view"


def test_a_change_in_the_workspace_shows_on_the_next_view(env: Env) -> None:  # noqa: F811
    """A note added, moved or removed anywhere in the workspace, a new folder, and a
    rule file rewritten with the same size: each shows on the very next view."""
    client, _, core, ws = env
    files = _workspace_with_notes(core, ws)

    def view() -> dict[str, Any]:
        return dict(client.get(f"/workspaces/{ws}/docs").json())

    missing = "Points to google-sync.md section 4: no such file."
    assert missing in _pointers(view())
    note = files / "research" / "2026" / "october" / "google-sync.md"
    note.write_text("# Sync\n")
    assert missing not in _pointers(view())
    moved = files / "archive" / "old" / "google-sync.md"
    moved.parent.mkdir(parents=True)
    note.rename(moved)
    assert missing not in _pointers(view())
    moved.unlink()
    assert missing in _pointers(view())
    (files / "new-folder" / "deeper").mkdir(parents=True)
    (files / "new-folder" / "deeper" / "google-sync.md").write_text("# Sync\n")
    assert missing not in _pointers(view())
    # Same size, same second: only the text says it changed.
    flow = docs.folder(core, ws) / "flow.md"
    before = flow.stat()
    flow.write_text(flow.read_text().replace("## 4. Sync", "## 5. Sync"))
    os.utime(flow, ns=(before.st_atime_ns, before.st_mtime_ns))
    shown = next(f for f in view()["files"] if f["path"] == "flow.md")
    assert "5. Sync" in shown["sections"] and "4. Sync" not in shown["sections"]
    # An agent whose text restates a rule: a duplicate on the next view.
    rule = "only Sam moves a task to done in the tracker and nobody else ever does it"
    team_md = docs.folder(core, ws) / "team.md"
    team_md.write_text(team_md.read_text() + f"\n## 6. Done\n{rule}\n")
    assert not any(f["kind"] == "duplicate" for f in view()["findings"])
    library.save_item(
        core,
        None,
        kind="agent",
        name="script-writer",
        title="Script Writer",
        summary="",
        definition={"instructions": f"You write scripts: {rule}.", "reads": [{"path": "team.md"}]},
        workspace_id=ws,
    )
    assert any(
        f["kind"] == "duplicate" and "agent Script Writer" in (f["where"], f["other"])
        for f in view()["findings"]
    )


def _python_names(files: Path, cap: int) -> set[str]:
    """The names as the check found them before: Python's own rglob, stopping past cap."""
    other: set[str] = set()
    for p in files.rglob("*.md"):
        if len(other) > cap:
            break
        other.add(p.name)
    return other


def test_the_kept_names_are_pythons_own_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hidden folders are walked, a symlinked folder is not entered, a link, a broken
    link and a folder named *.md count, .MD doesn't; past the cap, the same names in
    the same order as Python's rglob."""
    top = tmp_path / "files"
    for rel in ("a.md", ".hidden/h.md", "x/y/z/deep.md", "x/Upper.MD", "x/y/two.md", "q/r.txt"):
        (top / rel).parent.mkdir(parents=True, exist_ok=True)
        (top / rel).write_text("x")
    (top / "folder.md").mkdir()
    (top / "folder.md" / "inside.md").write_text("x")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "never.md").write_text("x")
    (top / "linked").symlink_to(elsewhere, target_is_directory=True)
    (top / "link.md").symlink_to(top / "a.md")
    (top / "broken.md").symlink_to(tmp_path / "nothing")
    for n in range(12):
        (top / f"many{n % 3}" / f"n{n}.md").parent.mkdir(exist_ok=True)
        (top / f"many{n % 3}" / f"n{n}.md").write_text("x")
    assert docs._md_names(top) == _python_names(top, docs.MAX_OTHER)
    assert "never.md" not in docs._md_names(top) and "Upper.MD" not in docs._md_names(top)
    for cap in (0, 2, 5, 9):
        monkeypatch.setattr(docs, "MAX_OTHER", cap)
        docs._NAMES.drop()
        assert docs._md_names(top) == _python_names(top, cap), cap
