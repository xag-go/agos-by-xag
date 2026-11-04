"""Where a card stands in its review: its situation read from Hermes's board, its view, its chip, what the owner may do.
Must not: move a card.

Split out of agos_core.actions.reviews (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.board.review_rules import (
    OWNER,
    Org,
    defaults,
    label,
    org,
    reviewer_of,
)
from agos_core.context import Core
from agos_core.engine import reviews as rules

__all__ = [
    "Situation",
    "chip",
    "situation",
    "view",
]

# ---- one card, as it stands ---------------------------------------------------------------


@dataclass
class Situation:
    card: str
    title: str
    status: str
    assignee: str
    body: str
    parents: list[str]
    children: list[str]
    pol: rules.Policy
    state: rules.State
    implementer: str
    reviewers: list[str]
    current: int  # 1-based stage it waits for (0 = none)
    plan_reviewer: str
    people: Org

    @property
    def total(self) -> int:
        return len(self.pol.stages)

    def stage_label(self, k: int) -> str:
        return label(self.pol.stages[k - 1], self.reviewers[k - 1], self.people) if k else ""

    @property
    def plan_label(self) -> str:
        return label(self.pol.plan_reviewer, self.plan_reviewer, self.people)

    @property
    def plan_open(self) -> bool:
        return self.pol.plan and self.state.plan != "accepted"


def _implementer(state: rules.State, task: dict[str, Any], events: list[Any]) -> str:
    """Who did the work: the card's assignee while the work is with it; once it is in
    a reviewer's hands, who handed it over (its marker, else Hermes's own handoff)."""
    assignee = str(task.get("assignee") or "")
    status = str(task.get("status") or "")
    with_reviewer = (
        status == "review" or state.phase in ("review", "stuck") or state.plan == "waiting"
    )
    if not with_reviewer and assignee and assignee != OWNER:
        return assignee
    if state.implementer:
        return state.implementer
    for e in reversed(events or []):
        if isinstance(e, dict) and e.get("kind") == "review_requested":
            payload = e.get("payload")
            if isinstance(payload, dict) and payload.get("implementer"):
                return str(payload["implementer"])
    return "" if assignee == OWNER else assignee


def situation(
    core: Core,
    workspace_id: str,
    card_id: str,
    raw: dict[str, Any] | None = None,
    people: Org | None = None,
    base: dict[str, Any] | None = None,
) -> Situation:
    """The card as Hermes's board holds it (one read: `raw` when the caller has it)."""
    from agos_core.actions import kanban_board

    if raw is None:
        raw, _extra = kanban_board._shown(core, workspace_id, card_id)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    people = people or org(core, workspace_id)
    body = str(task.get("body") or "")
    children = [str(c) for c in raw.get("children") or []]
    pol = rules.policy(
        body,
        base if base is not None else defaults(core, workspace_id),
        has_children=bool(children),
    )
    comments = [c for c in raw.get("comments") or [] if isinstance(c, dict)]
    state = rules.derive(card_id, pol, comments)
    implementer = _implementer(state, task, raw.get("events") or [])
    reviewers = [reviewer_of(s, implementer, people) for s in pol.stages]
    plan_reviewer = reviewer_of(pol.plan_reviewer, implementer, people)
    if plan_reviewer in ("", implementer):
        plan_reviewer = OWNER  # nobody else to accept it: the owner does
    return Situation(
        card=card_id,
        title=str(task.get("title") or ""),
        status=str(task.get("status") or ""),
        assignee=str(task.get("assignee") or ""),
        body=body,
        parents=[str(p) for p in raw.get("parents") or []],
        children=children,
        pol=pol,
        state=state,
        implementer=implementer,
        reviewers=reviewers,
        current=rules.current_stage(state, reviewers, implementer),
        plan_reviewer=plan_reviewer,
        people=people,
    )


def view(s: Situation) -> dict[str, Any] | None:
    """The card modal's Review tab and Plan section (None: no review rules on it)."""
    if not s.pol.stages and not s.pol.plan:
        return None
    skipped = rules.skipped(s.state, s.reviewers, s.implementer)
    changed = {n["stage"] for n in s.state.notes if n["verb"] in rules.ROUND_VERBS}
    stages = []
    for k, stage in enumerate(s.pol.stages, start=1):
        if k in s.state.approved or (s.state.passed and k not in skipped):
            where = "approved"
        elif k in skipped:
            where = "skipped"
        elif k == s.current and s.state.phase == "review":
            where = "current"
        elif k == s.current and s.state.phase == "stuck":
            where = "stuck"
        elif k == s.current and k in changed:
            where = "changes"
        else:
            where = "waiting"
        stages.append(
            {
                "stage": stage,
                "reviewer": s.people.names.get(s.reviewers[k - 1], s.reviewers[k - 1]),
                "label": s.stage_label(k),
                "state": where,
            }
        )
    at_owner = s.status == "review" and s.assignee == OWNER
    return {
        "stages": stages,
        "phase": s.state.phase if s.pol.stages else "",
        "current": s.current,
        "round": s.state.round,
        "rounds": s.state.rounds,
        "cap": s.pol.cap,
        "own": s.pol.own,
        "notes": s.state.notes[-30:],
        "plan": s.state.plan,
        "planRevision": s.state.plan_revision,
        "planReviewer": s.pol.plan_reviewer,
        "planReviewerLabel": s.plan_label if s.pol.plan else "",
        # What the owner may do now (his buttons): a stage or plan waiting at him or
        # at a reviewer Hermes hasn't started yet (Hermes's review column), or stuck.
        "ownerCan": _owner_can(s),
        "atOwner": at_owner,
    }


def _owner_can(s: Situation) -> list[str]:
    if s.state.phase == "stuck" and s.status == "blocked":
        return ["approve", "changes", "reassign", "drop"]
    if s.status == "review" and (
        (s.plan_open and s.state.plan == "waiting") or (s.current and s.state.phase == "review")
    ):
        return ["approve", "changes"]
    return []


def chip(s: Situation) -> dict[str, Any] | None:
    """The board card's chip: 'Review 2/3 · round 1', 'Plan waiting'."""
    if not s.pol.stages and not s.pol.plan:
        return None
    return {
        "stage": s.current if s.state.phase in ("review", "stuck") else 0,
        "stages": s.total,
        "round": s.state.round,
        "phase": s.state.phase if s.pol.stages else "",
        "plan": s.state.plan,
    }


# ---- the guard's question: may this tool call go? -----------------------------------------


def _profile(core: Core, workspace_id: str, member: str) -> str:
    from agos_core.actions import kanban_board

    if not member:
        return core.engine.hermes_name(workspace_id) if core.engine else ""
    return kanban_board._profile_of(core, workspace_id, member)
