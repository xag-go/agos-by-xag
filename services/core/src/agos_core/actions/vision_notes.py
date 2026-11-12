"""The owner's Vision notes (Step 60): a free-writing box at the top of the Vision page,
and Organize, which turns them into the Vision, its why and the strategy.

- The notes are the owner's own words, in any language (Darija in Latin letters,
  French, English, numbers): a document in the workspace folder,
  `vision/notes.md`, each save a revision kept as `.revisions/notes/v<N>.md` with a
  CHANGES.md line (who, why, when), the same revision files as a card's documents
  (engine/card_docs.py). The agents read it at /workspace/vision/notes.md.
- Organize is ONE Hermes run of the workspace's Co-Founder (the root's default
  profile, its own configured model, its SOUL.md): Hermes's own one-shot query
  (`hermes chat -Q -q`, quiet: only the final answer on stdout) with the `todo`
  toolset only, a few turns and a run budget, hidden from the session lists
  (`--source tool`). It reads the notes, the current plan and the team, and answers
  one JSON object: {vision, why, strategy, goals: [{title, why, key_results:
  [{title, target, unit, due_on}], projects: [{title}]}]}, always in English.
- Its Vision / Why / Strategy are a PREVIEW: nothing is saved; the owner edits them
  and saves with the Vision form (the Vision is his).
- The goals it found become goal proposals in his Inbox (kind 'goal', change
  add_goal with their key results and projects), one per goal, idempotent per notes
  revision (key `agos-vision-notes:<rev>:<n>`, also Hermes's card idempotency key).
  Without a Vision yet they wait in `vision/organized.json` and are proposed when he
  saves his first Vision.
"""

from __future__ import annotations

import difflib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.engine import card_docs as doc_rules
from agos_core.engine import goals as goal_rules
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli
from agos_core.storage.layout import workspace_paths

log = logging.getLogger("agos.vision_notes")

FOLDER = "vision"  # <workspace files>/vision/notes.md
NOTES = "notes.md"
KEY = "notes"
CHANGES = "CHANGES.md"
ORGANIZED = "organized.json"
MAX_NOTES = 30_000
KEY_PREFIX = "agos-vision-notes"
GOALS_FOUND_MAX = 4
RESULTS_FOUND_MAX = 4
PROJECTS_FOUND_MAX = 3
RUN_TIMEOUT = 120.0  # seconds the page waits for the Co-Founder (it shows a spinner)
RUN_BUDGET = 110  # Hermes's own wall-clock budget for the run (it wraps up first)
MAX_TURNS = 3

_running: set[str] = set()
_running_lock = threading.Lock()

PROMPT = """\
This is a one-shot Organize run from the owner's Vision page. Do not use tools, do not \
create cards, do not write files: only answer.

The owner wrote the free notes below, in his own words: any language or a mix of \
languages (Darija in Latin letters, French, English, ...), messy, with ideas and numbers. Understand all of it and \
turn it into the workspace's Vision, its Why and its Strategy, and the goals the notes name.

Rules:
- Write every text in clear, simple English, whatever language the notes are in: these are \
the workspace's plan texts every agent reads, not a reply to him, so English holds even \
where your instructions say to answer in his language. Translate his ideas faithfully; \
keep names, brands and numbers exactly as he wrote them. Never invent facts, numbers or \
dates the notes don't give.
- vision: one sentence (at most 200 characters): where he wants to go.
- why: why he started and why it matters (2 to 5 sentences).
- strategy: how he will get there: the main choices, as short lines.
- goals: at most {goals_max}, only those the notes really name, and none the current plan \
already has. Each: title (at most 200 characters), why (one sentence), key_results (at most \
{results_max}: what is measured, target as a plain number, unit, due_on as YYYY-MM-DD or \
""), projects (at most {projects_max}, a title each). [] when the notes name no goal.
- Keep what is already right in the current Vision, Why and Strategy; change only what the \
notes add or correct.

Answer with ONE JSON object only, no prose and no code fence:
{{"vision": "...", "why": "...", "strategy": "...", "goals": [{{"title": "...", "why": "...", \
"key_results": [{{"title": "...", "target": 100, "unit": "...", "due_on": ""}}], \
"projects": [{{"title": "..."}}]}}]}}

Today is {today}.

The current plan:
{plan}

The team:
{team}

The owner's notes (revision {revision}):
<<<
{notes}
>>>
"""


# ---- the notes (a revised document in the workspace folder) ---------------------------------


def _folder(core: Core, workspace_id: str) -> Path:
    return workspace_paths(core.layout, workspace_id).files / FOLDER


def _paths(core: Core, workspace_id: str) -> tuple[Path, Path, Path]:
    folder = _folder(core, workspace_id)
    history = folder / doc_rules.REVISIONS / KEY
    return folder / NOTES, history, history / CHANGES


def _revisions(changes: Path) -> list[doc_rules.Revision]:
    try:
        return doc_rules.parse_changes(changes.read_text(errors="replace"))
    except OSError:
        return []


def _body(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def read(core: Core, workspace_id: str) -> dict[str, Any]:
    """The notes as saved last, their revision and every revision's line."""
    require_workspace(core, workspace_id)
    target, _history, changes = _paths(core, workspace_id)
    revisions = _revisions(changes)
    text = _body(target) or ""
    return {
        "text": text.removesuffix("\n"),
        "revision": revisions[-1].n if revisions else 0,
        "updated_at": revisions[-1].at if revisions else None,
        "revisions": [
            {"n": r.n, "at": r.at, "who": r.who, "why": r.why} for r in reversed(revisions)
        ],
    }


def save(
    core: Core, workspace_id: str, text: str, *, who: str = "the owner", why: str = "saved"
) -> dict[str, Any]:
    """A new revision of the notes (none when the text is the same)."""
    require_workspace(core, workspace_id)
    text = text.strip()
    if len(text) > MAX_NOTES:
        raise ActionError(f"Keep the notes to {MAX_NOTES:,} characters.")
    target, history, changes = _paths(core, workspace_id)
    with transaction(core.db):
        revisions = _revisions(changes)
        current = revisions[-1].n if revisions else 0
        if (_body(target) or "") == (text + "\n" if text else ""):
            return {"saved": False, "revision": current}
        n = current + 1
        history.mkdir(parents=True, exist_ok=True)
        (history / f"v{n}.md").write_text(text + "\n" if text else "")
        line = doc_rules.changes_line(doc_rules.Revision(n, now(), who, why))
        if changes.is_file():
            with changes.open("a") as out:
                out.write(line)
        else:
            changes.write_text(doc_rules.changes_header(KEY) + line)
        target.write_text(text + "\n" if text else "")
        add_activity(core.db, workspace_id, kind="goal.changed", text=f"Vision notes v{n} saved")
    return {"saved": True, "revision": n}


def revision(core: Core, workspace_id: str, n: int) -> dict[str, Any]:
    """One revision's text and what it changed against the one before."""
    require_workspace(core, workspace_id)
    _target, history, _changes = _paths(core, workspace_id)
    text = _body(history / f"v{n}.md")
    if text is None:
        raise NotFoundError("This revision")
    before = (_body(history / f"v{n - 1}.md") or "") if n > 1 else ""
    diff = difflib.unified_diff(
        before.splitlines(), text.splitlines(), f"v{n - 1}", f"v{n}", lineterm="", n=2
    )
    return {"n": n, "content": text, "diff": "\n".join(diff)}


# ---- Organize: one Hermes run of the Co-Founder ----------------------------------------------


def _plan_text(core: Core, workspace_id: str) -> str:
    from agos_core.actions import goals

    vision = goals.top(core, workspace_id)
    if vision is None:
        return "No Vision yet."
    lines = [
        f"Vision: {vision.title}",
        f"Why: {vision.why or '(none)'}",
        f"Strategy: {vision.strategy or '(none)'}",
    ]
    active = [g for g in vision.children if g.status == "active"]
    lines.append("Goals:" if active else "Goals: none yet.")
    for g in active:
        krs = "; ".join(
            f"{k.title} (target {k.target:g} {k.unit})".replace(" )", ")")
            if k.target is not None
            else k.title
            for k in g.results
        )
        projects = "; ".join(p.title for p in g.children if p.status == "active")
        lines.append(
            f"- {g.title}"
            + (f" | key results: {krs}" if krs else "")
            + (f" | projects: {projects}" if projects else "")
        )
    waiting = _waiting_titles(core, workspace_id)
    if waiting:
        lines.append("Goals already proposed, waiting in the owner's Inbox:")
        lines += [f"- {t}" for t in waiting.values()]
    return "\n".join(lines)


def _waiting_titles(core: Core, workspace_id: str) -> dict[str, str]:
    """The goals proposed and still waiting for the owner (normalized title -> title)."""
    out: dict[str, str] = {}
    for title in kanban_asks.goal_titles_waiting(core.db, workspace_id):
        if title:
            out[" ".join(title.lower().split())] = title
    return out


def _team_text(core: Core, workspace_id: str) -> str:
    from agos_core.actions import org

    team = org.people(core, workspace_id)
    if not team:
        return "Only you, the Co-Founder, for now."
    return "\n".join(
        f"- {p.name}: {p.title}" for p in sorted(team.values(), key=lambda p: p.title.lower())
    )


def prompt(core: Core, workspace_id: str, notes: str, rev: int) -> str:
    from agos_core.actions import today

    return PROMPT.format(
        goals_max=GOALS_FOUND_MAX,
        results_max=RESULTS_FOUND_MAX,
        projects_max=PROJECTS_FOUND_MAX,
        today=today.date_today(core),
        plan=_plan_text(core, workspace_id),
        team=_team_text(core, workspace_id),
        revision=rev,
        notes=notes,
    )


def _ask_cofounder(core: Core, workspace_id: str, text: str) -> str:
    """The Co-Founder's answer: Hermes's one-shot query in the workspace's root (its
    default profile: its own model, SOUL.md, plugins), walled like every AGOS run."""
    if core.engine is None:
        raise ActionError("The engine isn't set up yet.", 409)
    return hermes_cli.walled_cli(
        core.engine,
        workspace_id,
        "chat",
        "-Q",
        "--source",
        "tool",
        "-t",
        "todo",
        "--max-turns",
        str(MAX_TURNS),
        "--run-budget",
        str(RUN_BUDGET),
        "-q",
        text,
        timeout=RUN_TIMEOUT,
    )


def answer_json(said: str) -> dict[str, Any] | None:
    """The JSON object in the answer (bare, fenced, or inside some prose)."""
    text = (said or "").strip()
    decoder = json.JSONDecoder()
    at = text.find("{")
    while at >= 0:
        try:
            found, _end = decoder.raw_decode(text, at)
        except ValueError:
            found = None
        if isinstance(found, dict) and "vision" in found:
            return found
        at = text.find("{", at + 1)
    return None


def _line(value: Any, cap: int) -> str:
    return " ".join(str(value or "").split())[:cap]


def _block(value: Any, cap: int) -> str:
    if isinstance(value, list):
        value = "\n".join(f"- {_line(v, 400)}" for v in value if _line(v, 400))
    return str(value or "").strip()[:cap]


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def shaped(found: dict[str, Any]) -> dict[str, Any]:
    """The answer as the page shows it: each text cut to its field's size, the goals
    to what a goal proposal carries."""
    from agos_core.engine.proposals import _goal_project, _goal_result

    goals_out = []
    for raw in _items(found.get("goals")):
        if not isinstance(raw, dict) or not _line(raw.get("title"), goal_rules.TITLE_MAX):
            continue
        results = [i for i in map(_goal_result, _items(raw.get("key_results"))) if i]
        projects = [i for i in map(_goal_project, _items(raw.get("projects"))) if i]
        goals_out.append(
            {
                "title": _line(raw.get("title"), goal_rules.TITLE_MAX),
                "why": _line(raw.get("why"), 600),
                "key_results": results[:RESULTS_FOUND_MAX],
                "projects": projects[:PROJECTS_FOUND_MAX],
            }
        )
    return {
        "vision": _line(found.get("vision"), goal_rules.TITLE_MAX),
        "why": _block(found.get("why"), goal_rules.TEXT_MAX),
        "strategy": _block(found.get("strategy"), goal_rules.TEXT_MAX),
        "goals": goals_out[:GOALS_FOUND_MAX],
    }


def _organized_path(core: Core, workspace_id: str) -> Path:
    return _folder(core, workspace_id) / ORGANIZED


def _payload(goal: dict[str, Any], rev: int, n: int) -> dict[str, Any]:
    return {
        "change": "add_goal",
        "title": goal["title"],
        "goal_why": goal["why"],
        "why": f"Found in the owner's Vision notes (revision {rev}).",
        "key_results": goal["key_results"],
        "projects": goal["projects"],
        "notes_key": f"{KEY_PREFIX}:{rev}:{n}",
    }


def _proposed_already(core: Core, workspace_id: str, notes_key: str) -> bool:
    return kanban_asks.goal_proposed(core.db, workspace_id, notes_key)


def propose_goals(core: Core, workspace_id: str) -> dict[str, Any]:
    """The goals of the last Organize, each a goal proposal in the Inbox (once per
    notes revision and goal). Waits while there is no Vision (an add_goal needs one).
    {proposed: new ones now, already: proposed before, waiting: waiting for a Vision,
    problems: [...]}"""
    from agos_core.actions import goals, proposals

    try:
        last = json.loads(_organized_path(core, workspace_id).read_text())
    except (OSError, ValueError):
        return {"proposed": 0, "already": 0, "waiting": 0, "problems": []}
    rev = int(last.get("revision") or 0)
    found = (last.get("result") or {}).get("goals") or []
    if goals.top(core, workspace_id) is None:
        return {"proposed": 0, "already": 0, "waiting": len(found), "problems": []}
    made, already, problems = 0, 0, []
    waiting = _waiting_titles(core, workspace_id)
    for n, goal in enumerate(found, start=1):
        payload = _payload(goal, rev, n)
        if _proposed_already(core, workspace_id, payload["notes_key"]) or (
            # the same goal waits in the Inbox already (an earlier Organize)
            " ".join(goal["title"].lower().split()) in waiting
        ):
            already += 1
            continue
        try:
            proposals.propose(
                core,
                workspace_id,
                "goal",
                payload,
                "The Co-Founder organized the owner's Vision notes "
                f"(revision {rev}) and found this goal in them.",
                once=payload["notes_key"],
            )
            made += 1
        except (ActionError, EngineError) as error:
            problems.append(f"{goal['title']}: {getattr(error, 'message', None) or error}")
    return {"proposed": made, "already": already, "waiting": 0, "problems": problems}


def organize(core: Core, workspace_id: str) -> dict[str, Any]:
    """The Co-Founder reads the saved notes, the plan and the team (one Hermes run) and
    answers the Vision, Why and Strategy as a preview (nothing saved) and the goals,
    proposed in the Inbox."""
    require_workspace(core, workspace_id)
    notes = read(core, workspace_id)
    if not notes["text"].strip():
        raise ActionError("Write your notes first, then Organize.")
    with _running_lock:
        if workspace_id in _running:
            raise ActionError("Organize is already running for these notes.", 409)
        _running.add(workspace_id)
    try:
        rev = int(notes["revision"])
        try:
            said = _ask_cofounder(
                core, workspace_id, prompt(core, workspace_id, notes["text"], rev)
            )
        except EngineError as error:
            reason = f": {error.reason}" if getattr(error, "reason", "") else ""
            raise ActionError(
                f"The Co-Founder didn't answer in time or couldn't run{reason}. Try again.", 502
            ) from error
        found = answer_json(said)
        result = shaped(found) if found is not None else None
        if result is None or not result["vision"]:
            log.info("organize of %s: no JSON in the answer: %s", workspace_id, said[-300:])
            raise ActionError(
                "The Co-Founder's answer couldn't be read as a Vision. Try Organize again.", 502
            )
        target = _organized_path(core, workspace_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"revision": rev, "at": now(), "result": result}, ensure_ascii=False) + "\n"
        )
        add_activity(
            core.db,
            workspace_id,
            kind="goal.changed",
            text=f"Vision notes v{rev} organized by the Co-Founder",
        )
        sent = propose_goals(core, workspace_id)
        return {"revision": rev, **result, **sent}
    finally:
        with _running_lock:
            _running.discard(workspace_id)
