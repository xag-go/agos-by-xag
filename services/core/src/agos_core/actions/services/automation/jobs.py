"""Writing an automation's job into Hermes cron: who runs it, its JobSpec, its
place (which profile's cron), a team automation's board script, the notices a
job Hermes refused or lost leaves on the row, and removing / parking jobs.

Owns: sync_job and its helpers. Must not: decide what the owner changed
(owner.py) or run on a timer (sync_loop.py).
"""

import contextlib
import logging
from typing import Any, Literal

from agos_core.actions import (
    agent_profiles,
    automation_cards,
    automation_variables,
    hooks,
    idle,
)
from agos_core.actions.errors import ActionError
from agos_core.actions.services.automation.cron import (
    COFOUNDER,
    Jobs,
    cron_bridge,
    get_with_source,
    hermes_jobs,
    home_of,
    homes,
    read_all,
)
from agos_core.actions.services.automation.instructions import drop_file
from agos_core.context import Core
from agos_core.db import automations as repo
from agos_core.db.records import (
    Automation,
)
from agos_core.engine import config_file
from agos_core.engine.cron import (
    ARCHIVED_REASON,
    FAILURES_TO,
    HELD_REASONS,
    CronBridge,
    CronError,
    JobSpec,
    automation_prompt,
    fire_script_name,
    instructions_of,
    legacy_job_name,
)
from agos_core.engine.hermes import EngineError
from agos_core.engine.models import (
    hermes_model,
)

__all__ = [
    "check_who",
    "gone_notice",
    "park",
    "pinned_skills",
    "resync_workspace",
    "runner",
    "sync_job",
    "team_notice",
    "who_label",
]

log = logging.getLogger("agos.automations")


def _on_team(core: Core, workspace_id: str, agent: str) -> bool:
    return agent in agent_profiles.team_names(core, workspace_id)


def gone_notice(core: Core, automation: Automation) -> str | None:
    """An agent that is gone or turned off never stops the automation: the
    Co-Founder does it, and the owner is told."""
    if not automation.agent or _on_team(core, automation.workspace_id, automation.agent):
        return None
    return (
        f"@{automation.agent} is no longer on in this team, so the Co-Founder does it. "
        "Pick someone else in the automation, or turn the agent back on."
    )


def runner(core: Core, automation: Automation, current: str | None = None) -> str:
    """Whose Hermes cron runs a one-agent automation: its agent's own profile, or
    the Co-Founder's (no agent picked, or the agent is off). `current`: whose cron
    holds its job now (None: none); it stays there while a new agent's profile is
    still being made. Raises CronError when there is nowhere to put it yet."""
    agent = automation.agent
    workspace_id = automation.workspace_id
    if not agent or not _on_team(core, workspace_id, agent):
        return COFOUNDER
    if agent_profiles.ready(core, workspace_id, agent):
        return agent
    if current is not None:
        return current
    raise CronError(f"@{agent}'s own profile isn't set up yet")


def _spec(core: Core, automation: Automation, owner: str = COFOUNDER) -> JobSpec:
    """The one-agent job. Who does it is whose cron holds it (its SOUL.md says who
    it is), so the prompt is the automation's alone: the one copy of its
    instructions."""
    from agos_core.actions.hermes_channel import cofounder_chat  # late: heavy imports

    model = hermes_model(automation.model)
    effort = (model.get("model_options") or {}).get("reasoning_effort")
    # Hermes tells a failed run to the Co-Founder chat: the root's agos platform has
    # it as its home chat; a member's profile names it.
    chat = cofounder_chat(core, automation.workspace_id) if owner else None
    return JobSpec(
        name=automation.name,  # the one copy of the owner's name (AGOS keeps none)
        prompt=automation_prompt(
            automation.instructions, automation_variables.prompt_tail(automation.variables)
        ),
        schedule=automation.schedule,
        model=str(model["model"]),
        provider=str(model["provider"]),
        reasoning_effort=str(effort) if effort else None,
        enabled=automation.on,
        failure_deliver=f"{FAILURES_TO}:{chat}" if chat is not None else FAILURES_TO,
        skills=tuple(pinned_skills(core, automation.workspace_id, owner)),
    )


def pinned_skills(core: Core, workspace_id: str, owner: str) -> list[str]:
    """The skills the job's profile pins (its `skills.auto_load`, set from the
    member's skills). Hermes's cron leaves auto_load out of a run (cron/scheduler.py
    skip_context_files), so they go on the job as its own `skills`."""
    home = homes(core, workspace_id).get(owner) if core.engine is not None else None
    if home is None:
        return []
    try:
        cfg = config_file.read(home)
    except (OSError, ValueError):
        return []
    return config_file.string_list(config_file.get(cfg, "skills.auto_load")) or []


def sync_job(
    core: Core,
    workspace_id: str,
    automation_id: int,
    want: tuple[str, bool] | None = None,
    agent: str | Literal[False] | None = False,
) -> str | None:
    """Makes the Hermes job match the automation. `want`: the schedule and on/off
    the owner just asked for (None: keep Hermes's); `agent`: who he just picked
    (False: keep who does it now). Returns the problem, if any (saved on the
    automation and shown to the owner; never silent). Once a one-agent job holds
    the instructions, AGOS's file of them goes."""
    found = get_with_source(core, workspace_id, automation_id)
    if found is None:
        return None
    automation, source = found
    if want is not None:
        automation = automation.model_copy(update={"schedule": want[0], "on": want[1]})
    elif source in ("missing", "unknown"):
        # Hermes doesn't say (or lost the job): nothing is guessed, nothing removed.
        return automation.problem
    if agent is not False:
        automation = automation.model_copy(update={"agent": agent})
    job = repo.job_id(core.db, automation_id)
    if (automation.steps or automation.check_first) and automation.schedule:
        return _sync_board_job(core, automation)
    if not automation.schedule:
        # Started by an event (no time): nothing in Hermes's cron; its on/off is its route's.
        remove_job(core, workspace_id, automation_id, job)
        repo.clear_job(core.db, automation_id)
        repo.set_job(core.db, automation_id, job=None, error=None)
        repo.forget_request(core.db, automation_id)  # its on/off is its Hermes route's
        repo.set_agent(core.db, automation_id, automation.agent)
        # No job to hold its name: its Hermes route does (else AGOS until it can).
        if not hooks.held_by_route(core, workspace_id, automation_id, automation.name):
            repo.set_name(core.db, automation_id, automation.name)
        write_scripts(core, automation)
        set_notice(
            core,
            automation,
            team_notice(core, automation) if automation.steps else gone_notice(core, automation),
        )
        return None
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        _keep_unsent(core, automation)
        return None
    problem: str | None = None
    try:
        if not (core.engine.profile_home(workspace_id) / "config.yaml").is_file():
            raise CronError("this workspace's agent isn't set up yet (is Docker running?)")
        jobs = read_all(core, workspace_id)
        held = jobs.get(str(job)) if job else None
        owner = runner(core, automation, str(held["owner"]) if held else None)
        spec = _spec(core, automation, owner)
        job = _place(core, bridge, automation, jobs, owner, spec)
        repo.forget_request(core.db, automation_id, model=True, name=True)  # Hermes has them
        drop_file(core, workspace_id, automation.file, automation.instructions)
        # Its own cron holds the job: Hermes says who does it. Else the owner's pick
        # stays (the Co-Founder does it while the agent is off).
        repo.set_agent(core.db, automation_id, None if owner else automation.agent)
        if automation.on:
            # The scheduler ticks inside the gateway. Hermes's service keeps it up
            # (Restart=always); a gateway stopped on purpose stays stopped and the job
            # waits for it like the inbox. Only the test-only spawn supervisor restarts.
            idle.spawned_up(core, workspace_id)
    except (CronError, EngineError, OSError, ValueError) as error:
        problem = f"Not scheduled: {error}"[:300]
        log.warning("automation %s/%s: %s", workspace_id, automation_id, error)
        # What Hermes didn't take is shown (and tried again) from AGOS's row.
        repo.keep_request(
            core.db,
            automation_id,
            schedule=automation.schedule,
            on=automation.on,
            agent=automation.agent,
            name=automation.name,
        )
    repo.set_job(core.db, automation_id, job=job, error=problem)
    set_notice(core, automation, gone_notice(core, automation))
    return problem


def _keep_unsent(core: Core, automation: Automation) -> None:
    """No engine to give it to: his request waits in AGOS's row (as when Hermes
    refuses it)."""
    repo.keep_request(
        core.db,
        automation.id,
        schedule=automation.schedule,
        on=automation.on,
        agent=automation.agent,
        name=automation.name,
    )


def _place(
    core: Core,
    bridge: CronBridge,
    automation: Automation,
    jobs: Jobs,
    owner: str,
    spec: JobSpec,
) -> str:
    """Puts the automation's job in `owner`'s Hermes cron and returns its id. A
    job of it in another profile's cron (its agent changed, or it was made in the
    Co-Founder's cron before each member ran its own) moves: made here, linked, and
    then removed there (Hermes removes its finished runs with it). Safe to repeat after a stop at any point: Hermes's jobs
    are found again by their name."""
    assert core.engine is not None
    home = homes(core, automation.workspace_id).get(owner)
    if home is None or not (home / "config.yaml").is_file():
        raise CronError(f"@{owner}'s own profile isn't set up yet")
    linked = repo.job_id(core.db, automation.id)
    mine = [j for j in jobs.values() if str(j["id"]) == linked or _its_job(automation, spec, j)]
    here = sorted((j for j in mine if j["owner"] == owner), key=lambda j: str(j["id"]) != linked)
    if here:
        job = str(here[0]["id"])
        bridge.update(home, job, spec)
    else:
        job = str(bridge.create(home, spec)["id"])
        before = next((j for j in mine if str(j["id"]) == linked), None)
        reason = before.get("paused_reason") if before and not before.get("enabled") else None
        if spec.enabled and reason in HELD_REASONS:
            bridge.pause(home, job, str(reason))  # still held, as it was
    repo.set_job(core.db, automation.id, job=job, error=None)
    for other in mine:
        if str(other["id"]) == job:
            continue
        there = home_of(core, automation.workspace_id, other)
        bridge.remove(there, str(other["id"]))
    return job


def _its_job(automation: Automation, spec: JobSpec, job: dict[str, Any]) -> bool:
    """A job of this automation that lost its link (a stop between Hermes making it
    and AGOS saving its id, or a move that stopped halfway): its old AGOS name, its
    own script (a Kanban automation's), or the owner's name with its instructions."""
    if job.get("name") == legacy_job_name(automation.id):
        return True
    if spec.script:
        return job.get("script") == spec.script
    return (
        job.get("name") == spec.name
        and not job.get("script")
        and instructions_of(str(job.get("prompt") or "")) == automation.instructions.strip()
    )


def _board_spec(automation: Automation) -> JobSpec:
    return JobSpec(
        name=automation.name,  # the one copy of the owner's name (AGOS keeps none)
        prompt="",
        schedule=automation.schedule,
        model="",
        provider="",
        reasoning_effort=None,
        enabled=automation.on,
        script=fire_script_name(automation.id),
    )


def _sync_board_job(core: Core, automation: Automation) -> str | None:
    """A team automation (or one that checks first) on a schedule: its clock is a
    Hermes cron job that runs a small script (no agent, no tokens) with which
    Hermes puts its steps on the workspace's Kanban at each time (automation_cards).
    The job is the Co-Founder's (the root's): the cards say who does each step."""
    workspace_id = automation.workspace_id
    bridge = cron_bridge(core)
    set_notice(
        core,
        automation,
        team_notice(core, automation) if automation.steps else gone_notice(core, automation),
    )
    if bridge is None or core.engine is None:
        _keep_unsent(core, automation)
        return None
    home = core.engine.profile_home(workspace_id)
    job = repo.job_id(core.db, automation.id)
    problem: str | None = None
    try:
        if not (home / "config.yaml").is_file():
            raise CronError("this workspace's agent isn't set up yet (is Docker running?)")
        automation_cards.write_scripts(core, automation)
        spec = _board_spec(automation)
        jobs = read_all(core, workspace_id)
        job = _place(core, bridge, automation, jobs, COFOUNDER, spec)
        repo.forget_request(core.db, automation.id, name=True)  # Hermes has it now
        repo.set_agent(core.db, automation.id, automation.agent)  # the plan's (AGOS's)
        if automation.on:
            # The scheduler ticks inside the gateway. Hermes's service keeps it up
            # (Restart=always); a gateway stopped on purpose stays stopped and the job
            # waits for it like the inbox. Only the test-only spawn supervisor restarts.
            idle.spawned_up(core, workspace_id)
    except (CronError, EngineError, OSError, ValueError) as error:
        problem = f"Not scheduled: {error}"[:300]
        log.warning("automation %s/%s: %s", workspace_id, automation.id, error)
        repo.keep_request(
            core.db,
            automation.id,
            schedule=automation.schedule,
            on=automation.on,
            agent=automation.agent,
            name=automation.name,
        )
    repo.set_job(core.db, automation.id, job=job, error=problem)
    return problem


def write_scripts(core: Core, automation: Automation) -> str | None:
    """Hermes's scripts for a Kanban automation follow it (its plan: steps, who,
    texts). Returns the problem, if any."""
    try:
        automation_cards.write_scripts(core, automation)
    except (ActionError, OSError, ValueError) as error:
        log.warning("automation %s: its script: %s", automation.id, error)
        return f"Not ready: {error}"[:300]
    return None


def set_notice(core: Core, automation: Automation, notice: str | None) -> None:
    """Saved on the automation; a NEW notice also reaches the owner (Co-Founder's DM)."""
    if notice == automation.notice:
        return
    repo.set_notice(core.db, automation.id, notice)
    if notice:
        from agos_core.actions.services.channel.owner_needs import tell_owner

        tell_owner(core, automation.workspace_id, f"⚠️ Automation “{automation.name}”: {notice}")


def who_label(agent: str | None, steps: list[dict[str, Any]]) -> str:
    if steps:
        names = [
            f"@{s['agent']}"
            if s.get("agent")
            else ("you" if s.get("kind") == "approval" else "Co-Founder")
            for s in steps
        ]
        # Steps side by side (e.g. one per style) read once: @a → @b, not @a → @a → @a.
        order = " → ".join(n for i, n in enumerate(names) if i == 0 or names[i - 1] != n)
        return f"the team: {order}"
    return f"@{agent}" if agent else "the Co-Founder"


def team_notice(core: Core, automation: Automation) -> str | None:
    from agos_core.actions.library import agent_text

    gone = sorted(
        {
            s.agent
            for s in automation.steps
            if s.agent and agent_text(core, automation.workspace_id, s.agent) is None
        }
    )
    if not gone:
        return None
    who = ", ".join(f"@{g}" for g in gone)
    return (
        f"{who} {'is' if len(gone) == 1 else 'are'} no longer on in this team, so the "
        "Co-Founder does those steps. Pick someone else in the automation, or turn them back on."
    )


def check_who(
    core: Core, workspace_id: str, agent: str | None, steps: list[Any]
) -> tuple[str | None, list[dict[str, Any]]]:
    """The agent / the team plan, checked against this workspace's team."""
    from agos_core.actions.library import check_agent
    from agos_core.engine import team_steps

    if steps:
        from agos_core.actions import team

        members = [a.name for a in team.members(core, workspace_id)]
        raw = [s if isinstance(s, dict) else s.model_dump() for s in steps]
        try:
            plan = team_steps.parse_plan({"title": "automation", "steps": raw}, members)
        except team_steps.PlanError as error:
            raise ActionError(f"Team steps: {error}.") from error
        return None, [
            {
                "key": s.key,
                "title": s.title,
                "description": s.description,
                "kind": s.kind,
                "agent": s.agent,
                "waits_on": list(s.waits_on),
                "reviews": s.reviews,
            }
            for s in plan.steps
        ]
    if agent and agent.lower() not in (
        "cofounder",
        "manager",
        "",
    ):  # "manager": the name before step 44, still in old rows and cards
        return check_agent(core, workspace_id, agent), []
    return None, []


def remove_job(
    core: Core, workspace_id: str, automation_id: int, linked: str | None = None
) -> None:
    """The automation's job goes from whichever profile's cron holds it."""
    bridge = cron_bridge(core)
    if bridge is None or core.engine is None:
        return
    linked = linked or repo.job_id(core.db, automation_id)
    name = legacy_job_name(automation_id)
    script = fire_script_name(automation_id)
    for job in (hermes_jobs(core, workspace_id) or {}).values():
        if str(job["id"]) == linked or job.get("name") == name or job.get("script") == script:
            with contextlib.suppress(CronError, OSError):
                bridge.remove(home_of(core, workspace_id, job), str(job["id"]))


def park(core: Core, workspace_id: str) -> None:
    """Workspace archived or trashed: its automations stop firing. Only jobs that
    are on are paused (with the archive's reason), so a restore turns back on
    exactly those."""
    if not any(r["hermes_job_id"] for r in repo.rows(core.db, workspace_id)):
        return
    bridge = cron_bridge(core)
    jobs = hermes_jobs(core, workspace_id)
    if bridge is None or core.engine is None or jobs is None:
        return
    for row in repo.rows(core.db, workspace_id):
        job = jobs.get(str(row["hermes_job_id"] or ""))
        if job is not None and job.get("enabled"):
            with contextlib.suppress(CronError, OSError):
                bridge.pause(home_of(core, workspace_id, job), str(job["id"]), ARCHIVED_REASON)


def resync_workspace(core: Core, workspace_id: str) -> None:
    """Workspace restored: jobs match AGOS again (an archived job resumes)."""
    for row in repo.rows(core.db, workspace_id):
        sync_job(core, workspace_id, int(row["id"]))
