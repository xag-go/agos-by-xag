"""An automation's runs as the owner sees them: Hermes's finished runs of its job,
a team automation's runs read from the board, the cards a run proposed, and
which were a catch-up or by hand.

Owns: the runs list. Must not: start a run (owner.py run_now).
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from agos_core.actions import (
    automation_cards,
    hooks,
)
from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.automation import run_detail
from agos_core.actions.services.automation.cron import cron_bridge, hermes_jobs, home_of
from agos_core.context import Core
from agos_core.db import automations as repo
from agos_core.db.records import (
    AutomationProposal,
    AutomationRun,
    RunDetail,
)
from agos_core.engine.cron import (
    CronError,
    finished_runs,
    report_text,
)

__all__ = [
    "detail_of",
    "proposed_cards",
    "runs",
]

log = logging.getLogger("agos.automations")


def runs(core: Core, workspace_id: str, automation_id: int) -> list[AutomationRun]:
    """Its runs, read from Hermes: a one-agent automation's cron runs (Hermes's
    executions, with their report or error from its output files), and the runs
    Hermes put on the Kanban (team steps, check first, webhooks), read from their
    cards."""
    row = repo.row(core.db, workspace_id, automation_id)
    if row is None:
        raise NotFoundError("This automation")
    automation = repo.from_row(row, hooks.hooks_of(core, workspace_id).get(automation_id))
    from agos_core.actions import catch_up

    caught = catch_up.asked(core, workspace_id).get(str(row["hermes_job_id"] or ""))
    ended = [r for r in automation_cards.runs(core, automation) if not r.going]
    shown = run_detail.details(core, workspace_id, [(automation, r) for r in ended])
    card_runs = [
        _caught_up(
            _manual_or_not(automation_cards.as_record(r), row["manual_at"]).model_copy(
                update={"detail": d}
            ),
            caught,
        )
        for r, d in zip(ended, shown, strict=True)  # a run shows once all its cards ended
    ]
    live: list[AutomationRun] = []
    job = _hermes_job_runs(core, row)
    if job is not None:
        proposed = proposed_cards(core, workspace_id, str(row["hermes_job_id"]))
        held = run_detail.job_home(core, workspace_id, automation_id)
        for run in finished_runs(job):
            answer = report_text(run.output).strip()
            error = None if run.ok else (run.error or answer[:500] or "The run failed.")
            live.append(
                AutomationRun(
                    id=_run_number(run.id),
                    result="ok" if run.ok else "failed",
                    source="manual" if _by_hand(row["manual_at"], run.started_at) else "schedule",
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    report=answer[:20_000],
                    error=error,
                    proposals=_proposed_in(proposed, run.started_at, run.finished_at),
                    caught_up=catch_up.run_of(caught, run.started_at),
                )
            )
            live[-1] = live[-1].model_copy(
                update={
                    "detail": run_detail.cron_detail(
                        core, workspace_id, automation, live[-1], run.id, held
                    )
                }
            )
    both = card_runs + live
    return sorted(both, key=lambda r: (r.started_at, r.id), reverse=True)[:20]


def detail_of(core: Core, workspace_id: str, automation_id: int, run_id: str) -> RunDetail:
    """One run of this workspace's automation in detail, going or ended (NotFound:
    no such run)."""
    row = repo.row(core.db, workspace_id, automation_id)
    if row is None:
        raise NotFoundError("This automation")
    automation = repo.from_row(row, hooks.hooks_of(core, workspace_id).get(automation_id))
    for run in automation_cards.runs(core, automation):
        if run.id == run_id:
            return run_detail.details(core, workspace_id, [(automation, run)])[0]
    for shown in runs(core, workspace_id, automation_id):
        if shown.detail is not None and shown.detail.run_id == run_id:
            return shown.detail
    raise NotFoundError("This run")


def proposed_cards(core: Core, workspace_id: str, job: str) -> list[dict[str, Any]]:
    """The cards a one-agent automation's runs proposed: made with Hermes's
    kanban_create in its cron sessions (cron_<job>_…), waiting on the board for
    the owner (the guard has them made blocked)."""
    from agos_core.actions import kanban_board

    return kanban_board.made_in(core, workspace_id, f"cron_{job}_") if job else []


def _proposed_in(
    cards: list[dict[str, Any]], started_at: str, finished_at: str | None
) -> list[AutomationProposal]:
    """The run's own: made between its start and a little after its end."""

    def epoch(text: str | None) -> float | None:
        try:
            return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    start = epoch(started_at)
    if start is None:
        return []
    end = (epoch(finished_at) or start) + 120
    return [
        AutomationProposal(
            id=_run_number(c["id"]),
            title=c["title"],
            description=c["body"][:2000],
            kanban_card=c["id"],
        )
        for c in cards
        if start - 5 <= c["created_at"] <= end
    ]


def _run_number(hermes_run_id: str) -> int:
    """A Hermes run's stable number in AGOS's list (its id is Hermes's text)."""
    return int(hashlib.sha256(hermes_run_id.encode()).hexdigest()[:12], 16)


def _hermes_job_runs(core: Core, row: sqlite3.Row) -> dict[str, Any] | None:
    """A one-agent automation's Hermes job with its executions and outputs."""
    job = row["hermes_job_id"]
    if not job or row["steps"] is not None or row["check_first"]:
        return None
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        return None
    held = (hermes_jobs(core, str(row["workspace_id"])) or {}).get(str(job))
    if held is None:
        return None
    try:
        return bridge.get(home_of(core, str(row["workspace_id"]), held), str(job))
    except (CronError, OSError) as error:
        log.warning("cron job %s can't be read: %s", job, error)
        return None


def _caught_up(run: AutomationRun, caught: tuple[str, str] | None) -> AutomationRun:
    """A run of a catch-up AGOS asked for (actions/catch_up.py): its missed time."""
    from agos_core.actions import catch_up

    missed = catch_up.run_of(caught, run.started_at)
    return run.model_copy(update={"caught_up": missed}) if missed else run


def _manual_or_not(run: AutomationRun, manual_at: str | None) -> AutomationRun:
    """Hermes ran a Run now as the job's own run (`hermes cron run`): its cards say
    "schedule", and the click just before tells it was by hand."""
    if run.source == "schedule" and _by_hand(manual_at, run.started_at):
        return run.model_copy(update={"source": "manual"})
    return run


def _by_hand(manual_at: str | None, started_at: str) -> bool:
    """A run that started within 2 minutes after a "Run now" click."""
    if not manual_at or not started_at:
        return False
    try:
        clicked = datetime.fromisoformat(manual_at.replace("Z", "+00:00"))
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timedelta(0) <= started - clicked <= timedelta(minutes=2)
