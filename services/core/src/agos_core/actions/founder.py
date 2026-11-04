"""The Founder: the owner himself (a person, not an agent) as a box beside the
Co-Founder, and the tasks only a human can do (record, pay, sign, call, log in).

Hermes is the engine of it, nothing is copied:
- a Founder task is a card on the workspace's own Hermes board assigned to
  `founder`, a name no Hermes profile has and that is never in the root's
  `kanban.dispatch_profiles` (actions/agent_profiles.py dispatch_list). Hermes's
  dispatcher never spawns a worker for it, never claims it, so it is never
  reclaimed or flagged stale: it records `skipped_nonspawnable` once and leaves it
  in `ready` ("non-spawnable assignee — terminal lane, OK", hermes_cli/
  kanban_db_dispatch.py _dispatch_lane_task, hermes_cli/kanban_ops.py). Like the
  owner's review stage (engine/reviews.py OWNER).
- who may give him one: the Co-Founder (Hermes's own kanban_create with assignee
  `founder`, or its agos_action assign_founder) and the owner himself (the Board).
  A member never can: kanban_create is the Co-Founder's tool (agos_guard
  COFOUNDER_TOOLS), every AGOS path that assigns refuses `founder` unless it says
  it is the owner's or the Co-Founder's (kanban_board._profile_of), and the guard
  refuses a member's terminal `hermes kanban` that names him (agos_guard
  founder_refused). A member that needs the human asks its lead / agos_ask_owner.
- he is told in his Inbox (derived from the board, inbox.items) and on Telegram
  (the Co-Founder's chat, owner_needs.push, once per card: the outbox's own
  (connection, address, source) key), when the card is ready for him.
- Done (Inbox, the card, Today, the Hierarchy box, the phone's button, or the
  Co-Founder when he says so) is Hermes's own `kanban complete`: Hermes promotes
  the cards that wait on it and the pipeline rules see the move.

AGOS keeps only his box's words: his name (Settings → General, app_settings
`owner.name`, one for all workspaces; default his account's name) and the title
under it per workspace (`founder.<workspace>`, default 'Founder').
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.hermes_gateway import board_reads, hermes_db

log = logging.getLogger("agos.founder")

FOUNDER = "founder"  # the card's Hermes assignee: no profile has it, never dispatched
SETTING = "founder.{}"  # the title under his name, per workspace
NAME_KEY = "owner.name"  # his name, one for every workspace (Settings → General)
DEFAULT_TITLE = "Founder"
TITLE_MAX = 64
OPEN = ("triage", "todo", "ready", "running", "blocked", "review", "scheduled")
ACTIONABLE = ("ready", "blocked", "review", "running")  # Hermes completes these
DONE_SHOWN = 20
BUTTON = "fdone:"  # the phone's Done button (actions/channels.py button)
NOTE = (
    "This is the Founder's own task (the owner, a person): no agent works it. He marks "
    "it Done in AGOS (Inbox, Today, the card) or tells the Co-Founder, and the cards "
    "that wait on it go on."
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


# ---- his box ------------------------------------------------------------------------------


def owner_name(core: Core) -> str:
    """His name as he set it in Settings → General (one for every workspace), else "".
    A plain setting: AGOS has one user and no accounts."""
    return str(get_setting(core.db, NAME_KEY, "") or "").strip()


def save_owner_name(core: Core, name: str) -> str:
    """Settings → General → Your name ("" = no name: his box shows his title)."""
    set_setting(core.db, NAME_KEY, " ".join(name.split())[:TITLE_MAX])
    return owner_name(core)


def who(core: Core, workspace_id: str) -> dict[str, str]:
    """His box's words: {name, title, shown}. The name is his (Settings → General);
    the title the one he gave himself in this workspace (default 'Founder'); `shown`
    what a card's member slot, the filters and his notices say (his name, else the
    title)."""
    saved = get_setting(core.db, SETTING.format(workspace_id), {})
    saved = saved if isinstance(saved, dict) else {}
    title = str(saved.get("title") or "").strip() or DEFAULT_TITLE
    name = owner_name(core)
    return {"name": name, "title": title, "shown": name or title}


def save_who(core: Core, workspace_id: str, title: str) -> dict[str, str]:
    """The title under his name on the Hierarchy box ("" = 'Founder')."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    clean_title = " ".join(title.split())[:TITLE_MAX]
    set_setting(core.db, SETTING.format(workspace_id), {"title": clean_title or DEFAULT_TITLE})
    return who(core, workspace_id)


def member_entry(core: Core, workspace_id: str) -> dict[str, str]:
    """How the Board shows him as a card's member (filters, group-by, the modal)."""
    return {"name": FOUNDER, "title": who(core, workspace_id)["shown"]}


# ---- his cards (read from Hermes's board) -------------------------------------------------


def _rows(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Every card assigned to him on this workspace's board (rows_of)."""
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return []
    return rows_of(agent_profiles.board_db(core, workspace_id))


def rows_of(board_db: Path) -> list[dict[str, Any]]:
    """Every card assigned to him (archived left out), with the cards it waits on and
    the ones that wait on it: read-only queries of Hermes's board database (its
    tasks / task_links tables, hermes_cli/kanban_db.py). [] when there is none."""
    if not board_db.is_file():
        return []
    try:
        with contextlib.closing(hermes_db.connect_ro(board_db, timeout=2)) as db:
            rows = board_reads.assigned(db, FOUNDER)
            links = board_reads.links_of(db, [str(r[0]) for r in rows])
    except sqlite3.Error:
        return []
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    for parent, child in links:
        parents.setdefault(str(child), []).append(str(parent))
        children.setdefault(str(parent), []).append(str(child))
    return [
        {
            "id": str(i),
            "title": str(t or ""),
            "body": str(b or ""),
            "status": str(s or ""),
            "createdAt": int(c or 0),
            "completedAt": int(d) if d else None,
            "createdBy": str(by or ""),
            "result": str(r or ""),
            "waitsOn": parents.get(str(i), []),
            "unblocks": children.get(str(i), []),
        }
        for i, t, b, s, c, d, by, r in rows
    ]


def _shown(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "status": row["status"],
        "createdAt": row["createdAt"],
        "completedAt": row["completedAt"],
        "waitsOn": row["waitsOn"],
        "unblocks": row["unblocks"],
        # Done is Hermes's complete: a card still waiting on its parents (todo) can't.
        "canFinish": row["status"] in ACTIONABLE,
    }


def open_cards(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    rows = [r for r in _rows(core, workspace_id) if r["status"] in OPEN]
    return [_shown(r) for r in sorted(rows, key=lambda r: (r["createdAt"], r["id"]))]


def view(core: Core, workspace_id: str) -> dict[str, Any]:
    """His box: who he is, his open tasks (oldest first) and the last done ones."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    rows = _rows(core, workspace_id)
    done = sorted(
        (r for r in rows if r["status"] == "done"),
        key=lambda r: (r["completedAt"] or 0, r["id"]),
        reverse=True,
    )[:DONE_SHOWN]
    shown_open = open_cards(core, workspace_id)
    return {
        **who(core, workspace_id),
        "open": shown_open,
        "done": [_shown(r) for r in done],
        "openCount": len(shown_open),
    }


def is_his(core: Core, workspace_id: str, card_id: str) -> bool:
    return any(r["id"] == card_id for r in _rows(core, workspace_id))


# ---- giving him a task ---------------------------------------------------------------------


def body_of(what: str, due: str = "", unblocks: list[str] | None = None) -> str:
    """The card's words: what to do, by when, which cards wait on it, the note."""
    parts = [what.strip()]
    if due.strip():
        parts.append(f"By: {due.strip()[:120]}")
    if unblocks:
        parts.append("Unblocks: " + ", ".join(unblocks))
    parts.append(NOTE)
    return "\n\n".join(p for p in parts if p)


def assign(
    core: Core,
    workspace_id: str,
    title: str,
    what: str = "",
    *,
    due: str = "",
    unblocks: list[str] | None = None,
    parents: list[str] | None = None,
    by: str = "owner",
    once: str = "",
) -> str:
    """A task for him on Hermes's board (the Co-Founder's agos_action assign_founder,
    or the owner's own): a card assigned to `founder`; the cards it `unblocks` wait on
    it (Hermes's link, parent -> child). He is told at once. Returns the card id."""
    from agos_core.actions import kanban_board

    for card in [*(unblocks or []), *(parents or [])]:
        if not _ID.fullmatch(card):
            raise ActionError("Unknown card to link.")
    created_by = (
        kanban_board._profile_of(core, workspace_id, kanban_board.COFOUNDER)
        if by == kanban_board.COFOUNDER
        else kanban_board.OWNER
    )
    card_id = kanban_board.create(
        core,
        workspace_id,
        title,
        body_of(what, due, unblocks),
        FOUNDER,
        parents=parents,
        once=once,
        created_by=created_by,
        founder=True,
    )
    for child in unblocks or []:
        kanban_board._cli(core, workspace_id, "link", card_id, child)
    tell(core, workspace_id)
    return card_id


# ---- telling him ---------------------------------------------------------------------------


def _phone_text(core: Core, workspace_id: str, row: dict[str, Any]) -> str:
    body = str(row["body"]).replace(NOTE, "").strip()
    me = who(core, workspace_id)
    lines = [f"🙋 **For you, {me['shown']}**: {row['title']}"]
    if body:
        lines.append(body[:1500])
    if row["unblocks"]:
        lines.append(f"It unblocks {', '.join(row['unblocks'][:5])}.")
    lines.append("Press Done when it's done, or tell the Co-Founder.")
    return "\n".join(lines)


def tell(core: Core, workspace_id: str) -> int:
    """Each of his cards that is ready for him reaches his phone once (the Co-Founder's
    chat, with a Done button): the outbox keeps one row per card. His Inbox reads the
    board itself. Run when a card is given and on each dispatcher tick (a card whose
    parents just finished is his now). Returns how many were queued now."""
    from agos_core.actions.services.channel import owner_needs

    sent = 0
    for row in _rows(core, workspace_id):
        if row["status"] not in ACTIONABLE:
            continue
        sent += owner_needs.push(
            core,
            workspace_id,
            _phone_text(core, workspace_id, row),
            f"founder:{row['id']}",
            buttons=[("Done", f"{BUTTON}{row['id']}")],
            chat_id=owner_needs.cofounder_chat(core, workspace_id),
        )
    return sent


def sweep(core: Core, workspace_id: str) -> int:
    """The dispatcher ticked (or a card moved): what is newly his is told."""
    try:
        return tell(core, workspace_id)
    except (ActionError, sqlite3.Error) as error:
        log.info("founder cards of %s not told: %s", workspace_id, error)
        return 0


# ---- done ----------------------------------------------------------------------------------


def done(core: Core, workspace_id: str, card_id: str, note: str = "", *, by: str = "owner") -> bool:
    """He finished it: Hermes's own complete (it promotes the cards that wait on it),
    then the pipeline rules look. False when it was done already."""
    from agos_core.actions import kanban_board
    from agos_core.engine import doorbell

    if not _ID.fullmatch(card_id):
        raise NotFoundError("This task")
    row = next((r for r in _rows(core, workspace_id) if r["id"] == card_id), None)
    if row is None:
        raise NotFoundError("This task of yours")
    if row["status"] == "done":
        return False
    if row["status"] not in ACTIONABLE:
        raise ActionError(
            "It still waits on other cards (" + ", ".join(row["waitsOn"][:5]) + "): "
            "Done once they are finished.",
            409,
        )
    said = "Done by the founder" + (" (he told the Co-Founder)" if by == "cofounder" else "")
    words = f"{said}: {note.strip()}" if note.strip() else f"{said}."
    kanban_board._cli(core, workspace_id, *kanban_board.complete_args(card_id, words[:4000]))
    kanban_board._moved(core, workspace_id, card_id)
    doorbell.ring(doorbell.SEND)  # its card on his phone loses its button
    return True


def button(core: Core, workspaces: set[str], card_id: str) -> str:
    """His Done on the phone (the workspaces of the chat he pressed it in)."""
    for ws in sorted(workspaces):
        if not is_his(core, ws, card_id):
            continue
        try:
            return (
                "Done: the cards waiting on it go on."
                if done(core, ws, card_id)
                else ("Already done.")
            )
        except ActionError as error:
            return error.message
    return "That task is gone."


# ---- for the Co-Founder --------------------------------------------------------------------


def prompt_name(core: Core, workspace_id: str) -> str:
    """Who the Founder is, for the Co-Founder's prompt."""
    me = who(core, workspace_id)
    return f"{me['name']} ({me['title']})" if me["name"] else me["title"]


def lines(core: Core, workspace_id: str) -> list[tuple[str, str, str]]:
    """His open tasks for the Co-Founder's prompt: (card, title, status)."""
    try:
        return [(c["id"], c["title"], c["status"]) for c in open_cards(core, workspace_id)]
    except (ActionError, NotFoundError):
        return []
