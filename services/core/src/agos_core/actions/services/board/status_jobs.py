"""Status cards, their life: create, update, refresh, delete, each one's Hermes cron job and script, the page.
Must not: write a summary (the job's agent does).

Split out of agos_core.actions.status_cards (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.schedule_times import time_day
from agos_core.actions.services.board.status_defs import (
    DEFAULT_DAY,
    DEFAULT_TIME,
    JOB_NAME,
    PROMPT,
    SCRIPT,
    _body,
    _check,
    _paths,
    _revisions,
    _row,
    _schedule,
    _when,
    scope_label,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import status_cards
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction

__all__ = [
    "create",
    "delete",
    "one",
    "page",
    "refresh",
    "script_text",
    "update",
]


def script_text(card_id: int) -> str:
    """The monitor script Hermes runs before each tick of the card's job: it asks
    AGOS (the workspace's own bridge, key from agos-bridge.json in the profile
    home) for the scope's facts and prints them. A failure exits non-zero: Hermes
    reports it and never counts it as a change."""
    return f'''"""AGOS status card {int(card_id)}: the facts the engine's monitor compares (written by AGOS)."""
import json
import os
import sys
import urllib.request
from pathlib import Path

CARD = {int(card_id)}
home = Path(os.environ.get("HERMES_HOME") or ".")
bridge = json.loads((home / "agos-bridge.json").read_text())
core = str(bridge["core"]).rstrip("/")
if not core.startswith(("http://127.0.0.1", "http://localhost")):
    sys.exit("AGOS's core is not on this machine")
request = urllib.request.Request(
    core + "/hermes-bridge/" + str(bridge["workspace"]) + "/status-card",
    data=json.dumps({{"action": "monitor", "card": CARD}}).encode(),
    headers={{"content-type": "application/json", "authorization": "Bearer " + str(bridge["key"])}},
    method="POST",
)
with urllib.request.urlopen(request, timeout=60) as reply:
    answer = json.loads(reply.read() or b"{{}}")
if not isinstance(answer, dict) or answer.get("error"):
    sys.exit(str(answer.get("error") if isinstance(answer, dict) else "no answer"))
sys.stdout.write(str(answer.get("monitor") or ""))
'''


def _home_jobs(core: Core, workspace_id: str) -> tuple[Path, list[dict[str, Any]]]:
    from agos_core.actions import automations, heartbeat

    return heartbeat._home_and_jobs(core, workspace_id, automations.COFOUNDER)


def _spec(core: Core, workspace_id: str, row: Any, time: str, day: int | None) -> Any:
    from agos_core.actions import automations
    from agos_core.actions.engine import _default_model
    from agos_core.engine.cron import FAILURES_TO, JobSpec

    provider, model, effort = _default_model(core, workspace_id) or ("", "", "")
    return JobSpec(
        name=JOB_NAME.format(int(row["id"])),
        prompt=PROMPT.format(
            title=" ".join(str(row["title"]).split()),
            id=int(row["id"]),
            scope=scope_label(core, workspace_id, row),
        ),
        schedule=_schedule(time, day, str(row["policy"])),
        model=model,
        provider=provider,
        reasoning_effort=effort if effort and effort not in ("standard", "default") else None,
        enabled=True,
        failure_deliver=FAILURES_TO,
        skills=tuple(automations.pinned_skills(core, workspace_id, "")),
        monitor_script=SCRIPT.format(int(row["id"])),
    )


def _write_script(home: Path, card_id: int) -> None:
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    script = scripts / SCRIPT.format(int(card_id))
    text = script_text(card_id)
    with contextlib.suppress(OSError):
        if script.read_text() == text:
            return
    script.write_text(text)
    script.chmod(0o600)


def _job_of(jobs: list[dict[str, Any]], card_id: int) -> dict[str, Any] | None:
    return next((j for j in jobs if j.get("name") == JOB_NAME.format(int(card_id))), None)


def _sync_job(core: Core, workspace_id: str, row: Any, time: str, day: int | None) -> None:
    """The card's Hermes job made or brought up to date (schedule, prompt, monitor)."""
    from agos_core.actions import automations
    from agos_core.engine.cron import CronError
    from agos_core.engine.hermes import EngineError

    bridge = automations.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so the Co-Founder's job can't change now.", 409)
    try:
        home, jobs = _home_jobs(core, workspace_id)
        _write_script(home, int(row["id"]))
        spec = _spec(core, workspace_id, row, time, day)
        job = _job_of(jobs, int(row["id"]))
        if job is None:
            bridge.create(home, spec)
        else:
            bridge.update(home, str(job["id"]), spec)
    except (CronError, EngineError, OSError, ValueError) as error:
        raise ActionError(f"The Co-Founder's job didn't change: {error}"[:300], 503) from error


# ---- what the page does ---------------------------------------------------------------------


def create(
    core: Core,
    workspace_id: str,
    *,
    title: str,
    scope: str,
    scope_ref: str = "",
    policy: str = "daily",
    time: str = DEFAULT_TIME,
    day: int | None = None,
) -> dict[str, Any]:
    require_workspace(core, workspace_id)
    title, scope, ref, policy = _check(core, workspace_id, title, scope, scope_ref, policy)
    time, day = time_day(policy, time, day)
    with transaction(core.db):
        card_id = status_cards.add(core.db, workspace_id, title, scope, ref, policy)
        add_activity(
            core.db, workspace_id, kind="status.created", text=f"Status card added: {title}"
        )
    if core.engine is not None:
        _sync_job(core, workspace_id, _row(core, workspace_id, card_id), time, day)
    return one(core, workspace_id, card_id)


def update(
    core: Core,
    workspace_id: str,
    card_id: int,
    *,
    title: str,
    scope: str,
    scope_ref: str = "",
    policy: str = "daily",
    time: str = DEFAULT_TIME,
    day: int | None = None,
) -> dict[str, Any]:
    require_workspace(core, workspace_id)
    _row(core, workspace_id, card_id)
    title, scope, ref, policy = _check(core, workspace_id, title, scope, scope_ref, policy)
    time, day = time_day(policy, time, day)
    status_cards.change(core.db, workspace_id, card_id, title, scope, ref, policy)
    if core.engine is not None:
        _sync_job(core, workspace_id, _row(core, workspace_id, card_id), time, day)
    return one(core, workspace_id, card_id)


def refresh(core: Core, workspace_id: str, card_id: int) -> dict[str, Any]:
    """Refresh now: the refresh is marked (the monitor's output changes, so Hermes
    wakes the Co-Founder) and Hermes's job fires on its next tick."""
    from agos_core.actions import automations
    from agos_core.engine.cron import CronError
    from agos_core.engine.hermes import EngineError

    require_workspace(core, workspace_id)
    row = _row(core, workspace_id, card_id)
    bridge = automations.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so nothing can run.", 409)
    status_cards.refresh_asked(core.db, card_id)
    try:
        home, jobs = _home_jobs(core, workspace_id)
        job = _job_of(jobs, card_id)
        if job is None:
            _sync_job(core, workspace_id, row, DEFAULT_TIME, DEFAULT_DAY)
            home, jobs = _home_jobs(core, workspace_id)
            job = _job_of(jobs, card_id)
        if job is None:
            raise ActionError("The Co-Founder's job for this card isn't there.", 409)
        core.engine.start(workspace_id)
        bridge.run_now(home, str(job["id"]))
    except (CronError, EngineError, OSError) as error:
        raise ActionError(f"Couldn't start it: {error}"[:300], 503) from error
    add_activity(
        core.db,
        workspace_id,
        kind="status.refresh",
        text=f"Status card refresh asked: {row['title']}",
    )
    return one(core, workspace_id, card_id)


def delete(core: Core, workspace_id: str, card_id: int) -> None:
    """The card, its Hermes job and its monitor script. Its summary's files stay in
    the workspace folder (status/<id>/), like any document."""
    from agos_core.actions import automations
    from agos_core.engine.cron import CronError
    from agos_core.engine.hermes import EngineError

    require_workspace(core, workspace_id)
    row = _row(core, workspace_id, card_id)
    bridge = automations.cron_bridge(core)
    if bridge is not None and core.engine is not None:
        try:
            home, jobs = _home_jobs(core, workspace_id)
            job = _job_of(jobs, card_id)
            if job is not None:
                bridge.remove(home, str(job["id"]))
            (home / "scripts" / SCRIPT.format(int(card_id))).unlink(missing_ok=True)
        except (CronError, EngineError, OSError, ActionError) as error:
            raise ActionError(f"The Co-Founder's job wasn't removed: {error}"[:300], 503) from error
    status_cards.delete(core.db, workspace_id, card_id)
    add_activity(
        core.db, workspace_id, kind="status.deleted", text=f"Status card removed: {row['title']}"
    )


def _shown(
    core: Core, workspace_id: str, row: Any, jobs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    target, _history, changes = _paths(core, workspace_id, int(row["id"]))
    revisions = _revisions(changes)
    last = revisions[-1] if revisions else None
    job = jobs.get(JOB_NAME.format(int(row["id"])))
    time, day = _when(job.get("schedule") if job else None)
    asked = str(row["refresh_asked_at"] or "")
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "scope": str(row["scope"]),
        "scopeRef": str(row["scope_ref"]),
        "scopeLabel": scope_label(core, workspace_id, row),
        "policy": str(row["policy"]),
        "time": time,
        "day": day if day is not None else (DEFAULT_DAY if row["policy"] == "weekly" else None),
        "summary": (_body(target) or "").strip() if last else "",
        "revision": last.n if last else 0,
        "writtenAt": last.at if last else "",
        "writtenBy": last.who if last else "",
        "revisions": [
            {"n": r.n, "at": r.at, "who": r.who, "why": r.why} for r in reversed(revisions)
        ],
        "refreshAskedAt": asked or None,
        "job": None
        if job is None
        else {
            "nextAt": job.get("next_run_at"),
            "lastAt": job.get("last_run_at"),
            "lastStatus": job.get("last_status"),
            "changedAt": job.get("monitor_changed_at"),
            "problem": (
                f"Paused by the engine: {job.get('paused_reason')}"[:300]
                if not job.get("enabled")
                else None
            ),
        },
    }


def _jobs_by_name(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    from agos_core.engine.cron import CronError

    if core.engine is None:
        return {}
    try:
        _home, jobs = _home_jobs(core, workspace_id)
    except (CronError, OSError, ValueError, ActionError):
        return {}
    return {str(j.get("name")): j for j in jobs}


def one(core: Core, workspace_id: str, card_id: int) -> dict[str, Any]:
    return _shown(
        core, workspace_id, _row(core, workspace_id, card_id), _jobs_by_name(core, workspace_id)
    )


def page(core: Core, workspace_id: str) -> dict[str, Any]:
    """The Status page in one read: every card with its summary and revisions, its
    Hermes job's times, and the scopes the form may pick (goals, projects, members)."""
    from agos_core.actions import agent_profiles, team

    require_workspace(core, workspace_id)
    jobs = _jobs_by_name(core, workspace_id)
    cards = [
        _shown(core, workspace_id, r, jobs)
        for r in status_cards.of_workspace(core.db, workspace_id)
    ]
    plan = [
        {"id": int(r["id"]), "level": str(r["level"] or "goal"), "title": str(r["title"])}
        for r in goals_repo.rows(core.db, workspace_id)
        if r["level"] in ("goal", "project")
    ]
    names = agent_profiles.team_names(core, workspace_id) if core.engine is not None else []
    members = [{"name": n, "title": team.title_of(core, workspace_id, n) or n} for n in names]
    return {"cards": cards, "plan": plan, "members": members}
