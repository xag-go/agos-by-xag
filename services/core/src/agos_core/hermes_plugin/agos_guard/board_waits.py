"""A Kanban card's waits for the owner, and the board in an automation's run.

Split out of agos_core.hermes_plugin.agos_guard (the guard's facade). Owns: his
Allow once / Deny answers per card (agos-kanban-allowed.json), the card's block
that waits for him, AGOS told when a card blocks for him or a teammate or moves
(its pipeline rules), and an automation's cards that wait on the board for him.

Must not: read the owner's rules itself (the caller passes them) or ask Hermes's
approval gate.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from . import runtime
from .guard_contract import ACTIONS
from .policy import action_of

__all__ = [
    "ALLOWED_FILE",
    "AUTOMATION_READS",
    "OWNER_OK",
    "REFUSED",
    "TEAMMATE_WAIT",
    "_allowed",
    "_answers",
    "_refused",
    "answered_block",
    "automation_card",
    "blocked_for_owner",
    "card_ask",
    "pipeline_event",
]

ALLOWED_FILE = "agos-kanban-allowed.json"


# His answers per card in that file: "<action>" = allowed once, "no:<action>" = denied.
REFUSED = "no:"


# The reason a card blocks with while it waits for his Allow once / Deny.
OWNER_OK = "waiting for the owner:"


# The reason a card blocks with while it waits for a teammate or the Co-Founder
# (the unblock owner; AGOS hands the card to that agent: actions/blocked.py).
TEAMMATE_WAIT = "waiting for @"


def _answers(card: str) -> set[str]:
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        data = json.loads((Path(get_hermes_home()) / ALLOWED_FILE).read_text())
    except ImportError as error:
        runtime._report("hermes_constants.get_hermes_home", error)
        return set()
    except (OSError, ValueError):
        return set()
    return {str(a) for a in (data.get(card) or [])} if isinstance(data, dict) else set()


def _allowed(card: str) -> set[str]:
    return {a for a in _answers(card) if not a.startswith(REFUSED)}


def _refused(card: str) -> set[str]:
    return {a[len(REFUSED) :] for a in _answers(card) if a.startswith(REFUSED)}


def answered_block(card: str, args: dict[str, Any]) -> dict[str, str] | None:
    """The card is about to block for his OK, but he has already answered (his
    click reached AGOS while the card was still running, a second before the
    block): no wait, it uses his answer now. Hermes's kanban_block is refused."""
    reason = str(args.get("reason") or "")
    card = str(args.get("task_id") or card or "")
    if not card or not reason.startswith(OWNER_OK):
        return None
    label = reason[len(OWNER_OK) :].strip()
    action = next((a for a, shown in ACTIONS.items() if shown == label), "")
    if action and action in _allowed(card):
        return {
            "action": "block",
            "message": f"Don't block this card: the owner already allowed “{label}” once "
            "for it. Go on and do it now.",
        }
    if action and action in _refused(card):
        return {
            "action": "block",
            "message": f"Don't block this card: the owner already said no to “{label}”. "
            "Don't do it; finish what you can without it and say what is left.",
        }
    return None


def blocked_for_owner(task_id: str, reason: Any) -> None:
    """Hermes's kanban_task_blocked hook (after the block is written): a card that
    blocked for his OK is told to AGOS, which lets it go on at once when he
    already answered (the other side of the race answered_block covers). A card
    that blocked for a teammate ("waiting for @<name>: …", the unblock owner) is
    told too: AGOS hands it to that agent through Hermes (assign + unblock)."""
    text = str(reason or "")
    if task_id and (text.startswith(OWNER_OK) or text.lower().startswith(TEAMMATE_WAIT)):
        runtime._bridge_module().post("kanban-blocked", {"card": str(task_id)}, 20)


def pipeline_event(task_id: str, *, sweep: bool = False) -> None:
    """Tell AGOS a card moved (its pipeline rules, Step 59), off Hermes's path: the
    hooks fire inside the dispatcher and the worker, which never wait for AGOS. Not a
    daemon: a worker that exits right after its kanban_complete still tells it."""
    if not task_id and not sweep:
        return
    path, body = ("pipeline-sweep", {}) if sweep else ("pipeline-event", {"card": task_id})
    threading.Thread(
        target=lambda: runtime._bridge_module().post(path, body, 10),
        name="agos-pipeline-event",
        daemon=False,
    ).start()


def card_ask(
    policy: dict[str, Any], card: str, tool: str, args: dict[str, Any]
) -> dict[str, str] | None:
    """A member working a Kanban card alone: nobody is there to click Allow, so an
    "Ask me" action waits for the owner. Allowed once for this card = it runs; else
    AGOS asks him (the Co-Founder's chat and his phone) and the card blocks until he
    answers: Hermes's own typed human wait (`kanban_block` kind `needs_input`, which
    stays blocked until a person unblocks it; hermes_cli/kanban_db.py block_task).
    AGOS keeps only the ask's key (its Allow once / Deny buttons) and the grant."""
    action = action_of(tool, args) or ""
    if action in _allowed(card):
        return None
    label = ACTIONS.get(action, action)
    if action in _refused(card):
        return {
            "action": "block",
            "message": f"The owner said no to “{label}” for this card: don't do it and "
            "don't block for it again; finish what you can without it and say what is left.",
        }
    detail = str(args.get("command") or args.get("path") or args.get("code") or tool)[:900]
    runtime._bridge_module().post(
        "kanban-ask",
        {
            "card": card,
            "member": str(policy.get("member") or ""),
            "action": action,
            "label": label,
            "detail": detail,
        },
        15,
    )
    return {
        "action": "block",
        "message": f"The owner must OK “{label}” first ({tool}); AGOS has asked him. "
        f'Block this card now with kanban_block (kind "needs_input", reason: "waiting for '
        f'the owner: {label}") and stop. When he answers, the card comes back to you with '
        "his answer.",
    }


AUTOMATION_READS = {"kanban_list", "kanban_show"}


def automation_card(
    tool: str, decision: dict[str, str] | None, args: dict[str, Any]
) -> dict[str, Any] | None:
    """The board in an automation's run (Hermes's cron, nobody there to say yes):
    it reads, and a card it makes is a proposal that waits on the board for the
    owner: Hermes makes it blocked (the hook's own "modify" of the call), and he
    starts it or archives it. His "Never" for cards holds."""
    if tool in AUTOMATION_READS:
        return None
    if tool != "kanban_create":
        return {
            "action": "block",
            "message": "In an automation's run the board is read only: never start, move or "
            'finish cards. Propose new ones with kanban_create (initial_status "blocked").',
        }
    if decision is not None and decision.get("action") == "block":
        return decision
    if str(args.get("initial_status") or "") == "blocked" and not args.get("triage"):
        return None  # it waits for him anyway: no Allow / Deny to ask in a cron run
    return {"action": "modify", "args": {"initial_status": "blocked", "triage": False}}
