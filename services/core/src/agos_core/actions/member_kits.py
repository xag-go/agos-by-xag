"""A kit for a member already on the team ("Suggest kit" on Hierarchy and on the
member's Readiness tab).

Members hired before kits existed (step 62) have none; others may have one with a
part missing. AGOS finds them (`state`: none / incomplete / whole, the same
whole-kit rule a hire meets: engine/hire_kit.py kit_missing). The owner's "Suggest
kit" puts ONE Hermes Kanban card on the Co-Founder (like "Suggest hires"): it reads
the member (its role, skills, model, latest cards), follows its team-design skill and
sends the kit with agos_propose kind "kit". That proposal is checked like a hire's kit
(actions/proposals.py check_new) and waits in the owner's Inbox as 'Kit for @x':
Edit kit, then Approve / Revise / Reject. Approve writes it with the hire's own code
(`apply`: the model and library skills through the team's save, the kit through
actions/hire_kit.py provision: the profile fact, copied files, its SOUL's 'Your team',
one memory entry, then Readiness), keeps the member's memory and sessions, and keeps
what Undo needs. AGOS keeps no copy of the ask: the card is found again on Hermes's
board by its idempotency key's prefix; while one is open (or its proposal waits) a
second ask returns it. "Suggest kits for all" makes one card per member, each waiting
on the one before (Hermes starts the next once the last is done), at most MAX_ALL per
press, so the Co-Founder works them one at a time.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.engine import hire_kit as rules

KEY = "agos-suggest-kit:"  # + member + ":" + the ask's time (ms)
MAX_ALL = 10  # cards one "Suggest kits for all" makes (the rest on the next press)
_CLOSED = frozenset({"done", "archived"})
_lock = threading.Lock()


# ---- who lacks a kit -------------------------------------------------------------------


def state(core: Core, workspace_id: str, member: str, skills: list[str] | None = None) -> str:
    """none / incomplete / whole."""
    from agos_core.actions import hire_kit

    return hire_kit.kit_state(core, workspace_id, member, skills)


def lacking(core: Core, workspace_id: str) -> list[str]:
    """The members on the team without a whole kit, in the team's order."""
    from agos_core.actions import team

    return [
        a.name
        for a in team.members(core, workspace_id, on_only=True)
        if state(core, workspace_id, a.name, a.skills) != "whole"
    ]


def _waiting_proposals(core: Core, workspace_id: str) -> dict[str, str]:
    """member -> the card of its kit proposal waiting in the Inbox."""
    out: dict[str, str] = {}
    for r in kanban_asks.waiting_payloads(core.db, workspace_id, "kit"):
        try:
            payload = json.loads(r["payload"] or "{}")
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("member"):
            out.setdefault(str(payload["member"]), str(r["card"]))
    return out


def _open_asks(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    from agos_core.actions import kanban_board

    found = [c for c in kanban_board.keyed(core, workspace_id, KEY) if c["status"] not in _CLOSED]
    return sorted(found, key=lambda c: str(c["key"]))


def _member_of_key(key: str) -> str:
    return key[len(KEY) :].rsplit(":", 1)[0]


def open_cards(core: Core, workspace_id: str) -> dict[str, str]:
    """member -> the card that already carries its kit: the Co-Founder's ask still
    open on the board, else its proposal waiting for the owner."""
    out = _waiting_proposals(core, workspace_id)
    for c in _open_asks(core, workspace_id):
        out[_member_of_key(str(c["key"]))] = str(c["id"])
    return out


# ---- the ask -----------------------------------------------------------------------------


def _body(core: Core, workspace_id: str, member: str, note: str) -> str:
    from agos_core.actions import agent_profiles, hire_kit, kanban_board, team

    agent = team.get(core, workspace_id, member)
    assert agent is not None
    kit = hire_kit.kit_of(core, workspace_id, member)
    model = agent_profiles.model_of(core, workspace_id, agent)
    missing = (
        hire_kit.required_problems(core, workspace_id, {"kit": kit, "skills": agent.skills})
        if kit
        else []
    )
    shown = {k: v for k, v in (kit or {}).items() if k not in ("goal_id", "telegram_topic")}
    return rules.suggest_body(
        member=member,
        title=agent.title,
        role=agent.instructions,
        skills=list(agent.skills),
        model=rules.model_line({"model": model[1], "effort": model[2]}) if model else "",
        kit=shown or None,
        missing=missing,
        cards=kanban_board.latest_of(core, workspace_id, member),
        note=note,
    )


def _make(core: Core, workspace_id: str, member: str, note: str, parents: list[str] | None) -> str:
    from agos_core.actions import kanban_board

    return kanban_board.create(
        core,
        workspace_id,
        f"Suggest a kit for @{member}",
        _body(core, workspace_id, member, note),
        kanban_board.COFOUNDER,
        parents=parents or None,
        once=f"{KEY}{member}:{time.time_ns() // 1_000_000}",
    )


def ask(core: Core, workspace_id: str, member: str, note: str = "") -> tuple[str, bool]:
    """(the card, made now): a card on the Co-Founder for @member's whole kit; while
    one is open, or its proposal waits for the owner, that one (nothing new)."""
    from agos_core.actions import team
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    agent = team.get(core, workspace_id, member)
    if agent is None:
        raise NotFoundError("This member")
    with _lock:
        found = open_cards(core, workspace_id).get(member)
        if found is not None:
            return found, False
        if state(core, workspace_id, member, agent.skills) == "whole":
            raise ActionError(
                f"@{member} already has its whole kit: edit it on its Readiness.", 409
            )
        return _make(core, workspace_id, member, note, None), True


def ask_all(core: Core, workspace_id: str, note: str = "") -> dict[str, Any]:
    """One card per member without a whole kit (not those already asked), each
    waiting on the one before so the Co-Founder takes them one at a time; at most
    MAX_ALL now (`left`: how many the next press asks for)."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    with _lock:
        have = open_cards(core, workspace_id)
        todo = [m for m in lacking(core, workspace_id) if m not in have]
        opened = _open_asks(core, workspace_id)
        last = str(opened[-1]["id"]) if opened else None
        asked: list[dict[str, str]] = []
        for member in todo[:MAX_ALL]:
            last = _make(core, workspace_id, member, note, [last] if last else None)
            asked.append({"member": member, "card": last})
    return {
        "asked": asked,
        "already": [{"member": m, "card": c} for m, c in have.items()],
        "left": max(0, len(todo) - MAX_ALL),
    }


# ---- the proposal --------------------------------------------------------------------------


def required(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """What a kit for this member lacks of a whole kit (the skills it loads count)."""
    from agos_core.actions import hire_kit, team

    agent = team.get(core, workspace_id, str(payload.get("member") or ""))
    skills = list(agent.skills) if agent is not None else []
    return hire_kit.required_problems(
        core, workspace_id, {"kit": payload.get("kit"), "skills": skills}
    )


def problems(
    core: Core, workspace_id: str, payload: dict[str, Any], *, kept_ok: bool = False, new: bool
) -> list[str]:
    """What keeps a kit proposal from being made (`new`) or approved: a member of
    this team, no other kit for it waiting, its whole kit (tools mapped to Hermes's
    connectors in place), its whole model (resolved in place) and model_why."""
    from agos_core.actions import agent_profiles, hire_kit, hire_model, team_design

    out = []
    member = str(payload.get("member") or "")
    if member and member not in agent_profiles.team_names(core, workspace_id):
        out.append(f"member: there is no member named {member} on this team")
        return out
    if new:
        team_design.ensure(core, workspace_id)
        waiting = _waiting_proposals(core, workspace_id).get(member)
        if waiting:
            out.append(
                f"a kit for @{member} already waits for the owner (card {waiting}): wait "
                "for his answer"
            )
    out += hire_model.check(core, workspace_id, payload, kept_ok=kept_ok, hire=True)
    if isinstance(payload.get("kit"), dict):
        payload["kit"] = hire_kit.fill(core, workspace_id, payload["kit"])
        out += hire_kit.kit_problems(core, workspace_id, payload["kit"])
    out += required(core, workspace_id, payload)
    return out


# ---- what the owner's Approve writes, and its Undo --------------------------------------


def _same_model(a: Any, b: Any) -> bool:
    def key(m: Any) -> tuple[str, str]:
        return (
            (str(m.get("model") or ""), str(m.get("effort") or ""))
            if isinstance(m, dict)
            else ("", "")
        )

    return key(a) == key(b)


def _write_member(
    core: Core, workspace_id: str, agent: Any, model: Any, skills: list[str], why: str
) -> None:
    """The member's model and skills, through the team's own save (its Hermes
    profile: model.*, agent.reasoning_effort, skills), recorded as a revision."""
    from agos_core.actions import agent_revisions
    from agos_core.actions import library as library_actions

    with agent_revisions.by("owner", why):
        library_actions.save_item(
            core,
            agent.id,
            kind="agent",
            name=agent.name,
            title=agent.title,
            summary=agent.summary,
            definition={**agent.definition, "model": model, "skills": skills},
            workspace_id=workspace_id,
        )


def apply(core: Core, workspace_id: str, payload: dict[str, Any], card: str) -> dict[str, Any]:
    """The owner approved 'Kit for @x': its model and the kit's library skills go
    into the member, then its kit is provisioned as a hire's is (fresh=False: his
    earlier Readiness choices stay). Its memory, sessions and role text stay.
    Returns what Undo needs."""
    from agos_core.actions import hire_kit, team

    member = str(payload.get("member") or "")
    agent = team.get(core, workspace_id, member)
    if agent is None:
        raise NotFoundError("This member")
    before_kit = hire_kit.kit_of(core, workspace_id, member)
    kit = hire_kit.fill(core, workspace_id, dict(payload.get("kit") or {}))
    wrong = hire_kit.kit_problems(core, workspace_id, kit) + required(
        core, workspace_id, {"member": member, "kit": kit}
    )
    if wrong:
        raise ActionError("; ".join(wrong))
    for key in ("goal_id", "telegram_topic"):
        if before_kit and key in before_kit:
            kit[key] = before_kit[key]
    raw = payload.get("model") if isinstance(payload.get("model"), dict) else None
    model = (
        {k: raw[k] for k in rules.MODEL_KEYS if k in raw}
        if raw and raw.get("model")
        else agent.model
    )
    skills = [*agent.skills]
    skills += [s for s in hire_kit.library_skills(core, workspace_id, kit) if s not in skills]
    before = {"model": agent.model, "skills": list(agent.skills)}
    if not _same_model(model, agent.model) or skills != list(agent.skills):
        _write_member(core, workspace_id, agent, model, skills, f"approved its kit (card {card})")
    shown = hire_kit.provision(core, workspace_id, member, kit, fresh=False)
    return {
        "kit_for": member,
        "before_kit": before_kit,
        "before": before,
        "readiness": shown["state"] if shown else None,
    }


def undo(core: Core, workspace_id: str, result: dict[str, Any]) -> None:
    """Back to how the member was before the approve: its model and skills, and its
    old kit (none: the kit fact goes). Files copied into its folder stay."""
    from agos_core.actions import hire_kit, team

    member = str(result.get("kit_for") or "")
    agent = team.get(core, workspace_id, member)
    if agent is None:
        raise NotFoundError("This member")
    before: dict[str, Any] = result["before"] if isinstance(result.get("before"), dict) else {}
    model = before.get("model")
    skills = [str(s) for s in before.get("skills") or []]
    if not _same_model(model, agent.model) or skills != list(agent.skills):
        _write_member(core, workspace_id, agent, model, skills, "undid its kit")
    old = result.get("before_kit")
    if isinstance(old, dict) and old:
        hire_kit.provision(core, workspace_id, member, old, fresh=False)
    else:
        hire_kit.drop_kit(core, workspace_id, member)
