"""The owner's review actions from AGOS: a stage, a plan, the way out of a stuck card, his buttons, a card's policy.
Must not: check an agent's call.

Split out of agos_core.actions.reviews (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import kanban_cli
from agos_core.actions.services.board.review_rules import OWNER, OWNER_ACTIONS, _check_names
from agos_core.actions.services.board.review_situation import Situation, _owner_can, situation, view
from agos_core.actions.services.board.review_verdicts import _accepted_words, decompose
from agos_core.context import Core
from agos_core.engine import reviews as rules

__all__ = [
    "button",
    "owner_act",
    "set_card",
]

# ---- the owner's decisions -----------------------------------------------------------------


def _cli(core: Core, workspace_id: str, *args: str) -> str:
    return kanban_cli.run(core, workspace_id, *args)


def owner_act(
    core: Core,
    workspace_id: str,
    card_id: str,
    action: str,
    note: str = "",
    member: str = "",
) -> dict[str, Any]:
    """His Approve / Request changes on a stage or a plan waiting in Hermes's review
    column (at him, or at a reviewer Hermes hasn't started yet), and his four ways out
    of a card stuck in review: approve, send back (changes), reassign, drop."""
    if action not in OWNER_ACTIONS:
        raise ActionError(f"Decide with one of {', '.join(OWNER_ACTIONS)}.")
    s = situation(core, workspace_id, card_id)
    note = note.strip()[:4000]
    can = _owner_can(s)
    if action not in can:
        raise ActionError("This card doesn't wait for that decision now.", 409)
    if action == "changes" and not note:
        raise ActionError("Write what to change first.")
    if s.state.phase == "stuck":
        _stuck_way_out(core, workspace_id, s, action, note, member)
    elif s.plan_open:
        _owner_plan(core, workspace_id, s, action, note)
    else:
        _owner_stage(core, workspace_id, s, action, note)
    from agos_core.actions import pipelines
    from agos_core.engine import doorbell

    pipelines.after_review(core, workspace_id, card_id)  # his approve / accept (step 59)

    doorbell.ring(doorbell.SEND)  # his phone card loses its buttons
    found = view(situation(core, workspace_id, card_id))
    return found or {}


def _owner_stage(core: Core, workspace_id: str, s: Situation, action: str, note: str) -> None:
    mark = rules.review_marker(s.card, s.state.round, s.current, action)
    if action == "changes":
        # Hermes's own way back for a human review: review -> ready, the implementer
        # from the review handoff, the reason as its "CHANGES REQUESTED:" comment.
        _cli(core, workspace_id, "reopen-review", s.card, "--reason", f"{mark} owner: {note}")
        return
    after = rules.next_stage(s.state, s.reviewers, s.implementer, s.current)
    words = f"{mark} owner: {note or 'approved'}"
    if after:
        words += f" Next: stage {after} of {s.total}, {s.stage_label(after)}."
    _cli(core, workspace_id, "comment", s.card, words, "--author", OWNER)
    if after:
        # Still in Hermes's review column: the next reviewer is its assignee (the
        # dispatcher wakes a profile; `owner` waits for him again).
        _cli(core, workspace_id, "assign", s.card, s.reviewers[after - 1])
    else:
        summary = note or "Approved by the owner at the last review stage."
        _cli(core, workspace_id, "complete", s.card, f"--summary={summary}")


def _owner_plan(core: Core, workspace_id: str, s: Situation, action: str, note: str) -> None:
    n = s.state.plan_revision
    if action == "changes":
        mark = rules.plan_marker(s.card, n, "changes")
        _cli(core, workspace_id, "reopen-review", s.card, "--reason", f"{mark} owner: {note}")
        return
    made = decompose(core, workspace_id, s)
    for child in made:
        if child not in s.parents:
            # The card waits for its plan's task cards (Hermes's decompose shape: the
            # root wakes when they are done); linked while it is still in review.
            _cli(core, workspace_id, "link", child, s.card)
    _cli(
        core,
        workspace_id,
        "comment",
        s.card,
        _accepted_words(s.card, n, "owner", note, made),
        "--author",
        OWNER,
    )
    _cli(core, workspace_id, "reopen-review", s.card)


def _stuck_way_out(
    core: Core, workspace_id: str, s: Situation, action: str, note: str, member: str
) -> None:
    stage = s.current or s.total
    if action == "drop":
        _cli(
            core,
            workspace_id,
            "comment",
            s.card,
            f"{rules.review_marker(s.card, s.state.round, stage, 'reset')} owner: dropped. " + note,
            "--author",
            OWNER,
        )
        _cli(core, workspace_id, "archive", s.card)
        return
    if action == "approve":
        _cli(
            core,
            workspace_id,
            "comment",
            s.card,
            f"{rules.review_marker(s.card, s.state.round, stage, 'pass')} owner: "
            f"{note or 'approved as it is'}",
            "--author",
            OWNER,
        )
        _cli(
            core,
            workspace_id,
            "complete",
            s.card,
            f"--summary={note or 'Approved by the owner after the review rounds.'}",
        )
        return
    who = s.implementer
    if action == "reassign":
        from agos_core.actions import kanban_board

        who = kanban_board._profile_of(core, workspace_id, member)
        if who == "none":
            raise ActionError("Pick who takes the card.")
    words = note or (f"given to @{member}" if action == "reassign" else "try again")
    _cli(
        core,
        workspace_id,
        "comment",
        s.card,
        f"{rules.review_marker(s.card, s.state.round, stage, 'reset')} owner: {words}",
        "--author",
        OWNER,
    )
    # Blocked (nobody's run): reassign first, then Hermes's unblock lands it ready.
    _cli(core, workspace_id, "assign", s.card, who)
    _cli(core, workspace_id, "unblock", s.card)


def button(core: Core, workspaces: set[str], card_id: str) -> str:
    """His Approve on a Telegram card (the workspaces of the chat he pressed it in)."""
    for ws in sorted(workspaces):
        try:
            s = situation(core, ws, card_id)
        except (NotFoundError, ActionError):
            continue
        if "approve" not in _owner_can(s) or s.state.phase == "stuck":
            return "Already decided."
        owner_act(core, ws, card_id, "approve")
        return "Approved."
    return "That card is gone."


# ---- a card's own rules (the modal) --------------------------------------------------------


def set_card(
    core: Core, workspace_id: str, card_id: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    """The card's `agos-review` block in its Hermes body (`kanban edit --body`); an
    empty dict = the workspace's defaults again."""
    from agos_core.actions import kanban_board

    _check_names(
        core,
        workspace_id,
        [
            *rules.clean_stages(data.get("stages")),
            *([str(data["planReviewer"])] if data.get("planReviewer") else []),
        ],
    )
    raw, _extra = kanban_board._shown(core, workspace_id, card_id)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    body = str(task.get("body") or "")
    new = rules.with_policy(body, data)
    if new.strip() != body.strip():
        _cli(core, workspace_id, "edit", card_id, "--body", new)
    return view(situation(core, workspace_id, card_id))
