"""The buttons of AGOS's own Telegram cards: what a press does (approve, review, answer...).
Must not: send or queue a card.

Split out of agos_core.actions.channels (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import chats as chats_repo
from agos_core.db import kanban_asks as kanban_asks_repo

__all__ = [
    "button",
]

# ---- AGOS's own buttons (pressed in Telegram) ---------------------------------------------
# Only the cards about AGOS's own state carry AGOS's buttons; Hermes's gateway checks
# who pressed (its own allowlist) before it hands one to AGOS.


def button(core: Core, row: Any, address: str, data: str) -> tuple[str, str]:
    """One of AGOS's buttons, pressed in the chat at `address`: (what happened, what
    to show on the card)."""
    chatcmd = re.fullmatch(r"chatcmd:(once|deny):(\d{1,12})", data)
    if chatcmd:
        return _room_approval_button(core, row, address, chatcmd.group(1), int(chatcmd.group(2)))
    kask = re.fullmatch(r"kask:(once|deny):(\d{1,12})", data)
    if kask:
        return _kanban_ask_button(core, row, address, kask.group(1) == "once", int(kask.group(2)))
    prop = re.fullmatch(r"kask:(approve|reject):(\d{1,12})", data)
    if prop:
        return _proposal_button(core, row, address, prop.group(1), int(prop.group(2)))
    ans = re.fullmatch(r"kask:ans:(\d{1,12}):([a-z0-9_-]{1,32})", data)
    if ans:
        return _question_button(core, row, address, int(ans.group(1)), ans.group(2))
    tok = re.fullmatch(r"tok:(go|stop):([A-Za-z0-9_-]{1,64})", data)
    if tok:
        return _tokens_button(core, row, address, tok.group(1), tok.group(2))
    rev = re.fullmatch(r"krev:ok:([A-Za-z0-9_-]{1,64})", data)
    if rev:
        return _review_button(core, row, address, rev.group(1))
    fdone = re.fullmatch(r"fdone:([A-Za-z0-9_-]{1,64})", data)
    if fdone:
        return _founder_button(core, row, address, fdone.group(1))
    return "ignored: unknown button", ""


def _founder_button(core: Core, row: Any, address: str, card: str) -> tuple[str, str]:
    """Done on one of his Founder tasks (actions/founder.py); only on this chat's own
    workspaces' boards."""
    from agos_core.actions import founder

    said = founder.button(core, _workspace_of_address(core, row, address), card)
    return "button: founder done", said


def _review_button(core: Core, row: Any, address: str, card: str) -> tuple[str, str]:
    """Approve on a card's review stage or plan waiting for him (actions/reviews.py);
    only on this chat's own workspaces' boards."""
    from agos_core.actions import reviews
    from agos_core.actions.errors import ActionError

    try:
        said = reviews.button(core, _workspace_of_address(core, row, address), card)
    except ActionError as error:
        return "button: review approve refused", error.message
    return "button: review approve", said


def _workspace_of_address(core: Core, row: Any, address: str) -> set[str]:
    found = addresses_repo.workspaces_at(core.db, int(row["id"]), address)
    if row["workspace_id"] and not str(address).startswith("-"):
        found.add(str(row["workspace_id"]))  # the bot's own chat with him (its workspace)
    return found


def _room_approval_button(
    core: Core, row: Any, address: str, choice: str, chat_id: int
) -> tuple[str, str]:
    """Allow once / Deny on a command a member of a group's Hermes room asks."""
    chat_in = chats_repo.visible_workspace_of(core.db, chat_id)
    if chat_in is None or chat_in not in _workspace_of_address(core, row, address):
        return "ignored: chat gone", ""
    from agos_core.actions import chat as chat_actions

    try:
        chat_actions.answer_approval(core, chat_in, chat_id, choice)
    except ActionError:
        return "button: chat command (stale)", "Already answered: nothing is waiting anymore."
    shown = "Allowed once: the agent goes on." if choice == "once" else "Denied."
    return f"button: chatcmd {choice}", shown


def _kanban_ask_button(
    core: Core, row: Any, address: str, allow: bool, ask_id: int
) -> tuple[str, str]:
    """Allow once / Deny on what a member working a Kanban card asks."""
    asked_in = kanban_asks_repo.workspace_of(core.db, ask_id)
    if asked_in is None or asked_in not in _workspace_of_address(core, row, address):
        return "ignored: request gone", ""
    from agos_core.actions import kanban_asks

    shown = kanban_asks.answer(core, asked_in, ask_id, allow)
    return f"button: kanban ask {'once' if allow else 'deny'}", shown


def _proposal_button(
    core: Core, row: Any, address: str, choice: str, ask_id: int
) -> tuple[str, str]:
    """Approve / Reject on an agent's proposal (a revise, with its note, is in AGOS)."""
    asked_in = kanban_asks_repo.workspace_of(core.db, ask_id)
    if asked_in is None or asked_in not in _workspace_of_address(core, row, address):
        return "ignored: request gone", ""
    from agos_core.actions import proposals
    from agos_core.actions.errors import ActionError

    try:
        shown = proposals.decide(core, asked_in, ask_id, choice)
    except ActionError as error:
        return f"button: proposal {choice} refused", error.message
    words = {"approved": "Approved.", "rejected": "Rejected."}
    if shown["payload"].get("change") == "daily_plan":  # Accept / Skip of today's plan
        words = {"approved": "Accepted: today's cards are on the board.", "rejected": "Skipped."}
    said = words.get(str(shown["status"]), "Decided.")
    return f"button: proposal {choice}", said


def _question_button(
    core: Core, row: Any, address: str, ask_id: int, value: str
) -> tuple[str, str]:
    """Yes / No on a confirm, or one option of a choice, asked by an agent's card."""
    asked_in = kanban_asks_repo.workspace_of(core.db, ask_id)
    if asked_in is None or asked_in not in _workspace_of_address(core, row, address):
        return "ignored: request gone", ""
    from agos_core.actions import questions
    from agos_core.actions.errors import ActionError

    try:
        said = questions.answer_button(core, asked_in, ask_id, value)
    except ActionError as error:
        return "button: question answer refused", error.message
    return "button: question answered", said


def _tokens_button(core: Core, row: Any, address: str, choice: str, card: str) -> tuple[str, str]:
    """Let it go on / Stop it, on a Kanban card using far more tokens than usual
    (only a card of a workspace this chat belongs to)."""
    from agos_core.actions import token_watch

    for workspace_id in sorted(_workspace_of_address(core, row, address)):
        if token_watch.knows(core, workspace_id, card):
            return f"button: tokens {choice}", token_watch.answer(core, workspace_id, card, choice)
    return "ignored: card gone", ""
