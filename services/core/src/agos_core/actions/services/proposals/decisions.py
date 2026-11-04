"""The owner's decision on a proposal: approve, revise, reject, edited before approval, Undo.
Must not: create the member itself (hiring does).

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.proposals.hiring import consent, hire, unhire
from agos_core.actions.services.proposals.inbox_view import ask_row, ask_view
from agos_core.actions.services.proposals.proposal_states import CHOICE_OF, FAILED, STATUS_OF, _json
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.db.connection import transaction
from agos_core.engine import proposals as rules

__all__ = [
    "decide",
    "edited",
    "undo",
]

# ---- deciding --------------------------------------------------------------------------


def edited(
    core: Core, workspace_id: str, kind: str, payload: dict[str, Any], changes: dict[str, Any]
) -> dict[str, Any]:
    """The proposal as the owner edited it before approving: a plan change (the
    numbers of a key result, a project's fields, a goal's, a daily plan's items), or
    a hire's kit (step 62: its tools, skills, docs, team context, onboarding test) and
    its model (family, version, effort: checked against Hermes's catalog in decide).
    What it changes (`change`) and which row it names stay as proposed."""
    if kind in ("hire", "kit"):
        if set(changes) - {"kit", "model"}:
            raise ActionError(
                f"Only a {kind}'s kit and model are edited before approving; revise the rest."
            )
        from agos_core.actions import hire_kit, hire_model, member_kits

        out = dict(payload)
        if "kit" in changes:
            kit = hire_kit.fill(core, workspace_id, changes.get("kit") or {})
            problems = hire_kit.kit_problems(core, workspace_id, kit)
            problems += (
                member_kits.required(core, workspace_id, {**payload, "kit": kit})
                if kind == "kit"
                else hire_kit.required_problems(core, workspace_id, {**payload, "kit": kit})
            )
            if problems:
                raise ActionError(
                    "Can't approve as edited: "
                    + "; ".join(problems)
                    + ". Put it back in the kit, or ask for changes."
                )
            out["kit"] = kit
        if "model" in changes:
            out = hire_model.edited(out, changes.get("model"))
        return out
    if kind != "goal":
        raise ActionError("Only a goal, key result, project, daily plan or a hire's kit is edited.")
    fixed = ("change", "goal_id", "kr_id", "project_id")
    merged = rules.clean(kind, {**payload, **changes, **{k: payload.get(k) for k in fixed}})
    if not merged.get("why"):
        merged["why"] = str(payload.get("why") or "")
    from agos_core.actions import goals

    problems = list(dict.fromkeys(goals.check_change(core, workspace_id, merged)))
    if problems:
        raise ActionError("Can't approve as edited: " + "; ".join(problems) + ".")
    return merged


def decide(
    core: Core,
    workspace_id: str,
    ask_id: int,
    choice: str,
    note: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Approve / Revise / Reject. `payload`: the owner's edits of the proposal, applied
    with an approve (kept in the row's result, the proposal itself stays as made)."""
    if choice not in rules.DECISIONS:
        raise ActionError("Decide with approve, revise or reject.")
    row = ask_row(core, workspace_id, ask_id)
    if str(row["kind"]) == "skill" and choice == "revise":
        raise ActionError("A skill is approved or rejected; there is nothing to revise.")
    status = str(row["status"])
    if status != "waiting":
        if CHOICE_OF.get(status) == choice:
            return ask_view(core, workspace_id, row)  # the same decision again: nothing new
        raise ActionError(f"Already decided: {status}.", 409)
    card, kind, round_ = str(row["card"]), str(row["kind"]), int(row["round"])
    proposed = _json(row["payload"])
    applied = proposed
    if payload is not None:
        if choice != "approve":
            raise ActionError("Edits go with an approve; a revise sends a note.")
        applied = edited(core, workspace_id, kind, proposed, payload)
    owner_edited = applied is not proposed
    if choice == "approve":
        problems = rules.problems(kind, applied)
        if kind == "hire":
            from agos_core.actions import hire_kit, hire_model

            # Every hire, as approved: its full kit and its model (one the workspace's
            # provider offers now; a model checked when proposed stands while Hermes
            # can't list them). An owner's edit that took a part out is refused here.
            applied = dict(applied)
            problems += hire_kit.required_problems(core, workspace_id, applied)
            problems += hire_model.check(
                core, workspace_id, applied, kept_ok="model" not in (payload or {}), hire=True
            )
        if kind == "kit":
            from agos_core.actions import member_kits

            # As approved: still a member of the team, its whole kit and model.
            applied = dict(applied)
            problems += member_kits.problems(
                core, workspace_id, applied, kept_ok="model" not in (payload or {}), new=False
            )
        if not problems and kind == "goal":
            from agos_core.actions import goals

            problems = goals.check_change(core, workspace_id, applied)
        if problems:
            if payload is not None and kind in ("hire", "kit"):
                raise ActionError(
                    "Can't approve as edited: "
                    + "; ".join(problems)
                    + ". Put it back (Edit kit, the model picker), or ask for changes."
                )
            raise ActionError("Can't approve as is: " + "; ".join(problems) + ". Revise it.")
    marked = _decided_on_card(core, workspace_id, card, round_)
    if marked is not None and marked != choice:
        # His decision was written on the card, but the row never heard (a cut
        # between the two): the card is the truth.
        with transaction(core.db):
            kanban_asks.decide(core.db, ask_id, STATUS_OF[marked])
        raise ActionError(f"Already decided: {STATUS_OF[marked]}.", 409)
    if marked is None:
        from agos_core.actions.kanban_asks import _hermes_kanban

        words = rules.decision_text(kind, choice, note, str(proposed.get("change") or ""))
        text = f"{rules.marker(card, round_, choice)} {words}"
        _hermes_kanban(core, workspace_id, "comment", card, text, "--author", "owner")
    try:
        result = _act(core, workspace_id, row, choice, note, applied)
    except ActionError:
        # The decision is on the card but did not go through: say so there too, or
        # the card reads as decided and the proposal is stuck (approved, nothing made).
        from agos_core.actions.kanban_asks import _hermes_kanban

        failed = f"{rules.marker(card, round_, FAILED)} The owner's {choice} did not go through."
        _hermes_kanban(core, workspace_id, "comment", card, failed, "--author", "owner")
        raise
    if owner_edited:  # his edits (a hire's model resolved as proposed is not one)
        result = {**result, "edited": applied}
    _record(core, workspace_id, ask_id, choice, note, result)
    from agos_core.engine import doorbell

    doorbell.ring(doorbell.SEND)  # its card on his phone loses its buttons
    return ask_view(core, workspace_id, ask_row(core, workspace_id, ask_id))


def _record(
    core: Core, workspace_id: str, ask_id: int, choice: str, note: str, result: dict[str, Any]
) -> None:
    """The owner's decision on the proposal's row (unless it was decided meanwhile)."""
    with transaction(core.db):
        kanban_asks.decided(
            core.db,
            workspace_id,
            ask_id,
            STATUS_OF[choice],
            note.strip() or None,
            json.dumps(result) if result else None,
        )


def _decided_on_card(core: Core, workspace_id: str, card: str, round_: int) -> str | None:
    """The choice AGOS already wrote on the card for this round (its marker
    comment), or None. Read from Hermes's board; unreadable = none known."""
    from agos_core.actions import kanban_board

    try:
        raw, _extra = kanban_board._shown(core, workspace_id, card)
    except (ActionError, NotFoundError):
        return None
    choices = []
    for c in raw.get("comments") or [] if isinstance(raw, dict) else []:
        found = rules.read_marker(str(c.get("body") or "")) if isinstance(c, dict) else None
        if found is not None and found[0] == card and found[1] == round_:
            choices.append(found[2])
    # Each failed marker cancels one decision marker before it (same-second comments
    # may come back in any order, so they are counted, not ordered).
    decided = [c for c in choices if c in STATUS_OF]
    return decided[-1] if len(decided) > choices.count(FAILED) else None


def _act(
    core: Core, workspace_id: str, row: Any, choice: str, note: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """What the decision does on Hermes's side (after its comment is on the card).
    `payload`: the proposal as approved (the owner's edits in)."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    card, kind = str(row["card"]), str(row["kind"])
    if kind == "skill":
        from agos_core.actions import skill_requests

        # The request row that names this very ask (an agent's own card can't land one).
        made = skill_requests.decided(
            core, workspace_id, int(payload.get("request") or 0), int(row["id"]), choice
        )
        summary = (
            f"Skill {payload.get('name')}: {made.get('status')}"
            if choice == "approve"
            else f"Rejected by the owner{': ' + note.strip() if note.strip() else ''}."
        )
        _hermes_kanban(
            core,
            workspace_id,
            "complete",
            card,
            f"--result={'approved' if choice == 'approve' else 'rejected'}",
            f"--summary={summary}",
        )
        return made
    if choice == "reject":
        what = "Skipped" if payload.get("change") == "daily_plan" else "Rejected"
        _hermes_kanban(
            core,
            workspace_id,
            "complete",
            card,
            "--result=rejected",
            f"--summary={what} by the owner{': ' + note.strip() if note.strip() else ''}.",
        )
        return {}
    if choice == "revise":
        _hermes_kanban(core, workspace_id, "unblock", card)
        return {}
    if kind == "hire":
        made = hire(core, workspace_id, payload)
        summary = f"Hired @{made['name']} ({payload.get('title')}) as the owner approved."
        if made.get("topic_error"):
            summary += f" Telegram topic not made: {made['topic_error']}"
        _hermes_kanban(
            core, workspace_id, "complete", card, f"--result={summary}", f"--summary={summary}"
        )
        return made
    if kind == "kit":
        from agos_core.actions import member_kits

        made = member_kits.apply(core, workspace_id, payload, card)
        summary = f"Wrote @{made['kit_for']}'s kit as the owner approved."
        _hermes_kanban(
            core, workspace_id, "complete", card, f"--result={summary}", f"--summary={summary}"
        )
        return made
    if kind == "goal":
        from agos_core.actions import goals

        made = goals.apply_change(core, workspace_id, payload)
        summary = (
            f"Today's plan accepted: {len(made.get('cards') or [])} cards for the team, "
            f"{len(made.get('you') or [])} for the owner."
            if payload.get("change") == "daily_plan"
            else f"Goal changed as the owner approved: {rules.label(kind, payload)}."
        )
        _hermes_kanban(
            core, workspace_id, "complete", card, f"--result={summary}", f"--summary={summary}"
        )
        return made
    if kind == "instructions":
        consent(core, workspace_id, str(row["member"]), card, payload)
    _hermes_kanban(core, workspace_id, "unblock", card)
    return {}


def undo(core: Core, workspace_id: str, ask_id: int) -> dict[str, Any]:
    row = ask_row(core, workspace_id, ask_id)
    result = _json(row["result"])
    if str(row["status"]) != "approved" or not (result.get("member_id") or result.get("kit_for")):
        raise ActionError("This can't be undone.", 409)
    if str(row["kind"]) == "kit":
        from agos_core.actions import member_kits

        member_kits.undo(core, workspace_id, result)
        words = f"kit: @{result.get('kit_for')} is back to how it was before."
    else:
        with contextlib.suppress(NotFoundError):  # gone already
            unhire(core, workspace_id, result)
        words = f"hire: @{result.get('name')} was removed."
    from agos_core.actions.kanban_asks import _hermes_kanban

    _hermes_kanban(
        core,
        workspace_id,
        "comment",
        str(row["card"]),
        f"{rules.marker(str(row['card']), int(row['round']), 'undo')} The owner undid this "
        + words,
        "--author",
        "owner",
    )
    with transaction(core.db):
        kanban_asks.decide(core.db, ask_id, "undone")
    return ask_view(core, workspace_id, ask_row(core, workspace_id, ask_id))
