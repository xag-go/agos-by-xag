"""The workspace's Inbox: one derived list of everything waiting for the owner.

Nothing here is a copy: the items are read from AGOS's asks (proposals, typed
questions, Autonomy asks: kanban_asks rows, written from Hermes's block hook) and
from Hermes's own board (cards blocked for him with no row, cards whose blocker
chain has stalled: actions/blocked.py attention, one read-only query), plus the
command approvals Hermes is asking right now in a chat (the live turn, in memory).
Deduped by card: a card with a row shows its row, never twice.

What persists is only what the owner did to an item: read, or dismissed (hidden
until the item changes: its key carries the item's stamp), in `inbox_marks`;
undo = the mark goes. The sidebar's badge counts AGOS's waiting rows not yet read
or dismissed, in one query, without the board.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db import inbox as inbox_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import now

MARKS = ("read", "dismissed")
TYPES = (
    "proposal",
    "question",
    "ask",
    "review",
    "blocked",
    "attention",
    "approval",
    "chain",
    "note",
    "mention",
    "held",
    "readiness",
    "founder",
)


def _marks(core: Core, workspace_id: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for key, mark in inbox_repo.marks(core.db, workspace_id):
        found.setdefault(key, set()).add(mark)
    return found


def items(core: Core, workspace_id: str, *, with_dismissed: bool = False) -> list[dict[str, Any]]:
    """Newest first; dismissed ones left out unless asked."""
    from agos_core.actions import blocked, kanban_asks, kanban_board, proposals, questions

    marks = _marks(core, workspace_id)
    out: list[dict[str, Any]] = []
    cards_seen: set[str] = set()

    def add(key: str, type_: str, card: str, title: str, who: str, at: Any, **data: Any) -> None:
        state = marks.get(key, set())
        if "dismissed" in state and not with_dismissed:
            return
        if card:
            cards_seen.add(card)
        out.append(
            {
                "key": key,
                "type": type_,
                "card": card,
                "title": title,
                "memberName": who,
                "createdAt": str(at or ""),
                "read": "read" in state,
                "dismissed": "dismissed" in state,
                **data,
            }
        )

    for p in proposals.waiting(core, workspace_id):
        add(
            f"ask:{p['id']}",
            "proposal",
            p["card"],
            p["label"],
            p["memberName"],
            p["createdAt"],
            proposal=p,
        )
    for q in questions.waiting(core, workspace_id):
        add(
            f"ask:{q['id']}",
            "question",
            q["card"],
            q["label"],
            q["memberName"],
            q["createdAt"],
            question=q,
        )
    for a in kanban_asks.waiting(core, workspace_id, 50):
        add(f"ask:{a['id']}", "ask", a["card"], a["label"], a["memberName"], a["createdAt"], ask=a)
    from agos_core.actions import reviews

    # A stage or a plan waiting at him, a card stuck in review (one board read).
    for r in reviews.inbox(core, workspace_id):
        add(r["key"], "review", r["card"], r["title"], r["member"], r["at"], review=r["review"])
    from agos_core.actions import founder

    # His own tasks (the Founder's cards on Hermes's board) that are his to do now,
    # with their Done; derived from the board, gone once Hermes has them done.
    me = founder.who(core, workspace_id)
    for t in founder.open_cards(core, workspace_id):
        if not t["canFinish"]:
            continue  # still waiting on other cards: not his yet
        add(
            f"founder:{t['id']}",
            "founder",
            t["id"],
            t["title"],
            me["shown"],
            _iso(t["createdAt"]),
            founder=t,
        )
    members = kanban_board._members(core, workspace_id)
    attention = blocked.attention(core, workspace_id)
    for card_id, state in sorted(attention.items(), key=lambda kv: -kv[1]["since"]):
        if card_id in cards_seen or state["state"] != "needs_attention":
            continue
        who = members.get(str(state.get("assignee") or ""), {}).get("title", "")
        type_ = (
            "blocked"
            if state.get("blockKind") == "needs_input" and not state.get("stalled")
            else "attention"
        )
        add(
            f"card:{card_id}:{int(state['since'])}",
            type_,
            card_id,
            state["title"],
            who,
            _iso(state["since"]),
            blocked={
                "reason": state["reason"],
                "state": state["state"],
                "stalled": bool(state.get("stalled")),
                "why": state["why"],
                "owner": state["owner"],
                "action": state["action"],
                "blockKind": state.get("blockKind", ""),
                "blockers": state["blockers"],
            },
        )
    from agos_core.actions import org

    # ONE item for every team a lead above it keeps from moving (actions/org.py),
    # derived from the profiles and the same board read as above.
    chain = org.inbox_item(
        org.health(core, workspace_id, org.stuck_from_attention(core, workspace_id, attention))
    )
    if chain is not None:
        add(chain["key"], "chain", "", chain["title"], "", now(), chain=chain)
    from agos_core.actions import threads

    # A comment that @mentions him, or one on a card at his own Review stage
    # (derived from Hermes's board; gone once he comments on the card after it).
    for m in threads.inbox_items(core, workspace_id):
        add(
            m["key"],
            "mention",
            m["card"],
            m["title"],
            m["who"],
            _iso(m["at"]),
            mention=m["mention"],
        )
    for n in inbox_repo.notes(core.db, workspace_id):
        add(
            f"note:{n['id']}",
            "note",
            "",
            str(n["title"]),
            "",
            str(n["created_at"]),
            note={"kind": str(n["kind"]), "detail": str(n["detail"])},
        )
    from agos_core.actions import held_writes

    # What an agent wants to remove or change in its memory / skills and Hermes
    # holds for him (its write_approval queue, read in Hermes; the same request
    # asked again is one item).
    try:
        held = held_writes.groups(core, workspace_id)
    except ActionError:
        held = []
    for g in held:
        add(
            f"held:{g['group']}",
            "held",
            "",
            g["title"],
            g["agent"],
            _iso(g["last_at"]),
            held={**g, "first_at": _iso(g["first_at"]), "last_at": _iso(g["last_at"])},
        )
    from agos_core.actions import hire_kit

    # Step 62: a new member that waits for him to be ready (connect, a key, a file,
    # a decision), or whose onboarding test failed every try (derived each read).
    for r in hire_kit.inbox_items(core, workspace_id):
        add(r["key"], "readiness", "", r["title"], r["memberName"], "", readiness=r["readiness"])
    for approval in _approvals(core, workspace_id):
        add(
            approval["key"],
            "approval",
            "",
            approval["title"],
            approval["memberName"],
            approval["createdAt"],
            approval=approval,
        )
    out.sort(key=_newest, reverse=True)
    return out


def _newest(item: dict[str, Any]) -> tuple[str, int]:
    """Newest first; rows made in the same instant by their id."""
    key = str(item["key"])
    row_id = int(key[4:]) if key.startswith("ask:") and key[4:].isdigit() else 0
    return (str(item["createdAt"]), row_id)


def _iso(epoch: float) -> str:
    from datetime import UTC, datetime

    if not epoch:
        return ""
    return (
        datetime.fromtimestamp(float(epoch), UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _approvals(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Hermes's Allow / Deny cards waiting in this workspace's chats right now (the
    live turns in this process); the Inbox links to the chat, the answer is there."""
    from agos_core.actions import chat as chat_actions
    from agos_core.actions import voice

    found: list[dict[str, Any]] = []
    for turn_id, live in list(chat_actions._registry(core).items()):
        if live.turn.status != "waiting":
            continue
        turn = chats_repo.get_turn(core.db, turn_id)
        if turn is None or turn.workspace_id != workspace_id:
            continue
        row = chats_repo.any_row(core.db, turn.chat_id)
        for item in live.turn.activity:
            if item.kind == "approval" and item.status == "waiting":
                found.append(
                    {
                        "key": f"approval:{turn_id}:{item.id}",
                        "chatId": int(turn.chat_id),
                        "title": item.title,
                        "detail": item.detail or "",
                        "memberName": voice.name_of(
                            core, workspace_id, str(row["agent"] or "") or None if row else None
                        ),
                        "createdAt": now(),
                    }
                )
    return found


def count(core: Core, workspace_id: str) -> int:
    """The sidebar's badge: AGOS's waiting rows the owner hasn't read or dismissed
    (one query; the derived board items are not counted: they need the board),
    plus the memory / skill changes Hermes holds for him (held_writes.waiting:
    a file check, Hermes asked only while one is held, its read cached)."""
    asks = inbox_repo.unread_asks(core.db, workspace_id)
    notes = inbox_repo.unread_notes(core.db, workspace_id)
    from agos_core.actions import held_writes

    held = held_writes.waiting(core, workspace_id)
    return asks + notes + held


def mark(core: Core, workspace_id: str, key: str, which: str) -> None:
    """Read (seen) or dismissed (hidden until the item changes)."""
    if which not in MARKS:
        raise ActionError("Mark an item read or dismissed.")
    if not key or len(key) > 160:
        raise ActionError("Unknown Inbox item.")
    with transaction(core.db):
        inbox_repo.add_mark(core.db, workspace_id, key, which)


def unmark(core: Core, workspace_id: str, key: str, which: str) -> bool:
    """Undo of a read or a dismiss. True when there was one."""
    if which not in MARKS:
        raise ActionError("Mark an item read or dismissed.")
    with transaction(core.db):
        return inbox_repo.drop_mark(core.db, workspace_id, key, which)


def sweep(core: Core, workspace_id: str) -> int:
    """Marks of asks that ended (decided, answered) are of no use: dropped. Keys are
    read back from the rows, never built."""
    with transaction(core.db):
        return inbox_repo.drop_marks_of_ended_asks(core.db, workspace_id)


def note(core: Core, workspace_id: str, kind: str, title: str, detail: str = "") -> int:
    """A note AGOS leaves the owner about his team (read / dismissed like any item)."""
    with transaction(core.db):
        return inbox_repo.add_note(core.db, workspace_id, kind[:40], title[:300], detail[:2000])
