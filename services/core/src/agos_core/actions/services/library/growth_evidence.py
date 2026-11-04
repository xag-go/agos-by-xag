"""Skills that grow, the evidence: what the week says about each workspace skill (sessions, the owner's votes, review notes, failed tests), read-only.
Must not: write anything.

Split out of agos_core.actions.skill_growth (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.context import Core
from agos_core.db import feedback_votes
from agos_core.db import skill_candidates as candidates_repo
from agos_core.db import skill_requests as requests_repo
from agos_core.db import skill_tests as tests_repo
from agos_core.engine import hermes_transcript
from agos_core.hermes_gateway import board_reads, hermes_db, session_reads

__all__ = [
    "CORRECTION",
    "JOB_DAY",
    "JOB_NAME",
    "JOB_TIME",
    "MAX_LINES_PER_SKILL",
    "MAX_TESTS",
    "NOTE_KIND",
    "NOTHING",
    "NO_SKILL",
    "OFF_REASON",
    "PROMPT",
    "SCRIPT",
    "WINDOW_DAYS",
    "Evidence",
    "editable_skills",
    "evidence",
    "gather",
    "render",
    "session_evidence",
]

log = logging.getLogger("agos.skill_growth")

WINDOW_DAYS = 7
NO_SKILL = "(no skill named)"
NOTHING = "No evidence this week."
MAX_LINES_PER_SKILL = 12
MAX_TESTS = 2
NOTE_KIND = "skills_improved"
JOB_NAME = "AGOS skill review"
JOB_TIME = "18:00"  # the owner's clock (Hermes's timezone), an hour after the weekly review (actions/rhythm.py)
JOB_DAY = 5  # Friday
SCRIPT = "agos-skill-review.py"  # in the root's Hermes scripts folder
OFF_REASON = "Turned off in AGOS (skill review)"

# An owner's message that corrects the agent's last answer (start of the message).
CORRECTION = re.compile(
    r"^\s*(no\b|nope\b|wrong\b|that'?s not\b|that is not\b|not what\b|don'?t\b|do not\b|"
    r"stop\b|instead\b|actually\b|incorrect\b|you forgot\b|you missed\b|redo\b|"
    r"fix (it|this|that)\b|machi\b|ghalat\b|la[,.! ])",
    re.I,
)

PROMPT = "\n".join(
    [
        "This is your weekly skill review run. The monitor output above is this week's",
        "evidence about your workspace's skills: corrections and tool errors in the",
        "team's sessions, the owner's 👎 notes, review 'Changes' notes and failed skill",
        "tests, grouped by skill, each line with its ref in [brackets].",
        "",
        "1. For each skill listed: read it (skill_view) and the evidence. Improve it only",
        "   when the evidence shows its guidance was wrong, missing or unclear. Not when",
        "   the agent ignored guidance that was right (an agent problem), not for one-off",
        "   environment noise (a flaky API, a timeout). When in doubt, skip it.",
        "2. For each skill you improve: call agos_skill_candidate with skill, text (the",
        "   whole new SKILL.md: targeted edits, the same name, structure and facts, no",
        "   generic advice), why (one line), evidence (the refs you used) and, when the",
        "   skill has no tests yet, tests: 1-2 inputs from the evidence, each with its",
        "   expected answer. Never write the skill with skill_manage in this run: AGOS",
        "   tests the candidate on the skill's tests and makes it the new version only",
        "   when it passes them all and scores at least as well as the current one.",
        f"3. Lines under '{NO_SKILL}': name a recurring gap in your answer (the owner",
        "   decides); create no skill here.",
        "4. Answer with one line per skill: proposed or skipped, and why. Nothing more:",
        "   this run must stay cheap.",
    ]
)


@dataclass(frozen=True)
class Evidence:
    skill: str  # a workspace skill's name, or NO_SKILL
    kind: str  # correction / tool error / 👎 note / review changes / failed test
    ref: str  # where it is: session:<profile>/<id>, vote:<id>, card:<id>, run:<id>
    text: str

    def line(self) -> str:
        return f'- {self.kind} [{self.ref}] "{self.text}"'


def _one_line(text: Any, n: int = 160) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _since(at: datetime | None = None) -> datetime:
    return (at or datetime.now(UTC)) - timedelta(days=WINDOW_DAYS)


# ---- evidence: the team's Hermes sessions ---------------------------------------------------


def session_evidence(rows: Iterable[Any], profile: str, skills: set[str]) -> list[Evidence]:
    """One profile's messages of the week (session_id, role, content, tool_calls,
    tool_name; in order) -> corrections and tool errors, under the skills each
    session used (or NO_SKILL)."""
    by_session: dict[str, list[Any]] = {}
    for r in rows:
        by_session.setdefault(str(r["session_id"]), []).append(r)
    out: list[Evidence] = []
    for sid, messages in by_session.items():
        used = set()
        found: list[tuple[str, str]] = []
        last_role = ""
        for m in messages:
            role = str(m["role"] or "")
            if role == "assistant":
                used |= hermes_transcript.called_skills(m["tool_calls"])
            elif (
                role == "user"
                and last_role == "assistant"
                and CORRECTION.match(str(m["content"] or ""))
            ):
                found.append(("correction", _one_line(m["content"])))
            elif role == "tool":
                said = hermes_transcript.tool_error(m["content"])
                if said:
                    found.append(("tool error", _one_line(f"{m['tool_name'] or 'tool'}: {said}")))
            if role in ("user", "assistant"):
                last_role = role
        named = sorted(used & skills) or [NO_SKILL]
        ref = f"session:{profile}/{sid[:24]}"
        for kind, words in found[:4]:
            out += [Evidence(s, kind, ref, words) for s in named]
    return out


def _sessions(core: Core, workspace_id: str, since: datetime, skills: set[str]) -> list[Evidence]:
    from agos_core.db import hermes_chats

    store = hermes_chats.store()
    if store is None or core.engine is None:
        return []
    out: list[Evidence] = []
    for profile in core.engine.own_profiles(workspace_id):
        if "tool_calls" not in store.columns(profile):
            continue
        rows = session_reads.messages_since(store, profile, since.timestamp())
        out += session_evidence(rows, profile, skills)
    return out


# ---- evidence: AGOS's own signals and Hermes's board ------------------------------------------


def _card_skills(db: sqlite3.Connection, card: str, skills: set[str]) -> list[str]:
    try:
        found = board_reads.card_skills(db, card)
    except sqlite3.Error:
        return []
    try:
        listed = json.loads(found) if found else []
    except ValueError:
        listed = []
    return sorted({str(s) for s in listed if isinstance(s, str)} & skills)


def _board(core: Core, workspace_id: str) -> sqlite3.Connection | None:
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return None
    path = agent_profiles.board_db(core, workspace_id)
    if not path.is_file():
        return None
    try:
        return hermes_db.connect_ro(path, timeout=2)
    except sqlite3.Error:
        return None


def _board_evidence(
    core: Core, workspace_id: str, since: datetime, skills: set[str]
) -> list[Evidence]:
    """The owner's 👎 of the week and the review 'Changes' notes on Hermes's board,
    under the skills the card loaded (its Hermes `skills`), else NO_SKILL."""
    from agos_core.engine import reviews

    out: list[Evidence] = []
    db = _board(core, workspace_id)
    with contextlib.closing(db) if db is not None else contextlib.nullcontext():
        for v in feedback_votes.dislikes_since(
            core.db, workspace_id, since.isoformat(timespec="seconds")
        ):
            named: list[str] = []
            if v["kind"] == "revision" and db is not None:
                named = _card_skills(db, str(v["ref"]).split(":")[0], skills)
            text = _one_line(v["note"]) or "(no note)"
            out += [Evidence(s, "👎 note", f"vote:{v['id']}", text) for s in named or [NO_SKILL]]
        if db is None:
            return out
        try:
            comments = board_reads.review_comments(db, int(since.timestamp()))
        except sqlite3.Error:
            comments = []
        for card, body in comments:
            mark = reviews.read_mark(str(card), str(body))
            if mark is None or mark.verb != "changes":
                continue
            named = _card_skills(db, str(card), skills)
            text = _one_line(mark.rest) or "(no note)"
            out += [
                Evidence(s, "review changes", f"card:{card}", text) for s in named or [NO_SKILL]
            ]
    return out


def _tested_here(core: Core, workspace_id: str) -> set[int]:
    """Runs that belong to a candidate or a skill request (their own decision)."""
    from agos_core.actions.skill_requests import _json_list

    ids: set[int] = set()
    for raw in candidates_repo.runs_of(core.db, workspace_id):
        ids |= {int(r["run"]) for r in _json_list(raw) if isinstance(r, dict) and "run" in r}
    for raw in requests_repo.runs_of(core.db, workspace_id):
        ids |= {int(r) for r in _json_list(raw) if isinstance(r, int)}
    return ids


def _failed_tests(core: Core, workspace_id: str, since: datetime) -> list[Evidence]:
    own = _tested_here(core, workspace_id)
    out = []
    for r in tests_repo.failed_since(core.db, workspace_id, since.isoformat(timespec="seconds")):
        if int(r["id"]) not in own:
            words = _one_line(f"{r['input_name']}: {r['notes'] or 'failed'}")
            out.append(Evidence(str(r["name"]), "failed test", f"run:{r['id']}", words))
    return out


def editable_skills(core: Core, workspace_id: str) -> set[str]:
    """The workspace's skills the review may change (AGOS's own background ones not)."""
    from agos_core.actions import workspace_skills

    return {str(r["name"]) for r in workspace_skills.shown(core, workspace_id)}


def gather(core: Core, workspace_id: str, at: datetime | None = None) -> list[Evidence]:
    since = _since(at)
    skills = editable_skills(core, workspace_id)
    found = _sessions(core, workspace_id, since, skills)
    found += _board_evidence(core, workspace_id, since, skills)
    found += _failed_tests(core, workspace_id, since)
    return found


def render(found: list[Evidence], at: datetime | None = None) -> str:
    """The monitor's text: stable (no clock in it but the week's dates), grouped by
    skill, the skills first and the unnamed ones last."""
    if not found:
        return NOTHING
    end = (at or datetime.now(UTC)).date()
    groups: dict[str, list[Evidence]] = {}
    for e in found:
        groups.setdefault(e.skill, []).append(e)
    order = sorted(k for k in groups if k != NO_SKILL) + ([NO_SKILL] if NO_SKILL in groups else [])
    lines = [f"Skill review evidence, {end - timedelta(days=WINDOW_DAYS)} to {end} (UTC).", ""]
    for skill in order:
        items = list(dict.fromkeys(e.line() for e in groups[skill]))
        lines.append(f"## {skill} ({len(items)})")
        lines += items[:MAX_LINES_PER_SKILL]
        if len(items) > MAX_LINES_PER_SKILL:
            lines.append(f"- … and {len(items) - MAX_LINES_PER_SKILL} more")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def evidence(core: Core, workspace_id: str) -> str:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return render(gather(core, workspace_id))


def _json_list(value: Any) -> list[Any]:
    from agos_core.actions.skill_requests import _json_list as parse

    return parse(value)
