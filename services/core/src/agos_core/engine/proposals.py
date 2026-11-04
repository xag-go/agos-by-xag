"""Proposals an agent makes to the owner, as Hermes Kanban cards: pure rules.

A proposal is a card the agent creates (kanban_create) whose body carries ONE
fenced block, then blocks for the owner (kanban_block, kind needs_input, reason
starting with "waiting for the owner:"). The block is machine-shaped JSON:

    ```agos-proposal
    {"kind": "hire", "payload": {...}}
    ```

- the info string is exactly `agos-proposal`;
- the content is one JSON object: `kind` (hire | instructions | plan | goal), `payload`
  (per kind, below), optional `revises` (the card id of the earlier round this
  one replaces: Hermes routes a second needs_input block of the SAME card to
  triage (hermes_cli/kanban_db.py BLOCK_RECURRENCE_LIMIT), so a revised proposal
  is a NEW card);
- anything before or after the fence is the agent's own words (shown as is).

Payloads (every field a string unless said; unknown fields are kept and shown):
- hire: name (lowercase-with-dashes), title (the job title), role (its mission
  text), model (required on a new hire: {model, effort}: an exact version the
  workspace's provider offers in Hermes's catalog, sized to the role's work,
  engine/hire_kit.py resolve_model; nothing else in it), model_why (required: why that
  model, one line, its own field), skills (list of skill
  names), telegram_topic (bool), coding_engine (hermes | claude_code | codex |
  opencode; kept for later), reports_to ("" = the Co-Founder, else a member's name),
  why (required: the exact gap against the workspace goal and why no member on the
  team covers it; the team-design skill's first rule), goal_id (int: the goal or
  project it serves; required on a new hire while the workspace has an open one),
  source_card (optional: the card id the need came from), kit (required on a new
  hire: the tools, skills, docs, team context and onboarding test the member needs;
  engine/hire_kit.py says its shape and kit_missing what may not be empty; the owner
  may edit it before approving).
- kit: a whole kit for a member ALREADY on the team (hired before kits, or with a
  part of its kit missing; actions/member_kits.py): member (its name), kit (the
  hire's kit shape, whole), model ({model, effort}, as a hire's), model_why, why (what
  its role and work show it needs), source_card. Approve writes it into that member's
  Hermes profile the way a hire's kit is written; nothing else of the member changes.
- instructions: target (SOUL.md | config.yaml | AGENTS.md | profile.yaml, the
  proposing agent's own), diff (a unified diff of the change), sha256 (of the whole
  proposed file content, hex), summary.
- plan: title, markdown.
- goal: a change to the workspace's plan (the Vision page, step 53), `change` says
  which (GOAL_CHANGES), why (required, except a daily plan: what it does for the
  goal). suggest_vision: title, vision_why, strategy (the Vision is the owner's: a
  suggestion). add_goal / update_goal / drop_goal: goal_id (update / drop), title,
  goal_why, owner (a member's name), due_on, status (active | paused | done |
  dropped: a dropped goal stays on the page, marked dropped). delete_goal /
  delete_kr / delete_project: goal_id / kr_id / project_id, why: the row is gone
  (a goal with its key results and projects); an update whose status says
  'deleted' is read as the delete (as_delete). An add_goal may also carry
  key_results ([{title, target, unit, due_on}]) and projects ([{title}]), made with
  it on approve (step 60, the Vision notes' Organize). add_kr / update_kr / drop_kr:
  kr_id (update / drop), goal_id (add), title, start, current, target (numbers),
  unit, due_on. kr_update: kr_id, current, source (where the number comes from).
  add_project / update_project / drop_project: project_id (update / drop), goal_id
  (add), title, project_why, owner, project_kind (dated | recurring), starts_on,
  ends_on, rhythm. daily_plan: date (YYYY-MM-DD), you (the owner's own items:
  {title, why}), members ({member, title, body, project_id}), summary. Step 51's
  set_goal / add_subgoal / update_subgoal / drop_subgoal are still read.

The owner's decision is written on the card as a comment that starts with a
stable marker, `[agos-decision <card> r<round>: <choice>]`, so a replay is read
from the card itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

FENCE = "agos-proposal"
KINDS = ("hire", "instructions", "plan", "goal", "skill", "kit")
# A skill proposal is AGOS's own (actions/skill_requests.py): a hub skill an agent asked
# for that carries scripts or that Hermes's scan warned about, waiting for the owner.
# Agents never propose one (the guard's agos_propose enum leaves it out); its approve
# acts only on the request row that names this very ask.
# What the agent blocks with: the asks' prefix (the guard's hook tells AGOS), then
# the word that says it is a proposal, not an Autonomy ask.
OWNER_OK = "waiting for the owner:"
BLOCK_REASON = f"{OWNER_OK} proposal"
DECISIONS = ("approve", "revise", "reject")
# The files an agent may only change through an instructions proposal.
INSTRUCTION_FILES = ("SOUL.md", "config.yaml", "AGENTS.md", "profile.yaml")
ENGINES = ("hermes", "claude_code", "codex", "opencode")

_OPEN = re.compile(r"^[ \t]*```[ \t]*" + re.escape(FENCE) + r"[ \t]*$", re.M)
_MARK = re.compile(r"^\[agos-decision (?P<card>[A-Za-z0-9_-]+) r(?P<round>\d+): (?P<choice>\w+)\]")


def parse(body: str) -> dict[str, Any] | None:
    """The proposal in a card body, or None (no block, or one AGOS can't read).
    The JSON is read with raw_decode from the fence on: skill and doc texts often
    contain ``` themselves, so the closing fence is never searched for."""
    found = _OPEN.search(body or "")
    if found is None:
        return None
    rest = body[found.end() :].lstrip()
    try:
        raw, _ = json.JSONDecoder().raw_decode(rest)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip().lower()
    payload = raw.get("payload")
    if kind not in KINDS or not isinstance(payload, dict):
        return None
    out: dict[str, Any] = {"kind": kind, "payload": clean(kind, payload)}
    revises = str(raw.get("revises") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", revises):
        out["revises"] = revises
    return out


def clean(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload AGOS keeps: its known fields typed, the rest as given."""
    p: dict[str, Any] = {str(k)[:40]: v for k, v in payload.items() if isinstance(k, str)}
    if kind == "kit":
        return _clean_kit(p)
    if kind == "hire":
        model = p.get("model")
        p["name"] = str(p.get("name") or "").strip().lower()
        p["title"] = str(p.get("title") or "").strip()
        p["role"] = str(p.get("role") or p.get("instructions") or "").strip()
        p.pop("instructions", None)
        if isinstance(model, str) and model.strip():  # a bare model id or family
            model = {"model": model.strip()}
        # Kept whole (hire_model.check refuses anything in it but model and effort: a
        # why or free text put there is sent back, the why has its own field).
        p["model"] = (
            {str(k): str(v) for k, v in model.items() if isinstance(k, str) and v is not None}
            if isinstance(model, dict) and any(str(v or "").strip() for v in model.values())
            else None
        )
        # Why this model for this role (shown on the card): its own field.
        if "model_why" in p:
            p["model_why"] = " ".join(str(p.get("model_why") or "").split())[:200]
        skills = p.get("skills")
        p["skills"] = (
            [str(s).strip() for s in skills if str(s).strip()] if isinstance(skills, list) else []
        )
        p["telegram_topic"] = p.get("telegram_topic") in (True, "true", "yes", 1)
        engine = str(p.get("coding_engine") or "hermes").strip().lower()
        p["coding_engine"] = engine if engine in ENGINES else "hermes"
        p["reports_to"] = str(p.get("reports_to") or "").strip().lower()
        if p["reports_to"] in (
            "cofounder",
            "manager",
            "none",
        ):  # "manager": the name before step 44, still in old rows and cards
            p["reports_to"] = ""
        if "why" in p:  # absent in proposals made before step 51 (their digest holds)
            p["why"] = str(p.get("why") or "").strip()
        # Both absent in hires made before the hire checks (their digest holds).
        if "goal_id" in p:
            p["goal_id"] = _int(str(p.get("goal_id") or "").strip().lstrip("#"))
        if "source_card" in p:
            card = str(p.get("source_card") or "").strip()
            p["source_card"] = card if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", card) else ""
        if "kit" in p:  # step 62: absent in hires made before kits (their digest holds)
            from agos_core.engine import hire_kit

            p["kit"] = hire_kit.clean_kit(p.get("kit"))
    elif kind == "goal":
        p["change"] = str(p.get("change") or "").strip().lower()
        p["title"] = " ".join(str(p.get("title") or "").split())
        p["why"] = str(p.get("why") or "").strip()
        for key in ("goal_id", "parent_id", "kr_id", "project_id"):
            if key in p or key in ("goal_id", "parent_id"):
                p[key] = _int(p.get(key))
        for key in ("start", "current", "target"):
            if key in p:
                p[key] = _num(p.get(key))
        if "owner" in p:
            p["owner"] = str(p.get("owner") or "").strip().lstrip("@").lower()
        if "key_results" in p:  # an add_goal with its key results (step 60)
            p["key_results"] = [
                i for i in (_goal_result(x) for x in _list(p.get("key_results"))[:6]) if i
            ]
        if "projects" in p:  # an add_goal with its projects (step 60)
            p["projects"] = [
                i for i in (_goal_project(x) for x in _list(p.get("projects"))[:5]) if i
            ]
        if p["change"] == "daily_plan":
            p["date"] = str(p.get("date") or "").strip()
            p["you"] = [i for i in (_plan_item(x, False) for x in _list(p.get("you"))) if i]
            p["members"] = [i for i in (_plan_item(x, True) for x in _list(p.get("members"))) if i]
        p = as_delete(p)
    elif kind == "skill":
        p["request"] = _int(p.get("request"))
        p["name"] = str(p.get("name") or "").strip()
        p["source"] = str(p.get("source") or "").strip()
        p["why"] = str(p.get("why") or "").strip()
    elif kind == "instructions":
        p["target"] = str(p.get("target") or "").strip()
        p["diff"] = str(p.get("diff") or "")
        p["sha256"] = str(p.get("sha256") or "").strip().lower()
        p["summary"] = str(p.get("summary") or "").strip()
    else:
        p["title"] = str(p.get("title") or "").strip()
        p["markdown"] = str(p.get("markdown") or p.get("text") or "")
        p.pop("text", None)
    return p


def _clean_kit(p: dict[str, Any]) -> dict[str, Any]:
    """A kit proposal for a member already on the team (its model as a hire's)."""
    from agos_core.engine import hire_kit

    model = p.get("model")
    if isinstance(model, str) and model.strip():
        model = {"model": model.strip()}
    p["member"] = str(p.get("member") or p.get("name") or "").strip().lstrip("@").lower()
    p.pop("name", None)
    p["kit"] = hire_kit.clean_kit(p.get("kit"))
    p["model"] = (
        {str(k): str(v) for k, v in model.items() if isinstance(k, str) and v is not None}
        if isinstance(model, dict) and any(str(v or "").strip() for v in model.values())
        else None
    )
    p["model_why"] = " ".join(str(p.get("model_why") or "").split())[:200]
    p["why"] = str(p.get("why") or "").strip()
    card = str(p.get("source_card") or "").strip()
    p["source_card"] = card if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", card) else ""
    return p


def problems(kind: str, payload: dict[str, Any]) -> list[str]:
    """What keeps a proposal from being decided (shown to the owner, told the agent)."""
    out = []
    if kind == "hire":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", payload.get("name") or ""):
            out.append("name must be lowercase-with-dashes")
        if not payload.get("title"):
            out.append("title (the job title) is missing")
        if not payload.get("role"):
            out.append("role (its mission) is missing")
    elif kind == "kit":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", payload.get("member") or ""):
            out.append("member (the name of the member the kit is for) is missing")
    elif kind == "instructions":
        if payload.get("target") not in INSTRUCTION_FILES:
            out.append(f"target must be one of {', '.join(INSTRUCTION_FILES)}")
        if not re.fullmatch(r"[0-9a-f]{64}", payload.get("sha256") or ""):
            out.append("sha256 must be the hex SHA-256 of the whole proposed file")
        if not payload.get("diff"):
            out.append("diff is missing")
    elif kind == "goal":
        out += _goal_problems(payload)
    elif kind == "skill":
        if not payload.get("request"):
            out.append("request (the skill request's number) is missing")
        if not payload.get("source"):
            out.append("source (where the skill comes from) is missing")
    elif not payload.get("title") or not payload.get("markdown"):
        out.append("title and markdown are both needed")
    return out


GOAL_CHANGES = (
    "suggest_vision",
    "add_goal",
    "update_goal",
    "drop_goal",
    "add_kr",
    "update_kr",
    "drop_kr",
    "kr_update",
    "add_project",
    "update_project",
    "drop_project",
    "daily_plan",
    "delete_goal",
    "delete_kr",
    "delete_project",
    # Step 51's words (proposals made before step 53 are still decided).
    "set_goal",
    "add_subgoal",
    "update_subgoal",
    "drop_subgoal",
)
# What each change needs to name (the row it changes).
_NEEDS: dict[str, tuple[str, str]] = {
    "update_goal": ("goal_id", "the goal's number"),
    "drop_goal": ("goal_id", "the goal's number"),
    "update_subgoal": ("goal_id", "the goal's number"),
    "drop_subgoal": ("goal_id", "the goal's number"),
    "add_kr": ("goal_id", "the goal it measures"),
    "update_kr": ("kr_id", "the key result's number"),
    "drop_kr": ("kr_id", "the key result's number"),
    "kr_update": ("kr_id", "the key result's number"),
    "add_project": ("goal_id", "the goal it serves"),
    "update_project": ("project_id", "the project's number"),
    "drop_project": ("project_id", "the project's number"),
    "delete_goal": ("goal_id", "the goal's number"),
    "delete_kr": ("kr_id", "the key result's number"),
    "delete_project": ("project_id", "the project's number"),
}
# The statuses a goal or a project takes (engine/goals.py STATUSES; repeated here so
# the proposal rules stay import-free, test_plan_delete pins the two together).
ITEM_STATUSES = ("active", "paused", "done", "dropped")
# A status that means the agent wants the row gone, not marked: the delete itself.
DELETE_WORDS = ("deleted", "delete", "removed", "remove", "gone")
_DELETE_OF = {
    "update_goal": "delete_goal",
    "update_project": "delete_project",
    "update_kr": "delete_kr",
}


def as_delete(payload: dict[str, Any]) -> dict[str, Any]:
    """An update whose status says 'deleted' is the delete it meant (agents wrote that
    before delete_goal / delete_kr / delete_project existed, and AGOS refused it on
    approve). Anything else comes back as it is."""
    change = str(payload.get("change") or "")
    status = str(payload.get("status") or "").strip().lower()
    if change not in _DELETE_OF or status not in DELETE_WORDS:
        return payload
    out = {k: v for k, v in payload.items() if k != "status"}
    out["change"] = _DELETE_OF[change]
    return out


PLAN_ITEMS_MAX = 30


def _int(raw: Any) -> int | None:
    return int(raw) if isinstance(raw, int | str) and str(raw).strip().isdigit() else None


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        value = float(str(raw).replace(",", "").strip())
    except ValueError:
        return None
    return value if value == value and abs(value) < 1e15 else None  # NaN, inf: none


def _list(raw: Any) -> list[Any]:
    return list(raw)[:PLAN_ITEMS_MAX] if isinstance(raw, list) else []


def _goal_result(raw: Any) -> dict[str, Any] | None:
    """One key result an add_goal carries: {title, target, unit, due_on}."""
    if not isinstance(raw, dict):
        return None
    title = " ".join(str(raw.get("title") or "").split())[:200]
    if not title:
        return None
    due = str(raw.get("due_on") or "").strip()
    return {
        "title": title,
        "target": _num(raw.get("target")),
        "unit": " ".join(str(raw.get("unit") or "").split())[:40],
        "due_on": due if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) else "",
    }


def _goal_project(raw: Any) -> dict[str, Any] | None:
    """One project an add_goal carries: {title} (a bare string is a title)."""
    title = raw.get("title") if isinstance(raw, dict) else raw if isinstance(raw, str) else ""
    clean = " ".join(str(title or "").split())[:200]
    return {"title": clean} if clean else None


def _plan_item(raw: Any, member: bool) -> dict[str, Any] | None:
    """One line of a daily plan: the owner's ({title, why}) or a member's ({member,
    title, body, project_id}). A bare string is a title."""
    if not isinstance(raw, str | dict):
        return None
    item: dict[str, Any] = {"title": raw} if isinstance(raw, str) else dict(raw)
    title = " ".join(str(item.get("title") or "").split())[:200]
    if not title:
        return None
    out: dict[str, Any] = {"title": title}
    if member:
        out["member"] = str(item.get("member") or "").strip().lstrip("@").lower()
        out["body"] = str(item.get("body") or "").strip()[:4000]
        out["project_id"] = _int(item.get("project_id") or item.get("goal_id"))
    else:
        out["why"] = " ".join(str(item.get("why") or "").split())[:300]
        out["project_id"] = _int(item.get("project_id") or item.get("goal_id"))
    return out


def _goal_problems(payload: dict[str, Any]) -> list[str]:
    out = []
    payload = as_delete(payload)
    change = str(payload.get("change") or "")
    if change not in GOAL_CHANGES:
        return [f"change must be one of {', '.join(GOAL_CHANGES[:15])}"]
    status = str(payload.get("status") or "").strip().lower()
    updates = ("update_goal", "update_project", "update_subgoal")
    if change in updates and status and status not in ITEM_STATUSES:
        out.append(
            "status is active, paused, done or dropped (to remove it for good: "
            f"change {'delete_project' if change == 'update_project' else 'delete_goal'})"
        )
    if change in (
        "suggest_vision",
        "set_goal",
        "add_goal",
        "add_subgoal",
        "add_kr",
        "add_project",
    ) and not payload.get("title"):
        out.append("title is missing")
    need = _NEEDS.get(change)
    if need is not None and not payload.get(need[0]):
        out.append(f"{need[0]} ({need[1]}) is missing")
    if change == "kr_update":
        if payload.get("current") is None:
            out.append("current (the key result's new number) is missing")
        if not str(payload.get("source") or "").strip():
            out.append(
                "source (where the number comes from) is missing: without one, ask the owner"
            )
    if change in ("add_kr", "update_kr") and "target" in payload and payload["target"] is None:
        out.append("target must be a number")
    if change in ("add_project", "update_project") and payload.get("project_kind") not in (
        None,
        "",
        "dated",
        "recurring",
    ):
        out.append("project_kind is dated or recurring")
    if change == "daily_plan":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(payload.get("date") or "")):
            out.append("date (YYYY-MM-DD, today) is missing")
        if not payload.get("you") and not payload.get("members"):
            out.append("the plan is empty: give the owner's items (you) or the members' (members)")
        if any(not i.get("member") for i in payload.get("members") or []):
            out.append("each members item names its member")
    elif not payload.get("why"):
        out.append("why (what this change does for the goal) is missing")
    return out


# The team-design skill's first rule, held at the door: a hire names its gap.
NO_WHY = (
    "why is missing: say the exact gap against the workspace goal this hire fills and "
    "why no member on the team covers it (the team-design skill), then propose again"
)


def proposing_problems(kind: str, payload: dict[str, Any]) -> list[str]:
    """What keeps a NEW proposal from being made (problems() plus the rules a
    proposal must meet when it is made, not when an old one is decided)."""
    out = problems(kind, payload)
    if kind == "hire" and len(str(payload.get("why") or "").strip()) < 12:
        out.append(NO_WHY)
    return out


def block(kind: str, payload: dict[str, Any], revises: str = "") -> str:
    """The fenced block, as AGOS itself writes it into a card (the Co-Founder's Ask
    mode): the same shape the agents write."""
    raw: dict[str, Any] = {"kind": kind, "payload": payload}
    if revises:
        raw["revises"] = revises
    return f"```{FENCE}\n{json.dumps(raw, ensure_ascii=False, indent=1)}\n```"


def digest(kind: str, payload: dict[str, Any]) -> str:
    """What makes two rounds the same proposal (a replayed block vs a new round)."""
    text = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def label(kind: str, payload: dict[str, Any]) -> str:
    """One line for the card, the push and the Inbox."""
    if kind == "hire":
        who = payload.get("title") or payload.get("name") or "someone"
        return f"Hire a {who}" if payload.get("title") else f"Hire {who}"
    if kind == "kit":
        return f"Kit for @{payload.get('member') or '?'}"
    if kind == "instructions":
        return f"Change its {payload.get('target') or 'instructions'}"
    if kind == "skill":
        return f"Add the skill {payload.get('name') or payload.get('source') or '?'}"
    if kind == "goal":
        title = str(payload.get("title") or "").strip()
        named = f": {title}" if title else ""
        unit = f" {payload.get('unit')}" if payload.get("unit") else ""
        return {
            "suggest_vision": f"Change the Vision: {title}",
            "set_goal": f"Set the workspace goal: {title}",
            "add_goal": f"Add the goal: {title}",
            "update_goal": f"Change goal #{payload.get('goal_id')}{named}",
            "drop_goal": f"Drop goal #{payload.get('goal_id')}",
            "add_subgoal": f"Add the sub-goal: {title}",
            "update_subgoal": f"Change sub-goal #{payload.get('goal_id')}{named}",
            "drop_subgoal": f"Drop sub-goal #{payload.get('goal_id')}",
            "add_kr": f"Add the key result: {title}",
            "update_kr": f"Change key result #{payload.get('kr_id')}{named}",
            "drop_kr": f"Drop key result #{payload.get('kr_id')}",
            "kr_update": f"Key result #{payload.get('kr_id')} is now "
            f"{_shown_number(payload.get('current'))}{unit}",
            "add_project": f"Add the project: {title}",
            "update_project": f"Change project #{payload.get('project_id')}{named}",
            "drop_project": f"Drop project #{payload.get('project_id')}",
            "delete_goal": f"Delete goal #{payload.get('goal_id')}{named}",
            "delete_kr": f"Delete key result #{payload.get('kr_id')}{named}",
            "delete_project": f"Delete project #{payload.get('project_id')}{named}",
            "daily_plan": f"Today's plan ({payload.get('date') or 'today'})",
        }.get(str(payload.get("change") or ""), "Change the goal")
    return f"Plan: {payload.get('title') or 'untitled'}"


def marker(card: str, round_: int, choice: str) -> str:
    return f"[agos-decision {card} r{round_}: {choice}]"


def read_marker(comment: str) -> tuple[str, int, str] | None:
    """(card, round, choice) when a comment is one of AGOS's decision comments."""
    found = _MARK.match(comment.strip())
    if found is None:
        return None
    return found["card"], int(found["round"]), found["choice"]


def _shown_number(value: Any) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else f"{value:g}"
    return str(value or "?")


def decision_text(kind: str, choice: str, note: str = "", change: str = "") -> str:
    """The words under the marker: what the agent reads when its card goes on."""
    if change == "daily_plan":
        if choice == "approve":
            return (
                "The owner accepted today's plan: AGOS created today's cards (and his own "
                "list); this card is done."
            )
        if choice == "revise":
            return (
                "The owner wants today's plan changed"
                + (f": {note.strip()}" if note.strip() else "")
                + ". Propose it again with agos_goals (action propose, kind daily_plan) and "
                '"revises": "<this card>"; the new plan replaces this one.'
            )
        return "The owner skipped today's plan" + (f": {note.strip()}" if note.strip() else ".")
    if choice == "approve":
        if kind == "hire":
            return "The owner approved this hire: AGOS created the member; this card is done."
        if kind == "kit":
            return (
                "The owner approved this kit: AGOS wrote it into the member's profile and "
                "its Readiness runs now; this card is done."
            )
        if kind == "goal":
            return "The owner approved this goal change: AGOS made it; this card is done."
        if kind == "skill":
            return (
                "The owner approved this skill: AGOS adds it to the workspace; this card is done."
            )
        if kind == "instructions":
            return (
                "The owner approved this change to your instructions. Write the file now "
                "with write_file and the exact content you proposed (its SHA-256 must match "
                "the one in your proposal): the guard lets that one write through once. "
                "Then complete this card."
            )
        return "approved"
    if choice == "revise":
        return (
            "The owner asks for changes"
            + (f": {note.strip()}" if note.strip() else "")
            + ". Propose again on a NEW card (kanban_create with a new agos-proposal block "
            'carrying "revises": "<this card>"), block it the same way, then complete this '
            "card with the new card's id as its result."
        )
    return "The owner rejected this proposal" + (f": {note.strip()}" if note.strip() else ".")
