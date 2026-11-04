"""A team member working a Kanban card (Hermes's board) needs the owner's OK.

The owner's Autonomy rules say "Ask me" for that kind of action: the guard inside
the member's Hermes stops the action, AGOS records the ask, and the member blocks
its card (Hermes's own kanban_block). The ask reaches him in the Co-Founder's chat
(AGOS and the phone) with Allow once / Deny:
- Allow once: that card may do that kind of action (written in the member's
  profile, read by the guard), and the card is unblocked (Hermes's CLI);
- Deny: the card is unblocked with a comment: go on without it (and the guard
  keeps it from asking or blocking for it again).

His click can reach AGOS while the card is still running, a second before its
kanban_block lands (Hermes's unblock then finds nothing blocked). Both sides of
that race use his answer: the guard refuses a block he has already answered
(`answered_block`), and a block that lands anyway is told here by Hermes's
kanban_task_blocked hook (`settle`), which unblocks it at once.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import kanban_cli
from agos_core.context import Core
from agos_core.db import kanban_asks as repo
from agos_core.db.connection import transaction
from agos_core.hermes_gateway import kanban_rows

log = logging.getLogger(__name__)

# In the member's profile home (AGOS writes it, the guard reads it):
# {card: ["<action>" allowed once, "no:<action>" denied]}.
ALLOWED_FILE = "agos-kanban-allowed.json"
REFUSED = "no:"
OWNER_OK = "waiting for the owner:"  # the reason a card blocks with for an ask
# A card's permissions are kept this long (cards finish well before).
KEEP = 300


def ask(
    core: Core, workspace_id: str, card: str, member: str, action: str, label: str, detail: str
) -> bool:
    """Records the ask once (per card and action) and tells him. True = new."""
    from agos_core.actions import agent_profiles

    if member and member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Not a member of this workspace's team.")
    with transaction(core.db):
        ask_id = repo.add_ask(
            core.db, workspace_id, card[:64], member, action[:40], label[:120], detail[:900]
        )
        if ask_id is None:
            return False
        _tell(core, workspace_id, ask_id)
    return True


def _tell(core: Core, workspace_id: str, ask_id: int) -> None:
    from agos_core.actions import voice
    from agos_core.actions.services.channel import owner_needs

    row = repo.get(core.db, ask_id)
    assert row is not None  # made just now, in the same transaction
    who = voice.name_of(core, workspace_id, str(row["member"]) or None)
    body = f"⚠️ **{who}** needs your OK on card {row['card']}: {row['label']}."
    if row["detail"]:
        body += f"\n`{row['detail'][:400]}`"
    owner_needs.push(
        core,
        workspace_id,
        body,
        f"kanban-ask:{ask_id}",
        buttons=[("Allow once", f"kask:once:{ask_id}"), ("Deny", f"kask:deny:{ask_id}")],
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )


def waiting(core: Core, workspace_id: str, limit: int = 20) -> list[dict[str, Any]]:
    from agos_core.actions import voice

    return [
        {
            "id": int(r["id"]),
            "card": str(r["card"]),
            "member": str(r["member"]),
            "memberName": voice.name_of(core, workspace_id, str(r["member"]) or None),
            "label": str(r["label"]),
            "detail": str(r["detail"]),
            "createdAt": str(r["created_at"]),
        }
        for r in repo.waiting_asks(core.db, workspace_id, limit)
    ]


def answer(core: Core, workspace_id: str, ask_id: int, allow: bool) -> str:
    row = repo.in_workspace(core.db, workspace_id, ask_id)
    if row is None or str(row["kind"]) != "ask":
        raise NotFoundError("This request")  # a proposal is decided in proposals.decide
    if row["status"] != "waiting":
        return "Already answered."
    card, member, action = str(row["card"]), str(row["member"]), str(row["action"])
    # In this order: the guard and the card's comment hold his answer before the
    # ask reads as answered (what `settle` goes by) and before the unblock.
    _remember(core, workspace_id, member, card, action if allow else REFUSED + action)
    note = (
        f"The owner allowed “{row['label']}” once for this card: go on."
        if allow
        else f"The owner said no to “{row['label']}”: don't do it; finish what you can "
        "without it and say what is left."
    )
    _hermes_kanban(core, workspace_id, "comment", card, note)
    with transaction(core.db):
        repo.decide(core.db, ask_id, "allowed" if allow else "denied")
    from agos_core.engine import doorbell

    doorbell.ring(doorbell.SEND)  # its card in Telegram loses its buttons now
    _hermes_kanban(core, workspace_id, "unblock", card)
    return "Allowed once: the card goes on." if allow else "Denied: the card goes on without it."


def settle(core: Core, workspace_id: str, card: str) -> bool:
    """A card just blocked for someone (Hermes's kanban_task_blocked hook, through the
    guard). For his OK: when he has already answered that ask, it goes on now
    (Hermes's unblock; his answer is already in its comments). True = the card moved.
    A card whose body carries an agos-proposal block is a proposal (hire,
    instructions, plan): recorded for his Approve / Revise / Reject
    (actions/proposals.py), or released when it is one he already decided; an
    agos-question block is a question (actions/questions.py), the same way. A card
    that waits for a teammate ("waiting for @<name>: …") is handed to that agent
    through Hermes (actions/blocked.py route)."""
    from agos_core.actions import blocked, proposals, questions
    from agos_core.engine import proposals as proposal_rules
    from agos_core.engine import questions as question_rules

    reason, body, assignee = _blocked_card(core, workspace_id, card)
    if reason.lower().startswith("waiting for @"):
        return blocked.route(core, workspace_id, card, reason, assignee)
    if not reason.startswith(OWNER_OK):
        return False
    proposal = proposal_rules.parse(body)
    if proposal is not None:
        return proposals.arrived(core, workspace_id, card, proposals.member_of(assignee), proposal)
    question = question_rules.parse(body)
    if question is not None:
        return questions.arrived(core, workspace_id, card, proposals.member_of(assignee), question)
    label = reason[len(OWNER_OK) :].strip()
    rows = repo.ask_labels(core.db, workspace_id, card[:64])
    same = [r for r in rows if str(r["label"]) == label] or rows
    if not same or any(str(r["status"]) == "waiting" for r in same):
        return False  # not answered yet: it waits for him (his click unblocks it)
    _hermes_kanban(core, workspace_id, "unblock", card)
    return True


def _blocked_card(core: Core, workspace_id: str, card: str) -> tuple[str, str, str]:
    """(reason, body, assignee) of a card blocked for a person now; ("", "", "")
    when it isn't. Hermes's board, read only."""
    import sqlite3

    from agos_core.actions import agent_profiles

    none = ("", "", "")
    if core.engine is None:
        return none
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return none
    try:
        with kanban_rows.opened(board_db, timeout=5) as board:
            row = board.needs_input_of(card)
    except sqlite3.Error:
        return none
    if row is None:
        return none
    try:
        reason = str((json.loads(row[0] or "{}") or {}).get("reason") or "")
    except ValueError:
        reason = ""
    return reason, str(row[1] or ""), str(row[2] or "")


def _remember(core: Core, workspace_id: str, member: str, card: str, action: str) -> None:
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return
    home = core.engine.profile_home(
        agent_profiles.key(workspace_id, member) if member else workspace_id
    )
    target = home / ALLOWED_FILE
    try:
        allowed = json.loads(target.read_text())
    except (OSError, ValueError):
        allowed = {}
    actions = set(allowed.get(card) or [])
    allowed[card] = sorted(actions | {action})
    allowed = dict(list(allowed.items())[-KEEP:])
    _write(target, allowed)


def _write(target: Path, value: Any) -> None:
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(value, handle, sort_keys=True)
    tmp.replace(target)


def _hermes_kanban(core: Core, workspace_id: str, *args: str) -> None:
    """Hermes's own Kanban CLI, on the workspace's board."""
    kanban_cli.tried(core, workspace_id, *args)
