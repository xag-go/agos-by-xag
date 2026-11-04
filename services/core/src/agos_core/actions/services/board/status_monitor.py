"""Status cards, what the agent reads: the cards in scope on Hermes's board, the events since the last summary, its agos tool.
Must not: change the card's definition or job.

Split out of agos_core.actions.status_cards (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board.status_defs import (
    _body,
    _paths,
    _revisions,
    _row,
    scope_label,
    titles,
)
from agos_core.actions.services.board.status_summaries import write_summary
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import key_results as key_results_repo
from agos_core.hermes_gateway import kanban_rows

__all__ = [
    "monitor",
    "read_for_agent",
    "tool",
]

log = logging.getLogger("agos.status_cards")  # the old module's logger (one name)

# ---- the scope's facts (Hermes's board, AGOS's plan) ---------------------------------------


def _board(core: Core, workspace_id: str) -> dict[str, Any]:
    """The board as the scope needs it, one read of Hermes's database: cards, links,
    comment counts, and each card's events (for what moved since a time)."""
    from agos_core.actions import agent_profiles

    empty: dict[str, Any] = {"tasks": [], "links": [], "comments": {}}
    if core.engine is None:
        return empty
    path = agent_profiles.board_db(core, workspace_id)
    if not path.is_file():
        return empty
    try:
        with kanban_rows.opened(path) as board:
            tasks = board.scope_tasks()
            tables = board.tables()
            links = [(str(p), str(c)) for p, c in board.links()] if "task_links" in tables else []
            comments = (
                {str(t): int(n) for t, n in board.comment_counts()}
                if "task_comments" in tables
                else {}
            )
    except sqlite3.Error as error:
        log.info("the board of %s not read: %s", workspace_id, error)
        return empty
    return {"tasks": tasks, "links": links, "comments": comments}


def _profile(core: Core, workspace_id: str, member: str) -> str:
    from agos_core.actions import agent_profiles

    assert core.engine is not None
    return core.engine.hermes_name(agent_profiles.key(workspace_id, member))


def _in_scope(
    core: Core, workspace_id: str, row: Any, board: dict[str, Any]
) -> list[dict[str, Any]]:
    """The scope's cards (archived ones left out), by id."""
    from agos_core.actions.search import matches, terms
    from agos_core.engine import goals as goal_rules

    scope, ref = str(row["scope"]), str(row["scope_ref"])
    tasks = [t for t in board["tasks"] if str(t["status"] or "") != "archived"]
    if scope == "member":
        mine = _profile(core, workspace_id, ref) if core.engine is not None else ""
        tasks = [t for t in tasks if str(t["assignee"] or "") == mine]
    elif scope in ("goal", "project"):
        served = goal_rules.card_goals(
            {str(t["id"]): (str(t["status"] or ""), str(t["body"] or "")) for t in board["tasks"]},
            board["links"],
        )
        wanted = {int(ref)}
        if scope == "goal":
            wanted |= {
                int(r["id"])
                for r in goals_repo.rows(core.db, workspace_id)
                if r["parent_id"] == int(ref)
            }
        tasks = [t for t in tasks if str(t["id"]) in served and served[str(t["id"])][0] in wanted]
    elif scope == "query":
        words = terms(ref)
        tasks = [t for t in tasks if matches(f"{t['title'] or ''}\n{t['body'] or ''}", words)]
    return sorted(tasks, key=lambda t: str(t["id"]))


def _results(core: Core, workspace_id: str, row: Any) -> list[Any]:
    scope, ref = str(row["scope"]), str(row["scope_ref"])
    if scope == "workspace":
        return sorted(
            key_results_repo.rows(core.db, workspace_id),
            key=lambda r: (r["goal_id"], r["position"], r["id"]),
        )
    if scope == "goal":
        return [r for r in key_results_repo.rows(core.db, workspace_id) if r["goal_id"] == int(ref)]
    return []


def _who(core: Core, workspace_id: str) -> Any:
    from agos_core.actions import kanban_board

    members = kanban_board._members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""

    def name(profile: str) -> str:
        if not profile:
            return "nobody"
        found = members.get(profile)
        if found:
            return "Co-Founder" if found["name"] == kanban_board.COFOUNDER else f"@{found['name']}"
        return "Co-Founder" if profile == cofounder else profile

    return name


def _number(value: Any) -> str:
    return f"{float(value):g}" if value is not None else "?"


def monitor(core: Core, workspace_id: str, card_id: int) -> str:
    """What the card's monitor script prints: stable lines of the scope's facts, so
    Hermes wakes the Co-Founder only when one of them changed (status, who has a
    card, a new comment, a card in or out of the scope, a key result's number, a
    refresh asked). An on-demand card prints only its refresh line."""
    row = _row(core, workspace_id, card_id)
    lines = [f"Status card {card_id}: {row['title']} ({scope_label(core, workspace_id, row)})"]
    if row["refresh_asked_at"]:
        lines.append(f"Refresh asked by the owner: {row['refresh_asked_at']}")
    if row["policy"] == "manual":
        return "\n".join(lines) + "\n"
    board = _board(core, workspace_id)
    who = _who(core, workspace_id)
    for t in _in_scope(core, workspace_id, row, board):
        lines.append(
            " | ".join(
                (
                    f"card {t['id']}",
                    str(t["status"] or ""),
                    who(str(t["assignee"] or "")),
                    f"{board['comments'].get(str(t['id']), 0)} comments",
                    str(t["block_kind"] or ""),
                    " ".join(str(t["title"] or "").split())[:120],
                )
            )
        )
    for k in _results(core, workspace_id, row):
        lines.append(
            f"key result {k['id']} | {_number(k['current'])} / {_number(k['target'])} {k['unit']}"
        )
    return "\n".join(lines) + "\n"


def _since_events(core: Core, workspace_id: str, ids: set[str], since: float) -> list[str]:
    """What Hermes's board says moved on these cards since `since` (unix seconds)."""
    from agos_core.actions import agent_profiles, kanban_board

    if core.engine is None or not ids:
        return []
    path = agent_profiles.board_db(core, workspace_id)
    if not path.is_file():
        return []
    kinds = tuple(kanban_board.EVENTS)
    try:
        with kanban_rows.opened(path) as board:
            rows = board.events_since(since, kinds)
    except sqlite3.Error:
        return []
    out = []
    for task, kind, payload, _at, title in rows:
        if str(task) not in ids:
            continue
        try:
            data = json.loads(payload or "{}")
        except ValueError:
            data = {}
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("summary") or data.get("reason") or data.get("error") or "")
        word = kanban_board.EVENTS[str(kind)][1]
        out.append(
            f"- card {task} “{title or ''}”: {word}"
            + (f": {' '.join(detail.split())[:200]}" if detail else "")
        )
    return out[-60:]


def _epoch(iso: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def read_for_agent(core: Core, workspace_id: str, card_id: int) -> str:
    """`agos_status_card` read: the scope's facts, what moved since the last summary,
    and that summary, in short lines."""
    row = _row(core, workspace_id, card_id)
    board = _board(core, workspace_id)
    cards = _in_scope(core, workspace_id, row, board)
    who = _who(core, workspace_id)
    target, _history, changes = _paths(core, workspace_id, card_id)
    revisions = _revisions(changes)
    last = revisions[-1] if revisions else None
    out = [
        f"Status card {card_id} “{row['title']}”: {scope_label(core, workspace_id, row)}.",
        f"Update policy: {row['policy']}.",
    ]
    if row["refresh_asked_at"]:
        out.append(f"The owner asked for a fresh summary at {row['refresh_asked_at']}: write one.")
    by_status: dict[str, int] = {}
    for t in cards:
        by_status[str(t["status"] or "?")] = by_status.get(str(t["status"] or "?"), 0) + 1
    out.append(
        f"{len(cards)} cards: " + ", ".join(f"{n} {s}" for s, n in sorted(by_status.items()))
        if cards
        else "No cards in this scope yet."
    )
    open_cards = [t for t in cards if str(t["status"] or "") != "done"]
    for t in open_cards[:60]:
        comments = board["comments"].get(str(t["id"]), 0)
        out.append(
            f"- card {t['id']} [{t['status']}] {who(str(t['assignee'] or ''))}"
            + (f", blocked ({t['block_kind']})" if t["block_kind"] else "")
            + (f", {comments} comments" if comments else "")
            + f": {' '.join(str(t['title'] or '').split())[:140]}"
        )
    if len(open_cards) > 60:
        out.append(f"... and {len(open_cards) - 60} more open cards.")
    done = sorted(
        (t for t in cards if str(t["status"] or "") == "done"),
        key=lambda t: -int(t["completed_at"] or 0),
    )
    if done:
        out.append("Done (newest first):")
        out += [
            f"- card {t['id']} {who(str(t['assignee'] or ''))}: "
            f"{' '.join(str(t['title'] or '').split())[:140]}"
            for t in done[:30]
        ]
    results = _results(core, workspace_id, row)
    if results:
        out.append("Key results:")
        out += [
            f"- {k['title']}: {_number(k['current'])} / {_number(k['target'])} {k['unit']}".rstrip()
            for k in results
        ]
    since = _epoch(last.at) if last else 0.0
    moved = _since_events(core, workspace_id, {str(t["id"]) for t in cards}, since)
    if last is None:
        out.append("No summary yet: write the first one.")
    elif moved:
        out.append(f"Moved since your last summary (v{last.n}, {last.at}):")
        out += moved
    else:
        out.append(f"Nothing moved on the board since your last summary (v{last.n}, {last.at}).")
    if last is not None:
        out.append("Your last summary:")
        out.append((_body(target) or "").strip()[:4000])
    return "\n".join(out)


def tool(
    core: Core, workspace_id: str, *, member: str, action: str, card_id: int, summary: str, why: str
) -> dict[str, Any]:
    """`agos_status_card` as the agents call it: read the scope, write the summary
    (the Co-Founder only), or the monitor's facts (the card's monitor script)."""
    try:
        if action == "monitor":
            return {"monitor": monitor(core, workspace_id, card_id)}
        if action == "list":
            return {
                "cards": [
                    {"card": i, "title": t} for i, t in sorted(titles(core, workspace_id).items())
                ]
            }
        if action == "read":
            return {"card": card_id, "read": read_for_agent(core, workspace_id, card_id)}
        if member:
            return {"error": "Only the Co-Founder writes the status cards' summaries."}
        return {
            "card": card_id,
            **write_summary(
                core,
                workspace_id,
                card_id,
                summary,
                who="Co-Founder",
                why=" ".join(why.split())[:200] or "the scheduled update",
            ),
        }
    except ActionError as error:
        return {"error": error.message}
