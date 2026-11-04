"""Find-skills (Step 63): an agent that lacks a capability mid-task finds a skill and
asks for it; AGOS adds it only through Hermes and only once it is tested.

- Every workspace has AGOS's background skill `find-skills` (adapted from Vercel's
  skills/find-skills/SKILL.md; hidden from the owner like team-design): look in the
  workspace's own skills first, then search Hermes's skills hub (its sources include
  skills.sh), check quality, then ask with `agos_skill_request` (the guard's
  skills.py) giving the source, why, and 1-2 test inputs with what a good answer says.
- Search is Hermes's own `hermes skills search` in the workspace's root (the agents'
  sandbox has no Hermes CLI); nothing calls skills.sh or npx directly.
- A request (one row, `skill_requests`: the source, who asked and why, its tests, what
  Hermes's scan said: the provenance log) goes through the normal install path:
  Hermes's hub installs it into the workspace's skill folder with its skills-guard
  scan, but OFF in the workspace (skills.disabled) until it lands. Then Skill Studio
  runs the requester's tests on it (Kanban cards with the skill's text as the
  revision under test, graded by `hermes agos-grade`). All pass:
  - no scripts and a SAFE verdict: it lands (on in the workspace) at once;
  - it carries scripts, or Hermes's scan said CAUTION: a 'skill' proposal waits for
    the owner in the Inbox (Approve lands it, Reject uninstalls it).
  A scan Hermes blocks unless forced ("needs confirmation") asks the owner FIRST:
  his approve is Hermes's own --force (the Library's Install anyway), then the
  tests. A hard block (dangerous, unverified source) is refused. A failed test
  uninstalls it (Hermes's `skills uninstall`).
- At most `limit` requests per workspace per UTC day (app_settings
  `skill_requests.<workspace>`, default 3). Each workspace sees and changes only its
  own requests; nothing leaves the server.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import skill_requests as requests_repo
from agos_core.db.activity import add_activity
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.hermes_gateway import process as hermes_process

log = logging.getLogger("agos.skill_requests")

NAME = "find-skills"
TITLE = "Find skills"
DESCRIPTION = "Use when you lack a skill: find one, then ask AGOS for it."
BODY = """\
# Find skills: when you lack a capability mid-task

Adapted from vercel-labs/skills find-skills, for this workspace's Hermes.

## 1. Name the need
The domain (e.g. invoices, React, deployment) and the exact task (e.g. check totals,
write e2e tests). Only look for a skill when the task is specialised enough that one
likely exists and you can't do it well from what you have.

## 2. This workspace's skills first
Call `agos_skill_request` with action `search` and a short query: it lists this
workspace's own skills (on and off) and Hermes's skills hub (which includes
skills.sh). A workspace skill that fits: load it (skill_view) and carry on.

## 3. Check quality before you ask
From the hub results prefer: an official or trusted source, a clear description
that matches your task, a skill without scripts when an instructions-only one does
the job. Never pick a skill that asks for secrets, deploys or publishes by itself.

## 4. Ask for it
Call `agos_skill_request` with action `request`:
- `source`: the hub identifier exactly as search printed it;
- `reason`: one line, the task you need it for;
- `tests`: 1-2 test inputs taken from your real task, each with `expected` (what a
  good answer says);
- `criteria`: optional, what every good answer must do (a short checklist).
AGOS installs it through Hermes's hub and its security scan, tests it on your
inputs, and asks the owner when it carries scripts or the scan warns. It is not
usable until it lands: check with action `status`, and meanwhile do the task with
what you have (say so in your work).

## 5. Nothing fits
Say no skill was found and do the task directly. Requests are limited per day:
ask only for what you need now.
"""

DEFAULT_LIMIT = 3
LIMIT_RANGE = (0, 20)
SETTING = "skill_requests.{}"
OPEN = ("installing", "testing", "approval")
STATUSES = (*OPEN, "landed", "refused", "failed", "rejected")
MAX_TESTS = 2
SCRIPT_EXTENSIONS = (".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".rb", ".pl", ".ps1", ".bat")
# Hermes's words (hermes_cli/skills_hub.py _scan_block_message, tools/skills_guard.py
# format_scan_report), pinned in engine/hermes_contract.py.
HARD_BLOCK = "even with --force"
_VERDICT = re.compile(r"Verdict:\s*(SAFE|CAUTION|DANGEROUS)", re.I)

_ship_lock = threading.Lock()  # the shipped skill, once per start
_done: set[str] = set()
_asking = threading.Lock()  # the daily limit: one request counted at a time
_advancing = threading.Lock()


def text() -> str:
    from agos_core.engine import library as lib

    return lib.skill_template(NAME, DESCRIPTION, BODY)


def ensure(core: Core, workspace_id: str) -> bool:
    """The find-skills skill in the workspace at its shipped text (once per start)."""
    from agos_core.actions import workspace_skills

    return workspace_skills.ensure_shipped(
        core, workspace_id, NAME, TITLE, text(), done=_done, lock=_ship_lock
    )


def ensure_all(core: Core) -> int:
    from agos_core.db import workspaces as workspaces_repo

    return sum(ensure(core, w.id) for w in workspaces_repo.list_workspaces(core.db))


# ---- the daily limit ------------------------------------------------------------------


def limit(core: Core, workspace_id: str) -> int:
    raw = get_setting(core.db, SETTING.format(workspace_id), {})
    value = raw.get("limit") if isinstance(raw, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return max(LIMIT_RANGE[0], min(LIMIT_RANGE[1], value))
    return DEFAULT_LIMIT


def set_limit(core: Core, workspace_id: str, value: int) -> int:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    if not LIMIT_RANGE[0] <= value <= LIMIT_RANGE[1]:
        raise ActionError(f"The daily limit is {LIMIT_RANGE[0]} to {LIMIT_RANGE[1]} requests.")
    with transaction(core.db):
        set_setting(core.db, SETTING.format(workspace_id), {"limit": int(value)})
    return value


def used_today(core: Core, workspace_id: str) -> int:
    return requests_repo.count_since(core.db, workspace_id, now()[:10])


# ---- rows -------------------------------------------------------------------------------


def _json_list(value: Any) -> list[Any]:
    try:
        found = json.loads(value) if value else []
    except ValueError:
        return []
    return found if isinstance(found, list) else []


def _get(core: Core, workspace_id: str, request_id: int) -> Any:
    row = requests_repo.get(core.db, workspace_id, request_id)
    if row is None:
        raise NotFoundError("This skill request")
    return row


def _set(core: Core, request_id: int, **fields: Any) -> None:
    with transaction(core.db):
        requests_repo.update(core.db, request_id, fields)


def view(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "member": str(row["member"]),
        "name": str(row["name"]),
        "source": str(row["source"]),
        "reason": str(row["reason"]),
        "status": str(row["status"]),
        "verdict": str(row["verdict"]),
        "scan": str(row["scan"]),
        "scripts": bool(row["scripts"]),
        "forced": bool(row["forced"]),
        "itemId": int(row["item_id"]) if row["item_id"] is not None else None,
        "askId": int(row["ask_id"]) if row["ask_id"] is not None else None,
        "tests": _json_list(row["tests"]),
        "note": str(row["note"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


def listed(core: Core, workspace_id: str, limit_rows: int = 50) -> list[dict[str, Any]]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    return [view(r) for r in requests_repo.recent(core.db, workspace_id, limit_rows)]


def _log(core: Core, workspace_id: str, kind: str, words: str) -> None:
    with transaction(core.db):
        add_activity(core.db, workspace_id, kind=kind, text=words[:500])


# ---- the agent's tool ---------------------------------------------------------------------


def search(core: Core, workspace_id: str, query: str) -> dict[str, Any]:
    """The workspace's own skills (on or off) whose name or description has a word of
    the query, then Hermes's skills hub (`hermes skills search` in its root)."""
    from agos_core.actions import hermes_config as hc
    from agos_core.actions import workspace_skills

    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1]
    on = hc.here(core, workspace_id).skills if hc.has_root(core, workspace_id) else set()
    mine = []
    for row in workspace_skills.shown(core, workspace_id):
        head = workspace_skills.head(core, row)
        hay = f"{row['name']} {head.get('description', '')}".lower()
        if not words or any(w in hay for w in words):
            mine.append(
                {
                    "name": str(row["name"]),
                    "description": head.get("description", "")[:300],
                    "on": str(row["name"]) in on,
                }
            )
    hub: list[dict[str, Any]] = []
    problem = ""
    if query.strip():
        try:
            hub = [
                {"source": f.origin, "name": f.name, "description": f.summary, "trust": f.trust}
                for f in workspace_skills.search_web(core, workspace_id, query)
            ]
        except ActionError as error:
            problem = error.message
    out: dict[str, Any] = {"workspace": mine[:20], "hub": hub[:12]}
    if problem:
        out["hubProblem"] = problem
    return out


def status(core: Core, workspace_id: str, member: str) -> dict[str, Any]:
    rows = requests_repo.of_member(core.db, workspace_id, member)
    return {
        "requests": [
            {k: view(r)[k] for k in ("id", "name", "source", "status", "note")} for r in rows
        ],
        "leftToday": max(0, limit(core, workspace_id) - used_today(core, workspace_id)),
    }


def _clean_tests(raw: Any) -> list[dict[str, str]]:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            item = {"input": item}
        if not isinstance(item, dict):
            continue
        given = str(item.get("input") or "").strip()[:4000]
        if given:
            out.append({"input": given, "expected": str(item.get("expected") or "").strip()[:4000]})
    return out[:MAX_TESTS]


def request(
    core: Core,
    workspace_id: str,
    *,
    member: str,
    source: str,
    reason: str,
    tests: Any,
    criteria: str = "",
) -> dict[str, Any]:
    """An agent asks for a hub skill: checked, logged, then installed and tested in the
    background. Returns what the tool answers."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.workspaces import require_workspace
    from agos_core.engine import sources

    require_workspace(core, workspace_id)
    if member and member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Not a member of this workspace's team.")
    source = source.strip()
    try:
        sources._check_identifier(source)
    except sources.SourceError as error:
        raise ActionError(f"source: {error}") from error
    clean = _clean_tests(tests)
    if not clean:
        raise ActionError(
            "Give 1-2 tests: inputs from your real task, each with its expected answer."
        )
    if not criteria.strip() and not all(t["expected"] for t in clean):
        raise ActionError("Each test needs its expected answer (or give criteria).")
    if not reason.strip():
        raise ActionError("reason: say the task you need the skill for.")
    with _asking:
        cap = limit(core, workspace_id)
        if used_today(core, workspace_id) >= cap:
            _log(
                core,
                workspace_id,
                "skill.request.limit",
                f"Skill request refused (limit {cap}/day): {source}",
            )
            raise ActionError(
                f"This workspace's limit of {cap} skill request(s) a day is reached: "
                "do the task with what you have, or ask again tomorrow.",
                429,
            )
        busy = requests_repo.open_for(core.db, workspace_id, source, OPEN)
        if busy is not None:
            return {"request": busy, "status": "already asked", "next": _NEXT}
        stamp = now()
        with transaction(core.db):
            request_id = requests_repo.insert(
                core.db,
                workspace_id,
                member=member,
                source=source[:300],
                reason=reason.strip()[:1000],
                tests=json.dumps(clean, ensure_ascii=False),
                criteria=criteria.strip()[:4000],
                stamp=stamp,
            )
            add_activity(
                core.db,
                workspace_id,
                kind="skill.request",
                text=f"@{member or 'cofounder'} asked for the skill {source}: {reason.strip()[:200]}",
            )
    _soon(_install_and_test, core, workspace_id, request_id, False)
    return {"request": request_id, "status": "installing", "next": _NEXT}


_NEXT = (
    "AGOS installs it through Hermes's hub and its scan, then tests it on your inputs; it "
    "is not usable until it lands (check with action status). Carry on with what you have."
)


def _soon(fn: Callable[..., None], *args: Any) -> None:
    """In the background (a hub install takes up to minutes); tests run it inline."""

    def go() -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("skill request step failed")

    threading.Thread(target=go, name="skill-request", daemon=True).start()


# ---- installing and testing ---------------------------------------------------------------


def has_scripts(folder: Path) -> bool:
    """A skill that runs code: a file under scripts/, an executable, or a script file."""
    for path in folder.rglob("*"):
        if not path.is_file() or path.name == "SKILL.md":
            continue
        rel = path.relative_to(folder)
        if rel.parts[0] == "scripts" or path.suffix.lower() in SCRIPT_EXTENSIONS:
            return True
        with contextlib.suppress(OSError):
            if path.stat().st_mode & 0o111:
                return True
    return False


def verdict_of(scan: str) -> str:
    found = _VERDICT.search(scan or "")
    return found.group(1).lower() if found else ""


def _off(core: Core, workspace_id: str, name: str, on: bool) -> None:
    from agos_core.actions import library

    def edit(here: Any) -> None:
        here.skills = (here.skills | {name}) if on else (here.skills - {name})

    library.change(core, workspace_id, edit)


def _install_and_test(core: Core, workspace_id: str, request_id: int, force: bool) -> None:
    """Hermes's hub installs the skill (its scan; off in the workspace), then its tests
    start. A scan Hermes blocks unless forced asks the owner first."""
    from agos_core.actions import workspace_skills
    from agos_core.db import library as repo
    from agos_core.engine import library as lib
    from agos_core.engine import sources

    row = _get(core, workspace_id, request_id)
    identifier = str(row["source"])
    src = workspace_skills._hub(core, workspace_id)
    try:
        name = src.skill_name(identifier)
    except (sources.SourceError, hermes_process.TimeoutExpired) as error:
        _end(core, workspace_id, request_id, "failed", f"Hermes's hub didn't find it: {error}")
        return
    _set(core, request_id, name=name)
    if not force and (
        repo.find_item(core.db, "skill", name, workspace_id) is not None
        or (workspace_skills.skill_dir(core, workspace_id, name) or Path("/nonexistent")).exists()
    ):
        _end(core, workspace_id, request_id, "refused", f"This workspace already has {name}.")
        return
    item_id = repo.insert_item(
        core.db,
        kind="skill",
        name=name,
        title=name,
        summary="",
        definition={"identifier": identifier, "requested": request_id},
        source="web",
        workspace_id=workspace_id,
    )
    try:
        _off(core, workspace_id, name, on=False)  # off before its files land
        text, folder, scan = src.install_skill(identifier, name, force=force)
        workspace_skills._hub_changed(src)
        lib.check_skill(text)
    except (
        sources.SourceError,
        hermes_process.TimeoutExpired,
        ActionError,
        lib.LibraryError,
    ) as error:
        repo.delete_item(core.db, item_id)
        said = str(getattr(error, "message", "") or error).strip()
        if not isinstance(error, sources.SourceError | hermes_process.TimeoutExpired):
            with contextlib.suppress(sources.SourceError, hermes_process.TimeoutExpired):
                src.uninstall_skill(name)
        workspace_skills.applied(core, workspace_id)
        if isinstance(error, sources.SourceError) and workspace_skills.SCAN_BLOCKED in said:
            if HARD_BLOCK in said or force:
                _end(core, workspace_id, request_id, "refused", f"Hermes's scan blocked it: {said}")
                return
            # Hermes installs it only with --force: the owner decides first.
            _set(core, request_id, verdict="caution", scan=said[:2000])
            _ask_owner(core, workspace_id, request_id)
            return
        _end(core, workspace_id, request_id, "failed", f"Not installed: {said}"[:900])
        return
    scripts = has_scripts(folder)
    _set(
        core,
        request_id,
        item_id=item_id,
        verdict=verdict_of(scan) or ("forced" if force else "safe"),
        scan=scan[:2000],
        scripts=int(scripts),
        forced=int(force),
    )
    workspace_skills.applied(core, workspace_id)
    _start_tests(core, workspace_id, request_id, text)


def _start_tests(core: Core, workspace_id: str, request_id: int, revision: str) -> None:
    from agos_core.actions import skill_tests

    row = _get(core, workspace_id, request_id)
    item_id = int(row["item_id"])
    if str(row["criteria"]).strip():
        skill_tests.save_settings(
            core, workspace_id, item_id, template="", checklist=str(row["criteria"])
        )
    runs = []
    try:
        for n, test in enumerate(_json_list(row["tests"]), start=1):
            input_id = skill_tests.add_input(
                core,
                workspace_id,
                item_id,
                name=f"Request {request_id}, test {n}",
                text=str(test.get("input") or ""),
                expected=str(test.get("expected") or ""),
            )
            runs.append(
                skill_tests.candidate_run(
                    core,
                    workspace_id,
                    item_id,
                    input_id=input_id,
                    member=str(row["member"]) or "cofounder",
                    revision=revision,
                    load=False,  # off in the workspace: Hermes refuses to force-load it
                )
            )
    except ActionError as error:
        _uninstall(core, workspace_id, request_id)
        _end(core, workspace_id, request_id, "failed", f"Its tests didn't start: {error.message}")
        return
    _set(core, request_id, status="testing", runs=json.dumps(runs))


def _runs(core: Core, run_ids: list[Any]) -> list[Any]:
    from agos_core.db import skill_tests as tests_repo

    return [r for r in (tests_repo.get_run(core.db, int(i)) for i in run_ids) if r is not None]


def advance(core: Core, workspace_id: str) -> int:
    """Requests under test: their cards read (graded inline), and each decided once
    every run is graded. Cheap when none waits (one query). Returns how many moved."""
    from agos_core.actions import skill_tests

    rows = requests_repo.testing(core.db, workspace_id)
    if not rows:
        return 0
    moved = 0
    with _advancing:
        for row in rows:
            if row["item_id"] is None:
                continue
            skill_tests.refresh(core, workspace_id, int(row["item_id"]), grade_inline=True)
            runs = _runs(core, _json_list(row["runs"]))
            if not runs or any(r["status"] in ("running", "blocked") for r in runs):
                continue
            if any(r["status"] == "done" and r["grade"] is None for r in runs):
                continue
            moved += 1
            failed = [r for r in runs if r["grade"] != "pass"]
            if failed:
                notes = "; ".join(
                    f"{r['input_name']}: {r['grade'] or r['status']} {r['notes'] or ''}".strip()
                    for r in failed
                )
                _uninstall(core, workspace_id, int(row["id"]))
                _end(
                    core, workspace_id, int(row["id"]), "failed", f"Its tests failed: {notes}"[:900]
                )
            elif row["forced"] or (str(row["verdict"]) == "safe" and not row["scripts"]):
                _land(core, workspace_id, int(row["id"]))
            else:
                _ask_owner(core, workspace_id, int(row["id"]))
    return moved


def _ask_owner(core: Core, workspace_id: str, request_id: int) -> None:
    from agos_core.actions import proposals

    row = _get(core, workspace_id, request_id)
    why = []
    if row["item_id"] is None:
        why.append("Hermes's scan wants a yes before it installs it (Install anyway)")
    if row["scripts"]:
        why.append("it carries scripts")
    if str(row["verdict"]) == "caution" and row["item_id"] is not None:
        why.append("Hermes's scan warned")
    payload = {
        "request": request_id,
        "name": str(row["name"]),
        "source": str(row["source"]),
        "why": str(row["reason"]),
        "member": str(row["member"]) or "cofounder",
        "scan": str(row["scan"])[:900],
        "scripts": bool(row["scripts"]),
        "tested": row["item_id"] is not None,
        "asked": "; ".join(why),
    }
    words = (
        f"@{payload['member']} asked for the skill {payload['name'] or payload['source']} "
        f"({payload['why']}). Your yes is needed: {payload['asked']}."
    )
    made = proposals.propose(
        core, workspace_id, "skill", payload, words, once=f"agos-skill-request:{request_id}"
    )
    _set(core, request_id, status="approval", ask_id=made.get("ask_id"))


def decided(
    core: Core, workspace_id: str, request_id: int, ask_id: int, choice: str
) -> dict[str, Any]:
    """The owner's answer on the request's proposal (actions/proposals.py _act): only
    the request that names this ask, while it waits for him."""
    row = _get(core, workspace_id, request_id)
    if str(row["status"]) != "approval" or int(row["ask_id"] or 0) != ask_id:
        raise ActionError("This skill request isn't waiting for this answer.", 409)
    if choice != "approve":
        _uninstall(core, workspace_id, request_id)
        _end(core, workspace_id, request_id, "rejected", "The owner said no.")
        return {"request": request_id, "status": "rejected"}
    if row["item_id"] is None:
        # His Install anyway: Hermes's own --force, then the requester's tests.
        _set(core, request_id, status="installing", forced=1)
        _soon(_install_and_test, core, workspace_id, request_id, True)
        return {"request": request_id, "status": "installing"}
    _land(core, workspace_id, request_id)
    return {"request": request_id, "status": "landed"}


def _land(core: Core, workspace_id: str, request_id: int) -> None:
    row = _get(core, workspace_id, request_id)
    try:
        _off(core, workspace_id, str(row["name"]), on=True)
    except ActionError as error:
        _set(core, request_id, note=f"Not turned on yet: {error.message}"[:900])
        return
    _end(core, workspace_id, request_id, "landed", "Tested and on in the workspace.")


def _uninstall(core: Core, workspace_id: str, request_id: int) -> None:
    """Hermes's hub takes the skill back out; its row (and its test rows) go."""
    from agos_core.actions import workspace_skills
    from agos_core.db import library as repo
    from agos_core.engine import sources

    row = _get(core, workspace_id, request_id)
    if row["item_id"] is None:
        return
    item = repo.get_item(core.db, int(row["item_id"]))
    with contextlib.suppress(sources.SourceError, hermes_process.TimeoutExpired, ActionError):
        workspace_skills._hub(core, workspace_id).uninstall_skill(str(row["name"]))
    if item is not None and item["workspace_id"] == workspace_id:
        repo.delete_item(core.db, int(item["id"]))
    workspace_skills.applied(core, workspace_id)


def _end(core: Core, workspace_id: str, request_id: int, state: str, note: str) -> None:
    row = _get(core, workspace_id, request_id)
    _set(core, request_id, status=state, note=note[:900])
    who = str(row["member"]) or "cofounder"
    what = str(row["name"] or row["source"])
    _log(core, workspace_id, f"skill.request.{state}", f"Skill {what} for @{who}: {state}. {note}")
    if state in ("landed", "failed", "refused"):
        from agos_core.actions import inbox

        inbox.note(
            core,
            workspace_id,
            "skill_request",
            f"Skill {what} for @{who}: {state}",
            json.dumps(
                {
                    "request": request_id,
                    "status": state,
                    "source": str(row["source"]),
                    "note": note,
                },
                ensure_ascii=False,
            ),
        )
