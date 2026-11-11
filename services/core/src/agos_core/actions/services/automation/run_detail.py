"""An automation's run in detail, and what its runs cost this month and last
month: who worked each step, who was skipped and why, when it started and ended,
its tokens and cost (Hermes's own counts, run_usage.py), and the run's totals.

A team automation's run is its Kanban cards (automation_cards); a one-agent
automation's run is one of its Hermes cron runs, worked by one session.

Step states, from the card and its attempts:
- skipped: the card was completed with a result starting `agos-skipped:` (the
  reason follows); it never started an agent;
- done / stopped (archived) / running (or in review) / waiting;
- failed: blocked after an attempt that crashed, timed out, could not start or
  gave up; needs_you: blocked otherwise (for his answer or his OK).

Owns: the detail and the monthly sums. Must not: start or change a run, or read a
Hermes store itself (run_usage and the board service do).
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from datetime import UTC, datetime
from typing import Any

from agos_core.actions import automation_cards
from agos_core.actions.services.automation import run_usage
from agos_core.actions.services.automation.cron import hermes_jobs, home_of, list_all
from agos_core.actions.services.board import card_members
from agos_core.context import Core
from agos_core.db import automations as repo
from agos_core.db.records import (
    Automation,
    AutomationCost,
    AutomationRun,
    MonthUsage,
    RunDetail,
    RunStep,
    StepStatus,
    Usage,
)
from agos_core.engine import read_cache

__all__ = [
    "SKIPPED",
    "cron_detail",
    "details",
    "job_home",
    "month_costs",
    "step_state",
]

SKIPPED = "agos-skipped:"  # lane b's mark: the step had nothing to do
_FAILED = ("crashed", "timed_out", "spawn_failed", "gave_up")
_COSTS: read_cache.ReadCache[list[AutomationCost]] = read_cache.ReadCache("automation.costs")


def _iso(epoch: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(epoch), UTC).isoformat() if epoch else None
    except (TypeError, ValueError, OSError):
        return None


def _epoch(text: str | None) -> float | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _seconds(start: str | None, end: str | None) -> int | None:
    a, b = _epoch(start), _epoch(end)
    return max(int(b - a), 0) if a is not None and b is not None else None


def step_state(
    card: dict[str, Any], attempts: Sequence[dict[str, Any]]
) -> tuple[StepStatus, str | None]:
    """The step's state and why (skipped, failed, waits on him), from its card."""
    status = str(card.get("status") or "")
    result = str(card.get("result") or "").strip()
    last = attempts[-1] if attempts else {}
    if status == "done" and result.lower().startswith(SKIPPED):
        return "skipped", result[len(SKIPPED) :].strip()[:300] or None
    if status == "done":
        return "done", None
    if status == "archived":
        return "stopped", None
    if status in ("running", "review"):
        return "running", None
    if status == "blocked":
        said = str(last.get("error") or last.get("summary") or "").strip()[:300] or None
        if str(last.get("outcome") or "") in _FAILED:
            return "failed", said or f"The work stopped ({last['outcome']})."
        return "needs_you", said
    return "waiting", None


def _ordered(cards: dict[str, dict[str, Any]], plan: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """The run's steps in run order: after the cards they wait on, then in the
    plan's order, then by when their card was made."""
    ids = {str(c["id"]): step for step, c in cards.items()}
    place = {k: n for n, k in enumerate(plan)}
    done: set[str] = set()
    left = dict(cards)
    out: list[tuple[str, dict[str, Any]]] = []
    while left:
        free = [
            s
            for s, c in left.items()
            if {ids[p] for p in c.get("parents") or [] if p in ids} <= done
        ] or list(left)  # never for a run's own links; keep the rest as they are
        free.sort(key=lambda s: (place.get(s, len(place)), int(left[s].get("created_at") or 0), s))
        for s in free:
            out.append((s, left.pop(s)))
            done.add(s)
    return out


def _who(card: dict[str, Any], members: dict[str, dict[str, str]]) -> str:
    assignee = str(card.get("assignee") or "")
    if assignee in ("", "none", card_members.OWNER):
        return "You"
    member = members.get(assignee)
    if member is None:
        return assignee
    if member["name"] == card_members.COFOUNDER:
        return "Co-Founder"
    return member.get("title") or member["name"]


def _step(key: str, card: dict[str, Any], work: run_usage.CardWork, who: str) -> RunStep:
    state, reason = step_state(card, work.attempts)
    starts = [a["started_at"] for a in work.attempts if a.get("started_at")]
    ends = [a["ended_at"] for a in work.attempts if a.get("ended_at")]
    started = _iso(min(starts)) if starts else None
    finished: str | None = None
    if state in ("done", "skipped", "stopped"):
        finished = _iso(card.get("completed_at")) or (_iso(max(ends)) if ends else None)
    elif state in ("failed", "needs_you") and ends:
        finished = _iso(max(ends))
    return RunStep(
        key=key,
        title=str(card.get("title") or key),
        card_id=str(card["id"]),
        agent=who,
        status=state,
        reason=reason,
        started_at=started,
        finished_at=finished,
        duration_s=_seconds(started, finished),
        attempts=len(work.attempts),
        usage=work.usage,
    )


def details(
    core: Core, workspace_id: str, runs: Sequence[tuple[Automation, automation_cards.Run]]
) -> list[RunDetail]:
    """These Kanban runs in detail (one board read and one read per profile store
    for all of them)."""
    cards = [c for _, run in runs for c in run.cards.values()]
    work = run_usage.card_work(core, workspace_id, cards)
    members = card_members.members(core, workspace_id)
    out = []
    for automation, run in runs:
        plan = (["owner-ok"] if automation.check_first else []) + [s.key for s in automation.steps]
        steps = [
            _step(key, card, work.get(str(card["id"])) or run_usage.CardWork(), _who(card, members))
            for key, card in _ordered(run.cards, plan)
        ]
        out.append(
            RunDetail(
                automation_id=int(automation.id),
                automation_name=automation.name,
                run_id=run.id,
                source=run.source,
                started_at=run.started_at,
                finished_at=run.finished_at,
                duration_s=_seconds(run.started_at, run.finished_at),
                steps=steps,
                totals=run_usage.total(s.usage for s in steps),
            )
        )
    return out


def job_home(core: Core, workspace_id: str, automation_id: int) -> tuple[str, Any] | None:
    """A one-agent automation's Hermes job and the profile home holding it."""
    row = repo.row(core.db, workspace_id, automation_id)
    if row is None or not row["hermes_job_id"] or core.engine is None:
        return None
    held = (hermes_jobs(core, workspace_id) or {}).get(str(row["hermes_job_id"]))
    return (str(row["hermes_job_id"]), home_of(core, workspace_id, held)) if held else None


def cron_detail(
    core: Core,
    workspace_id: str,
    automation: Automation,
    run: AutomationRun,
    run_id: str,
    found: tuple[str, Any] | None,
) -> RunDetail:
    """A one-agent automation's cron run: one step, its agent, its session's usage
    (`found`: its job and the home holding it, job_home)."""
    start = _epoch(run.started_at) or 0.0
    end = _epoch(run.finished_at) or start
    sessions = (
        run_usage.cron_sessions(core, found[1], found[0], start - 5, end + 5) if found else []
    )
    usage = run_usage.total(u for _, u in sessions)
    titles = {
        m["name"]: m.get("title") or m["name"]
        for m in card_members.members(core, workspace_id).values()
    }
    who = titles.get(automation.agent or "", automation.agent) if automation.agent else "Co-Founder"
    step = RunStep(
        key="run",
        title=automation.name,
        card_id="",
        agent=str(who),
        status="done" if run.result == "ok" else "failed",
        reason=None if run.result == "ok" else (run.error or None),
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_s=_seconds(run.started_at, run.finished_at),
        attempts=1,
        usage=usage,
    )
    return RunDetail(
        automation_id=int(automation.id),
        automation_name=automation.name,
        run_id=run_id,
        source=run.source,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_s=step.duration_s,
        steps=[step],
        totals=usage,
    )


# ---- what it cost this month and last month ------------------------------------------------


def _months(now: datetime) -> tuple[tuple[str, float, float], tuple[str, float, float]]:
    """(YYYY-MM, start, end) of this calendar month and the last one, in UTC."""
    this = now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last = (
        this.replace(year=this.year - 1, month=12)
        if this.month == 1
        else this.replace(month=this.month - 1)
    )
    nxt = (
        this.replace(year=this.year + 1, month=1)
        if this.month == 12
        else this.replace(month=this.month + 1)
    )
    return (
        (this.strftime("%Y-%m"), this.timestamp(), nxt.timestamp()),
        (last.strftime("%Y-%m"), last.timestamp(), this.timestamp()),
    )


def _stores_stamp(core: Core, workspace_id: str) -> Hashable:
    """The workspace's board and every profile's session store, as they are now."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return ()
    root = core.engine.root(workspace_id)
    stores = [root / "state.db", *sorted((root / "profiles").glob("*/state.db"))]
    return (
        read_cache.sqlite_stamp(agent_profiles.board_db(core, workspace_id)),
        tuple((str(p), read_cache.sqlite_stamp(p)) for p in stores),
    )


def month_costs(core: Core, workspace_id: str, now: datetime | None = None) -> list[AutomationCost]:
    """Each automation of the workspace: what its runs used this month and last
    month (UTC; a run counts in the month it started). Kept while the board, the
    session stores and the automations' runs are unchanged."""
    months = _months(now or datetime.now(UTC))
    automations = list_all(core, workspace_id)
    runs = {a.id: automation_cards.runs(core, a) for a in automations}
    cards_now = tuple(
        (a.id, r.id, tuple(sorted((str(c["id"]), str(c["status"])) for c in r.cards.values())))
        for a in automations
        for r in runs[a.id]
    )
    stamp = (months[0][0], _stores_stamp(core, workspace_id), cards_now)
    return _COSTS.get(
        workspace_id, stamp, lambda: _month_costs(core, workspace_id, automations, runs, months)
    )


def _month_costs(
    core: Core,
    workspace_id: str,
    automations: list[Automation],
    runs: dict[int, list[automation_cards.Run]],
    months: tuple[tuple[str, float, float], tuple[str, float, float]],
) -> list[AutomationCost]:
    since, until = months[1][1], months[0][2]
    picked = [
        (a, r)
        for a in automations
        for r in runs[a.id]
        if since <= (_epoch(r.started_at) or 0.0) < until
    ]
    shown = details(core, workspace_id, picked)
    out = []
    for a in automations:
        used = [(_epoch(d.started_at) or 0.0, d.totals) for d in shown if d.automation_id == a.id]
        if not automation_cards.card_runs(a):
            found = job_home(core, workspace_id, int(a.id))
            if found:
                used += run_usage.cron_sessions(core, found[1], found[0], since, until)
        out.append(
            AutomationCost(
                automation_id=int(a.id),
                name=a.name,
                this_month=_month(months[0], used),
                last_month=_month(months[1], used),
            )
        )
    return out


def _month(month: tuple[str, float, float], used: list[tuple[float, Usage]]) -> MonthUsage:
    name, start, end = month
    inside = [u for at, u in used if start <= at < end]
    return MonthUsage(month=name, runs=len(inside), usage=run_usage.total(inside))
