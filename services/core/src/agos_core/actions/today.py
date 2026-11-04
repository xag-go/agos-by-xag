"""Today on the Vision page, and the Co-Founder's daily posts (Step 53).

- The daily plan is a proposal (kind 'goal', change 'daily_plan': a Hermes card
  blocked for the owner, actions/proposals.py): what the OWNER does today (`you`)
  and what each member does (`members`). In his Inbox and on Telegram: Accept /
  Change (a note: the Co-Founder proposes again) / Skip. One accepted plan per day.
- Accept creates today's cards on Hermes's board, each with the idempotency key
  `agos-today:<date>:<n>` (a replayed accept returns the same card, Hermes's own
  dedup): a member's card is assigned to it and starts with its project's
  '## Goal' line; the owner's items are his Founder tasks: cards assigned to
  `founder` (actions/founder.py: Hermes's dispatcher never spawns a worker for
  it), his 'You' list, so the Board shows them as his. Ticking one is the
  Founder's Done. Plans accepted before this hold unassigned cards (Hermes's
  dispatcher never runs an unassigned card either): they still list and tick.
- Nothing of it is a copy: the Today column is read from the board by that key
  (the same board read as the rest of the Vision page), the plan from its ask row.
- His Founder tasks (cards assigned to `founder`, actions/founder.py: what only a
  person can do, given by the Co-Founder) are in his You list too while they are
  open, from the same board read; ticking one is the Founder's Done.
- The evening recap and the weekly review are the Co-Founder's posts (agos_goals
  action post): one Inbox note each (informational) and a message in the
  Co-Founder's chat on Telegram, the way its asks are posted.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import inbox as inbox_repo
from agos_core.db import kanban_asks as asks_repo
from agos_core.db.connection import transaction

log = logging.getLogger("agos.today")

KEY = "agos-today:"
POSTS = ("recap", "weekly")
POST_MAX = 2000  # inbox_notes' detail (actions/inbox.py note)
OWNER_NOTE = "This is the owner's own item for today (his You list): no agent works it."


def date_today(core: Core | None = None) -> str:
    """Today's date on the owner's clock, the one Hermes's cron runs the daily jobs
    on: Hermes's `timezone` (Settings → General), else this server's local time."""
    from agos_core.actions import owner_time

    zone = owner_time.zone_of(owner_time.owner_zone(core)) if core is not None else None
    now = datetime.now(zone) if zone is not None else datetime.now().astimezone()
    return now.date().isoformat()


def key(date: str, n: int) -> str:
    return f"{KEY}{date}:{n}"


# ---- the plan's ask rows ------------------------------------------------------------


def _plans(core: Core, workspace_id: str, date: str) -> list[Any]:
    """The daily-plan proposals for `date`, newest first."""
    return asks_repo.daily_plans(core.db, workspace_id, date)


def plan_problems(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """What keeps a daily plan from being made or accepted (its shape: engine/proposals.py)."""
    from agos_core.actions import agent_profiles, goals
    from agos_core.actions.kanban_board import COFOUNDER

    out: list[str] = []
    names = set(agent_profiles.team_names(core, workspace_id)) | {COFOUNDER}
    for item in payload.get("members") or []:
        if item.get("member") and item["member"] not in names:
            out.append(f"members: there is no member named {item['member']} in this workspace")
    known = {g.id for g in goals.rows(core, workspace_id) if g.parent_id is not None}
    for item in [*(payload.get("members") or []), *(payload.get("you") or [])]:
        if item.get("project_id") and item["project_id"] not in known:
            out.append(f"project_id {item['project_id']} is not a goal or project here")
    date = str(payload.get("date") or "")
    if date and any(str(r["status"]) == "approved" for r in _plans(core, workspace_id, date)):
        out.append(
            f"the plan for {date} is accepted already: propose single changes or cards instead"
        )
    return out


def accept(core: Core, workspace_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The owner accepted the plan (as proposed or as he edited it): today's cards,
    on Hermes's board. Replayable: each card's idempotency key makes a second accept
    of the same plan return the same cards."""
    from agos_core.actions import goals, kanban_board

    date = str(payload.get("date") or "")
    known = {g.id for g in goals.rows(core, workspace_id) if g.parent_id is not None}
    made: list[str] = []
    mine: list[str] = []
    n = 0
    for item in payload.get("members") or []:
        project = item.get("project_id") if item.get("project_id") in known else None
        made.append(
            kanban_board.create(
                core,
                workspace_id,
                str(item["title"]),
                str(item.get("body") or ""),
                str(item.get("member") or ""),
                once=key(date, n),
                goal_id=project,
            )
        )
        n += 1
    from agos_core.actions import founder

    for item in payload.get("you") or []:
        project = item.get("project_id") if item.get("project_id") in known else None
        body = "\n\n".join(p for p in (str(item.get("why") or ""), OWNER_NOTE) if p)
        mine.append(
            kanban_board.create(
                core,
                workspace_id,
                str(item["title"]),
                body,
                founder.FOUNDER,  # his own: the Board shows it as the Founder's
                once=key(date, n),
                goal_id=project,
                founder=True,  # the owner accepted it: he gives it to himself
            )
        )
        n += 1
    if mine:
        founder.sweep(core, workspace_id)  # his phone gets each with its Done button
    return {"date": date, "cards": made, "you": mine}


# ---- the Today column ---------------------------------------------------------------


def _plan_view(row: Any) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload"] or "{}")
    except ValueError:
        payload = {}
    return {
        "askId": int(row["id"]),
        "card": str(row["card"]),
        "status": str(row["status"]),
        "summary": str(payload.get("summary") or ""),
        "note": row["note"],
    }


def _order(task: dict[str, Any]) -> int:
    tail = str(task["key"]).rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def view(
    core: Core, workspace_id: str, tasks: list[dict[str, Any]], team: dict[str, Any]
) -> dict[str, Any]:
    """Today's column: the plan's state, each member's cards of today's plan and the
    owner's own list. `tasks`: the Vision page's one board read."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.kanban_board import COFOUNDER
    from agos_core.engine import goals as rules

    date = date_today(core)
    prefix = f"{KEY}{date}:"
    profile_of: dict[str, tuple[str, str]] = {}
    if core.engine is not None:
        profile_of[core.engine.hermes_name(workspace_id)] = (COFOUNDER, "Co-Founder")
        for name, person in team.items():
            profile_of[core.engine.hermes_name(agent_profiles.key(workspace_id, name))] = (
                name,
                str(getattr(person, "title", "") or name),
            )
    from agos_core.actions import founder

    members: dict[str, dict[str, Any]] = {}
    you: list[dict[str, Any]] = []
    for t in sorted((t for t in tasks if t["key"].startswith(prefix)), key=_order):
        # The goal or project it serves (its body's '## Goal' line): the page shows
        # the project and the goal it moves.
        card = {
            "id": t["id"],
            "title": t["title"],
            "status": t["status"],
            "goalId": rules.card_goal(t["body"]),
        }
        if not t["assignee"] or t["assignee"] == founder.FOUNDER:  # his own item
            you.append({**card, "done": t["status"] == "done"})
            continue
        name, title = profile_of.get(t["assignee"], (t["assignee"], t["assignee"]))
        members.setdefault(name, {"member": name, "title": title, "cards": []})["cards"].append(
            card
        )
    for t in sorted(
        (
            t
            for t in tasks
            if t["assignee"] == founder.FOUNDER
            and t["status"] in founder.OPEN
            and not t["key"].startswith(prefix)  # today's plan items are listed above
        ),
        key=lambda t: (t.get("created_at") or 0, t["id"]),
    ):
        you.append(
            {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "goalId": rules.card_goal(t["body"]),
                "done": False,
                "founder": True,
                "canFinish": t["status"] in founder.ACTIONABLE,
            }
        )
    plans = _plans(core, workspace_id, date)
    return {
        "date": date,
        "plan": _plan_view(plans[0]) if plans else None,
        "members": list(members.values()),
        "you": you,
    }


def check(core: Core, workspace_id: str, card_id: str) -> None:
    """The owner ticked one of his own items: its card is done (Hermes's complete)."""
    from agos_core.actions import founder, kanban_board
    from agos_core.actions.kanban_asks import _hermes_kanban

    found = next(
        (c for c in kanban_board.keyed(core, workspace_id, KEY) if c["id"] == card_id), None
    )
    if found is None and founder.is_his(core, workspace_id, card_id):
        founder.done(core, workspace_id, card_id)  # one of his Founder tasks
        return
    mine = found is not None and found.get("assignee") in (None, "", founder.FOUNDER)
    if found is None or not mine:
        raise NotFoundError("This item of your list")
    if found["status"] == "done":
        return
    _hermes_kanban(
        core,
        workspace_id,
        "complete",
        card_id,
        "--result=Done by the owner.",
        "--summary=Done by the owner (his list on the Vision page).",
    )
    if found.get("assignee") == founder.FOUNDER:
        from agos_core.engine import doorbell

        kanban_board._moved(core, workspace_id, card_id)  # the pipeline rules look
        doorbell.ring(doorbell.SEND)  # its card on his phone loses its Done button


def status_lines(core: Core, workspace_id: str) -> list[str]:
    """Today's plan and the last recap, for the agents' agos_goals status."""
    date = date_today(core)
    plans = _plans(core, workspace_id, date)
    state = {
        "waiting": "waiting for the owner",
        "approved": "accepted (today's cards are on the board)",
        "revised": "sent back with a note: propose it again",
        "rejected": "skipped by the owner",
    }
    lines = [
        f"Today ({date}): "
        + (
            f"the plan is {state.get(str(plans[0]['status']), str(plans[0]['status']))}"
            + (f" — his note: {plans[0]['note']}" if plans[0]["note"] else "")
            if plans
            else "no plan proposed yet"
        )
    ]
    last = inbox_repo.last_note(core.db, workspace_id, "recap")
    if last is not None:
        lines += [f"Last recap ({last['title']}):", str(last["detail"])[:1200]]
    return lines


# ---- the Co-Founder's posts ---------------------------------------------------------


def plan_text(payload: dict[str, Any]) -> str:
    """The plan in words (Telegram, the card)."""
    lines = []
    if payload.get("summary"):
        lines.append(str(payload["summary"]))
    if payload.get("you"):
        lines.append("You:")
        lines += [f"• {i['title']}" for i in payload["you"]]
    for item in payload.get("members") or []:
        lines.append(f"@{item.get('member')}: {item['title']}")
    return "\n".join(lines)


def post(core: Core, workspace_id: str, kind: str, words: str) -> dict[str, Any]:
    """The Co-Founder's recap (evening) or weekly review: one Inbox note per day
    (a second post the same day replaces its words) and its chat on Telegram."""
    from agos_core.actions import inbox
    from agos_core.actions.services.channel import owner_needs

    if kind not in POSTS:
        raise ActionError("Post kind is recap or weekly.")
    text = words.strip()
    if not text:
        raise ActionError("Write the words of the post.")
    date = date_today(core)
    title = f"Recap — {date}" if kind == "recap" else f"Weekly review — {date}"
    found = inbox_repo.note_titled(core.db, workspace_id, kind, title)
    if found is None:
        note_id = inbox.note(core, workspace_id, kind, title, text[:POST_MAX])
    else:
        note_id = found
        with transaction(core.db):
            inbox_repo.set_note_detail(core.db, workspace_id, note_id, text[:POST_MAX])
    icon = "🌙" if kind == "recap" else "📊"
    owner_needs.push(
        core,
        workspace_id,
        f"{icon} **{title}**\n{text[:3500]}",
        f"{kind}:{workspace_id}:{date}",
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )
    return {"posted": True, "note": note_id}
