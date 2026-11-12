"""A card's thread (Step 58, F18): comments on Hermes's board and whom they wake.

The comments are Hermes's (`hermes kanban comment` for the owner, the agents' own
`kanban_comment` tool); AGOS keeps no copy. What AGOS adds is the wake rule of
engine/threads.py, carried out through Hermes's own paths:

- the card's assignee (in Review: the reviewer, Hermes's assignee there) and nobody
  else of the team. A running worker gets the comment from Hermes itself (it steers
  new comments into the live turn); the owner's answer to a card's question unblocks
  it (`kanban unblock`: Hermes's dispatcher starts the assignee, the comment in its
  context); a Ready card is started by the dispatcher anyway; a card held on purpose
  reads it when it starts. The owner's own stage in Review lands in his Inbox;
- `@member`: the member follows the card from now on (Hermes's notify subscription
  of its card conversation, `--delivery-mode wake`: Hermes's notifier wakes it when
  the card ends, blocks or asks for review) and is woken once with the comment (a
  message in that conversation, the agos platform's inbound queue: Hermes's own
  turn). The card is never reassigned;
- `@owner`: the comment is an item in his Inbox (`inbox_items`, derived from the
  board; read / dismissed like any item);
- card ids (`t_a5ba7050`): reference chips (`refs`).

An agent's comment reaches AGOS from the agos-guard plugin's `post_tool_call` hook
(hermes_plugin/agos_guard/threads.py): AGOS reads the comment back from Hermes's
board by its id (author included: Hermes's own identity of the run, never the
agent's words) and acts once per comment (`threads.seen.<ws>`).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import kanban_cli
from agos_core.context import Core
from agos_core.db import chats as chats_repo
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.connection import transaction
from agos_core.engine import threads as rules
from agos_core.hermes_gateway import kanban_rows

log = logging.getLogger("agos.threads")

SEEN = "threads.seen.{}"
SEEN_KEEP = 300
OWNER_AUTHORS = ("owner", "user", "")


# ---- who is who --------------------------------------------------------------------


def _people(core: Core, workspace_id: str) -> tuple[dict[str, dict[str, str]], str]:
    """Profile → {name, title} (the Co-Founder as `cofounder`), and its profile."""
    from agos_core.actions import kanban_board

    members = kanban_board._members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""
    return members, cofounder


def _name_of(profile: str, members: dict[str, dict[str, str]]) -> str:
    """A card's assignee / a comment's author as a name: a member's, `cofounder`,
    `owner` (his stage in Review, or what he wrote) or the raw value."""
    if profile in OWNER_AUTHORS:
        return rules.OWNER
    found = members.get(profile)
    return found["name"] if found else profile


def _title_of(name: str, members: dict[str, dict[str, str]]) -> str:
    if name == rules.OWNER:
        return "You"
    for m in members.values():
        if m["name"] == name:
            return m["title"]
    return name


def _handles(members: dict[str, dict[str, str]]) -> list[str]:
    return [m["name"] for m in members.values()]


# ---- the owner's comment ----------------------------------------------------------


def comment(
    core: Core, workspace_id: str, card_id: str, text: str, *, resume: bool = False
) -> dict[str, Any]:
    """His comment on the card (Hermes's `kanban comment`), then whom it wakes."""
    from agos_core.actions import kanban_board

    words = text.strip()
    if not words:
        raise ActionError("Write something first.")
    raw, extra = kanban_board._shown(core, workspace_id, card_id)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    members, _cofounder = _people(core, workspace_id)
    status = str(task.get("status") or "")
    block_kind = str(extra.get("block_kind") or task.get("block_kind") or "")
    reason = kanban_board._question(raw) if status == "blocked" else ""
    kanban_cli.run(core, workspace_id, "comment", card_id, words, "--author", kanban_board.OWNER)
    plan = rules.wake_plan(
        status=status,
        assignee=_name_of(str(task.get("assignee") or ""), members) if task.get("assignee") else "",
        author=rules.OWNER,
        mentioned=rules.mentions(words, _handles(members)),
        block_kind=block_kind,
        owner_answer=not reason.startswith(kanban_board.OWNER_OK),
        resume=resume,
    )
    return {"woke": _carry_out(core, workspace_id, card_id, task, plan, "You", words, members)}


# ---- an agent's comment (the plugin's hook) ----------------------------------------


def agent_commented(core: Core, workspace_id: str, card_id: str, comment_id: int) -> dict[str, Any]:
    """An agent's kanban_comment landed: read it back from Hermes's board and wake
    whom it names, once per comment."""
    from agos_core.actions import kanban_board

    seen_key = SEEN.format(workspace_id)
    seen = get_setting(core.db, seen_key, [])
    seen = [int(s) for s in seen if isinstance(s, int)] if isinstance(seen, list) else []
    if comment_id in seen:
        return {"woke": [], "again": True}
    raw, _extra = kanban_board._shown(core, workspace_id, card_id)
    task = raw.get("task") if isinstance(raw, dict) else None
    if not isinstance(task, dict):
        raise NotFoundError("This card")
    found = next(
        (
            c
            for c in raw.get("comments") or []
            if isinstance(c, dict) and int(c.get("id") or 0) == comment_id
        ),
        None,
    )
    if found is None:
        raise NotFoundError("This comment")
    members, _cofounder = _people(core, workspace_id)
    author = _name_of(str(found.get("author") or ""), members)
    with transaction(core.db):
        set_setting(core.db, seen_key, [*seen, comment_id][-SEEN_KEEP:])
    if author == rules.OWNER:
        return {"woke": []}  # his own comments are acted on where he writes them
    body = str(found.get("body") or "")
    plan = rules.wake_plan(
        status=str(task.get("status") or ""),
        assignee=_name_of(str(task.get("assignee") or ""), members) if task.get("assignee") else "",
        author=author,
        mentioned=rules.mentions(body, _handles(members)),
    )
    return {
        "woke": _carry_out(
            core, workspace_id, card_id, task, plan, _title_of(author, members), body, members
        )
    }


def _carry_out(
    core: Core,
    workspace_id: str,
    card_id: str,
    task: dict[str, Any],
    plan: list[rules.Wake],
    by: str,
    text: str,
    members: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    """Each wake through Hermes's path (steer / dispatch / review / waits are Hermes's
    own and need nothing here; inbox items are derived from the board)."""

    out: list[dict[str, str]] = []
    for wake in plan:
        if wake.how == "unblock":
            kanban_cli.run(core, workspace_id, "unblock", card_id)
        elif wake.how == "mention":
            try:
                mention(
                    core, workspace_id, card_id, str(task.get("title") or ""), wake.who, by, text
                )
            except ActionError as error:
                log.info("mention of %s on %s not delivered: %s", wake.who, card_id, error)
                continue
        out.append(
            {
                "who": wake.who,
                "title": _title_of(wake.who, members),
                "how": wake.how,
                "why": wake.why,
                "said": rules.HOW[wake.how],
            }
        )
    return out


# ---- @member: watch + one wake ------------------------------------------------------


def _thread_chat(core: Core, workspace_id: str, card_id: str, who: str) -> int:
    """The conversation a member hears this card in: its own chat about the card
    (made once; the same as the card's Chat tab when it is the assignee), and the
    Co-Founder's own chat for the Co-Founder."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.services.channel import owner_needs

    if who == rules.COFOUNDER:
        chat = owner_needs.ensure_cofounder_chat(core, workspace_id)
        if chat is None:
            raise ActionError("The Co-Founder has no chat yet.")
        return int(chat)
    if who not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Pick a member of this workspace's team.")
    found = chats_repo.member_card_chat(core.db, workspace_id, card_id, who)
    if found is not None:
        return found
    with transaction(core.db):
        return chats_repo.add_member_card_chat(core.db, workspace_id, card_id, who)


def _target(core: Core, workspace_id: str, who: str, chat: int) -> dict[str, str]:
    """Hermes's notify-subscribe destination of that conversation."""
    from agos_core.actions.services.channel import owner_needs

    if who == rules.COFOUNDER:
        found = owner_needs.kanban_notify_target(core, workspace_id)
        if found is not None:
            return found
    return {"platform": "agos", "chatId": str(chat), "chatType": "dm", "userId": "owner"}


def _subscribe(core: Core, workspace_id: str, card_id: str, target: dict[str, str]) -> None:

    args = [
        "notify-subscribe",
        card_id,
        "--platform",
        target["platform"],
        "--chat-id",
        target["chatId"],
        "--chat-type",
        target.get("chatType") or "dm",
        "--delivery-mode",
        "wake",
    ]
    if target.get("threadId"):
        args += ["--thread-id", target["threadId"]]
    if target.get("userId"):
        args += ["--user-id", target["userId"]]
    if core.engine is not None:
        # The workspace's one gateway delivers it (it serves every member).
        args += ["--notifier-profile", core.engine.hermes_name(workspace_id)]
    kanban_cli.run(core, workspace_id, *args)


def mention(
    core: Core, workspace_id: str, card_id: str, title: str, who: str, by: str, text: str
) -> None:
    """@member: follows the card (Hermes's subscription) and is woken once with the
    comment in its own conversation about the card. Never reassigned."""
    from agos_core.actions import hermes_channel

    chat = _thread_chat(core, workspace_id, card_id, who)
    _subscribe(core, workspace_id, card_id, _target(core, workspace_id, who, chat))
    note = (
        f"(AGOS) {by} mentioned you in a comment on card {card_id} “{title}”:\n\n"
        + "\n".join(f"> {line}" for line in text.strip().splitlines())
        + "\n\nYou follow this card now: you are told when it ends, blocks or asks "
        "for review. It is not assigned to you: read it with kanban_show, answer on the "
        "card with kanban_comment if you have something to add, and do only what is "
        "asked of you."
    )
    with transaction(core.db):
        hermes_channel.hand_over(core, workspace_id, chat, note)


# ---- watchers ------------------------------------------------------------------------


def _subs(core: Core, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
    """Hermes's notify subscriptions of the card, read from its board database (read
    only; what `hermes kanban notify-list` prints). No board yet: none."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.notify_subs(card_id)
    except sqlite3.Error:
        return []
    return [
        {"platform": p, "chat_id": c, "thread_id": t, "delivery_mode": m} for p, c, t, m in rows
    ]


def watchers(core: Core, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
    """Who follows the card (Hermes's subscriptions), as people. Read only: a
    Telegram subscription is the Co-Founder's (the only one AGOS or Hermes makes
    there: the bridge's notify target, or the chat a card was made in)."""
    members, _cofounder = _people(core, workspace_id)
    out: list[dict[str, Any]] = []
    for sub in _subs(core, workspace_id, card_id):
        platform, chat = str(sub.get("platform") or ""), str(sub.get("chat_id") or "")
        name, kind = "", "chat"
        if platform == "telegram":
            name = rules.COFOUNDER
        elif platform == "agos" and chat.isdigit():
            row = chats_repo.in_workspace(core.db, workspace_id, int(chat))
            if row is None:
                continue
            name = str(row["agent"] or "") or (rules.COFOUNDER if row["kind"] == "dm" else "")
        if name:
            kind = "member"
        if any(w["name"] == name and name for w in out):
            continue
        out.append(
            {
                "name": name,
                "title": _title_of(name, members) if name else f"{platform} chat",
                "kind": kind,
                "mode": str(sub.get("delivery_mode") or "notify"),
                "platform": platform,
                "chat": chat,
                "thread": str(sub.get("thread_id") or ""),
            }
        )
    return out


def watch(core: Core, workspace_id: str, card_id: str, who: str) -> list[dict[str, Any]]:
    """The owner adds a member (or the Co-Founder) as a watcher: subscribed, not woken."""
    chat = _thread_chat(core, workspace_id, card_id, who)
    _subscribe(core, workspace_id, card_id, _target(core, workspace_id, who, chat))
    return watchers(core, workspace_id, card_id)


def unwatch(core: Core, workspace_id: str, card_id: str, who: str) -> list[dict[str, Any]]:

    for w in watchers(core, workspace_id, card_id):
        if w["name"] == who:
            kanban_cli.run(
                core,
                workspace_id,
                "notify-unsubscribe",
                card_id,
                "--platform",
                str(w["platform"]),
                "--chat-id",
                str(w["chat"]),
                *(["--thread-id", str(w["thread"])] if w["thread"] else []),
            )
    return watchers(core, workspace_id, card_id)


# ---- reference chips -------------------------------------------------------------


def refs(core: Core, workspace_id: str, texts: list[str], own: str = "") -> list[dict[str, str]]:
    """The cards these texts name (`t_…`), as chips: title and status (one read of
    the board as listed; a card that isn't on it is left out)."""
    from agos_core.actions import kanban_board

    wanted: list[str] = []
    for text in texts:
        for card in rules.card_refs(text, own):
            if card not in wanted:
                wanted.append(card)
    if not wanted:
        return []
    found = kanban_board.facts(core, workspace_id, wanted)
    if not found:
        try:
            listed = kanban_board._listed(core, workspace_id)
        except ActionError:
            listed = []
        found = {
            str(c.get("id")): {
                "status": str(c.get("status") or ""),
                "title": str(c.get("title") or ""),
            }
            for c in listed
            if isinstance(c, dict) and str(c.get("id")) in wanted
        }
    labels = {c["status"]: c["label"] for c in kanban_board.columns(core)}
    return [
        {
            "id": card,
            "title": found[card]["title"],
            "status": found[card]["status"],
            "statusLabel": labels.get(found[card]["status"], found[card]["status"]),
        }
        for card in wanted
        if card in found
    ]


# ---- the owner's Inbox: mentions of him -------------------------------------------


def inbox_items(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Comments that wait for the owner (derived from Hermes's board, read only): an
    agent's comment that @mentions him, or one on a card in Review at his own stage.
    Gone once he commented on that card after it."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    board_db = agent_profiles.board_db(core, workspace_id)
    if not board_db.is_file():
        return []
    try:
        with kanban_rows.opened(board_db) as board:
            rows = board.for_owner()
    except sqlite3.Error:
        return []
    members, _cofounder = _people(core, workspace_id)
    out: list[dict[str, Any]] = []
    for cid, card, author, body, at, title, status, assignee in rows:
        text = str(body or "")
        if text.startswith(("[agos-review", "[agos-plan", "CHANGES REQUESTED: [agos-")):
            continue  # a review step: the Inbox's review item already shows it
        named = rules.OWNER in rules.mentions(text, [])
        at_owner = status == "review" and assignee == rules.OWNER
        if not (named or at_owner):
            continue
        who = _name_of(str(author or ""), members)
        out.append(
            {
                "key": f"mention:{int(cid)}",
                "card": str(card),
                "title": str(title or ""),
                "who": _title_of(who, members),
                "at": int(at or 0),
                "mention": {
                    "commentId": int(cid),
                    "body": text[:2000],
                    "reason": "mention" if named else "review",
                },
            }
        )
    return out
