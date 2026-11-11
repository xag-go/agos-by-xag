"""The owner's actions on an automation: save (create / change), its revisions and
restore, on/off, Run now (a Kanban automation's script run once), delete.

Owns: validating his input and recording a revision. Must not: build a job
spec itself (jobs.py) or read Hermes cron directly (cron.py).
"""

import contextlib
from pathlib import PurePosixPath
from typing import Any, Literal

from agos_core.actions import (
    automation_cards,
    automation_variables,
    hooks,
)
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.automation.cron import (
    MISSING,
    cron_bridge,
    get,
    get_with_source,
    hermes_jobs,
    home_of,
    schedule_problem,
)
from agos_core.actions.services.automation.instructions import file_path, write_file
from agos_core.actions.services.automation.jobs import (
    check_who,
    remove_job,
    set_notice,
    sync_job,
    team_notice,
    write_scripts,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import automation_revisions as revisions
from agos_core.db import automations as repo
from agos_core.db.activity import add_activity
from agos_core.db.records import (
    Automation,
    AutomationRevision,
    TicketMapping,
)
from agos_core.db.rows import now
from agos_core.domain.models import ModelSelection
from agos_core.domain.workspace import workspace_id_from_name
from agos_core.engine.automation_run import NOT_STARTED, STILL_GOING
from agos_core.engine.cron import (
    CronError,
    fire_script_name,
    hook_script_name,
)
from agos_core.engine.hermes import EngineError

__all__ = [
    "POLICIES",
    "delete",
    "list_revisions",
    "restore",
    "run_now",
    "save",
    "toggle",
]


def save(
    core: Core,
    workspace_id: str,
    automation_id: int | None,
    *,
    name: str,
    instructions: str,
    schedule: str,
    model: ModelSelection,
    on: bool,
    agent: str | None = None,
    steps: list[Any] | None = None,
    hook: bool | None = None,
    check_first: bool = False,
    variables: list[Any] | None = None,
    policy: str | None = None,
    ticket: dict[str, Any] | Literal[False] | None = False,
    who: str = "owner",
    restored_from: int | None = None,
    catch_up: str | None = None,
) -> int:
    """Starts on its schedule, the moment something happens (hook), or both.
    hook: True turns the webhook on (keeps its address), False off, None leaves it.
    check_first: the owner approves each run before anything starts.
    variables / policy: None keeps what the automation has (a change never wipes
    what it doesn't name); ticket: False keeps it, None removes it.
    The schedule, on/off and (one agent on a schedule) the instructions go into
    Hermes's job; the file keeps the instructions only while no job holds them.
    Every save that changed something appends a revision (`who` saved it).
    catch_up: a run missed while the server was off, "once" or "skip" (None keeps it;
    actions/catch_up.py)."""
    require_workspace(core, workspace_id)
    if catch_up is not None and catch_up not in ("once", "skip"):
        raise ActionError("If a run was missed: once (run it once when AGOS is back) or skip.")
    had_hook = automation_id is not None and automation_id in hooks.routes(core, workspace_id)
    if hook is None:
        hook = had_hook
    problem = schedule_problem(core, workspace_id, schedule) if schedule else None
    if problem:
        raise ActionError(f"Schedule: {problem}.")
    if not schedule and not hook:
        raise ActionError(
            "Say when it starts: a schedule, a webhook (the moment something happens), or both."
        )
    agent, clean_steps = check_who(core, workspace_id, agent, steps or [])
    current = repo.row(core.db, workspace_id, automation_id) if automation_id is not None else None
    if automation_id is not None and current is None:
        raise NotFoundError("This automation")
    kept = repo.from_row(current) if current is not None else None
    clean_variables = (
        automation_variables.check_variables(variables)
        if variables is not None
        else [v.model_dump() for v in kept.variables]
        if kept is not None
        else []
    )
    clean_policy = _checked_policy(policy) if policy is not None else (kept.policy if kept else "")
    clean_ticket = (
        (kept.ticket.model_dump() if kept is not None and kept.ticket else None)
        if ticket is False
        else _checked_ticket(core, workspace_id, ticket)
    )
    if clean_ticket is not None and not hook:
        raise ActionError("A ticket on-ramp needs the webhook on: that is where the issues arrive.")
    if automation_id is None:
        taken = {str(r["file"]) for r in repo.rows(core.db, workspace_id)}
        slug = workspace_id_from_name(name) or "automation"
        file, n = f"automations/{slug}.md", 2
        while file in taken:
            file, n = f"automations/{slug}-{n}.md", n + 1
        write_file(core, workspace_id, file=file, instructions=instructions)
        new_id = repo.insert_automation(
            core.db,
            workspace_id,
            name=name,
            file=file,
            schedule=schedule,
            model=model,
            agent=agent,
            steps=clean_steps,
            check_first=check_first,
            variables=clean_variables,
            policy=clean_policy or "skip_if_active",
            ticket=clean_ticket,
        )
        if catch_up is not None:
            repo.set_catch_up(core.db, new_id, catch_up)
        add_activity(
            core.db, workspace_id, kind="automation.created", text=f"Automation created: {name}"
        )
        sync_job(core, workspace_id, new_id, want=(schedule, on), agent=agent)
        if hook:
            try:
                hooks.set_hook(core, workspace_id, new_id, on=True, enabled=on)
                _preset_filters(core, workspace_id, new_id, None, clean_ticket, on)
            except ActionError:
                _undo_create(core, workspace_id, new_id)  # Hermes didn't take its webhook
                raise
        _record_revision(core, workspace_id, new_id, who, restored_from)
        return new_id
    assert current is not None
    held = get_with_source(core, workspace_id, automation_id)
    one_agent = bool(schedule) and not (clean_steps or check_first or hook)
    if not (
        one_agent
        and held is not None
        and held[1] == "hermes"
        and not automation_cards.card_runs(held[0])
        and held[0].instructions.strip() == instructions.strip()
    ):
        # Hermes's job doesn't hold these instructions (yet): they wait in the file.
        write_file(core, workspace_id, file=str(current["file"]), instructions=instructions)
    else:
        # Hermes's prompt already holds them: never written a second time, and an
        # older request still waiting in the file is dropped (this one replaces it).
        with contextlib.suppress(OSError, ValueError):
            file_path(core, workspace_id, str(current["file"])).unlink(missing_ok=True)
    repo.update_automation(
        core.db,
        workspace_id,
        automation_id,
        name=name,
        schedule=schedule,
        model=model,
        agent=agent,
        steps=clean_steps,
        check_first=check_first,
        variables=clean_variables,
        policy=clean_policy or "skip_if_active",
        ticket=clean_ticket,
    )
    if catch_up is not None:
        repo.set_catch_up(core.db, automation_id, catch_up)
    if bool(hook) != had_hook:
        hooks.set_hook(
            core, workspace_id, automation_id, on=bool(hook), schedule=schedule, enabled=on
        )
    sync_job(core, workspace_id, automation_id, want=(schedule, on), agent=agent)
    if hook:
        hooks.follow(core, workspace_id, automation_id, on=on)  # its route and script
        _preset_filters(core, workspace_id, automation_id, kept, clean_ticket, on)
    _record_revision(core, workspace_id, automation_id, who, restored_from)
    return automation_id


def _preset_filters(
    core: Core,
    workspace_id: str,
    automation_id: int,
    kept: Automation | None,
    ticket: dict[str, Any] | None,
    on: bool,
) -> None:
    """A ticket on-ramp just chosen (or changed): its preset's events and "Only if"
    lines go into the Hermes route once; the owner may edit them after."""
    from agos_core.actions import ticket_presets

    if ticket is None:
        return
    before = kept.ticket.source if kept is not None and kept.ticket else None
    if before == ticket["source"]:
        return
    found = ticket_presets.preset(str(ticket["source"]))
    hooks.set_hook(
        core,
        workspace_id,
        automation_id,
        on=True,
        events=list(found["events"]),
        conditions=list(found["conditions"]),
        enabled=on,
    )


POLICIES = ("skip_if_active", "coalesce_if_active", "always_enqueue")


def _checked_policy(policy: str) -> str:
    if policy not in POLICIES:
        raise ActionError("Policy: skip_if_active, coalesce_if_active or always_enqueue.")
    return policy


def _checked_ticket(
    core: Core, workspace_id: str, ticket: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The ticket on-ramp as saved: a known source and a member of this team."""
    from agos_core.actions.library import check_agent

    if ticket is None:
        return None
    clean = TicketMapping.model_validate(ticket)
    member = (clean.member or "").strip().lstrip("@") or None
    if member and member.lower() in ("cofounder", "manager"):
        member = None
    if member:
        check_agent(core, workspace_id, member)
    return {"source": clean.source, "member": member}


def _record_revision(
    core: Core, workspace_id: str, automation_id: int, who: str, restored_from: int | None
) -> None:
    """The save as a revision (only when something changed, or on a restore)."""
    automation = get(core, workspace_id, automation_id)
    if automation is None:
        return
    revisions.append(
        core.db,
        workspace_id,
        automation_id,
        revisions.snapshot_of(automation),
        who=who,
        restored_from=restored_from,
    )


def list_revisions(core: Core, workspace_id: str, automation_id: int) -> list[AutomationRevision]:
    if repo.row(core.db, workspace_id, automation_id) is None:
        raise NotFoundError("This automation")
    return revisions.list_revisions(core.db, automation_id)


def restore(core: Core, workspace_id: str, automation_id: int, n: int, who: str = "owner") -> int:
    """Restore = a new save from revision vN (its webhook lines included), recorded
    as a revision "restored from vN". Nothing is rewound in Hermes: the job and the
    route are written again as that revision had them."""
    if repo.row(core.db, workspace_id, automation_id) is None:
        raise NotFoundError("This automation")
    snapshot = revisions.get_snapshot(core.db, automation_id, n)
    if snapshot is None:
        raise NotFoundError(f"Revision v{n}")
    hook = snapshot.get("hook") if isinstance(snapshot.get("hook"), dict) else None
    save(
        core,
        workspace_id,
        automation_id,
        name=str(snapshot.get("name") or ""),
        instructions=str(snapshot.get("instructions") or ""),
        schedule=str(snapshot.get("schedule") or ""),
        model=ModelSelection.model_validate(snapshot["model"]),
        on=bool(snapshot.get("on", True)),
        agent=snapshot.get("agent"),
        steps=list(snapshot.get("steps") or []),
        hook=hook is not None,
        check_first=bool(snapshot.get("check_first")),
        variables=list(snapshot.get("variables") or []),
        policy=str(snapshot.get("policy") or "skip_if_active"),
        ticket=snapshot.get("ticket") if isinstance(snapshot.get("ticket"), dict) else None,
        who=who,
        restored_from=n,
    )
    if hook is not None:
        from agos_core.db.records import HookCondition

        hooks.set_hook(
            core,
            workspace_id,
            automation_id,
            on=True,
            events=[str(e) for e in hook.get("events") or []],
            conditions=[HookCondition.model_validate(c) for c in hook.get("conditions") or []],
        )
    add_activity(
        core.db,
        workspace_id,
        kind="automation.restored",
        text=f"Automation restored from v{n}: {snapshot.get('name') or automation_id}",
    )
    return n


def _undo_create(core: Core, workspace_id: str, automation_id: int) -> None:
    """A new automation whose webhook Hermes didn't take is not made at all."""
    job = repo.job_id(core.db, automation_id)
    file = repo.delete_automation(core.db, workspace_id, automation_id)
    remove_job(core, workspace_id, automation_id, job)
    if core.engine is not None:
        scripts = core.engine.profile_home(workspace_id) / "scripts"
        for name in (fire_script_name(automation_id), hook_script_name(automation_id)):
            (scripts / name).unlink(missing_ok=True)
    if file:
        file_path(core, workspace_id, file).unlink(missing_ok=True)


def toggle(core: Core, workspace_id: str, automation_id: int, on: bool) -> None:
    """On/off: into Hermes (pause/resume its job), or AGOS's own for an automation
    with no Hermes job (a webhook only)."""
    found = get_with_source(core, workspace_id, automation_id)
    if found is None:
        raise NotFoundError("This automation")
    current, source = found
    if source == "missing":
        raise ActionError(MISSING, 409)
    if source == "unknown":
        raise ActionError("The scheduler can't be read right now; try again in a moment.", 503)
    # Straight to Hermes's job (pause/resume); AGOS keeps it only if Hermes refuses.
    sync_job(core, workspace_id, automation_id, want=(current.schedule, on))
    if current.hook is not None:
        hooks.follow(core, workspace_id, automation_id, on=on)  # off: Hermes refuses them


def run_now(
    core: Core, workspace_id: str, automation_id: int, values: dict[str, Any] | None = None
) -> None:
    """Fires once on the scheduler's next tick (within a minute), whatever the schedule.
    An automation that is off fires this once and stays off. `values`: the typed
    variables for this run (Run now with variables), checked against their types;
    a Kanban automation's run takes them, a one-agent job runs on its defaults
    (Hermes's `POST /api/jobs/{id}/run` takes no input)."""
    automation = get(core, workspace_id, automation_id)
    if automation is None:
        raise NotFoundError("This automation")
    given = automation_variables.check_values(automation.variables, values)
    changed = given != automation_variables.defaults(automation.variables)
    if automation.steps or not automation.schedule or automation.check_first:
        _run_on_board(core, automation, given if changed else None)
        return
    if changed:
        raise ActionError(
            "This automation runs as one agent's scheduled job, which Run now starts with "
            "its default values. Change the defaults in Variables to run it otherwise.",
            409,
        )
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so nothing can run.", 409)
    problem = sync_job(core, workspace_id, automation_id)
    job = repo.job_id(core.db, automation_id)
    if problem or not job:
        raise ActionError(problem or "This automation isn't scheduled yet.", 409)
    held = (hermes_jobs(core, workspace_id) or {}).get(job)
    if held is None:
        raise ActionError(MISSING, 409)
    try:
        core.engine.start(workspace_id)
        bridge.run_now(home_of(core, workspace_id, held), job)
        repo.set_manual_at(core.db, automation_id, now())
    except (CronError, EngineError, OSError) as error:
        raise ActionError(f"Couldn't start it: {error}", 503) from error
    add_activity(
        core.db,
        workspace_id,
        kind="automation.run",
        text=f"Automation started by hand: {automation.name}",
    )


def delete(core: Core, workspace_id: str, automation_id: int) -> None:
    mine = repo.row(core.db, workspace_id, automation_id)
    if mine is None:
        return  # another workspace's (or gone): nothing of it is read or removed
    job = repo.job_id(core.db, automation_id)
    file = repo.delete_automation(core.db, workspace_id, automation_id)
    if file is None:
        return
    remove_job(core, workspace_id, automation_id, job)
    hooks.forget(core, workspace_id, automation_id)
    if core.engine is not None:
        scripts = core.engine.profile_home(workspace_id) / "scripts"
        for name in (fire_script_name(automation_id), hook_script_name(automation_id)):
            (scripts / name).unlink(missing_ok=True)
        automation_cards.deliveries_log(core, workspace_id, automation_id).unlink(missing_ok=True)
    file_path(core, workspace_id, file).unlink(missing_ok=True)
    add_activity(
        core.db,
        workspace_id,
        kind="automation.deleted",
        text=f"Automation deleted: {PurePosixPath(file).stem}",
    )


def _run_on_board(core: Core, automation: Automation, values: dict[str, str] | None = None) -> None:
    """Run now: its cards go on the Kanban. A scheduled one that is on: Hermes runs
    its job once (`hermes cron run`, recorded as its run). Without a job Hermes can
    run (started by a webhook only, or off: Hermes refuses a paused job's run, "Job
    is paused/disabled"), or with values for its variables (`hermes cron run` takes
    no input), Hermes's runtime runs its script once, the values on its stdin.
    Refused while its last run is still on the board (by the automation's policy)."""
    import json

    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so nothing can run.", 409)
    problem = write_scripts(core, automation)
    if problem:
        raise ActionError(problem, 409)
    set_notice(core, automation, team_notice(core, automation))
    home = core.engine.profile_home(automation.workspace_id)
    job = repo.job_id(core.db, automation.id) if automation.schedule else None
    held = (hermes_jobs(core, automation.workspace_id) or {}).get(str(job)) if job else None
    clicked = now()
    try:
        if held is not None and held.get("enabled") and values is None:
            repo.set_manual_at(core.db, automation.id, clicked)
            ok, said = bridge.run_inline(home_of(core, automation.workspace_id, held), str(job))
            code = STILL_GOING if said.startswith(NOT_STARTED) else 0 if ok else 1
        else:
            code, said = bridge.run_script(
                home,
                fire_script_name(automation.id),
                ["manual"],
                stdin=json.dumps({"variables": values}) if values else "",
            )
    except (CronError, OSError) as error:
        raise ActionError(f"Couldn't start it: {error}", 503) from error
    if code == STILL_GOING:
        text = f"Automation “{automation.name}” didn't start again: {said}"
        add_activity(core.db, automation.workspace_id, kind="automation.skipped", text=text)
        raise ActionError(text, 409)
    if code != 0:
        raise ActionError(f"Couldn't start it: {said or 'its script failed'}"[:300], 503)
    repo.set_manual_at(core.db, automation.id, clicked)
    add_activity(
        core.db,
        automation.workspace_id,
        kind="automation.run",
        text=f"Automation started by hand: {automation.name} ({said})"[:300],
    )
