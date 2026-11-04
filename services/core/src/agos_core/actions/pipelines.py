"""Pipeline rules (Step 59, F57): when a card moves, something follows by itself.

A rule says "when a card moves to <status> (or a review stage approves it, or its
plan is accepted), in project/goal X or with #label Y, do Z", where Z is one of:
a follow-up card for a member (Hermes's idempotency key agos-pipe:<rule>:<card>, so
a replay is the same card), a comment on the card, an assignment, an automation's
Run now, or a note to the owner (his Co-Founder chat and phone).

Everything a rule reads and writes is Hermes's board: the card's status, title,
body and marker comments are read from the workspace's kanban.db, every write is
Hermes's own `kanban` CLI. What starts a rule:
- Hermes's Kanban hooks in the agos-guard plugin (kanban_task_completed /
  kanban_task_claimed / kanban_task_blocked / on_kanban_task_updated with
  `status` changed), fired in whichever process moved the card, told to AGOS
  through the workspace's bridge (`/pipeline-event`);
- AGOS's own moves (the board's buttons) and the review flow's landed / owner
  decisions (actions/reviews.py), which call `card_moved` / `after_review` too.
`pipeline_seen` keeps the last move acted on per card (one compare-and-set
write), so the same move told twice acts once.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import card_writes
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import pipelines as pipelines_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.hermes_gateway import kanban_rows

log = logging.getLogger("agos.pipelines")

TRIGGERS = ("status", "review_approved", "plan_accepted")
ACTIONS = ("follow_up", "comment", "assign", "run_automation", "notify")
_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
# Hermes's marker comments of the review flow (engine/reviews.py review_marker /
# plan_marker): a stage's approve and a plan's accept.
_APPROVED = re.compile(r"\[agos-review (\S+) r(\d+) s(\d+): approve\]")
_ACCEPTED = re.compile(r"\[agos-plan (\S+) v(\d+): accept\]")


def _row(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "name": str(r["name"]),
        "trigger": str(r["trigger"]),
        "status": str(r["status"]),
        "goalId": int(r["goal_id"]) if r["goal_id"] is not None else None,
        "label": str(r["label"]),
        "action": str(r["action"]),
        "member": str(r["member"]),
        "automationId": int(r["automation_id"]) if r["automation_id"] is not None else None,
        "text": str(r["text"]),
        "enabled": bool(r["enabled"]),
        "lastFiredAt": r["last_fired_at"],
        "lastOutcome": str(r["last_outcome"]),
    }


def rules(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    return [_row(r) for r in pipelines_repo.of_workspace(core.db, workspace_id)]


def _checked(core: Core, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions import agent_profiles, automations, kanban_board

    trigger = str(data.get("trigger") or "")
    action = str(data.get("action") or "")
    if trigger not in TRIGGERS:
        raise ActionError("Pick when the rule acts.")
    if action not in ACTIONS:
        raise ActionError("Pick what the rule does.")
    status = str(data.get("status") or "").strip()
    if trigger == "status":
        known = {c["status"] for c in kanban_board.columns(core)}
        if status not in known:
            raise ActionError("Pick the column the card moves to.")
    else:
        status = ""
    label = str(data.get("label") or "").strip().lstrip("#")
    if label and not _LABEL.match(label):
        raise ActionError("A label is one word (letters, digits, - or _).")
    member = str(data.get("member") or "").strip()
    if action in ("follow_up", "assign"):
        team = set(agent_profiles.team_names(core, workspace_id)) | {kanban_board.COFOUNDER}
        if member not in team:
            raise ActionError("Pick a member of this workspace's team.")
    else:
        member = ""
    automation_id = data.get("automationId")
    if action == "run_automation":
        if (
            not isinstance(automation_id, int)
            or automations.get(core, workspace_id, automation_id) is None
        ):
            raise ActionError("Pick one of this workspace's automations.")
    else:
        automation_id = None
    text = str(data.get("text") or "").strip()[:4000]
    if action in ("comment", "notify") and not text:
        raise ActionError("Write the words the rule says.")
    goal_id = data.get("goalId")
    if goal_id is not None and goals_repo.get(core.db, workspace_id, goal_id) is None:
        raise ActionError("Pick one of this workspace's goals or projects.")
    return {
        "name": str(data.get("name") or "").strip()[:120],
        "trigger": trigger,
        "status": status,
        "goal_id": goal_id,
        "label": label,
        "action": action,
        "member": member,
        "automation_id": automation_id,
        "text": text,
        "enabled": 1 if data.get("enabled", True) else 0,
    }


def save(
    core: Core, workspace_id: str, rule_id: int | None, data: dict[str, Any]
) -> dict[str, Any]:
    """A new rule (rule_id None) or a changed one."""
    fields = _checked(core, workspace_id, data)
    at = now()
    with transaction(core.db):
        if rule_id is None:
            rule_id = pipelines_repo.insert(core.db, workspace_id, fields, at)
        elif not pipelines_repo.update(core.db, workspace_id, rule_id, fields, at):
            raise NotFoundError("This rule")
    if fields["trigger"] == "status" and fields["enabled"]:
        seed(core, workspace_id)
    return next(r for r in rules(core, workspace_id) if r["id"] == rule_id)


def delete(core: Core, workspace_id: str, rule_id: int) -> None:
    with transaction(core.db):
        gone = pipelines_repo.delete(core.db, workspace_id, rule_id)
    if not gone:
        raise NotFoundError("This rule")


# ---- a card moved ------------------------------------------------------------------


def _enabled(core: Core, workspace_id: str, triggers: tuple[str, ...]) -> list[sqlite3.Row]:
    return pipelines_repo.enabled(core.db, workspace_id, triggers)


def _card(core: Core, workspace_id: str, card_id: str) -> dict[str, Any] | None:
    """The card as Hermes's board has it now (read only), with its comments."""
    from agos_core.actions import agent_profiles

    path = agent_profiles.board_db(core, workspace_id)
    if not path.is_file():
        return None
    try:
        with kanban_rows.opened(path, timeout=3) as board:
            task, comments = board.card(card_id)
            if task is None:
                return None
    except sqlite3.Error as error:
        log.info("pipeline: board of %s not read: %s", workspace_id, error)
        return None
    return {
        "id": str(task["id"]),
        "title": str(task["title"] or ""),
        "body": str(task["body"] or ""),
        "status": str(task["status"] or ""),
        "createdAt": int(task["created_at"] or 0),
        "comments": comments,
    }


def _first_time(
    core: Core, workspace_id: str, card_id: str, kind: str, mark: str
) -> tuple[bool, bool]:
    """Set the card's last acted-on move to `mark`: (whether this writer changed it, a
    second report of the same move gets False; whether a move was seen before)."""
    with transaction(core.db):
        prior = pipelines_repo.seen_mark(core.db, workspace_id, card_id, kind)
        if prior is not None and prior == mark:
            return False, True
        pipelines_repo.set_seen(core.db, workspace_id, card_id, kind, mark, now())
    return True, prior is not None


def _statuses(core: Core, workspace_id: str) -> dict[str, tuple[str, int]] | None:
    """{card: (status, created_at)} of the board's cards (archive left out), read only."""
    from agos_core.actions import agent_profiles

    path = agent_profiles.board_db(core, workspace_id)
    if not path.is_file():
        return None
    try:
        with kanban_rows.opened(path, timeout=3) as board:
            return {str(r[0]): (str(r[1] or ""), int(r[2] or 0)) for r in board.unarchived()}
    except sqlite3.Error as error:
        log.info("pipeline: board of %s not read: %s", workspace_id, error)
        return None


def _seen(core: Core, workspace_id: str) -> dict[str, str]:
    return pipelines_repo.seen_statuses(core.db, workspace_id)


def seed(core: Core, workspace_id: str) -> None:
    """A status rule starts from the board as it is now: only later moves act."""
    found = _statuses(core, workspace_id) or {}
    at = now()
    with transaction(core.db):
        pipelines_repo.set_seen_statuses(
            core.db, workspace_id, ((c, status) for c, (status, _) in found.items()), at
        )


def sweep(core: Core, workspace_id: str) -> int:
    """Hermes's dispatcher ticked: every card whose status moved since it was last
    seen (moves no Kanban hook tells: review, unblock, schedule, archive) acts."""
    if not _enabled(core, workspace_id, ("status",)):
        return 0
    found = _statuses(core, workspace_id) or {}
    seen = _seen(core, workspace_id)
    return sum(
        card_moved(core, workspace_id, card_id)
        for card_id, (status, _) in sorted(found.items())
        if seen.get(card_id) != status
    )


def _epoch(iso: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _made_by(rule_id: int, card_id: str) -> str:
    """The line a follow-up card carries: that rule never acts on its own cards (a
    rule on "ready" whose follow-up starts ready would otherwise make cards forever)."""
    return f"[agos-pipe {rule_id} from {card_id}]"


def _in_scope(core: Core, workspace_id: str, rule: sqlite3.Row, card: dict[str, Any]) -> bool:
    if f"[agos-pipe {rule['id']} from " in card["body"]:
        return False
    label = str(rule["label"] or "")
    if label and not re.search(
        rf"(?<![\w#])#{re.escape(label)}(?![\w-])",
        card["title"] + "\n" + card["body"],
        re.IGNORECASE,
    ):
        return False
    wanted = rule["goal_id"]
    if wanted is None:
        return True
    from agos_core.engine import goals as goal_rules

    own = goal_rules.card_goal(card["body"])
    parents = {
        int(r["id"]): (int(r["parent_id"]) if r["parent_id"] is not None else None)
        for r in goals_repo.rows(core.db, workspace_id)
    }
    seen: set[int] = set()
    while own is not None and own not in seen:
        if own == int(wanted):
            return True
        seen.add(own)
        own = parents.get(own)
    return False


def card_moved(core: Core, workspace_id: str, card_id: str) -> int:
    """Hermes says the card changed: its status rules act once per move. The number of
    rules that acted."""
    found = _enabled(core, workspace_id, ("status",))
    if not found:
        return 0  # nothing to read: most workspaces have no rule
    card = _card(core, workspace_id, card_id)
    if card is None:
        return 0
    changed, before = _first_time(core, workspace_id, card_id, "status", card["status"])
    if not changed:
        return 0
    fired = 0
    for rule in found:
        if rule["status"] != card["status"] or not _in_scope(core, workspace_id, rule, card):
            continue
        if not before and card["createdAt"] < _epoch(str(rule["updated_at"])) - 1:
            continue  # first look at a card older than the rule: where it stands, no move
        _fire(core, workspace_id, rule, card)
        fired += 1
    return fired


def after_review(core: Core, workspace_id: str, card_id: str) -> int:
    """A review step landed (actions/reviews.py): a new stage approve or plan accept
    marker on the card acts its rules once."""
    found = _enabled(core, workspace_id, ("review_approved", "plan_accepted"))
    if not found:
        return 0
    card = _card(core, workspace_id, card_id)
    if card is None:
        return 0
    fired = 0
    for kind, trigger, pattern in (
        ("review", "review_approved", _APPROVED),
        ("plan", "plan_accepted", _ACCEPTED),
    ):
        marks = [m.group(0) for c in card["comments"] for m in pattern.finditer(c)]
        marks = [m for m in marks if f" {card_id} " in m]
        if not marks or not _first_time(core, workspace_id, card_id, kind, marks[-1])[0]:
            continue
        for rule in found:
            if rule["trigger"] == trigger and _in_scope(core, workspace_id, rule, card):
                _fire(core, workspace_id, rule, card)
                fired += 1
    return fired


def _words(text: str, card: dict[str, Any]) -> str:
    return text.replace("{card}", card["id"]).replace("{title}", card["title"])


def _fire(core: Core, workspace_id: str, rule: sqlite3.Row, card: dict[str, Any]) -> None:
    from agos_core.actions import automations
    from agos_core.actions.services.channel import owner_needs
    from agos_core.engine import goals as goal_rules

    action, text = str(rule["action"]), _words(str(rule["text"] or ""), card)
    try:
        if action == "follow_up":
            first = (text.splitlines() or [""])[0].strip()
            made = card_writes.create(
                core,
                workspace_id,
                (first or f"Follow-up of {card['title']}")[:200],
                f"{text}\n\nFollows card {card['id']} ({card['title']}).\n"
                f"{_made_by(int(rule['id']), card['id'])}".strip(),
                str(rule["member"]),
                once=f"agos-pipe:{rule['id']}:{card['id']}",
                goal_id=goal_rules.card_goal(card["body"]),
            )
            outcome = f"Card {made} for {rule['member']} (after card {card['id']})."
        elif action == "comment":
            card_writes.comment(core, workspace_id, card["id"], text)
            outcome = f"Commented on card {card['id']}."
        elif action == "assign":
            card_writes.assign(core, workspace_id, card["id"], str(rule["member"]))
            outcome = f"Card {card['id']} given to {rule['member']}."
        elif action == "run_automation":
            automations.run_now(core, workspace_id, int(rule["automation_id"]))
            outcome = f"Automation {rule['automation_id']} runs (after card {card['id']})."
        else:
            name = str(rule["name"] or "A pipeline rule")
            owner_needs.push(
                core,
                workspace_id,
                f"🔁 {name}: card {card['id']} ({card['title']}). {text}",
                f"pipe:{rule['id']}:{card['id']}:{now()}",
                chat_id=owner_needs.cofounder_chat(core, workspace_id),
            )
            outcome = f"Told you about card {card['id']}."
    except (ActionError, NotFoundError) as error:
        outcome = f"Couldn't act on card {card['id']}: {error.message}"
    log.info("pipeline rule %s on %s: %s", rule["id"], card["id"], outcome)
    with transaction(core.db):
        pipelines_repo.fired(core.db, workspace_id, int(rule["id"]), outcome[:500])
