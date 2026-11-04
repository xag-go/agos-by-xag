"""An agent's typed question to the owner (ask, confirm, checkbox, choice,
verdicts, suggest_tasks), answered from AGOS or from a Telegram button.

The question itself is a Hermes Kanban card (engine/questions.py says its shape):
AGOS makes it for the agent's `agos_ask_owner` tool (assigned to the asker, created
by it), blocks it for the owner (Hermes's `kanban block`, needs_input, "waiting for
the owner: question") and records the ask (one kanban_asks row, kind 'question').
A card an agent blocked by hand with the same block (Hermes's block hook) is
recorded the same way when it arrives.

The answer is written on the card as a comment with a stable marker (Hermes's
`kanban comment`), then the card goes on as its continuation says:
- wake_assignee (default): asked while working another card -> the question card
  is completed with the answer as its result, and Hermes wakes the asking card
  (it waits on the question card as a parent: hermes_cli/kanban_db.py
  recompute_ready, _ctx_parent_results); asked from a chat -> `kanban unblock`,
  the asker's own card comes back to it with the answer;
- none: completed with the answer; nobody is woken.
suggest_tasks: every task the owner accepted becomes a card (Hermes's `kanban
create`, assigned to the suggested member or the asker) before the card goes on.
Idempotent like proposals: the same answer again is a no-op, another answer after
one is a 409; the marker on the card is the truth when the row never heard.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import kanban_asks as asks
from agos_core.db.connection import transaction
from agos_core.engine import questions as rules

log = logging.getLogger(__name__)

KIND = "question"
# Telegram's buttons (actions/channels.py): kask:ans:<ask id>:<value>.
BUTTON = "kask:ans:"


def _json(value: Any) -> dict[str, Any]:
    try:
        found = json.loads(value) if value else None
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


# ---- asking -----------------------------------------------------------------------------


def ask(
    core: Core,
    workspace_id: str,
    member: str,
    kind: str,
    payload: dict[str, Any],
    words: str = "",
    *,
    continuation: str = "wake_assignee",
    asked_from: str = "",
) -> dict[str, Any]:
    """The agent's agos_ask_owner: the question card, blocked for the owner, recorded.
    `member` "" = the Co-Founder. Returns {card, ask_id}."""
    from agos_core.actions import agent_profiles, kanban_board
    from agos_core.actions.kanban_asks import _hermes_kanban

    if kind not in rules.KINDS:
        raise ActionError(f"Unknown question kind; use one of {', '.join(rules.KINDS)}.")
    if member and member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Not a member of this workspace's team.")
    payload = rules.clean(kind, payload)
    problems = rules.problems(kind, payload)
    if problems:
        raise ActionError("; ".join(problems))
    if continuation not in rules.CONTINUATIONS:
        continuation = "wake_assignee"
    body = (words.strip() + "\n\n" if words.strip() else "") + rules.block(
        kind, payload, continuation, asked_from
    )
    assignee = member or kanban_board.COFOUNDER
    created_by = kanban_board._profile_of(core, workspace_id, assignee)
    card = kanban_board.create(
        core,
        workspace_id,
        rules.label(kind, payload),
        body,
        assignee,
        created_by=created_by,
        blocked=True,
    )
    # Types the block in place (needs_input + the reason the hook and the Inbox read).
    _hermes_kanban(core, workspace_id, "block", card, "--kind", "needs_input", rules.BLOCK_REASON)
    ask_id = record(core, workspace_id, card, member, kind, payload, continuation, asked_from)
    if ask_id is None:  # the block's hook recorded it first
        ask_id = asks.latest_id(core.db, workspace_id, card)
    return {"card": card, "ask_id": ask_id}


def arrived(
    core: Core, workspace_id: str, card: str, member: str, question: dict[str, Any]
) -> bool:
    """A card carrying a question just blocked for the owner (the hook): recorded
    unless it is there already. True when the card was released (a replayed block
    of a question he already answered)."""
    rows = asks.of_card(core.db, workspace_id, card[:64], KIND)
    latest = rows[0] if rows else None
    if latest is not None and str(latest["status"]) == "waiting":
        return False
    if latest is not None and str(latest["status"]) == "answered":
        _go_on(core, workspace_id, latest, _json(latest["result"]))
        return True
    record(
        core,
        workspace_id,
        card,
        member,
        str(question["kind"]),
        dict(question["payload"]),
        str(question.get("continuation") or "wake_assignee"),
        str(question.get("from") or ""),
    )
    return False


def record(
    core: Core,
    workspace_id: str,
    card: str,
    member: str,
    kind: str,
    payload: dict[str, Any],
    continuation: str,
    asked_from: str,
) -> int | None:
    """One waiting row per card: the id, or None when it was there already. Tells
    the owner (Co-Founder chat and phone; yes / no and single choices have buttons)."""
    label = rules.label(kind, payload)
    detail = json.dumps({"continuation": continuation, "from": asked_from})
    with transaction(core.db):
        ask_id = asks.add_question(
            core.db,
            workspace_id,
            card[:64],
            member,
            f"question:{kind}",
            label[:120],
            detail[:900],
            KIND,
            json.dumps({"kind": kind, **payload}, ensure_ascii=False),
        )
        if ask_id is None:
            return None
        _tell(core, workspace_id, ask_id)
    return ask_id


def _tell(core: Core, workspace_id: str, ask_id: int) -> None:
    from agos_core.actions import voice
    from agos_core.actions.services.channel import owner_needs

    row = asks.get(core.db, ask_id)
    assert row is not None  # just written in the caller's transaction
    who = voice.name_of(core, workspace_id, str(row["member"]) or None)
    payload = _json(row["payload"])
    kind = str(payload.get("kind") or "ask")
    body = f"❓ **{who}** asks (card {row['card']}): {payload.get('question') or row['label']}"
    buttons: list[tuple[str, str]] = []
    if kind == "confirm":
        buttons = [("Yes", f"{BUTTON}{ask_id}:yes"), ("No", f"{BUTTON}{ask_id}:no")]
    elif kind == "choice":
        buttons = [
            (str(o["label"])[:40], f"{BUTTON}{ask_id}:{o['id']}")
            for o in (payload.get("options") or [])[:8]
        ]
    elif kind == "checkbox":
        body += "\n" + "\n".join(f"☐ {o['label']}" for o in payload.get("options") or [])
        body += "\nPick in AGOS → Inbox."
    elif kind == "verdicts":
        body += "\n" + "\n".join(f"• {i['label']}" for i in payload.get("items") or [])
        body += "\nApprove or reject each in AGOS → Inbox."
    elif kind == "suggest_tasks":
        body += "\n" + "\n".join(f"• {t['title']}" for t in payload.get("tasks") or [])
        body += "\nAccept them one by one in AGOS → Inbox."
    else:
        body += "\nAnswer in AGOS → Inbox (a written answer)."
    owner_needs.push(
        core,
        workspace_id,
        body,
        f"kanban-ask:{ask_id}",
        buttons=buttons or None,
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )


# ---- reading -----------------------------------------------------------------------------


def _view(core: Core, workspace_id: str, r: Any) -> dict[str, Any]:
    from agos_core.actions import voice

    payload = _json(r["payload"])
    detail = _json(r["detail"])
    kind = str(payload.pop("kind", "ask"))
    return {
        "id": int(r["id"]),
        "card": str(r["card"]),
        "kind": kind,
        "member": str(r["member"]),
        "memberName": voice.name_of(core, workspace_id, str(r["member"]) or None),
        "label": str(r["label"]),
        "payload": payload,
        "continuation": str(detail.get("continuation") or "wake_assignee"),
        "askedFrom": str(detail.get("from") or ""),
        "status": str(r["status"]),
        "answer": _json(r["result"]) or None,
        "createdAt": str(r["created_at"]),
        "decidedAt": r["decided_at"],
    }


def waiting(core: Core, workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return [
        _view(core, workspace_id, r)
        for r in asks.waiting_of_kind(core.db, workspace_id, KIND, limit)
    ]


def _row(core: Core, workspace_id: str, ask_id: int) -> Any:
    row = asks.of_kind(core.db, workspace_id, ask_id, KIND)
    if row is None:
        raise NotFoundError("This question")
    return row


# ---- answering ---------------------------------------------------------------------------


def answer(core: Core, workspace_id: str, ask_id: int, given: Any) -> dict[str, Any]:
    from agos_core.actions.kanban_asks import _hermes_kanban

    row = _row(core, workspace_id, ask_id)
    payload = _json(row["payload"])
    kind = str(payload.pop("kind", "ask"))
    try:
        typed = rules.check_answer(kind, payload, given)
    except ValueError as error:
        raise ActionError(str(error)) from error
    status, card, round_ = str(row["status"]), str(row["card"]), int(row["round"])
    if status != "waiting":
        before = _json(row["result"])
        before.pop("cards", None)
        if status == "answered" and before == typed:
            return _view(core, workspace_id, row)  # the same answer again
        raise ActionError("Already answered.", 409)
    marked = _answered_on_card(core, workspace_id, card, round_)
    if marked is not None and marked != typed:
        with transaction(core.db):
            asks.answered(core.db, ask_id, json.dumps(marked), only_waiting=False)
        raise ActionError("Already answered.", 409)
    if kind == "suggest_tasks":
        typed["cards"] = _accepted_cards(core, workspace_id, row, payload, typed)
    if marked is None:
        text = (
            f"{rules.marker(card, round_)} {json.dumps(typed, ensure_ascii=False)}\n"
            f"{rules.answer_text(kind, payload, typed)}"
        )
        _hermes_kanban(core, workspace_id, "comment", card, text, "--author", "owner")
    with transaction(core.db):
        asks.answered(core.db, ask_id, json.dumps(typed, ensure_ascii=False), only_waiting=True)
    _go_on(core, workspace_id, row, typed)
    from agos_core.engine import doorbell

    doorbell.ring(doorbell.SEND)  # its card on his phone loses its buttons
    return _view(core, workspace_id, _row(core, workspace_id, ask_id))


def answer_button(core: Core, workspace_id: str, ask_id: int, value: str) -> str:
    """A Telegram button: yes / no (confirm) or an option id (choice)."""
    row = _row(core, workspace_id, ask_id)
    kind = str(_json(row["payload"]).get("kind") or "")
    if kind == "confirm":
        given: dict[str, Any] = {"yes": value == "yes"}
    elif kind == "choice":
        given = {"selected": value}
    else:
        raise ActionError("Answer this one in AGOS → Inbox.")
    if str(row["status"]) != "waiting":
        return "Already answered."
    answer(core, workspace_id, ask_id, given)
    return "Answered: the card goes on."


def _answered_on_card(
    core: Core, workspace_id: str, card: str, round_: int
) -> dict[str, Any] | None:
    """The answer AGOS already wrote on the card for this round (its marker
    comment), or None. Read from Hermes's board; unreadable = none known."""
    from agos_core.actions import kanban_board

    try:
        raw, _extra = kanban_board._shown(core, workspace_id, card)
    except (ActionError, NotFoundError):
        return None
    for c in raw.get("comments") or [] if isinstance(raw, dict) else []:
        body = str(c.get("body") or "") if isinstance(c, dict) else ""
        found = rules.read_marker(body)
        if found is not None and found[0] == card and found[1] == round_:
            rest = body.strip()[len(rules.marker(card, round_)) :].strip()
            try:
                parsed, _ = json.JSONDecoder().raw_decode(rest)
            except ValueError:
                return {}
            if isinstance(parsed, dict):
                parsed.pop("cards", None)
                return parsed
            return {}
    return None


def _accepted_cards(
    core: Core, workspace_id: str, row: Any, payload: dict[str, Any], typed: dict[str, Any]
) -> list[str]:
    """The suggested tasks he accepted become cards (Hermes's own dedup key keeps
    a replay from making them twice)."""
    from agos_core.actions import agent_profiles, kanban_board

    tasks = payload.get("tasks") or []
    members = agent_profiles.team_names(core, workspace_id)
    made: list[str] = []
    for i in typed.get("accepted") or []:
        task = tasks[i]
        who = str(task.get("member") or "") or str(row["member"])
        if who and who not in members and who != kanban_board.COFOUNDER:
            who = str(row["member"])
        made.append(
            kanban_board.create(
                core,
                workspace_id,
                str(task["title"]),
                str(task.get("body") or ""),
                who or kanban_board.COFOUNDER,
                once=f"agos-suggested:{row['card']}:{i}",
            )
        )
    return made


def _go_on(core: Core, workspace_id: str, row: Any, typed: dict[str, Any]) -> None:
    """What the answer does on Hermes's side (after its comment is on the card)."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    payload = _json(row["payload"])
    kind = str(payload.pop("kind", "ask"))
    detail = _json(row["detail"])
    continuation = str(detail.get("continuation") or "wake_assignee")
    card = str(row["card"])
    if continuation == "wake_assignee" and not detail.get("from"):
        _hermes_kanban(core, workspace_id, "unblock", card)
        return
    result = rules.result_text(kind, payload, typed)
    _hermes_kanban(
        core, workspace_id, "complete", card, f"--result={result}", f"--summary={result}"
    )
