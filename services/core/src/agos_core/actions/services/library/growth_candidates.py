"""Skills that grow, the candidates: a proposed skill change, judged, tested, decided, its batch closed; the sweep.
Must not: gather evidence (growth_evidence does).

Split out of agos_core.actions.skill_growth (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.library.growth_evidence import (
    MAX_TESTS,
    NOTE_KIND,
    _json_list,
    _one_line,
)
from agos_core.actions.services.library.growth_job import ensure_job
from agos_core.context import Core
from agos_core.db import inbox as inbox_repo
from agos_core.db import skill_candidates as candidates_repo
from agos_core.db import skill_tests as tests_repo
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "advance",
    "batch_of",
    "candidate",
    "candidates",
    "card_moved",
    "judge",
    "sweep",
]

log = logging.getLogger("agos.skill_growth")  # the old module's logger (one name)

# ---- candidates ---------------------------------------------------------------------------------


def batch_of(at: datetime | None = None) -> str:
    year, week, _ = (at or datetime.now(UTC)).isocalendar()
    return f"{year}-W{week:02d}"


def _clean_tests(raw: Any) -> list[dict[str, str]]:
    from agos_core.actions.skill_requests import _clean_tests as clean

    return [t for t in clean(raw) if t["expected"]][:MAX_TESTS]


def candidate(
    core: Core,
    workspace_id: str,
    *,
    skill: str,
    text: str,
    why: str,
    evidence_refs: list[str],
    tests: Any = None,
) -> dict[str, Any]:
    """The Co-Founder's candidate for one skill: checked, then its runs start (the
    candidate's text and the current version on the same saved inputs)."""
    from agos_core.actions import skill_tests, skill_versions, workspace_skills
    from agos_core.actions.workspaces import require_workspace
    from agos_core.db import library as repo
    from agos_core.engine import library as lib

    require_workspace(core, workspace_id)
    row = repo.find_item(core.db, "skill", skill.strip(), workspace_id)
    if row is None or workspace_skills.hidden(row):
        raise NotFoundError("This skill")
    name, item_id = str(row["name"]), int(row["id"])
    folder = workspace_skills.existing_dir(core, workspace_id, name)
    if folder is None:
        raise ActionError("This skill has nothing in it yet.", 409)
    try:
        said_name, _description = lib.check_skill(text)
    except lib.LibraryError as error:
        raise ActionError(f"text: {error}") from error
    if said_name != name:
        raise ActionError(f"text: keep the skill's name ({name}).")
    if text.strip() == (folder / "SKILL.md").read_text(errors="replace").strip():
        raise ActionError("text: it is the same as the current version.")
    if not why.strip():
        raise ActionError("why: one line on what the evidence showed.")
    if candidates_repo.testing_for(core.db, workspace_id, item_id):
        raise ActionError("A candidate of this skill is already under test.", 409)
    refs = [str(r)[:120] for r in evidence_refs if str(r).strip()][:30]
    if not tests_repo.inputs(core.db, item_id):
        for n, t in enumerate(_clean_tests(tests), start=1):
            skill_tests.add_input(
                core,
                workspace_id,
                item_id,
                name=f"From evidence {n}",
                text=t["input"],
                expected=t["expected"],
            )
    inputs = tests_repo.inputs(core.db, item_id)
    base = skill_versions.current(core, workspace_id, name)
    stamp = now()
    with transaction(core.db):
        candidate_id = candidates_repo.insert(
            core.db,
            workspace_id,
            item_id,
            name=name,
            batch=batch_of(),
            base_version=base,
            text=text,
            why=_one_line(why, 300),
            evidence=json.dumps(refs),
            created_at=stamp,
        )
        add_activity(
            core.db,
            workspace_id,
            kind="skills.candidate",
            text=f"A candidate of {name} from the week's evidence: {_one_line(why, 200)}",
        )
    if not inputs:
        _decide(
            core,
            workspace_id,
            candidate_id,
            False,
            "No tests to check it: add one in Skill Studio.",
        )
        return {"candidate": candidate_id, "status": "discarded", "note": "no tests"}
    runs: list[dict[str, Any]] = []
    try:
        for i in inputs:
            input_id = int(i["id"])
            runs.append(
                {
                    "run": skill_tests.candidate_run(
                        core,
                        workspace_id,
                        item_id,
                        input_id=input_id,
                        member="cofounder",
                        revision=text,
                    ),
                    "side": "candidate",
                    "input": input_id,
                }
            )
            kept = tests_repo.last_graded(core.db, item_id, input_id, base)
            runs.append(
                {
                    "run": kept
                    if kept is not None
                    else skill_tests.candidate_run(
                        core, workspace_id, item_id, input_id=input_id, member="cofounder"
                    ),
                    "side": "current",
                    "input": input_id,
                }
            )
    except ActionError as error:
        _decide(core, workspace_id, candidate_id, False, f"Its tests didn't start: {error.message}")
        raise
    finally:
        with transaction(core.db):
            candidates_repo.set_runs(core.db, candidate_id, json.dumps(runs))
    return {
        "candidate": candidate_id,
        "status": "testing",
        "runs": len([r for r in runs if r["side"] == "candidate"]),
        "next": "AGOS tests it on the skill's inputs; it becomes the new version only if it "
        "passes them all and scores at least as well as the current one.",
    }


def judge(
    candidate_runs: list[dict[str, Any]], current_runs: list[dict[str, Any]]
) -> tuple[bool, float, float, str]:
    """SkillClaw's replay rule on Skill Studio grades: every candidate run passes AND
    its mean score >= the current version's mean on the same inputs. Each run is
    {grade, score, input_name, notes}; a score missing counts pass 1 / fail 0."""

    def score(r: dict[str, Any]) -> float:
        s = r.get("score")
        if isinstance(s, int | float) and not isinstance(s, bool):
            return float(s)
        return 1.0 if r.get("grade") == "pass" else 0.0

    if not candidate_runs:
        return False, 0.0, 0.0, "No test ran."
    mean = round(sum(map(score, candidate_runs)) / len(candidate_runs), 3)
    base = round(sum(map(score, current_runs)) / len(current_runs), 3) if current_runs else 0.0
    failed = [r for r in candidate_runs if r.get("grade") != "pass"]
    if failed:
        names = ", ".join(str(r.get("input_name") or "?") for r in failed)
        return False, mean, base, f"Failed {len(failed)} of {len(candidate_runs)} tests ({names})."
    if mean < base:
        return False, mean, base, f"Scored {mean} against {base} for the current version."
    return True, mean, base, f"Passed {len(candidate_runs)} tests, scored {mean} (current {base})."


def _decide(
    core: Core,
    workspace_id: str,
    candidate_id: int,
    promote: bool,
    note: str,
    score: float | None = None,
    base_score: float | None = None,
) -> None:
    from agos_core.actions import skill_versions, workspace_skills

    row = candidates_repo.get(core.db, workspace_id, candidate_id)
    if row is None or row["status"] != "testing":
        return
    version = None
    name = str(row["name"])
    if promote:
        current = skill_versions.current(core, workspace_id, name)
        if current != int(row["base_version"]):
            promote, note = False, f"The skill changed while it was tested (now v{current})."
    if promote:
        refs = ", ".join(_json_list(row["evidence"])[:6])
        summary = f"evolved from evidence: {row['why']}" + (f" ({refs})" if refs else "")
        try:
            workspace_skills._write(
                core,
                workspace_id,
                name,
                str(row["text"]),
                actor="agent",
                author="cofounder",
                summary=summary[:400],
            )
            workspace_skills.applied(core, workspace_id)
            version = skill_versions.current(core, workspace_id, name)
        except (ActionError, OSError) as error:
            promote, note = False, f"Hermes didn't write it: {error}"[:900]
    with transaction(core.db):
        candidates_repo.decide(
            core.db,
            candidate_id,
            status="promoted" if promote else "discarded",
            note=note[:900],
            score=score,
            base_score=base_score,
            version=version,
            decided_at=now(),
        )
        add_activity(
            core.db,
            workspace_id,
            kind="skills.promoted" if promote else "skills.discarded",
            text=f"{name}: " + (f"v{version}, evolved from evidence. " if promote else "") + note,
        )
    _close_batch(core, workspace_id, str(row["batch"]))


def advance(core: Core, workspace_id: str) -> int:
    """Candidates under test: their cards read (graded inline), each decided once all
    its runs are graded. One query when none waits."""
    from agos_core.actions import skill_tests

    rows = candidates_repo.testing(core.db, workspace_id)
    moved = 0
    for row in rows:
        skill_tests.refresh(core, workspace_id, int(row["item_id"]), grade_inline=True)
        planned = [r for r in _json_list(row["runs"]) if isinstance(r, dict)]
        runs: list[tuple[dict[str, Any], Any]] = []
        for plan in planned:
            run = tests_repo.get_run(core.db, int(plan.get("run") or 0))
            if run is not None:
                runs.append((plan, run))
        if not planned:
            continue
        if len(runs) < len(planned):
            _decide(core, workspace_id, int(row["id"]), False, "A test run went missing.")
            moved += 1
            continue
        if any(r["status"] in ("running", "blocked") for _p, r in runs):
            continue
        if any(r["status"] == "done" and r["grade"] is None for _p, r in runs):
            continue

        def shown(r: Any) -> dict[str, Any]:
            return {
                "grade": r["grade"] if r["status"] == "done" else r["status"],
                "score": r["score"],
                "input_name": r["input_name"],
            }

        ok, score, base, note = judge(
            [shown(r) for p, r in runs if p.get("side") == "candidate"],
            [shown(r) for p, r in runs if p.get("side") == "current"],
        )
        _decide(core, workspace_id, int(row["id"]), ok, note, score, base)
        moved += 1
    return moved


def _close_batch(core: Core, workspace_id: str, batch: str) -> None:
    """The week's candidates all decided: one Inbox note with each outcome (Skill
    Studio has the diffs and Restore) and, when a skill changed, one curator pass."""
    from agos_core.actions import inbox

    rows = candidates_repo.in_batch(core.db, workspace_id, batch)
    if not rows or any(r["status"] == "testing" for r in rows):
        return
    stamp = json.dumps({"batch": batch})[:-1]  # '{"batch": "2026-W44"'
    if inbox_repo.has_note_like(core.db, workspace_id, NOTE_KIND, stamp):
        return
    items = [
        {
            "candidate": int(r["id"]),
            "itemId": int(r["item_id"]),
            "name": str(r["name"]),
            "status": str(r["status"]),
            "from": int(r["base_version"]),
            "to": r["version"],
            "why": _one_line(r["why"], 140),
            "note": _one_line(r["note"], 160),
        }
        for r in rows
    ]
    promoted = [i for i in items if i["status"] == "promoted"]
    detail = json.dumps({"batch": batch, "items": items}, ensure_ascii=False)
    while len(detail) > 2000 and items:
        items.pop()
        detail = json.dumps({"batch": batch, "items": items}, ensure_ascii=False)
    inbox.note(
        core,
        workspace_id,
        NOTE_KIND,
        f"Skills improved this week: {len(promoted)} of {len(rows)}",
        detail,
    )
    if promoted:
        _curator_soon(core, workspace_id)


def _curator_soon(core: Core, workspace_id: str) -> None:
    """Hermes's own curator, one pass in the workspace's root (its consolidation
    merges overlapping skills through skill_manage; its ledger records it)."""

    def go() -> None:
        try:
            assert core.engine is not None
            hermes_cli.cli(core.engine, workspace_id, "curator", "run", "--background", timeout=120)
        except Exception as error:  # noqa: BLE001 — the week's note stands either way
            log.info("curator pass of %s not started: %s", workspace_id, error)

    threading.Thread(target=go, name="skill-curator", daemon=True).start()


def candidates(core: Core, workspace_id: str, limit_rows: int = 30) -> list[dict[str, Any]]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return [
        {
            "id": int(r["id"]),
            "itemId": int(r["item_id"]),
            "name": str(r["name"]),
            "batch": str(r["batch"]),
            "status": str(r["status"]),
            "from": int(r["base_version"]),
            "to": r["version"],
            "why": str(r["why"]),
            "evidence": [str(e) for e in _json_list(r["evidence"])],
            "score": r["score"],
            "baseScore": r["base_score"],
            "note": str(r["note"]),
            "createdAt": str(r["created_at"]),
            "decidedAt": r["decided_at"],
        }
        for r in candidates_repo.recent(core.db, workspace_id, limit_rows)
    ]


# ---- Hermes's board moved: requests and candidates advance ---------------------------------------


def card_moved(core: Core, workspace_id: str, card: str) -> int:
    """A card moved: when it is a test run of a waiting request or candidate, both
    advance. One query otherwise."""
    from agos_core.actions import skill_requests

    if not tests_repo.card_waits_on_test(core.db, workspace_id, card):
        return 0
    return skill_requests.advance(core, workspace_id) + advance(core, workspace_id)


def sweep(core: Core, workspace_id: str) -> int:
    """Hermes's dispatcher ticked: the workspace's find-skills and skill review job are
    there (once per start), and what waits on a test advances."""
    from agos_core.actions import skill_requests

    skill_requests.ensure(core, workspace_id)
    ensure_job(core, workspace_id)
    return skill_requests.advance(core, workspace_id) + advance(core, workspace_id)
