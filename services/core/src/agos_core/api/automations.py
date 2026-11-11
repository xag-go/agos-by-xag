"""Automations of a workspace."""

from typing import Annotated, Literal

from fastapi import APIRouter, Header

from agos_core.actions import automations as actions
from agos_core.actions import hooks, ticket_presets
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.automation.hooks_address import hooks_address as hooks_address
from agos_core.actions.services.automation.hooks_address import (
    save_hooks_address as save_hooks_address,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import (
    AutomationBody,
    Created,
    HookBody,
    HooksSettings,
    RunNowBody,
    Toggle,
)
from agos_core.db.records import (
    Automation,
    AutomationCost,
    AutomationEvent,
    AutomationHook,
    AutomationRevision,
    AutomationRun,
    AutomationRunGroup,
    Record,
    RunDetail,
)
from agos_core.ops import idempotency

router = APIRouter(tags=["automations"])


@router.get("/workspaces/{workspace_id}/automations")
def list_automations(
    core: CoreDep, workspace_id: str, kind: Literal["event", "schedule"] | None = None
) -> list[Automation]:
    """kind=event: the events tab; kind=schedule: the automations tab."""
    require_workspace(core, workspace_id)
    return actions.list_all(core, workspace_id, kind)


@router.get("/workspaces/{workspace_id}/automations/{automation_id}")
def get_automation(core: CoreDep, workspace_id: str, automation_id: int) -> Automation:
    found = actions.get(core, workspace_id, automation_id)
    if found is None:
        raise NotFoundError("This automation")
    return found


class ScheduleText(Record):
    """Hermes's own words for a schedule (None: Hermes couldn't be asked) and why
    it refuses it (None: it takes it)."""

    display: str | None
    problem: str | None


@router.get("/workspaces/{workspace_id}/schedule-text")
async def schedule_text(core: CoreDep, workspace_id: str, schedule: str = "") -> ScheduleText:
    import asyncio

    display, problem = await asyncio.to_thread(
        actions.describe_schedule, core, workspace_id, schedule[:500]
    )
    return ScheduleText(display=display, problem=problem)


@router.post("/workspaces/{workspace_id}/automations", status_code=201)
def create(core: CoreDep, workspace_id: str, body: AutomationBody) -> Created:
    return Created(
        id=actions.save(
            core,
            workspace_id,
            None,
            name=body.name.strip(),
            instructions=body.instructions.strip(),
            schedule=body.schedule.strip(),
            model=body.model,
            on=body.on,
            agent=body.agent,
            steps=body.steps,
            hook=body.hook,
            check_first=body.check_first,
            variables=body.variables,
            policy=body.policy,
            ticket=body.ticket.model_dump() if body.ticket else None,
            catch_up=body.catch_up,
        )
    )


@router.put("/workspaces/{workspace_id}/automations/{automation_id}")
def update(core: CoreDep, workspace_id: str, automation_id: int, body: AutomationBody) -> None:
    actions.save(
        core,
        workspace_id,
        automation_id,
        name=body.name.strip(),
        instructions=body.instructions.strip(),
        schedule=body.schedule.strip(),
        model=body.model,
        on=body.on,
        agent=body.agent,
        steps=body.steps,
        hook=body.hook,
        check_first=body.check_first,
        variables=body.variables,
        policy=body.policy,
        ticket=body.ticket.model_dump() if body.ticket else None,
        catch_up=body.catch_up,
    )


@router.get("/workspaces/{workspace_id}/automations/{automation_id}/revisions")
def list_revisions(
    core: CoreDep, workspace_id: str, automation_id: int
) -> list[AutomationRevision]:
    """The Revisions tab: every saved version, newest first, with its diff (one read)."""
    require_workspace(core, workspace_id)
    return actions.list_revisions(core, workspace_id, automation_id)


@router.post("/workspaces/{workspace_id}/automations/{automation_id}/revisions/{n}/restore")
def restore_revision(core: CoreDep, workspace_id: str, automation_id: int, n: int) -> Created:
    """Restore = a new save from revision vN (recorded as 'restored from vN')."""
    return Created(id=actions.restore(core, workspace_id, automation_id, n))


@router.get("/workspaces/{workspace_id}/automation-runs")
def run_history(core: CoreDep, workspace_id: str) -> list[AutomationRunGroup]:
    """The run history: the cards of each run grouped by run id, newest first, the
    run's status derived from its cards (no table of runs)."""
    from agos_core.actions import automation_cards

    require_workspace(core, workspace_id)
    return [
        AutomationRunGroup.model_validate(g)
        for g in automation_cards.run_groups(core, workspace_id)
    ]


class TicketPreset(Record):
    """A ticket on-ramp preset as the Automation dialog offers it."""

    source: str
    label: str
    signed: bool
    events: list[str]
    conditions: list[dict[str, object]]
    step: dict[str, object]


@router.get("/ticket-presets")
def list_ticket_presets() -> list[TicketPreset]:
    return [TicketPreset.model_validate(p) for p in ticket_presets.catalog()]


@router.post("/workspaces/{workspace_id}/automations/{automation_id}/hook")
def set_hook(
    core: CoreDep, workspace_id: str, automation_id: int, body: HookBody
) -> AutomationHook | None:
    return hooks.set_hook(
        core,
        workspace_id,
        automation_id,
        on=body.on,
        secret=body.secret,
        events=body.events,
        conditions=body.conditions,
        new_address=body.new_address,
        new_secret=body.new_secret,
        shown=True,  # this answer shows a made secret to him (the dialog)
    )


@router.post("/workspaces/{workspace_id}/automations/{automation_id}/hook/secret")
def show_hook_secret(core: CoreDep, workspace_id: str, automation_id: int) -> AutomationHook:
    """The signing secret AGOS made while saving the automation, shown to him once."""
    from agos_core.actions import hook_secrets

    found = hooks.hooks_of(core, workspace_id).get(automation_id)
    secret = hook_secrets.take(core, workspace_id, automation_id) if found else ""
    if found is None or not secret:
        raise ActionError("No signing secret waits to be shown here.", 404)
    return found.model_copy(update={"new_secret": secret, "secret_waiting": False})


@router.get("/workspaces/{workspace_id}/automations/{automation_id}/events")
def list_events(core: CoreDep, workspace_id: str, automation_id: int) -> list[AutomationEvent]:
    return hooks.events(core, workspace_id, automation_id)


@router.get("/settings/hooks")
def hooks_settings(core: CoreDep) -> HooksSettings:
    return HooksSettings(public_url=hooks_address(core))


@router.put("/settings/hooks")
async def save_hooks_settings(core: CoreDep, body: HooksSettings) -> HooksSettings:
    return HooksSettings(public_url=save_hooks_address(core, body.public_url))


@router.post("/workspaces/{workspace_id}/automations/{automation_id}/toggle")
def toggle(core: CoreDep, workspace_id: str, automation_id: int, body: Toggle) -> None:
    actions.toggle(core, workspace_id, automation_id, body.on)


@router.delete("/workspaces/{workspace_id}/automations/{automation_id}")
def delete(core: CoreDep, workspace_id: str, automation_id: int) -> None:
    actions.delete(core, workspace_id, automation_id)


@router.post("/workspaces/{workspace_id}/automations/{automation_id}/run", status_code=202)
def run_now(
    core: CoreDep,
    workspace_id: str,
    automation_id: int,
    body: RunNowBody | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> None:
    """Run now, with values for the typed variables when the dialog asked them. With
    an Idempotency-Key, a retry or a double click never runs it twice."""

    def run() -> dict[str, object]:
        actions.run_now(core, workspace_id, automation_id, body.variables if body else None)
        return {}

    key = f"{automation_id}:{idempotency_key}" if idempotency_key else None
    idempotency.once(core, "run_now", key, run, workspace_id=workspace_id, title="Run now")


@router.get("/workspaces/{workspace_id}/automations/{automation_id}/runs")
def list_runs(core: CoreDep, workspace_id: str, automation_id: int) -> list[AutomationRun]:
    return actions.runs(core, workspace_id, automation_id)


@router.get("/workspaces/{workspace_id}/automations/{automation_id}/runs/{run_id}/detail")
def run_detail(core: CoreDep, workspace_id: str, automation_id: int, run_id: str) -> RunDetail:
    """One run step by step: who worked each step (or why it was skipped), when, how
    long, its tokens and cost as Hermes counted them, and the run's totals."""
    require_workspace(core, workspace_id)
    return actions.detail_of(core, workspace_id, automation_id, run_id)


@router.get("/workspaces/{workspace_id}/automation-costs")
def automation_costs(core: CoreDep, workspace_id: str) -> list[AutomationCost]:
    """What each automation's runs used this calendar month and last month (UTC)."""
    require_workspace(core, workspace_id)
    return actions.month_costs(core, workspace_id)
