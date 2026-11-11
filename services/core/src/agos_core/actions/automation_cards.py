"""An automation's runs on the Kanban (team steps, "Check with me first", a
webhook): Hermes puts them there itself, AGOS only writes the plan and reads.

Each step is one card, given to its member (none = the Co-Founder); a step's card
waits on the cards of the steps it waits on (Hermes's own parents: a card starts
once its parents are done). A review step is a card for the reviewer that waits on
the work it reviews. An approval step — and "Check with me first" — is a card for
the owner (nobody's): the cards after it start once he moves it to Done.

The cards are made by a small script Hermes runs (engine/automation_run.py): its
cron job runs it at each time of the schedule, its webhook route for each
delivery, and Run now once. AGOS writes the script with the automation's plan
(who does each step, with what text and model), the way it writes any Hermes
config, and keeps it in step (`write_scripts`).

The run is its cards, and nothing else: each card's Hermes idempotency key is
`agos-automation:<automation>:<run>:<source>:<step>`, so AGOS reads an
automation's runs (going, done, stopped, what the last cards gave) straight from
the workspace's Kanban, with no copy and no polling. The run history (Step 48)
groups the workspace's cards by that run id and derives each run's status from
its cards: every card done → completed; any blocked → needs you; any running →
running; else waiting; every card archived → stopped. A ticket on-ramp's cards
(`agos-ticket:<source>:<issue>`) are one card per issue, not runs.

The plan also carries the automation's typed variables (the script fills {name}
in the cards), its concurrency policy and its ticket mapping (Step 48).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agos_core.context import Core
from agos_core.engine.team_steps import Step

PREFIX = "agos-automation:"
Status = Literal["completed", "needs_you", "running", "waiting", "stopped"]
OPEN = ("triage", "todo", "scheduled", "ready", "running", "blocked", "review")


@dataclass
class Run:
    """One run of an automation, as its cards on Hermes's Kanban say."""

    id: str
    source: str
    started_at: str
    cards: dict[str, dict[str, Any]] = field(default_factory=dict)  # step key -> card

    @property
    def going(self) -> list[str]:
        return [c["id"] for c in self.cards.values() if c["status"] in OPEN]

    @property
    def started(self) -> bool:
        """Any card of it began (or ended): it's no longer only waiting on the last run."""
        return any(
            c["status"] not in ("todo", "triage", "scheduled", "ready") for c in self.cards.values()
        )

    @property
    def last(self) -> list[dict[str, Any]]:
        """Its last cards: the ones no other card of the run waits on."""
        ids = {c["id"] for c in self.cards.values()}
        parents = {p for c in self.cards.values() for p in c.get("parents") or [] if p in ids}
        return [c for c in self.cards.values() if c["id"] not in parents]

    @property
    def first(self) -> list[dict[str, Any]]:
        """Its first cards: the ones that wait on no other card of the run."""
        ids = {c["id"] for c in self.cards.values()}
        return [c for c in self.cards.values() if not set(c.get("parents") or []) & ids]

    @property
    def finished_at(self) -> str | None:
        if self.going:
            return None
        stamps = [int(c["completed_at"]) for c in self.cards.values() if c.get("completed_at")]
        return _iso(max(stamps)) if stamps else self.started_at

    @property
    def stopped(self) -> bool:
        """Every card archived: the owner stopped it."""
        return not self.going and all(c["status"] != "done" for c in self.cards.values())

    @property
    def report(self) -> str:
        if self.stopped:
            return "Stopped: every card was archived."
        results = [str(c.get("result") or "").strip() for c in self.last]
        return "\n\n".join(r for r in results if r) or "Done."

    @property
    def status(self) -> Status:
        """Derived from its cards: completed / needs_you / running / waiting / stopped."""
        statuses = {str(c["status"]) for c in self.cards.values()}
        if not self.going:
            return "stopped" if self.stopped else "completed"
        if "blocked" in statuses:
            return "needs_you"
        if "running" in statuses or "review" in statuses:
            return "running"
        return "waiting"


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _started(run_id: str) -> str:
    try:
        return datetime.strptime(run_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC).isoformat()
    except ValueError:
        return run_id


def runs(core: Core, automation: Any) -> list[Run]:
    """The automation's runs on the workspace's Kanban, newest first."""
    from agos_core.actions import kanban_board

    prefix = f"{PREFIX}{int(automation.id)}:"
    found: dict[str, Run] = {}
    for card in kanban_board.keyed(core, automation.workspace_id, prefix):
        parts = str(card["key"])[len(prefix) :].split(":", 2)
        if len(parts) != 3:
            continue
        run_id, source, step = parts
        run = found.setdefault(run_id, Run(run_id, source, _started(run_id)))
        run.cards[step] = card
    return sorted(found.values(), key=lambda r: r.id, reverse=True)


def as_record(run: Run) -> Any:
    """The run as the automation's Runs list shows it."""
    from agos_core.db.records import AutomationRun

    started = datetime.fromisoformat(run.started_at) if "T" in run.started_at else None
    return AutomationRun(
        id=int(started.timestamp() * 1000) if started else 0,
        result="failed" if run.stopped else "ok",
        source=run.source,
        started_at=run.started_at,
        finished_at=run.finished_at,
        report=run.report[:20_000],
        error=run.report if run.stopped else None,
        proposals=[],
    )


def last_finished(core: Core, automation: Any) -> Any:
    """The newest run that ended, for the automation's list (None: none yet)."""
    from agos_core.db import automations as repo
    from agos_core.db.records import LastRun

    run = next((r for r in runs(core, automation) if not r.going), None)
    if run is None:
        return None
    return LastRun(
        at=run.finished_at or run.started_at,
        result="failed" if run.stopped else "ok",
        summary=repo.summary(run.report, run.report if run.stopped else None),
    )


def of_workspace(core: Core, workspace_id: str) -> list[tuple[Any, Run]]:
    """Every run AGOS put on this workspace's Kanban, with its automation."""
    from agos_core.actions import hooks
    from agos_core.db import automations as repo

    return [
        (a, run)
        for a in repo.list_automations(core.db, workspace_id, hooks.hooks_of(core, workspace_id))
        if a.steps or a.check_first or a.hook
        for run in runs(core, a)
    ]


def run_groups(core: Core, workspace_id: str, limit: int = 60) -> list[Any]:
    """The run history: the workspace's automation cards grouped by run (one board
    query per automation, read only), newest first, each run with its status."""
    from agos_core.actions import automations as automation_actions
    from agos_core.actions.services.automation import run_detail
    from agos_core.db.records import AutomationRunGroup, RunCard

    names = {a.id: a.name for a in automation_actions.list_all(core, workspace_id)}
    pairs = sorted(of_workspace(core, workspace_id), key=lambda p: p[1].id, reverse=True)[:limit]
    shown = run_detail.details(core, workspace_id, pairs)  # who worked, how long, tokens
    out = []
    for (automation, run), detail in zip(pairs, shown, strict=True):
        out.append(
            AutomationRunGroup(
                automation_id=int(automation.id),
                automation_name=names.get(automation.id) or f"Automation {automation.id}",
                run_id=run.id,
                source=run.source,
                started_at=run.started_at,
                finished_at=run.finished_at,
                status=run.status,
                cards=[
                    RunCard(
                        id=str(c["id"]),
                        step=step,
                        title=str(c.get("title") or ""),
                        status=str(c["status"]),
                        assignee=str(c.get("assignee") or ""),
                    )
                    for step, c in run.cards.items()
                ],
                detail=detail.model_copy(
                    update={"automation_name": names.get(automation.id) or detail.automation_name}
                ),
            )
        )
    out.sort(key=lambda g: g.run_id, reverse=True)
    return out[:limit]


def card_runs(automation: Any) -> bool:
    """Its runs go on the Kanban (else it is one agent's Hermes cron job)."""
    return bool(automation.steps or automation.check_first or automation.hook)


# ---- the plan Hermes's script runs ----------------------------------------------------


def steps_of(core: Core, automation: Any) -> list[Step]:
    """The run's steps: its saved team steps (or one step for the agent / the
    Co-Founder that does it). A member that's gone hands its steps to the Co-Founder."""
    from agos_core.actions.library import agent_text
    from agos_core.db.records import AutomationStep

    brief = automation.instructions.strip()
    saved = list(automation.steps) or [
        AutomationStep(key="s1", title=automation.name, agent=automation.agent)
    ]
    steps = []
    for s in saved:
        agent = s.agent if s.agent and agent_text(core, automation.workspace_id, s.agent) else None
        description = s.description or s.title
        if s.kind != "approval" and brief and brief != description:
            description = f"{description}\n\nThe automation's brief (“{automation.name}”):\n{brief}"
        steps.append(
            Step(
                key=s.key,
                title=s.title,
                description=description,
                kind=s.kind,
                agent=agent,
                waits_on=tuple(s.waits_on),
                reviews=s.reviews,
            )
        )
    if getattr(automation, "check_first", False):
        # The owner asked to be checked with first: nothing starts before his OK.
        gate = Step(
            key="owner-ok",
            title=f"Your OK to start “{automation.name}”",
            description="Move this card to Done to let the team start.",
            kind="approval",
            agent=None,
        )
        steps = [gate] + [
            Step(
                key=s.key,
                title=s.title,
                description=s.description,
                kind=s.kind,
                agent=s.agent,
                waits_on=s.waits_on or (() if s.kind == "review" else ("owner-ok",)),
                reviews=s.reviews,
            )
            for s in steps
        ]
    return steps


def _body(step: Step, titles: dict[str, str]) -> str:
    if step.kind == "review" and step.reviews:
        return (
            f"Review the work of “{titles.get(step.reviews, step.reviews)}” (the card this one "
            "waits on): check it against what was asked and say in a comment what passes "
            f"and what must change.\n\n{step.description}"
        ).strip()
    if step.kind == "approval":
        return f"For the owner: move this card to Done to let the next steps start.\n\n{step.description}".strip()
    return step.description


def _ordered(steps: list[Step]) -> list[Step]:
    """Steps after the ones they wait on (the steps were checked: no circles)."""
    done: set[str] = set()
    out: list[Step] = []
    left = list(steps)
    while left:
        free = [s for s in left if set(s.waits_on) <= done]
        if not free:  # never for checked steps; keep the rest as they are
            out += left
            break
        for s in free:
            out.append(s)
            done.add(s.key)
            left.remove(s)
    return out


def _on_team(core: Core, workspace_id: str, member: str) -> bool:
    from agos_core.actions.library import agent_text

    return agent_text(core, workspace_id, member) is not None


def deliveries_log(core: Core, workspace_id: str, automation_id: int) -> Path:
    """Where Hermes's script notes the webhook deliveries it took (in the
    workspace's Hermes home, never in an agent's sandbox)."""
    assert core.engine is not None
    return (
        core.engine.profile_home(workspace_id) / "agos-automations" / f"{automation_id}.deliveries"
    )


def plan(core: Core, automation: Any, mode: str) -> dict[str, Any]:
    """What Hermes's script needs to put a run on the board: the steps in order,
    each with its card's text and who does it (a member's profile, the Co-Founder's,
    or nobody for the owner's approval), the model, and where Hermes is."""
    from agos_core.actions import agent_profiles, automation_variables, kanban_board
    from agos_core.actions import ticket_presets as presets
    from agos_core.engine.models import hermes_slug

    assert core.engine is not None
    workspace_id = automation.workspace_id
    steps = steps_of(core, automation)
    titles = {s.key: s.title for s in steps}
    model = automation.model
    env = {
        **core.engine.hermes_env(workspace_id),
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
    }
    ticket = getattr(automation, "ticket", None)
    if ticket is not None:
        member = (
            ticket.member if ticket.member and _on_team(core, workspace_id, ticket.member) else None
        )
        ticket_plan = presets.plan_entry(
            ticket, kanban_board._profile_of(core, workspace_id, member or kanban_board.COFOUNDER)
        )
    else:
        ticket_plan = None
    return {
        "automation": int(automation.id),
        "name": automation.name,
        "mode": mode,
        "variables": automation_variables.plan_entries(list(getattr(automation, "variables", []))),
        "policy": str(getattr(automation, "policy", "") or "skip_if_active"),
        "ticket": ticket_plan,
        "hermes": core.engine.settings.hermes_bin,
        "env": env,
        "board": str(agent_profiles.board_db(core, workspace_id)),
        "deliveries": str(deliveries_log(core, workspace_id, int(automation.id))),
        "model": (
            ["--provider", hermes_slug(model.provider, model.mode), "--model", model.model]
            if model.model and model.provider
            else []
        ),
        "steps": [
            {
                "key": s.key,
                "title": s.title,
                "body": _body(s, titles),
                "assignee": (
                    None
                    if s.kind == "approval"
                    else kanban_board._profile_of(
                        core, workspace_id, s.agent or kanban_board.COFOUNDER
                    )
                ),
                "waits_on": list(s.waits_on),
                # What happened (a webhook) goes on the work and on the owner's OK.
                "happened": s.kind != "approval" or s.key == "owner-ok",
            }
            for s in _ordered(steps)
        ],
    }


def write_scripts(core: Core, automation: Any) -> None:
    """Hermes's scripts for this automation follow it: the one its cron job and
    Run now run, and the one its webhook route runs (only while it has one)."""
    from agos_core.engine.cron import fire_script_name, hook_script_name, write_run_script

    if core.engine is None:
        return
    home = core.engine.profile_home(automation.workspace_id)
    if not card_runs(automation):
        return
    write_run_script(home, fire_script_name(int(automation.id)), plan(core, automation, "cron"))
    hook = home / "scripts" / hook_script_name(int(automation.id))
    if automation.hook:
        write_run_script(home, hook.name, plan(core, automation, "webhook"))
    else:
        hook.unlink(missing_ok=True)
