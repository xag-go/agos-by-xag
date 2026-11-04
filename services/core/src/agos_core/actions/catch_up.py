"""A run missed while the server was off: run it once when AGOS is back, or skip it
(the owner's choice per automation, Automations → editor → "If a run was missed").

What Hermes does by itself (v0.22.2, cron/jobs.py): a recurring job late by less
than its grace (half its period, 2 min..2 h, `_compute_grace_seconds`) still runs,
late. Beyond that, `_fast_forward_missed_recurring` moves `next_run_at` to the next
occurrence (10 missed slots never make 10 runs) and then follows ONE setting for the
whole home, `cron.catch_up_missed`: true (its default) runs the job once at once,
false skips it and records the miss (`record_cron_missed`). Hermes has no per-job
field for it, no age limit, and `resume_job` keeps a slot that passed while the job
was paused due, so turning an automation back on ran a run it missed while it was
off.

So the split is:
- Hermes: `cron.catch_up_missed: false` in its managed scope (`pin_hermes`, one value
  every Hermes process reads at its next tick, no restart): Hermes never fires a
  missed run blindly; it re-anchors the schedule and logs the skip. Its scheduler
  still runs everything that is on time or late within its grace.
- AGOS (`keep`, every pass of the automation loop): for each job of the workspace's
  crons (its automations and AGOS's other jobs: heartbeats, the daily plan...), it
  asks Hermes's own schedule math (CronBridge.slots: compute_next_run in Hermes's
  timezone, and Hermes's grace) for the latest occurrence since the job last ran.
  One that passed beyond Hermes's grace, at most LIMIT_DAYS ago, while the job was on,
  with no run, dispatch, queued Run now or live fire claim since, was missed. Per the
  automation's choice (every other job: once) AGOS asks Hermes to run it once with
  Hermes's Run now (`POST /api/jobs/{id}/run` on the workspace's gateway, which fires
  it at its next tick), or records the skip. A gateway that is not up yet refuses the
  call: the catch-up waits (`waiting`) and goes the moment it answers.
- What AGOS keeps (`cron_catch_up`): when it saw each job off and back on (Hermes's
  resume clears `paused_at`, so there is no history in Hermes), and the occurrence it
  caught up or skipped, written BEFORE the Run now, so a core restart never asks
  twice. Paused off-hours (work hours) counts as on: work hours defer a run to the
  check-in, they don't cancel it. Archived or account-paused counts as off.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from agos_core.context import Core
from agos_core.db import cron_catch_up as catch_up_rows
from agos_core.db.activity import add_activity
from agos_core.engine.cron import WORK_HOURS_REASON, CronError
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.catch_up")

CHOICES = ("once", "skip")
LIMIT_DAYS = 7  # an older missed run is never caught up
HERMES_KEY = "cron.catch_up_missed"  # Hermes's own switch (cron/jobs.py), pinned off
CLAIM_TTL_S = 300  # Hermes's FIRE_CLAIM_TTL_SECONDS: an older fire claim is a dead run's
RECHECK_S = 600.0  # a profile whose jobs didn't change is asked again after this
SHOWN_FOR = timedelta(days=1)  # the automation card's "Caught up" chip
RUN_WINDOW = timedelta(minutes=15)  # a run that started this soon after the ask is it

# (workspace, profile owner) -> (what its jobs looked like, monotonic time asked)
_looked: dict[tuple[str, str], tuple[Any, float]] = {}
# workspace -> (its cron files' stamps and AGOS's rows, monotonic time looked)
_stamps: dict[str, tuple[Any, float]] = {}


def forget() -> None:
    """The next pass looks at everything again (a new core does)."""
    _looked.clear()
    _stamps.clear()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        found = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return found if found.tzinfo is not None else found.replace(tzinfo=UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


# ---- Hermes's switch -----------------------------------------------------------------


def pin_hermes(core: Core) -> bool:
    """`cron.catch_up_missed: false` in Hermes's managed scope (core start): Hermes
    skips a missed run and AGOS decides per automation. True when it was written."""
    from agos_core.actions import hermes_managed

    if core.engine is None:
        return False
    if hermes_managed.lookup(hermes_managed.pinned(core), HERMES_KEY) is False:
        return False
    hermes_cli.managed_write(core.engine, [(HERMES_KEY, "false")], [])
    log.info("%s: false in Hermes's managed scope (AGOS catches up per automation)", HERMES_KEY)
    return True


# ---- the owner's choice ----------------------------------------------------------------


def choice(core: Core, workspace_id: str, automation_id: int) -> str:
    from agos_core.actions.errors import NotFoundError
    from agos_core.db import automations as repo

    row = repo.row(core.db, workspace_id, automation_id)
    if row is None:
        raise NotFoundError("This automation")
    return "skip" if row["catch_up"] == "skip" else "once"


def set_choice(core: Core, workspace_id: str, automation_id: int, value: str) -> str:
    """Saves the choice; returns the one it had (for Undo)."""
    from agos_core.actions.errors import ActionError
    from agos_core.db import automations as repo

    if value not in CHOICES:
        raise ActionError("If a run was missed: once (run it once when AGOS is back) or skip.")
    before = choice(core, workspace_id, automation_id)
    repo.set_catch_up(core.db, automation_id, value)
    return before


# ---- what the owner sees -------------------------------------------------------------


def _row(core: Core, workspace_id: str, job_id: str) -> sqlite3.Row | None:
    return catch_up_rows.row(core.db, workspace_id, job_id)


def asked(core: Core, workspace_id: str) -> dict[str, tuple[str, str]]:
    """The workspace's catch-ups AGOS asked Hermes for: job id -> (asked at, missed at)."""
    return {
        str(r["job_id"]): (str(r["asked_at"]), str(r["missed_at"]))
        for r in catch_up_rows.asked(core.db, workspace_id)
    }


def recent(found: tuple[str, str] | None, now: datetime | None = None) -> str | None:
    """The missed occurrence of a catch-up asked within the last day (the card's chip)."""
    if found is None:
        return None
    at = _parse(found[0])
    if at is None or (now or _now()) - at > SHOWN_FOR:
        return None
    return found[1]


def run_of(found: tuple[str, str] | None, started_at: str) -> str | None:
    """The missed occurrence a run made up for: it started just after AGOS asked."""
    if found is None:
        return None
    at, started = _parse(found[0]), _parse(started_at)
    if at is None or started is None:
        return None
    return found[1] if -timedelta(seconds=5) <= started - at <= RUN_WINDOW else None


# ---- the loop ----------------------------------------------------------------------


def keep(core: Core) -> None:
    """One pass over every workspace (the automation loop, every 20 s)."""
    if core.engine is None:
        return
    now = _now()
    for ws in catch_up_rows.workspaces(core.db):
        try:
            _keep_workspace(core, str(ws["id"]), ws["archived_at"] is not None, now)
        except (CronError, EngineError, OSError, ValueError) as error:
            log.warning("catch-up of %s not checked: %s", ws["id"], error)


def _keep_workspace(core: Core, workspace_id: str, archived: bool, now: datetime) -> None:
    from agos_core.actions import account_pause
    from agos_core.actions import automations as autos
    from agos_core.db import automations as repo

    held = archived or account_pause.held(core, workspace_id)
    stamp = _stamp(core, workspace_id, held)
    before = _stamps.get(workspace_id)
    if before is not None and before[0] == stamp and time.monotonic() - before[1] < RECHECK_S:
        return  # no cron file, choice or pause moved since the last look: nothing new
    jobs = autos.hermes_jobs(core, workspace_id)
    if jobs is None:
        return  # Hermes's cron can't be read now: nothing is known, nothing changes
    seen = {str(r["job_id"]): r for r in catch_up_rows.of_workspace(core.db, workspace_id)}
    for gone in set(seen) - set(jobs):
        catch_up_rows.forget(core.db, workspace_id, gone)
    automations = {str(r["hermes_job_id"]): r for r in repo.rows(core.db, workspace_id)}
    groups: dict[str, list[dict[str, Any]]] = {}
    for job_id, job in jobs.items():
        on = not held and (
            bool(job.get("enabled")) or job.get("paused_reason") == WORK_HOURS_REASON
        )
        row = _observe(core, workspace_id, job_id, seen.get(job_id), on, now)
        if not on or not job.get("enabled"):
            continue  # off-hours: still on, its missed run waits for the check-in
        spec = job.get("schedule_spec")
        if not isinstance(spec, dict) or spec.get("kind") not in ("cron", "interval"):
            continue  # a one-shot is Hermes's own (its grace window retires it)
        policy = _policy(automations.get(job_id))
        if row is not None and row["state"] == "waiting":
            _retry(core, workspace_id, job, row, policy, now)
            continue
        groups.setdefault(str(job.get("owner") or ""), []).append(
            {"job": job, "row": row, "policy": policy, "automation": automations.get(job_id)}
        )
    for owner, items in groups.items():
        _look(core, workspace_id, owner, items, now)
    if not catch_up_rows.waiting(core.db, workspace_id):  # a waiting one is tried every pass
        _stamps[workspace_id] = (_stamp(core, workspace_id, held), time.monotonic())
    else:
        _stamps.pop(workspace_id, None)


def _stamp(core: Core, workspace_id: str, held: bool) -> Any:
    """What a pass depends on, read without Hermes: each profile's cron/jobs.json
    (Hermes rewrites it at every run, skip, pause and resume), the pause, and the
    owner's choices."""
    from agos_core.actions import automations as autos

    files = []
    for owner, home in sorted(autos.homes(core, workspace_id).items()):
        try:
            st = (home / "cron" / "jobs.json").stat()
            files.append((owner, st.st_mtime_ns, st.st_size))
        except OSError:
            files.append((owner, 0, 0))
    return (tuple(files), held, catch_up_rows.choices(core.db, workspace_id))


def _policy(automation: sqlite3.Row | None) -> str:
    return "skip" if automation is not None and automation["catch_up"] == "skip" else "once"


def _observe(
    core: Core,
    workspace_id: str,
    job_id: str,
    row: sqlite3.Row | None,
    on: bool,
    now: datetime,
) -> sqlite3.Row | None:
    """Writes the job's on/off change only (never once per pass)."""
    if row is None:
        if on:
            return None  # on since it was made, as far as AGOS knows
        catch_up_rows.turned_off_first(core.db, workspace_id, job_id, _iso(now))
    elif on and row["off_since"] is not None:
        catch_up_rows.turned_on(core.db, workspace_id, job_id, _iso(now))
    elif not on and row["off_since"] is None:
        catch_up_rows.turned_off(core.db, workspace_id, job_id, _iso(now))
    else:
        return row
    return _row(core, workspace_id, job_id)


def _not_run_since(job: dict[str, Any], slot: datetime, now: datetime) -> bool:
    """No run, dispatch, queued Run now or live fire claim since the occurrence."""
    for key in ("last_run_at", "dispatched_for"):
        at = _parse(job.get(key))
        if at is not None and at >= slot:
            return False
    if job.get("run_queued"):
        return False
    claimed = _parse(job.get("claimed_at"))
    return not (
        claimed is not None and timedelta(0) <= now - claimed < timedelta(seconds=CLAIM_TTL_S)
    )


def _after(job: dict[str, Any], row: sqlite3.Row | None, now: datetime) -> datetime:
    """Where the search for a missed occurrence starts: the latest of its last run,
    its last dispatch, when it was made, when it came back on, what was already
    caught up, and the age limit."""
    found = [now - timedelta(days=LIMIT_DAYS)]
    for value in (job.get("last_run_at"), job.get("dispatched_for"), job.get("created_at")):
        at = _parse(value)
        if at is not None:
            found.append(at)
    if row is not None:
        for key in ("on_since", "missed_at"):
            at = _parse(row[key])
            if at is not None:
                found.append(at)
    return max(found)


def _look(
    core: Core, workspace_id: str, owner: str, items: list[dict[str, Any]], now: datetime
) -> None:
    from agos_core.actions import automations as autos

    bridge = autos.cron_bridge(core)
    slots = getattr(bridge, "slots", None)
    if slots is None:
        return
    shape = tuple(
        sorted(
            (
                str(i["job"]["id"]),
                str(i["job"].get("next_run_at")),
                str(i["job"].get("last_run_at")),
                str(i["job"].get("dispatched_for")),
                bool(i["job"].get("run_queued")),
                str(i["job"].get("claimed_at")),
                tuple(i["row"]) if i["row"] is not None else None,
                i["policy"],
            )
            for i in items
        )
    )
    key = (workspace_id, owner)
    before = _looked.get(key)
    if before is not None and before[0] == shape and time.monotonic() - before[1] < RECHECK_S:
        return  # nothing changed in Hermes's jobs since the last look
    home = autos.home_of(core, workspace_id, items[0]["job"])
    ask = [
        {
            "id": str(i["job"]["id"]),
            "schedule": i["job"]["schedule_spec"],
            "after": _iso(_after(i["job"], i["row"], now)),
        }
        for i in items
    ]
    found = slots(home, ask, _iso(now))
    _looked[key] = (shape, time.monotonic())
    for item in items:
        answer = found.get(str(item["job"]["id"])) or {}
        slot = _parse(answer.get("slot"))
        if slot is None:
            continue
        grace = float(answer.get("grace") or 120)
        if now - slot <= timedelta(seconds=grace):
            continue  # Hermes runs it itself, late (within its grace)
        if now - slot > timedelta(days=LIMIT_DAYS):
            continue
        if not _not_run_since(item["job"], slot, now):
            continue
        _missed(core, workspace_id, item, slot, now)


def _name(job: dict[str, Any], automation: sqlite3.Row | None) -> str:
    if automation is not None and automation["name"]:
        return str(automation["name"])
    return str(job.get("name") or job.get("id"))


def _when(core: Core, slot: datetime) -> str:
    """The occurrence on the owner's clock (General → timezone; empty = UTC)."""
    from agos_core.actions.owner_time import owner_zone, zone_of

    zone = zone_of(owner_zone(core)) if core.engine is not None else None
    local = slot.astimezone(zone) if zone is not None else slot.astimezone(UTC)
    return local.strftime("%a %d %b %H:%M")


def _missed(
    core: Core, workspace_id: str, item: dict[str, Any], slot: datetime, now: datetime
) -> None:
    job, automation = item["job"], item["automation"]
    job_id = str(job["id"])
    state = "skipped" if item["policy"] == "skip" else "waiting"
    # Written first: a restart between this line and the Run now never asks twice.
    catch_up_rows.missed(core.db, workspace_id, job_id, _iso(slot), state)
    if state == "skipped":
        if automation is not None:
            add_activity(
                core.db,
                workspace_id,
                kind="automation.catch_up_skipped",
                text=f"Missed run skipped (missed at {_when(core, slot)}, the server was off): "
                f"{_name(job, automation)}. It runs again at its next time.",
            )
        return
    row = _row(core, workspace_id, job_id)
    if row is not None:
        _ask(core, workspace_id, job, row, automation, now)


def _retry(
    core: Core,
    workspace_id: str,
    job: dict[str, Any],
    row: sqlite3.Row,
    policy: str,
    now: datetime,
) -> None:
    """A catch-up still waiting for the workspace's gateway: asked again while it is
    still missing (it may have run meanwhile, or he chose skip)."""
    slot = _parse(row["missed_at"])
    if (
        slot is None
        or policy == "skip"
        or now - slot > timedelta(days=LIMIT_DAYS)
        or not _not_run_since(job, slot, now)
    ):
        catch_up_rows.clear_state(core.db, workspace_id, str(job["id"]))
        return
    from agos_core.db import automations as repo

    automation = next(
        (r for r in repo.rows(core.db, workspace_id) if str(r["hermes_job_id"]) == str(job["id"])),
        None,
    )
    _ask(core, workspace_id, job, row, automation, now)


def _ask(
    core: Core,
    workspace_id: str,
    job: dict[str, Any],
    row: sqlite3.Row,
    automation: sqlite3.Row | None,
    now: datetime,
) -> None:
    """Hermes's Run now on the workspace's gateway; a gateway not up yet keeps it waiting."""
    from agos_core.actions import automations as autos

    bridge = autos.cron_bridge(core)
    if bridge is None:
        return
    try:
        bridge.run_now(autos.home_of(core, workspace_id, job), str(job["id"]))
    except (CronError, EngineError, OSError) as error:
        log.info("catch-up of %s waits for its gateway: %s", job.get("id"), error)
        return
    catch_up_rows.mark_asked(core.db, workspace_id, str(job["id"]), _iso(now))
    slot = _parse(row["missed_at"])
    with contextlib.suppress(sqlite3.Error):
        add_activity(
            core.db,
            workspace_id,
            kind="automation.catch_up",
            text=f"Catch-up run (missed at {_when(core, slot) if slot else '?'}, the server was "
            f"off): {_name(job, automation)} runs once now.",
        )
