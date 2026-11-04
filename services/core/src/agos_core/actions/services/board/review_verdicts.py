"""An agent's review call checked (its `agos_review` tool): check, verdict, plan-first, submit, a plan's decomposition, landed.
Must not: act for the owner.

Split out of agos_core.actions.reviews (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board.review_rules import (
    CHECKED,
    IN_REVIEW,
    NOT_REVIEWER,
    OWN_RUN,
    OWNER,
    PLAN_FIRST,
    PLAN_WAITING,
    REVIEWING,
    STUCK,
    SUBMIT,
    VERDICTS,
    label,
)
from agos_core.actions.services.board.review_situation import Situation, _profile, situation
from agos_core.context import Core
from agos_core.engine import reviews as rules

__all__ = [
    "check",
    "decompose",
    "landed",
    "verdict",
]


def check(core: Core, workspace_id: str, card_id: str, tool: str, member: str) -> str:
    """ "" = let the call through; else the refusal the agent reads. Called by the guard
    for the card the agent works (its HERMES_KANBAN_TASK)."""
    if tool not in CHECKED or not card_id:
        return ""
    try:
        s = situation(core, workspace_id, card_id)
    except (NotFoundError, ActionError):
        return ""  # a card AGOS can't read: Hermes decides
    me = _profile(core, workspace_id, member)
    if s.plan_open:
        if s.state.plan == "waiting":
            if me == s.plan_reviewer and tool != "kanban_create":
                return (
                    f"You are reviewing this card's plan (v{s.state.plan_revision}): answer "
                    "with agos_review(verdict='approve') to accept it or "
                    "agos_review(verdict='changes', note=...), not " + tool + "."
                )
            return PLAN_WAITING.format(n=s.state.plan_revision, who=s.plan_label)
        if tool == "kanban_request_changes":
            return ""
        return PLAN_FIRST.format(who=s.plan_label)
    if tool == "kanban_create" or not s.pol.stages:
        return ""
    if s.state.phase == "stuck":
        return STUCK.format(r=s.state.rounds)
    if s.state.phase == "review" and s.current:
        if me == s.reviewers[s.current - 1]:
            return REVIEWING.format(k=s.current, n=s.total, tool=tool)
        return IN_REVIEW.format(k=s.current, n=s.total, who=s.stage_label(s.current))
    if s.current and tool in ("kanban_complete", "kanban_request_review"):
        return SUBMIT.format(k=s.current, n=s.total, who=s.stage_label(s.current), tool=tool)
    return ""


# ---- an agent's agos_review --------------------------------------------------------------


def verdict(
    core: Core,
    workspace_id: str,
    *,
    member: str,
    card_id: str,
    verdict: str,
    note: str = "",
    summary: str = "",
    working: str = "",
) -> dict[str, Any]:
    """The agent's verdict, checked: {"step": the Hermes step the guard takes with the
    agent's own run, "comment": the marker it writes after, "say": the agent's next
    words}, or {"error": why not}. `working`: the card the agent's run is on."""
    if verdict not in VERDICTS:
        return {"error": f"verdict is one of {', '.join(VERDICTS)}."}
    if working != card_id:
        return {"error": OWN_RUN.format(card=card_id)}
    try:
        s = situation(core, workspace_id, card_id)
    except (NotFoundError, ActionError):
        return {"error": f"Card {card_id} is not on this workspace's board."}
    me = _profile(core, workspace_id, member)
    note = note.strip()[:4000]
    if s.status != "running" or s.assignee != me:
        return {"error": f"Card {card_id} isn't running with you on it now (it is {s.status})."}
    if verdict == "plan_ready":
        return _plan_ready(core, workspace_id, s, me)
    if verdict == "submit":
        return _submit(s, me, summary.strip() or note)
    if s.plan_open and s.state.plan == "waiting":
        if me != s.plan_reviewer:
            return {"error": PLAN_WAITING.format(n=s.state.plan_revision, who=s.plan_label)}
        return _plan_verdict(core, workspace_id, s, me, verdict, note)
    if s.plan_open:
        return {"error": PLAN_FIRST.format(who=s.plan_label)}
    if not s.pol.stages:
        return {
            "error": "This card has no AGOS review stages: approve it with kanban_complete or "
            "send it back with kanban_request_changes."
        }
    if s.state.phase != "review" or not s.current:
        return {"error": f"Card {card_id} isn't waiting for a review now."}
    if me != s.reviewers[s.current - 1]:
        return {"error": NOT_REVIEWER.format(k=s.current, n=s.total, who=s.stage_label(s.current))}
    who = s.people.names.get(me, me)
    if verdict == "approve":
        after = rules.next_stage(s.state, s.reviewers, s.implementer, s.current)
        mark = rules.review_marker(card_id, s.state.round, s.current, "approve")
        comment = f"{mark} {who}: {note or 'approved'}"
        if not after:
            return {
                "step": {"do": "done", "summary": note or "Approved at every review stage."},
                "comment": comment,
                "say": "Approved: that was the last review stage, the card is done.",
            }
        return {
            "step": {
                "do": "hand",
                "to": s.reviewers[after - 1],
                "implementer": s.implementer,
                "summary": f"Review stage {s.current} approved by {who}.",
            },
            "comment": comment + f" Next: stage {after} of {s.total}, {s.stage_label(after)}.",
            "say": f"Approved. The card goes to stage {after} of {s.total}: "
            f"{s.stage_label(after)}. Stop here.",
        }
    if not note:
        return {"error": "Say what to change: note='<the changes needed>'."}
    if s.state.since_reset + 1 >= s.pol.cap:
        n = s.state.rounds + 1
        return {
            "step": {"do": "stuck", "reason": rules.STUCK.format(n=n)},
            "comment": f"{rules.review_marker(card_id, s.state.round, s.current, 'stuck')} "
            f"{who}: {note}",
            "say": f"That is round {n} of {s.pol.cap}: the card goes to the owner (stuck in "
            "review). Stop here.",
        }
    return {
        "step": {"do": "back", "reason": note, "implementer": s.implementer},
        "comment": f"{rules.review_marker(card_id, s.state.round, s.current, 'changes')} "
        f"{who}: {note}",
        "say": f"Sent back to its implementer with your note (round {s.state.round + 1}). Stop here.",
    }


def _submit(s: Situation, me: str, summary: str) -> dict[str, Any]:
    if s.plan_open:
        if s.state.plan == "waiting":
            return {"error": PLAN_WAITING.format(n=s.state.plan_revision, who=s.plan_label)}
        return {"error": PLAN_FIRST.format(who=s.plan_label)}
    if not s.pol.stages:
        return {"error": "This card has no review stages: finish it with kanban_complete."}
    if s.state.phase == "stuck":
        return {"error": STUCK.format(r=s.state.rounds)}
    if not summary:
        return {"error": "Say what you did and how you checked it: summary='...'."}
    current = s.current
    mark = rules.review_marker(s.card, s.state.round, current or s.total, "submit")
    if not current:
        return {
            "step": {"do": "done", "summary": summary},
            "comment": f"{mark} by {me}. {summary} (every review stage is the implementer "
            "itself: skipped)",
            "say": "No other reviewer on this card (self-review is skipped): it is done.",
        }
    who = label(s.pol.stages[current - 1], s.reviewers[current - 1], s.people)
    return {
        "step": {
            "do": "hand",
            "to": s.reviewers[current - 1],
            "implementer": me,
            "summary": summary,
        },
        "comment": f"{mark} by {me}. {summary} Review stage {current} of {s.total}: {who}.",
        "say": f"Handed to review: stage {current} of {s.total}, {who}. Stop here; it comes "
        "back to you if changes are asked.",
    }


def _plan_ready(core: Core, workspace_id: str, s: Situation, me: str) -> dict[str, Any]:
    from agos_core.actions import card_docs

    if not s.pol.plan:
        return {"error": "This card doesn't need a plan first: do the work."}
    if s.state.plan == "accepted":
        return {"error": "The plan is already accepted: do the work."}
    if s.state.plan == "waiting":
        return {"error": PLAN_WAITING.format(n=s.state.plan_revision, who=s.plan_label)}
    try:
        doc = card_docs.get_doc(core, workspace_id, s.card, rules.PLAN_KEY)
    except (NotFoundError, ActionError):
        return {
            "error": "Write the plan first: agos_card_document(key='plan', content=...) on "
            "this card, then call agos_review(verdict='plan_ready') again."
        }
    n = int(doc["revision"]) or 1
    if n <= s.state.plan_revision:
        return {"error": f"Plan v{n} was already sent back: write a new revision first."}
    tasks = rules.plan_tasks(str(doc["content"]))
    listed = f" It splits into {len(tasks)} cards on accept." if tasks else ""
    return {
        "step": {
            "do": "hand",
            "to": s.plan_reviewer,
            "implementer": me,
            "summary": f"Plan v{n} for review.",
        },
        "comment": f"{rules.plan_marker(s.card, n, 'ready')} by {me}. Plan v{n} is ready for "
        f"{s.plan_label}: read the card document 'plan' and answer "
        f"agos_review(verdict='approve') to accept it, or verdict='changes' with a note.{listed}",
        "say": f"Plan v{n} handed to {s.plan_label}. Stop here: the card comes back to you when "
        "it is accepted (then do the work) or sent back with notes.",
    }


def _plan_verdict(
    core: Core, workspace_id: str, s: Situation, me: str, verdict: str, note: str
) -> dict[str, Any]:
    who = s.people.names.get(me, me)
    n = s.state.plan_revision
    if verdict == "changes":
        if not note:
            return {"error": "Say what to change in the plan: note='...'."}
        return {
            "step": {"do": "back", "reason": note, "implementer": s.implementer},
            "comment": f"{rules.plan_marker(s.card, n, 'changes')} {who}: {note}",
            "say": "The plan goes back to its author with your note. Stop here.",
        }
    made = decompose(core, workspace_id, s)
    return {
        "step": {
            "do": "return",
            "implementer": s.implementer,
            "reason": f"Plan v{n} accepted by {who}.",
            "link": [c for c in made if c not in s.parents],
        },
        "comment": _accepted_words(s.card, n, who, note, made),
        "say": "Plan accepted"
        + (f": {len(made)} task cards made, the card waits for them" if made else "")
        + ". Stop here.",
    }


def _accepted_words(card: str, n: int, who: str, note: str, made: list[str]) -> str:
    words = f"{rules.plan_marker(card, n, 'accept')} {who}: {note or 'accepted'}."
    if made:
        words += " Task cards: " + ", ".join(made) + "."
    return words + " Do the work now."


def decompose(core: Core, workspace_id: str, s: Situation) -> list[str]:
    """The accepted plan's '## Tasks' lines as cards (Hermes's idempotency key
    agos-plan:<card>:<revision>:<n>: a replay is the same card), each for the
    @member it names (else the card's implementer)."""
    from agos_core.actions import card_docs, kanban_board

    try:
        doc = card_docs.get_doc(core, workspace_id, s.card, rules.PLAN_KEY)
    except (NotFoundError, ActionError):
        return []
    tasks = rules.plan_tasks(str(doc["content"]))
    n = s.state.plan_revision or int(doc["revision"])
    own = s.people.names.get(s.implementer, "")
    made = []
    for i, task in enumerate(tasks, start=1):
        who = task["member"] if task["member"] in s.people.profiles else own
        made.append(
            kanban_board.create(
                core,
                workspace_id,
                task["title"],
                f"A task of the accepted plan (v{n}) of card {s.card}: {s.title}.",
                who or kanban_board.COFOUNDER,
                once=rules.task_key(s.card, n, i),
            )
        )
    return made


def landed(core: Core, workspace_id: str, card_id: str) -> dict[str, Any]:
    """The guard took the step: when the card now waits for the owner, he hears it
    (his Co-Founder chat and phone; Approve on a button, changes with a note in AGOS)."""
    from agos_core.actions.services.channel import owner_needs

    s = situation(core, workspace_id, card_id)
    body, source = "", ""
    if s.status == "review" and s.assignee == OWNER:
        if s.plan_open and s.state.plan == "waiting":
            body = f"📝 The plan of card {card_id} ({s.title}) waits for your accept."
            source = f"review:{card_id}:plan:{s.state.plan_revision}"
        elif s.current:
            body = (
                f"🔎 Card {card_id} ({s.title}) waits for your review "
                f"(stage {s.current} of {s.total}, round {s.state.round})."
            )
            source = f"review:{card_id}:{s.state.round}:{s.current}"
    elif s.state.phase == "stuck":
        body = (
            f"⛔ Card {card_id} ({s.title}) is stuck in review after {s.state.rounds} rounds: "
            "approve it, send it back, give it to someone else or drop it in AGOS → Inbox."
        )
        source = f"review:{card_id}:stuck:{s.state.rounds}"
    if body:
        buttons = None if s.state.phase == "stuck" else [("Approve", f"krev:ok:{card_id}")]
        owner_needs.push(
            core,
            workspace_id,
            body + ("\nRequest changes (with a note) in AGOS → Inbox." if buttons else ""),
            source,
            buttons=buttons,
            chat_id=owner_needs.cofounder_chat(core, workspace_id),
        )
    from agos_core.actions import pipelines

    # A stage approved or a plan accepted: the workspace's pipeline rules (step 59).
    pipelines.after_review(core, workspace_id, card_id)
    return {"ok": True, "told": bool(body)}
