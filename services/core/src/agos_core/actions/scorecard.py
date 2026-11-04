"""The agent scorecard (Step 63): how each member did this week, derived from where
the facts live, nothing stored.

Per member (and the Co-Founder) for one ISO week, from ONE read of Hermes's board
(tasks, task_events, task_comments; read only) plus AGOS's own vote rows and each
profile's Hermes cron (its heartbeat job):
- cards done (completed in the week, assigned to it) and the median time per card
  (Hermes's started_at -> completed_at);
- times blocked and the time those blocks waited (blocked -> the card's next
  unblocked / completed / claimed event, else the week's end);
- review return rate: of its submissions to review (Step 52 `submit` markers), the
  share sent back with `changes`;
- the owner's 👍 / 👎 (feedback_votes, Step 49) on its replies and revisions;
- its last heartbeat (Hermes's job last_run_at), its pinned skills (Hermes's
  skills.auto_load), and its ready state when AGOS knows one (None until then).
Cheap enough per page view; no cache.
"""

from __future__ import annotations

import contextlib
import sqlite3
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.hermes_gateway import hermes_db


def week_bounds(week: str | None = None, today: date | None = None) -> tuple[str, float, float]:
    """(\"YYYY-Www\", start, end) in epoch seconds, Monday 00:00 UTC to the next."""
    if week:
        try:
            year, n = week.split("-W")
            monday = date.fromisocalendar(int(year), int(n), 1)
        except ValueError as error:
            raise ActionError("A week is YYYY-Www (an ISO week, e.g. 2026-W44).") from error
    else:
        d = today or datetime.now(UTC).date()
        monday = d - timedelta(days=d.weekday())
    start = datetime(monday.year, monday.month, monday.day, tzinfo=UTC)
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}", start.timestamp(), (start + timedelta(days=7)).timestamp()


def _empty(member: str, title: str) -> dict[str, Any]:
    return {
        "member": member,
        "title": title,
        "cardsDone": 0,
        "medianMinutes": None,
        "blocked": 0,
        "blockedMinutes": 0,
        "submitted": 0,
        "returned": 0,
        "returnRate": None,
        "thumbsUp": 0,
        "thumbsDown": 0,
        "lastHeartbeat": None,
        "skills": 0,
        "ready": None,
    }


def from_board(
    db: sqlite3.Connection,
    by_profile: dict[str, str],
    start: float,
    end: float,
    now_s: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """The board's part of each member's card: {member: counts} and {card: member}
    (each card's assignee, for votes on revisions). `by_profile`: Hermes's
    assignee name -> the member."""
    from agos_core.engine import reviews

    out: dict[str, dict[str, Any]] = {}
    owner_of: dict[str, str] = {}
    durations: dict[str, list[float]] = {}
    for card, assignee, status, started, completed in db.execute(
        "SELECT id, assignee, status, started_at, completed_at FROM tasks"
    ):
        member = by_profile.get(str(assignee or ""))
        if member is None:
            continue
        owner_of[str(card)] = member
        if status in ("done", "archived") and completed and start <= float(completed) < end:
            row = out.setdefault(member, {})
            row["cardsDone"] = row.get("cardsDone", 0) + 1
            if started and float(completed) > float(started):
                durations.setdefault(member, []).append((float(completed) - float(started)) / 60)
    for member, values in durations.items():
        out[member]["medianMinutes"] = round(statistics.median(values), 1)
    events: dict[str, list[tuple[float, str]]] = {}
    with contextlib.suppress(sqlite3.Error):
        for card, kind, at in db.execute(
            """SELECT task_id, kind, created_at FROM task_events
               WHERE kind IN ('blocked', 'unblocked', 'completed', 'claimed') AND created_at < ?
               ORDER BY created_at, id""",
            (end,),
        ):
            events.setdefault(str(card), []).append((float(at), str(kind)))
    for card, seq in events.items():
        member = owner_of.get(card)
        if member is None:
            continue
        for i, (at, kind) in enumerate(seq):
            if kind != "blocked" or not start <= at < end:
                continue
            ended = next((t for t, k in seq[i + 1 :] if k != "blocked"), min(end, now_s))
            row = out.setdefault(member, {})
            row["blocked"] = row.get("blocked", 0) + 1
            row["blockedMinutes"] = row.get("blockedMinutes", 0) + max(0, round((ended - at) / 60))
    with contextlib.suppress(sqlite3.Error):
        last_submit: dict[str, str] = {}
        for card, author, body, at in db.execute(
            """SELECT task_id, author, body, created_at FROM task_comments
               WHERE body LIKE '%[agos-review %' AND created_at < ? ORDER BY created_at, id""",
            (end,),
        ):
            mark = reviews.read_mark(str(card), str(body), str(author or ""))
            if mark is None or mark.kind != "review":
                continue
            if mark.verb == "submit":
                member = by_profile.get(str(author or "")) or owner_of.get(str(card))
                if member is None:
                    continue
                last_submit[str(card)] = member
                if start <= float(at) < end:
                    row = out.setdefault(member, {})
                    row["submitted"] = row.get("submitted", 0) + 1
            elif mark.verb == "changes" and start <= float(at) < end:
                member = last_submit.get(str(card))
                if member is not None:
                    row = out.setdefault(member, {})
                    row["returned"] = row.get("returned", 0) + 1
    return out, owner_of


def scorecards(core: Core, workspace_id: str, week: str | None = None) -> dict[str, Any]:
    """Every member's scorecard (and the Co-Founder's) for one ISO week."""
    from agos_core.actions import (
        agent_profiles,
        automations,
        heartbeat,
        kanban_board,
        team,
    )
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    label, start, end = week_bounds(week)
    now_s = datetime.now(UTC).timestamp()
    cards: dict[str, dict[str, Any]] = {
        kanban_board.COFOUNDER: _empty(kanban_board.COFOUNDER, "Co-Founder")
    }
    for name in agent_profiles.team_names(core, workspace_id):
        cards[name] = _empty(name, team.title_of(core, workspace_id, name))
    if core.engine is None:
        return {"week": label, "members": list(cards.values())}
    by_profile = {p: m["name"] for p, m in kanban_board._members(core, workspace_id).items()}
    owner_of: dict[str, str] = {}
    path = agent_profiles.board_db(core, workspace_id)
    if path.is_file():
        try:
            with contextlib.closing(hermes_db.connect_ro(path, timeout=2)) as db:
                found, owner_of = from_board(db, by_profile, start, end, now_s)
        except sqlite3.Error:
            found = {}
        for member, counts in found.items():
            if member in cards:
                cards[member].update(counts)
    _votes(core, workspace_id, cards, owner_of, start, end)
    try:
        beats = heartbeat.list_all(core, workspace_id)
    except ActionError:
        beats = []
    for beat in beats:
        member = beat.agent or kanban_board.COFOUNDER
        if member in cards:
            cards[member]["lastHeartbeat"] = beat.last_at
    for member, row in cards.items():
        owner = "" if member == kanban_board.COFOUNDER else member
        row["skills"] = len(automations.pinned_skills(core, workspace_id, owner))
        if row["submitted"]:
            row["returnRate"] = round(min(row["returned"], row["submitted"]) / row["submitted"], 2)
    return {"week": label, "members": list(cards.values())}


def _votes(
    core: Core,
    workspace_id: str,
    cards: dict[str, dict[str, Any]],
    owner_of: dict[str, str],
    start: float,
    end: float,
) -> None:
    from agos_core.actions import kanban_board

    since = datetime.fromtimestamp(start, UTC).isoformat(timespec="seconds")
    until = datetime.fromtimestamp(end, UTC).isoformat(timespec="seconds")
    rows = core.db.execute(
        """SELECT v.kind, v.ref, v.vote, c.agent FROM feedback_votes v
           LEFT JOIN chats c ON v.kind = 'reply' AND c.workspace_id = v.workspace_id
             AND CAST(c.id AS TEXT) = substr(v.ref, 1, instr(v.ref, ':') - 1)
           WHERE v.workspace_id = ? AND v.created_at >= ? AND v.created_at < ?""",
        (workspace_id, since, until),
    ).fetchall()
    for r in rows:
        if r["kind"] == "reply":
            member = str(r["agent"] or "") or kanban_board.COFOUNDER
        else:
            member = owner_of.get(str(r["ref"]).split(":")[0], "")
        if member not in cards:
            continue
        cards[member]["thumbsUp" if int(r["vote"]) > 0 else "thumbsDown"] += 1


def status_lines(core: Core, workspace_id: str) -> list[str]:
    """The scorecards in a few lines for the Co-Founder's agos_goals status (its
    weekly review reads them and proposes fixes)."""
    found = scorecards(core, workspace_id)
    lines = [f"Team scorecards ({found['week']}):"]
    for m in found["members"]:
        rate = "—" if m["returnRate"] is None else f"{int(m['returnRate'] * 100)}%"
        median = "—" if m["medianMinutes"] is None else f"{m['medianMinutes']:g} min"
        lines.append(
            f"- @{m['member']}: {m['cardsDone']} done (median {median}), blocked "
            f"{m['blocked']}x ({m['blockedMinutes']} min), returned from review {rate}, "
            f"👍 {m['thumbsUp']} / 👎 {m['thumbsDown']}, last heartbeat "
            f"{m['lastHeartbeat'] or 'none'}, {m['skills']} skills pinned"
        )
    return lines
