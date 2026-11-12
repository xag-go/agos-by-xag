"""Skill Studio: test runs of a workspace skill, each run a Hermes Kanban card.

- Saved inputs (name, text, an expected output) and the skill's run template
  (placeholders {skill} and {input}) with a grading checklist are AGOS rows
  (db/skill_tests.py): Hermes has no record of a skill test.
- Run = `hermes kanban create` on the workspace's board (actions/kanban_board.py
  create), assigned to the Co-Founder or a member, with `--skill <name>` so Hermes
  force-loads the skill for the worker, and a body made of the rendered template
  plus a fenced ```agos-skill-test``` block {skill, version, input_id, run_id}: the
  card says which exact skill version it tests. When the version under test is not
  the one installed (a re-run of an older run), the body also carries that
  version's SKILL.md text as the revision to follow.
- The result is the card's: its latest summary / result (Hermes's kanban result,
  else the worker's last comment), read when the Tests tab opens (`refresh`) and
  kept with the run. Then the grader (an expected output and / or the checklist):
  a Hermes auxiliary-model call through the agos-guard plugin's `hermes agos-grade`
  (hermes_plugin/agos_guard/grade.py), pass / fail with notes, kept with the run.
- Re-run: a new card with the same input and the same pinned version.
- A revision that is no version yet (Step 63: a candidate from the week's evidence, a
  hub skill an agent asked for that is still off in the workspace) runs the same
  way, its SKILL.md text on the card as the revision under test (`candidate_run`).
  The grader also gives a 0-1 score, kept with the run (the candidate's promotion
  compares it with the current version's).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import library as items
from agos_core.db import skill_tests as repo
from agos_core.db.connection import transaction
from agos_core.engine import card_blocks
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.skill_tests")

TEST_BLOCK = "agos-skill-test"
MAX_TEXT = 20_000
# What one grading call gets of each text (the plugin's argv carries it).
GRADED_CHARS = 8_000

_grading: set[int] = set()
_grading_lock = threading.Lock()


def _row(core: Core, workspace_id: str, item_id: int) -> Any:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    row = items.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This skill")
    return row


def _input(core: Core, item_id: int, input_id: int) -> Any:
    found = repo.get_input(core.db, input_id)
    if found is None or int(found["item_id"]) != item_id:
        raise NotFoundError("This test input")
    return found


# ---- inputs and settings ----------------------------------------------------------------


def save_settings(
    core: Core, workspace_id: str, item_id: int, *, template: str, checklist: str
) -> None:
    _row(core, workspace_id, item_id)
    template = template.strip()
    if template and "{input}" not in template:
        raise ActionError("The template needs {input} where the test input goes.")
    with transaction(core.db):
        repo.save_settings(core.db, workspace_id, item_id, template, checklist.strip())


def add_input(
    core: Core, workspace_id: str, item_id: int, *, name: str, text: str, expected: str
) -> int:
    _row(core, workspace_id, item_id)
    name, text = name.strip(), text.strip()
    if not name:
        raise ActionError("Give the input a name.")
    if not text:
        raise ActionError("Write the input text.")
    with transaction(core.db):
        return repo.add_input(core.db, workspace_id, item_id, name[:120], text, expected.strip())


def update_input(
    core: Core,
    workspace_id: str,
    item_id: int,
    input_id: int,
    *,
    name: str,
    text: str,
    expected: str,
) -> None:
    _row(core, workspace_id, item_id)
    _input(core, item_id, input_id)
    if not name.strip() or not text.strip():
        raise ActionError("An input needs a name and a text.")
    with transaction(core.db):
        repo.update_input(core.db, input_id, name.strip()[:120], text.strip(), expected.strip())


def delete_input(core: Core, workspace_id: str, item_id: int, input_id: int) -> None:
    _row(core, workspace_id, item_id)
    _input(core, item_id, input_id)
    with transaction(core.db):
        repo.delete_input(core.db, input_id)


# ---- running --------------------------------------------------------------------------


def render(template: str, skill: str, text: str) -> str:
    """The card's text: the template with its placeholders filled (no other
    formatting: a `{` in the input stays a `{`)."""
    return (template or repo.DEFAULT_TEMPLATE).replace("{skill}", skill).replace("{input}", text)


def _pinned_text(core: Core, workspace_id: str, item_id: int, name: str, version: int) -> str:
    """The SKILL.md of a version that isn't the installed one, for the card: the
    revision under test, as Paperclip's harness injects it."""
    from agos_core.actions import skill_versions

    try:
        files = skill_versions.content(core, workspace_id, item_id, version)
    except NotFoundError:
        return ""
    text = files.get("SKILL.md") or ""
    if not text:
        return ""
    return (
        f"\n\nThe revision under test is version {version} of the skill, below; follow it "
        f"rather than the installed copy where they differ.\n\n```markdown\n{text}\n```"
    )


def _start(
    core: Core,
    workspace_id: str,
    row: Any,
    *,
    input_id: int | None,
    input_name: str,
    input_text: str,
    expected: str,
    member: str,
    version: int | None,
    revision: str = "",
    load: bool = True,
) -> int:
    from agos_core.actions import kanban_board, skill_versions

    item_id, name = int(row["id"]), str(row["name"])
    settings = repo.settings(core.db, item_id)
    current = skill_versions.current(core, workspace_id, name)
    pinned = current if version is None else version
    body = render(settings["template"], name, input_text)
    if revision:
        body += (
            "\n\nThe revision under test is a candidate (no version of the skill yet), "
            "below; follow it rather than any installed copy.\n\n"
            f"```markdown\n{revision}\n```"
        )
    elif pinned != current:
        body += _pinned_text(core, workspace_id, item_id, name, pinned)
    with transaction(core.db):
        run_id = repo.add_run(
            core.db,
            workspace_id=workspace_id,
            item_id=item_id,
            input_id=input_id,
            input_name=input_name,
            input_text=input_text,
            expected=expected,
            checklist=settings["checklist"],
            version=pinned,
            member=member,
        )
    block = {"skill": name, "version": pinned, "input_id": input_id, "run_id": run_id}
    body = card_blocks.with_block(body, TEST_BLOCK, block)
    try:
        card = kanban_board.create(
            core,
            workspace_id,
            f"Skill test: {name} — {input_name}",
            body,
            member,
            skills=[name] if load else [],
        )
    except Exception:
        with transaction(core.db):
            repo.delete_run(core.db, run_id)
        raise
    with transaction(core.db):
        repo.set_card(core.db, run_id, card)
    return run_id


def run(core: Core, workspace_id: str, item_id: int, *, input_id: int, member: str) -> int:
    """One test run: a card for `member` (the Co-Founder, or a team member) with the
    skill loaded and the input rendered into the skill's template; the run row
    links to the card. Returns the run id."""
    row = _row(core, workspace_id, item_id)
    found = _input(core, item_id, input_id)
    return _start(
        core,
        workspace_id,
        row,
        input_id=input_id,
        input_name=str(found["name"]),
        input_text=str(found["text"]),
        expected=str(found["expected"] or ""),
        member=member,
        version=None,
    )


def candidate_run(
    core: Core,
    workspace_id: str,
    item_id: int,
    *,
    input_id: int,
    member: str,
    revision: str = "",
    load: bool = True,
) -> int:
    """One test run of a revision that is no version yet (`revision`: its SKILL.md on
    the card) or, with no revision, of the current version (the baseline it is
    compared with). `load`: Hermes force-loads the installed skill (not for a skill
    that is still off in the workspace: Hermes refuses a disabled one)."""
    row = items.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This skill")
    found = _input(core, item_id, input_id)
    return _start(
        core,
        workspace_id,
        row,
        input_id=input_id,
        input_name=str(found["name"]),
        input_text=str(found["text"]),
        expected=str(found["expected"] or ""),
        member=member,
        version=None,
        revision=revision,
        load=load,
    )


def rerun(core: Core, workspace_id: str, item_id: int, run_id: int) -> int:
    """The same test again: the input as the first run had it (its text, its
    expected output) and the same pinned version, on a new card."""
    row = _row(core, workspace_id, item_id)
    old = repo.get_run(core.db, run_id)
    if old is None or int(old["item_id"]) != item_id:
        raise NotFoundError("This run")
    return _start(
        core,
        workspace_id,
        row,
        input_id=int(old["input_id"]) if old["input_id"] is not None else None,
        input_name=str(old["input_name"]),
        input_text=str(old["input_text"]),
        expected=str(old["expected"] or ""),
        member=str(old["member"] or ""),
        version=int(old["version"]),
    )


# ---- results and grading -------------------------------------------------------------------

FINISHED = ("done", "archived")


def _card_output(raw: dict[str, Any]) -> str:
    """What the card says was done: Hermes's result / latest summary, else the
    worker's last comment."""
    from agos_core.actions.kanban_board import readable_result

    task: dict[str, Any] = raw["task"] if isinstance(raw.get("task"), dict) else {}
    text = readable_result(str(raw.get("latest_summary") or task.get("result") or ""))
    if text.strip():
        return text.strip()
    assignee = str(task.get("assignee") or "")
    for comment in reversed(raw.get("comments") or []):
        if isinstance(comment, dict) and (
            not assignee or str(comment.get("author") or "") == assignee
        ):
            return str(comment.get("body") or "").strip()
    return ""


def refresh(core: Core, workspace_id: str, item_id: int, *, grade_inline: bool = False) -> None:
    """Runs still going: their card read from Hermes's board (status, result);
    a finished one keeps its output and gets graded (in the background, or inline)."""
    from agos_core.actions import kanban_board

    for row in repo.runs(core.db, item_id):
        if row["status"] not in ("running", "blocked") or not row["card"]:
            continue
        try:
            raw, _extra = kanban_board._shown(core, workspace_id, str(row["card"]))
        except NotFoundError:
            with transaction(core.db):
                repo.finish(core.db, int(row["id"]), "lost", "")
            continue
        except ActionError as error:
            log.info("test run %s not read: %s", row["id"], error)
            continue
        task: dict[str, Any] = raw["task"] if isinstance(raw.get("task"), dict) else {}
        status = str(task.get("status") or "")
        if status in FINISHED:
            with transaction(core.db):
                repo.finish(core.db, int(row["id"]), "done", _card_output(raw)[:MAX_TEXT])
        elif status == "blocked" and row["status"] != "blocked":
            with transaction(core.db):
                repo.finish(core.db, int(row["id"]), "blocked", "")
        elif status not in ("blocked",) and row["status"] == "blocked":
            with transaction(core.db):
                repo.finish(core.db, int(row["id"]), "running", "")
    for row in repo.runs(core.db, item_id):
        if row["status"] == "done" and row["grade"] is None and _gradable(row):
            if grade_inline:
                grade(core, workspace_id, int(row["id"]))
            else:
                _grade_soon(core, workspace_id, int(row["id"]))


def _gradable(row: Any) -> bool:
    return bool(str(row["expected"] or "").strip() or str(row["checklist"] or "").strip())


def _grade_soon(core: Core, workspace_id: str, run_id: int) -> None:
    with _grading_lock:
        if run_id in _grading:
            return
        _grading.add(run_id)

    def go() -> None:
        try:
            grade(core, workspace_id, run_id)
        except Exception:
            log.exception("test run %s not graded", run_id)
        finally:
            with _grading_lock:
                _grading.discard(run_id)

    threading.Thread(target=go, name=f"skill-grade-{run_id}", daemon=True).start()


def grade(core: Core, workspace_id: str, run_id: int) -> dict[str, Any]:
    """Hermes's auxiliary model judges the run's output against the expected output
    and / or the checklist (`hermes agos-grade`, the agos-guard plugin): pass / fail
    with notes, kept with the run. A failure to grade is kept as 'error'."""
    row = repo.get_run(core.db, run_id)
    if row is None:
        raise NotFoundError("This run")
    if core.engine is None:
        raise ActionError("The engine isn't set up yet.")
    item = items.get_item(core.db, int(row["item_id"]))
    job = {
        "skill": str(item["name"]) if item is not None else "",
        "input": str(row["input_text"])[:GRADED_CHARS],
        "output": str(row["output"])[:GRADED_CHARS],
        "expected": str(row["expected"] or "")[:GRADED_CHARS],
        "checklist": str(row["checklist"] or "")[:GRADED_CHARS],
    }
    verdict, notes, score = "error", "", None
    try:
        said = hermes_cli.walled_cli(
            core.engine,
            workspace_id,
            "agos-grade",
            json.dumps(job, ensure_ascii=False),
            timeout=120,
        )
        found = _last_json(said)
        if found.get("ok"):
            verdict = "pass" if found.get("pass") else "fail"
            notes = str(found.get("notes") or "")
            score = _score(found.get("score"), verdict)
        else:
            notes = f"The engine couldn't grade it: {found.get('reason') or 'no answer'}"
    except EngineError as error:
        notes = f"The engine didn't grade it: {error}"
    with transaction(core.db):
        repo.grade(core.db, run_id, verdict, notes[:MAX_TEXT], score)
    return {"grade": verdict, "notes": notes}


def _score(raw: Any, verdict: str) -> float:
    """The grader's 0-1 score; a verdict with none (an older plugin) counts 1 / 0."""
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    return 1.0 if verdict == "pass" else 0.0


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def regrade(core: Core, workspace_id: str, item_id: int, run_id: int) -> dict[str, Any]:
    _row(core, workspace_id, item_id)
    row = repo.get_run(core.db, run_id)
    if row is None or int(row["item_id"]) != item_id:
        raise NotFoundError("This run")
    if row["status"] != "done":
        raise ActionError("The run hasn't finished yet.", 409)
    if not _gradable(row):
        raise ActionError("Give the input an expected output or the skill a checklist first.")
    return grade(core, workspace_id, run_id)


# ---- the tab ----------------------------------------------------------------------------


def _run_view(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "inputId": int(row["input_id"]) if row["input_id"] is not None else None,
        "inputName": str(row["input_name"]),
        "version": int(row["version"]),
        "member": str(row["member"] or ""),
        "card": str(row["card"] or ""),
        "status": str(row["status"]),
        "output": str(row["output"] or ""),
        "grade": row["grade"],
        "notes": str(row["notes"] or ""),
        "score": row["score"],
        "gradable": _gradable(row),
        "createdAt": str(row["created_at"]),
        "finishedAt": row["finished_at"],
    }


def overview(core: Core, workspace_id: str, item_id: int) -> dict[str, Any]:
    """The Tests tab in one read: template and checklist, inputs, runs (brought up
    to date with their cards first)."""
    from agos_core.actions import skill_versions

    row = _row(core, workspace_id, item_id)
    refresh(core, workspace_id, item_id)
    settings = repo.settings(core.db, item_id)
    return {
        "template": settings["template"],
        "defaultTemplate": repo.DEFAULT_TEMPLATE,
        "checklist": settings["checklist"],
        "version": skill_versions.current(core, workspace_id, str(row["name"])),
        "inputs": [
            {
                "id": int(i["id"]),
                "name": str(i["name"]),
                "text": str(i["text"]),
                "expected": str(i["expected"] or ""),
            }
            for i in repo.inputs(core.db, item_id)
        ],
        "runs": [_run_view(r) for r in repo.runs(core.db, item_id)],
    }
