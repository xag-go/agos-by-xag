"""Step 46, Skill Studio: a workspace skill's versions from Hermes's skill ledger
(list, diff, atomic restore through Hermes's skill_manage), version pins on a card,
test runs as Hermes Kanban cards with a grader, auto-update through a Hermes cron job."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import hermes_skills
from test_engine_sync import profile_dir
from test_library import SKILL, env, skill, ws  # noqa: F401 - fixture

from agos_core.engine import skill_versions as sv
from agos_core.engine.card_blocks import read_block

NAME = "invoice-check"
V2 = SKILL + "2. Check the total.\n"


def _root(home: Path, w: str) -> Path:
    return profile_dir(home, f"agos-{w}")


def _folder(home: Path, w: str) -> Path:
    return _root(home, w) / "skills" / "agos-library" / NAME


def _versions(client: Any, w: str, sid: int) -> list[dict[str, Any]]:
    r = client.get(f"/workspaces/{w}/skills/{sid}/versions")
    assert r.status_code == 200, r.text
    return list(r.json())


def _save(client: Any, w: str, sid: int, text: str, files: dict[str, str] | None = None) -> None:
    definition: dict[str, Any] = {"text": text}
    if files is not None:
        definition["files"] = files
    r = client.put(f"/workspaces/{w}/skills/{sid}", json={"name": NAME, "definition": definition})
    assert r.status_code == 204, r.text


# ---- versions ------------------------------------------------------------------------------


def test_every_ledger_write_is_a_version_with_author_time_summary_and_size(
    env: Any,  # noqa: F811
) -> None:
    client, _core, _runner, home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    [v1] = _versions(client, w, sid)
    assert (v1["number"], v1["author"], v1["action"]) == (1, "owner", "create")
    assert v1["summary"] == "created in AGOS" and v1["files"] == ["SKILL.md"]
    assert v1["size"] == len(SKILL.encode()) and v1["at"] and len(v1["entries"]) == 1
    # The owner's edit with a new file: one write (two ledger entries) = one version.
    _save(client, w, sid, V2, {"references/notes.md": "Totals matter."})
    v2, _ = _versions(client, w, sid)
    assert (v2["number"], v2["author"], v2["summary"]) == (2, "owner", "edited in AGOS")
    assert v2["files"] == ["SKILL.md", "references/notes.md"] and len(v2["entries"]) == 2
    assert v2["size"] == len(V2.encode()) + len(b"Totals matter.")
    # The Co-Founder's own skill_manage (its ledger actor "agent"): a version too,
    # labelled from the ledger.
    root = _root(home, w)
    made = hermes_skills.skill_manage(
        root,
        NAME,
        [{"action": "patch", "content": V2 + "3. Sign it.\n"}],
        delete=False,
        actor="agent",
    )
    assert made["ok"], made
    v3, *_rest = _versions(client, w, sid)
    assert (v3["number"], v3["author"], v3["action"]) == (3, "cofounder", "edit")
    assert v3["summary"] == "edited SKILL.md" and v3["entries"] == made["entries"]
    # Each version is one immutable snapshot file beside the root's skills (never
    # inside skills/, where Hermes would index a SKILL.md copy).
    store = root / ".agos-versions" / NAME
    assert sorted(p.name for p in store.iterdir()) == [
        "skill-version-1.json",
        "skill-version-2.json",
        "skill-version-3.json",
    ]
    assert not (root / "skills" / ".agos-versions").exists()
    assert sv.decode((store / "skill-version-1.json").read_text()).files == {
        "SKILL.md": SKILL.encode()
    }
    # Content of one version, and a change the ledger never saw (a file copied beside
    # the skill) is a version by "outside".
    r = client.get(f"/workspaces/{w}/skills/{sid}/versions/2")
    assert r.json() == {"SKILL.md": V2, "references/notes.md": "Totals matter."}
    (_folder(home, w) / "assets").mkdir()
    (_folder(home, w) / "assets" / "logo.png").write_bytes(b"\x89PNG\x00\xff")
    v4, *_rest = _versions(client, w, sid)
    assert (v4["number"], v4["author"], v4["action"]) == (4, "outside", "observed")
    assert "assets/logo.png" in v4["files"]
    assert client.get(f"/workspaces/{w}/skills/{sid}/versions/4").json()["assets/logo.png"] is None
    # Reading again adds nothing (no spurious versions).
    assert len(_versions(client, w, sid)) == 4


def test_diff_between_two_versions_is_a_unified_diff_per_file(env: Any) -> None:  # noqa: F811
    client, _core, _runner, _home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    _save(client, w, sid, V2, {"references/notes.md": "Totals matter."})
    r = client.get(f"/workspaces/{w}/skills/{sid}/versions/diff", params={"a": 1, "b": 2})
    assert r.status_code == 200, r.text
    by_path = {d["path"]: d["diff"] for d in r.json()}
    assert "+2. Check the total." in by_path["SKILL.md"]
    assert by_path["SKILL.md"].startswith("--- v1/SKILL.md\n+++ v2/SKILL.md\n")
    assert "+Totals matter." in by_path["references/notes.md"]
    assert (
        client.get(f"/workspaces/{w}/skills/{sid}/versions/diff", params={"a": 2, "b": 2}).json()
        == []
    )
    assert (
        client.get(
            f"/workspaces/{w}/skills/{sid}/versions/diff", params={"a": 1, "b": 9}
        ).status_code
        == 404
    )


def test_restore_is_one_hermes_write_recorded_as_the_next_version(env: Any) -> None:  # noqa: F811
    client, _core, _runner, home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    _save(client, w, sid, V2, {"references/notes.md": "Totals matter."})
    root, folder = _root(home, w), _folder(home, w)
    before = len(hermes_skills.entries(root))
    r = client.post(f"/workspaces/{w}/skills/{sid}/versions/1/restore")
    assert r.status_code == 200, r.text
    assert r.json() == {"restored": True, "version": 3, "skipped": []}
    # The folder is version 1 again: SKILL.md back, the file v1 didn't have removed.
    assert (folder / "SKILL.md").read_text() == SKILL
    assert not (folder / "references" / "notes.md").exists()
    # ONE skill_manage batch: Hermes's ledger got its entries (patch + remove_file),
    # and they are the new version, "restored from v1".
    entries = hermes_skills.entries(root)
    assert len(entries) == before + 2
    assert {e["action"] for e in entries[:2]} == {"patch", "remove_file"}
    v3, _v2, v1 = _versions(client, w, sid)
    assert (v3["number"], v3["author"], v3["action"], v3["summary"]) == (
        3,
        "owner",
        "restore",
        "restored from v1",
    )
    assert sorted(v3["entries"]) == sorted(e["id"] for e in entries[:2])
    assert v3["files"] == ["SKILL.md"] and v3["size"] == v1["size"]
    # Restoring the state the skill already has writes nothing: no entry, no version.
    r = client.post(f"/workspaces/{w}/skills/{sid}/versions/1/restore")
    assert r.json() == {"restored": False, "version": 3, "skipped": []}
    assert len(hermes_skills.entries(root)) == before + 2
    assert len(_versions(client, w, sid)) == 3
    # Undo of the restore = restore the version before it (v2): the file comes back.
    r = client.post(f"/workspaces/{w}/skills/{sid}/versions/2/restore")
    assert r.json()["restored"] is True and r.json()["version"] == 4
    assert (folder / "references" / "notes.md").read_text() == "Totals matter."
    assert (folder / "SKILL.md").read_text() == V2
    # The whole team reads that folder: the member's external dir is it.
    assert folder == _root(home, w) / "skills" / "agos-library" / NAME


def test_restore_skips_what_hermes_skill_tool_cannot_write(env: Any) -> None:  # noqa: F811
    """A binary file and a file outside Hermes's skill folders stay as they are and
    are named; the text files are restored."""
    client, _core, _runner, home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    folder = _folder(home, w)
    (folder / "assets").mkdir()
    (folder / "assets" / "logo.png").write_bytes(b"\x89PNG\x00\xff")
    (folder / "extra.txt").write_text("loose")
    assert len(_versions(client, w, sid)) == 2  # the observed one
    (folder / "assets" / "logo.png").write_bytes(b"\x89PNG\x01\xff")
    (folder / "extra.txt").write_text("changed")
    _save(client, w, sid, V2)
    r = client.post(f"/workspaces/{w}/skills/{sid}/versions/2/restore")
    assert r.status_code == 200, r.text
    assert r.json()["restored"] is True
    assert sorted(r.json()["skipped"]) == ["assets/logo.png", "extra.txt"]
    assert (folder / "SKILL.md").read_text() == SKILL
    assert (folder / "assets" / "logo.png").read_bytes() == b"\x89PNG\x01\xff"


def test_versions_are_derived_without_a_hermes_start_while_the_ledger_stands(
    env: Any,  # noqa: F811
    monkeypatch: Any,
) -> None:
    client, core, _runner, _home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    calls: list[str] = []
    real = type(core.engine).skill_history

    def counted(self: Any, *args: Any, **kw: Any) -> Any:
        calls.append(args[2])
        return real(self, *args, **kw)

    monkeypatch.setattr(type(core.engine), "skill_history", counted)
    assert len(_versions(client, w, sid)) == 1
    first = len(calls)
    assert len(_versions(client, w, sid)) == 1
    assert len(_versions(client, w, sid)) == 1
    assert len(calls) == first  # the ledger didn't move: Hermes not asked again
    _save(client, w, sid, V2)
    assert len(_versions(client, w, sid)) == 2
    assert len(calls) == first + 1


# ---- pins on a card ------------------------------------------------------------------------


def test_a_card_made_with_skills_loads_them_and_pins_their_versions(env: Any) -> None:  # noqa: F811
    client, _core, runner, _home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    _save(client, w, sid, V2)
    r = client.post(
        f"/workspaces/{w}/kanban",
        json={"title": "Check March", "body": "The March invoices.", "skills": [NAME, "github"]},
    )
    assert r.status_code == 201, r.text
    card = r.json()["id"]
    create = next(c for c in runner.calls if "kanban" in c and "create" in c)
    assert create[create.index("--skill") + 1] == NAME and create.count("--skill") == 2
    # Hermes's card body holds the pins block (the exact versions the worker read);
    # the card shown has them as pins and the body without the block.
    body = runner.kanban[f"agos-{w}"][card]["body"]
    assert read_block(body, "agos-skill-pins") == {NAME: 2}  # github isn't a workspace skill
    shown = client.get(f"/workspaces/{w}/kanban/{card}").json()
    assert shown["skillPins"] == [{"skill": NAME, "version": 2}]
    assert shown["body"] == "The March invoices."
    listed = next(
        c for c in client.get(f"/workspaces/{w}/kanban").json()["cards"] if c["id"] == card
    )
    assert listed["skillPins"] == [{"skill": NAME, "version": 2}]
    # A card without skills: no pins, body untouched.
    plain = client.post(f"/workspaces/{w}/kanban", json={"title": "Plain", "body": "x"}).json()[
        "id"
    ]
    assert client.get(f"/workspaces/{w}/kanban/{plain}").json()["skillPins"] == []


# ---- test runs -----------------------------------------------------------------------------


def _tests(client: Any, w: str, sid: int) -> dict[str, Any]:
    r = client.get(f"/workspaces/{w}/skills/{sid}/tests")
    assert r.status_code == 200, r.text
    return dict(r.json())


def _finish(client: Any, w: str, card: str, text: str) -> None:
    r = client.post(f"/workspaces/{w}/kanban/{card}/act", json={"action": "done", "summary": text})
    assert r.status_code == 204, r.text


def test_a_test_run_is_a_card_with_the_skill_loaded_and_the_version_pinned(
    env: Any,  # noqa: F811
) -> None:
    client, core, runner, _home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    base = f"/workspaces/{w}/skills/{sid}/tests"
    r = client.put(
        f"{base}/settings",
        json={"template": "Use {skill} on this:\n{input}", "checklist": "- names the total"},
    )
    assert r.status_code == 204, r.text
    assert client.put(f"{base}/settings", json={"template": "no placeholder"}).status_code == 400
    r = client.post(
        f"{base}/inputs",
        json={
            "name": "March",
            "text": "Invoice #12: 3 x 40 = 100",
            "expected": "The total is wrong: 120.",
        },
    )
    assert r.status_code == 201, r.text
    input_id = r.json()["id"]
    overview = _tests(client, w, sid)
    assert overview["template"] == "Use {skill} on this:\n{input}" and overview["version"] == 1
    assert [i["name"] for i in overview["inputs"]] == ["March"] and overview["runs"] == []
    assert "{skill}" in overview["defaultTemplate"] and "{input}" in overview["defaultTemplate"]
    # Run: a Hermes card for the Co-Founder with --skill and the agos-skill-test block.
    r = client.post(f"{base}/run", json={"inputId": input_id, "member": "cofounder"})
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    [run] = _tests(client, w, sid)["runs"]
    assert run["id"] == run_id and run["status"] == "running" and run["version"] == 1
    assert run["gradable"] is True and run["grade"] is None
    profile = core.engine.hermes_name(w)
    board = runner.kanban[f"agos-{w}"]
    card = board[run["card"]]
    assert card["assignee"] == profile and card["title"] == f"Skill test: {NAME} — March"
    assert card["body"].startswith(f"Use {NAME} on this:\nInvoice #12: 3 x 40 = 100")
    assert read_block(card["body"], "agos-skill-test") == {
        "skill": NAME,
        "version": 1,
        "input_id": input_id,
        "run_id": run_id,
    }
    assert read_block(card["body"], "agos-skill-pins") == {NAME: 1}
    create = next(c for c in runner.calls if "kanban" in c and "create" in c and "--skill" in c)
    assert create[create.index("--skill") + 1] == NAME
    # The worker finishes the card: its result is the run's output; the grader (a
    # Hermes auxiliary call through the plugin, mocked) says pass / fail with notes.
    graded: list[dict[str, Any]] = []

    def fake_grade(key: str, *args: str, timeout: float = 60) -> str:
        assert args[0] == "agos-grade" and key == w
        job = json.loads(args[1])
        graded.append(job)
        ok = "120" in job["output"]
        return json.dumps({"ok": True, "pass": ok, "notes": "names 120" if ok else "no total"})

    core.engine.walled_cli = fake_grade
    _finish(client, w, run["card"], "The total is wrong: it should be 120.")
    from agos_core.actions import skill_tests

    skill_tests.refresh(core, w, sid, grade_inline=True)
    [run] = _tests(client, w, sid)["runs"]
    assert run["status"] == "done" and run["output"] == "The total is wrong: it should be 120."
    assert (run["grade"], run["notes"]) == ("pass", "names 120")
    assert graded == [
        {
            "skill": NAME,
            "input": "Invoice #12: 3 x 40 = 100",
            "output": "The total is wrong: it should be 120.",
            "expected": "The total is wrong: 120.",
            "checklist": "- names the total",
        }
    ]
    # Re-run after the skill changed: same input, the SAME pinned version (v1), with
    # that revision's text on the card since the installed copy is now v2.
    _save(client, w, sid, V2)
    r = client.post(f"{base}/runs/{run_id}/rerun")
    assert r.status_code == 201, r.text
    again, first = _tests(client, w, sid)["runs"]
    assert again["id"] == r.json()["id"] and first["id"] == run_id
    assert again["version"] == 1 and again["inputName"] == "March" and again["status"] == "running"
    body = board[again["card"]]["body"]
    assert (read_block(body, "agos-skill-test") or {})["version"] == 1
    assert "The revision under test is version 1" in body and SKILL.strip() in body
    assert read_block(body, "agos-skill-pins") == {NAME: 2}  # what Hermes loaded
    # A fresh run pins the current version and carries no inline revision.
    r = client.post(f"{base}/run", json={"inputId": input_id})
    fresh = _tests(client, w, sid)["runs"][0]
    assert fresh["version"] == 2
    assert "revision under test" not in board[fresh["card"]]["body"]
    # Failing grade, and a run that can't be graded (no expected, no checklist).
    _finish(client, w, again["card"], "Looks fine.")
    skill_tests.refresh(core, w, sid, grade_inline=True)
    by_id = {r["id"]: r for r in _tests(client, w, sid)["runs"]}
    assert (by_id[again["id"]]["grade"], by_id[again["id"]]["notes"]) == ("fail", "no total")
    client.put(f"{base}/settings", json={"template": "", "checklist": ""})
    r = client.post(f"{base}/inputs", json={"name": "Bare", "text": "Invoice #13"})
    bare = client.post(f"{base}/run", json={"inputId": r.json()["id"]}).json()["id"]
    run_bare = next(x for x in _tests(client, w, sid)["runs"] if x["id"] == bare)
    assert run_bare["gradable"] is False
    _finish(client, w, run_bare["card"], "Done.")
    skill_tests.refresh(core, w, sid, grade_inline=True)
    run_bare = next(x for x in _tests(client, w, sid)["runs"] if x["id"] == bare)
    assert run_bare["status"] == "done" and run_bare["grade"] is None
    assert client.post(f"{base}/runs/{bare}/grade").status_code == 400
    # Deleting the input keeps the runs (their input text is their own).
    assert client.delete(f"{base}/inputs/{input_id}").status_code == 204
    kept = _tests(client, w, sid)
    assert [i["name"] for i in kept["inputs"]] == ["Bare"]
    assert next(x for x in kept["runs"] if x["id"] == run_id)["inputId"] is None
    assert next(x for x in kept["runs"] if x["id"] == run_id)["inputName"] == "March"


def test_a_grader_failure_is_kept_as_an_error_not_a_verdict(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    base = f"/workspaces/{w}/skills/{sid}/tests"
    input_id = client.post(
        f"{base}/inputs", json={"name": "x", "text": "y", "expected": "z"}
    ).json()["id"]
    run_id = client.post(f"{base}/run", json={"inputId": input_id}).json()["id"]
    [run] = _tests(client, w, sid)["runs"]
    core.engine.walled_cli = lambda key, *a, timeout=60: json.dumps(
        {"ok": False, "reason": "LLM error: Timeout"}
    )
    _finish(client, w, run["card"], "Something.")
    from agos_core.actions import skill_tests

    skill_tests.refresh(core, w, sid, grade_inline=True)
    [run] = _tests(client, w, sid)["runs"]
    assert run["grade"] == "error" and "LLM error: Timeout" in run["notes"]
    # Grade again once Hermes answers.
    core.engine.walled_cli = lambda key, *a, timeout=60: json.dumps(
        {"ok": True, "pass": True, "notes": "fine"}
    )
    assert client.post(f"{base}/runs/{run_id}/grade").json() == {"grade": "pass", "notes": "fine"}
    assert _tests(client, w, sid)["runs"][0]["grade"] == "pass"


# ---- auto-update -----------------------------------------------------------------------------


def test_auto_update_is_a_flag_and_one_hermes_cron_job_per_workspace(env: Any) -> None:  # noqa: F811
    client, core, _runner, home = env
    w = ws(client, "Alpha")
    sid = skill(client, w)
    # Only a skill installed from the web follows a source.
    r = client.put(f"/workspaces/{w}/skills/{sid}/auto-update", json={"on": True})
    assert r.status_code == 400, r.text
    core.db.execute("UPDATE library_items SET source = 'web' WHERE id = ?", (sid,))
    from agos_core.actions import skill_updates

    made: list[tuple[str, ...]] = []
    jobs = core.engine.root(w) / "cron" / "jobs.json"

    def hermes(_key: str, *args: str, **_: Any) -> str:
        made.append(args)
        if args[:2] == ("cron", "create"):
            jobs.parent.mkdir(parents=True, exist_ok=True)
            jobs.write_text(json.dumps({"jobs": [{"id": "up1", "name": skill_updates.JOB}]}))
            return "Created job: up1"
        if args[:2] == ("cron", "remove"):
            jobs.write_text(json.dumps({"jobs": []}))
        return ""

    core.engine._hermes = hermes
    r = client.put(f"/workspaces/{w}/skills/{sid}/auto-update", json={"on": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"on": True, "job": "made"}
    item = next(i for i in client.get(f"/workspaces/{w}/skills").json() if i["id"] == sid)
    assert item["definition"]["auto_update"] is True
    [create] = [a for a in made if a[:2] == ("cron", "create")]
    assert f"--script={skill_updates.SCRIPT}" in create and "--no-agent" in create
    assert create[-1] == skill_updates.SCHEDULE and f"--name={skill_updates.JOB}" in create
    script = core.engine.root(w) / "scripts" / skill_updates.SCRIPT

    def plan() -> dict[str, Any]:
        import ast

        line = next(ln for ln in script.read_text().splitlines() if ln.startswith("PLAN = "))
        return dict(json.loads(ast.literal_eval(line[len("PLAN = json.loads(") : -1])))

    assert plan()["skills"] == [NAME] and plan()["hermes"] == "/bin/hermes"
    assert plan()["env"]["HERMES_HOME"] == str(core.engine.root(w))
    assert '"skills", "update", name, "--force"' in script.read_text()
    assert skill_updates.keep_job(core, w) == ""  # already right: Hermes isn't asked again
    # Not an agent's job: Ongoing leaves it out.
    from agos_core.actions import ongoing

    assert ongoing.agent_jobs(core, w) == []
    # A second flagged skill rewrites the script; the last flag off removes the job.
    other = skill(client, w, "ledger-sync", SKILL.replace(NAME, "ledger-sync"))
    core.db.execute("UPDATE library_items SET source = 'web' WHERE id = ?", (other,))
    assert client.put(f"/workspaces/{w}/skills/{other}/auto-update", json={"on": True}).json() == {
        "on": True,
        "job": "rewritten",
    }
    assert plan()["skills"] == [NAME, "ledger-sync"]
    assert client.put(f"/workspaces/{w}/skills/{sid}/auto-update", json={"on": False}).json() == {
        "on": False,
        "job": "rewritten",
    }
    assert client.put(f"/workspaces/{w}/skills/{other}/auto-update", json={"on": False}).json() == {
        "on": False,
        "job": "removed",
    }
    assert ("cron", "remove", "up1") in made
    # The Update button's path (the same hub update) leaves a version by "hub": the
    # folder changed with no ledger entry.
    folder = _folder(home, w)
    (folder / "SKILL.md").write_text(V2)
    v2, _v1 = _versions(client, w, sid)
    assert (v2["author"], v2["action"]) == ("hub", "update")


def test_the_update_script_runs_hermes_hub_update_per_skill(tmp_path: Path) -> None:
    """The script Hermes's cron runs (standard library only): one `hermes skills
    update <name> --force` per flagged skill, in the root, one line each."""
    import subprocess
    import sys

    from agos_core.actions import skill_updates

    fake = tmp_path / "hermes"
    fake.write_text('#!/bin/sh\necho "$@" >> "$HERMES_HOME/calls"\necho "Updated $3"\n')
    fake.chmod(0o755)
    root = tmp_path / "root"
    root.mkdir()
    plan = {
        "hermes": str(fake),
        "env": {"HERMES_HOME": str(root), "PATH": "/usr/bin:/bin"},
        "skills": ["a-skill", "b-skill"],
    }
    text = skill_updates.SCRIPT_TEXT.replace("@PLAN@", json.dumps(json.dumps(plan)))
    script = tmp_path / skill_updates.SCRIPT
    script.write_text(text)
    done = subprocess.run(  # noqa: S603 - the script under test, fixed argv
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["a-skill: Updated a-skill", "b-skill: Updated b-skill"]
    assert (root / "calls").read_text().splitlines() == [
        "skills update a-skill --force",
        "skills update b-skill --force",
    ]
