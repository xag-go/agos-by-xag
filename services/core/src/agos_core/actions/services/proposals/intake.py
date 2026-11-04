"""A proposal arriving from Hermes's Kanban card: recorded once, refused, superseded, told to the owner; an agent proposing.
Must not: act on the owner's decision.

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.proposals.hire_checks import check_new
from agos_core.actions.services.proposals.proposal_states import REFUSED, TERMINAL, _json
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.db.connection import transaction
from agos_core.engine import proposals as rules

__all__ = [
    "arrived",
    "propose",
    "record",
]

# ---- recording -------------------------------------------------------------------------


def arrived(
    core: Core, workspace_id: str, card: str, member: str, proposal: dict[str, Any]
) -> bool:
    """A card carrying a proposal just blocked for the owner (the hook): recorded
    as a new round unless it is the same proposal again. True when the card was
    released (a replayed block of a proposal he already decided)."""
    kind, payload = str(proposal["kind"]), dict(proposal["payload"])
    rows = kanban_asks.card_rows(core.db, workspace_id, card[:64])
    latest = rows[0] if rows else None
    if latest is not None and str(latest["status"]) == "waiting":
        return False  # recorded already; it waits for him
    if (
        latest is not None
        and str(latest["kind"]) in rules.KINDS
        and str(latest["status"]) in TERMINAL
        and rules.digest(str(latest["kind"]), _json(latest["payload"]))
        == rules.digest(kind, payload)
    ):
        # The same proposal blocked again after his decision (a late block): his
        # answer is on the card already; the card goes on as that answer said.
        _release(core, workspace_id, card, str(latest["kind"]), str(latest["status"]))
        return True
    round_ = 1
    revises = str(proposal.get("revises") or "")
    if kind in ("hire", "kit"):
        # A hire (or a member's kit) an agent wrote by hand meets the same rules as
        # one made with agos_propose: refused before it reaches the owner, with what
        # is missing told on its card (the agent gets the card back and proposes again).
        problems = check_new(core, workspace_id, kind, payload, member=member, kept_ok=True)
        if problems:
            _refuse(core, workspace_id, card, problems, kind)
            return True
    if revises:
        before = kanban_asks.latest_round(core.db, workspace_id, revises[:64])
        round_ = before + 1 if before is not None else 1
    record(core, workspace_id, card, member, kind, payload, round_=round_, revises=revises)
    return False


def _refuse(
    core: Core, workspace_id: str, card: str, problems: list[str], kind: str = "hire"
) -> None:
    """A hand-written hire that misses what every hire needs: never in the owner's
    Inbox. Its card gets the reasons and goes back to the agent (Hermes's unblock),
    which proposes again with agos_propose on a new card."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    text = (
        f"{REFUSED} AGOS refused this {kind}, nothing reached the owner: "
        + "; ".join(problems)
        + f". Propose it again with agos_propose (kind {kind}) with all of it, then complete "
        "this card with the new card's id."
    )
    _hermes_kanban(core, workspace_id, "comment", card, text)
    _hermes_kanban(core, workspace_id, "unblock", card)


def record(
    core: Core,
    workspace_id: str,
    card: str,
    member: str,
    kind: str,
    payload: dict[str, Any],
    *,
    round_: int = 1,
    revises: str = "",
) -> int | None:
    """One waiting row per card (the asks' unique index): the id, or None when it
    was there already. Tells the owner (Co-Founder chat and phone)."""
    from agos_core.actions import agent_profiles

    if kind not in rules.KINDS:
        raise ActionError("Unknown proposal kind.")
    if member and member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Not a member of this workspace's team.")
    label = rules.label(kind, payload)
    detail = "; ".join(rules.proposing_problems(kind, payload))
    with transaction(core.db):
        added = kanban_asks.add_proposal(
            core.db,
            workspace_id,
            card[:64],
            member,
            kind,
            label[:120],
            detail[:900],
            json.dumps(payload, ensure_ascii=False),
            round_,
        )
        if added is None:
            return None
        ask_id = added
        _tell(core, workspace_id, ask_id)
    if revises:
        _supersede(core, workspace_id, revises, card)
    return ask_id


def _supersede(core: Core, workspace_id: str, old: str, new: str) -> None:
    """The earlier round's card is done: the new card carries the proposal."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    _hermes_kanban(
        core,
        workspace_id,
        "complete",
        old,
        f"--result=Proposed again on card {new} after the owner's revise.",
        f"--summary=Proposed again on card {new}.",
    )


def _tell(core: Core, workspace_id: str, ask_id: int) -> None:
    from agos_core.actions import voice
    from agos_core.actions.services.channel import owner_needs

    row = kanban_asks.get(core.db, ask_id)
    if row is None:  # recorded just now, in this transaction: never
        return
    who = voice.name_of(core, workspace_id, str(row["member"]) or None)
    payload = _json(row["payload"])
    body = f"📋 **{who}** proposes: {row['label']} (card {row['card']})."
    body += _kind_lines(str(row["kind"]), payload)
    buttons = [("Approve", f"kask:approve:{ask_id}"), ("Reject", f"kask:reject:{ask_id}")]
    if row["kind"] == "goal" and payload.get("change") == "daily_plan":
        from agos_core.actions import today

        # The daily plan: Accept / Skip on the phone, Change (a note) in AGOS.
        body = f"☀️ **{who}**: today's plan ({payload.get('date')}).\n{today.plan_text(payload)}"
        body += "\nChange it (with a note) in AGOS → Inbox or Vision."
        buttons = [("Accept", f"kask:approve:{ask_id}"), ("Skip", f"kask:reject:{ask_id}")]
    else:
        if row["kind"] == "goal" and payload.get("why"):
            body += f"\n{str(payload['why'])[:400]}"
        body += "\nRevise (with a note) in AGOS → Inbox."
    owner_needs.push(
        core,
        workspace_id,
        body,
        f"kanban-ask:{ask_id}",
        buttons=buttons,
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )


def _hire_lines(payload: dict[str, Any]) -> str:
    from agos_core.engine import hire_kit as hire_kit_rules

    parts = [
        f"@{payload.get('name')}" if payload.get("name") else "",
        f"model {hire_kit_rules.model_line(payload['model'])}"
        if isinstance(payload.get("model"), dict)
        else "the workspace's model",
        f"reports to @{payload['reports_to']}" if payload.get("reports_to") else "",
    ]
    body = "\n" + " · ".join(p for p in parts if p)
    if payload.get("model_why") and isinstance(payload.get("model"), dict):
        body += f"\nModel: {str(payload['model_why'])[:200]}"
    if payload.get("role"):
        body += f"\n{str(payload['role'])[:400]}"
    kit = payload.get("kit") if isinstance(payload.get("kit"), dict) else {}
    if kit:
        body += _kit_count(kit)
    return body


def _kit_count(kit: dict[str, Any]) -> str:
    return (
        f"\nKit: {len(kit.get('tools') or [])} tools, {len(kit.get('skills') or [])} "
        f"skills, {len(kit.get('docs') or [])} docs"
        + (", an onboarding test" if (kit.get("onboarding") or {}).get("task") else "")
    )


def _kit_lines(payload: dict[str, Any]) -> str:
    from agos_core.engine import hire_kit as hire_kit_rules

    given: dict[str, Any] = payload["kit"] if isinstance(payload.get("kit"), dict) else {}
    body = ""
    if isinstance(payload.get("model"), dict):
        body += f"\nModel: {hire_kit_rules.model_line(payload['model'])}"
        if payload.get("model_why"):
            body += f" ({str(payload['model_why'])[:200]})"
    if payload.get("why"):
        body += f"\n{str(payload['why'])[:400]}"
    return body + _kit_count(given)


def _kind_lines(kind: str, payload: dict[str, Any]) -> str:
    """The lines under a proposal's first line on his phone, by its kind."""
    if kind == "hire":
        return _hire_lines(payload)
    if kind == "kit":
        return _kit_lines(payload)
    if kind == "instructions" and payload.get("summary"):
        return f"\n{str(payload['summary'])[:400]}"
    if kind == "plan" and payload.get("markdown"):
        return f"\n{str(payload['markdown'])[:400]}"
    if kind == "skill":
        body = f"\nFrom {payload.get('source')}: {str(payload.get('why') or '')[:300]}"
        if payload.get("scan"):
            body += f"\n{str(payload['scan'])[:300]}"
        return body
    return ""


def _release(core: Core, workspace_id: str, card: str, kind: str, status: str) -> None:
    """A decided proposal's card blocked again: the same release as its decision."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    if status == "rejected" or (
        status in ("approved", "undone") and kind in ("hire", "goal", "skill", "kit")
    ):
        _hermes_kanban(core, workspace_id, "complete", card, f"--result={status}")
    else:
        _hermes_kanban(core, workspace_id, "unblock", card)


# ---- a proposal AGOS itself makes (every Co-Founder hire, Ask mode's others) ----------


def propose(
    core: Core,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    words: str = "",
    *,
    member: str = "",
    revises: str = "",
    by_tool: bool = False,
    once: str = "",
) -> dict[str, Any]:
    """A proposal AGOS writes for an agent: the same card the agent would make,
    written through Hermes's Kanban CLI, blocked for the owner, recorded.
    - the Co-Founder's hire_agent from a chat, a card or a run (every hire, in every
      autonomy mode; `member` "", no assignee: nobody claims it; AGOS acts on the
      approve);
    - an agent's agos_propose tool (the guard's asks.py, `by_tool`): created by and
      assigned to the proposer (the Co-Founder's own profile when `member` is ""),
      so an approved instructions change or plan comes back to it.
    `once`: Hermes's card idempotency key (the same proposal asked again is the same
    card; the Vision notes' goals, actions/vision_notes.py)."""
    from agos_core.actions import agent_profiles, kanban_board
    from agos_core.actions.kanban_asks import _hermes_kanban

    if kind not in rules.KINDS:
        raise ActionError(f"Unknown proposal kind; use one of {', '.join(rules.KINDS)}.")
    if member and member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Not a member of this workspace's team.")
    payload = rules.clean(kind, payload)
    problems = check_new(core, workspace_id, kind, payload, member=member)
    if problems and kind in ("hire", "kit"):
        raise ActionError(
            f"This {kind} was not proposed, nothing reached the owner. Missing or wrong: "
            + "; ".join(problems)
            + f". Send the {kind} again with all of it."
        )
    if problems:
        raise ActionError("; ".join(problems))
    body = (words.strip() + "\n\n" if words.strip() else "") + rules.block(kind, payload, revises)
    assignee = member or (kanban_board.COFOUNDER if by_tool else "")
    card = kanban_board.create(
        core,
        workspace_id,
        rules.label(kind, payload),
        body,
        assignee,
        created_by=kanban_board._profile_of(core, workspace_id, assignee) if assignee else "",
        blocked=True,
        once=once,
    )
    # Types the block in place (needs_input + the reason the hook and the Inbox read).
    _hermes_kanban(core, workspace_id, "block", card, "--kind", "needs_input", rules.BLOCK_REASON)
    round_ = 1
    if revises:
        before = kanban_asks.latest_round(core.db, workspace_id, revises[:64])
        round_ = before + 1 if before is not None else 1
    ask_id = record(core, workspace_id, card, member, kind, payload, round_=round_, revises=revises)
    if ask_id is None:  # the block's hook recorded it first
        ask_id = kanban_asks.latest_id(core.db, workspace_id, card)
    return {"card": card, "ask_id": ask_id, "proposed": True}
