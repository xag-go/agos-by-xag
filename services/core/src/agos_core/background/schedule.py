"""AGOS's own background work on the job queue (agos_core/jobs): each kind's handler
and how often it recurs, registered once at the core's start (before the job loop).

| kind             | what                                         | every    |
| ---------------- | -------------------------------------------- | -------- |
| idle.chores      | tidy inboxes, close unanswered turns, ...    | 1 min    |
| trash.purge      | workspaces in the trash > 30 days, for good  | 6 h      |
| retention.daily  | old machine records (background/retention)   | 1 day    |
| slo.health       | the core's /health probe (S3, actions/slis)  | 1 min    |
| slo.probes       | page probe (S1), automation delays (S4)      | 5 min    |
| sandbox.denials  | team sandboxes the broker refused, as errors | 1 min    |

A failed chore is a dead letter at once (its next round comes anyway); retention is
tried three times. Either way the error is in Settings → Errors.

Owns: that table. Must not: hold a chore's work (its module does).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from agos_core.actions import automations, idle, slis
from agos_core.background import retention, trash
from agos_core.db import workspaces as workspaces_repo
from agos_core.engine import sandbox_broker, sandboxd_watch
from agos_core.engine.cron import CronError, read_jobs
from agos_core.jobs import recurring, runner

__all__ = ["DENIALS", "HEALTH", "IDLE", "PROBES", "TRASH", "register"]

log = logging.getLogger("agos.jobs")

IDLE = "idle.chores"
TRASH = "trash.purge"
HEALTH = "slo.health"
PROBES = "slo.probes"
DENIALS = "sandbox.denials"


def _idle(core: Any, _payload: dict[str, Any]) -> None:
    idle.chores(core)


def _trash(core: Any, _payload: dict[str, Any]) -> None:
    purged = trash.purge_expired(core)
    if purged:
        log.info("trash: removed %d workspace(s) for good", len(purged))


def _retention(core: Any, _payload: dict[str, Any]) -> None:
    retention.run(core)


def _health(core: Any, _payload: dict[str, Any]) -> None:
    for sli, url in slis.probe_targets(core.settings):
        if sli == "health":
            slis.probe(core, sli, url)


def _scheduled_jobs(core: Any, workspace_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    custom = getattr(core.engine, "cron_bridge", None)
    for home in automations.homes(core, workspace_id).values():
        if not (home / "config.yaml").is_file():
            continue
        try:
            found += custom.job_states(home) if custom is not None else read_jobs(home)
        except (CronError, OSError, ValueError) as error:
            log.info("S4: cron of %s not read: %s", workspace_id, error)
    return found


def _probes(core: Any, _payload: dict[str, Any]) -> None:
    for sli, url in slis.probe_targets(core.settings):
        if sli == "page":
            slis.probe(core, sli, url)
    if core.engine is None:
        return
    for workspace in workspaces_repo.list_workspaces(core.db):
        slis.automation_delays(core, workspace.id, _scheduled_jobs(core, workspace.id))


def _denials(core: Any, _payload: dict[str, Any]) -> None:
    """Refused team sandboxes become errors the owner sees (engine/sandboxd_watch.py)."""
    engine = core.engine
    if engine is None or not hasattr(engine, "settings"):
        return
    policies, _sockets = sandbox_broker.paths(engine)
    sandboxd_watch.report_new(policies, engine.settings.profile_prefix)


def register() -> None:
    """The job loop runs these kinds (at the core's start, every copy)."""
    for kind, handler, every in (
        (IDLE, _idle, recurring.Recurring(timedelta(minutes=1))),
        (TRASH, _trash, recurring.Recurring(timedelta(seconds=trash.EVERY_SECONDS))),
        (retention.KIND, _retention, recurring.Recurring(timedelta(days=1), attempts=3)),
        (HEALTH, _health, recurring.Recurring(timedelta(minutes=1))),
        (PROBES, _probes, recurring.Recurring(timedelta(minutes=5))),
        (DENIALS, _denials, recurring.Recurring(timedelta(minutes=1))),
    ):
        runner.HANDLERS[kind] = handler
        recurring.EVERY[kind] = every
