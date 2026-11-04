"""A member's Readiness checklist: each item's state (keys, apps, topic, onboarding test), the owner's choices, held members.
Must not: change a kit or run the onboarding.

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from agos_core.actions.services.hire.kit_files import _files, _inside
from agos_core.actions.services.hire.kit_rules import required_problems
from agos_core.actions.services.hire.kit_store import (
    _CLOSED,
    ONBOARD_KEY,
    READY_KEY,
    _has_kit,
    kit_of,
)
from agos_core.context import Core
from agos_core.db import chat_addresses
from agos_core.db import member_readiness as readiness_repo
from agos_core.engine import hire_kit as rules

__all__ = [
    "busy_only_onboarding",
    "held",
    "held_names",
    "kit_state",
    "readiness",
    "state_of",
]

log = logging.getLogger("agos.hire_kit")  # the old module's logger (one name)


def kit_state(core: Core, workspace_id: str, member: str, skills: list[str] | None = None) -> str:
    """none / incomplete / whole (engine/hire_kit.py kit_state): the member's kit as
    its profile has it, against the same whole-kit rule a hire meets (`skills`: the
    skills it loads, which count for the library skill)."""
    kit = kit_of(core, workspace_id, member)
    if kit is None or rules.is_empty(kit):
        return "none"
    return (
        "incomplete"
        if required_problems(core, workspace_id, {"kit": kit, "skills": list(skills or [])})
        else "whole"
    )


# ---- the owner's choices -----------------------------------------------------------------


def _choices(core: Core, workspace_id: str, member: str) -> dict[str, Any]:
    return dict(readiness_repo.of_member(core.db, workspace_id, member))


# ---- reading: each item checked for real -------------------------------------------------


def _connected(core: Core, workspace_id: str) -> set[str]:
    """The connector apps on in the workspace's Hermes (its mcp_servers)."""
    from agos_core.actions import hermes_config

    try:
        return set(hermes_config.here(core, workspace_id).apps)
    except Exception:  # unreadable = none known
        log.info("connectors of %s not read", workspace_id, exc_info=True)
        return set()


def _keys(core: Core, workspace_id: str) -> set[str]:
    """The key names Hermes passes to the workspace's tools whose .env line is there."""
    from agos_core.actions import tool_keys
    from agos_core.engine import config_file

    if core.engine is None:
        return set()
    try:
        env = config_file.read_env(core.engine.profile_home(workspace_id))
        return {n for n in tool_keys.names(core, workspace_id) if str(env.get(n) or "").strip()}
    except Exception:  # unreadable = none known
        log.info("keys of %s not read", workspace_id, exc_info=True)
        return set()


def _topic(core: Core, workspace_id: str, member: str) -> bool:
    """The member's DM has its address in the team group (its Telegram topic)."""
    return chat_addresses.dm_has_place(core.db, workspace_id, member)


def _cards(core: Core, workspace_id: str, prefix: str) -> list[dict[str, Any]]:
    from agos_core.actions import kanban_board

    return sorted(kanban_board.keyed(core, workspace_id, prefix), key=lambda c: str(c["key"]))


def _try_number(card: dict[str, Any]) -> int:
    try:
        return int(str(card["key"]).rsplit(":", 1)[-1])
    except ValueError:
        return 0


def _item(
    id_: str,
    kind: str,
    label: str,
    ok: bool,
    how: str,
    *,
    action: str = "none",
    owner: bool = False,
    href: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id_,
        "kind": kind,
        "label": label,
        "ok": ok,
        "state": "ready" if ok else "missing",
        "how": "" if ok else how,
        "action": "none" if ok else action,
        "owner": False if ok else owner,
        "href": None if ok else href,
        "route": None,
        "reason": "",
    }


def _items(core: Core, workspace_id: str, member: str, kit: dict[str, Any]) -> list[dict[str, Any]]:
    from agos_core.actions import agent_profiles, proposals, team

    base = f"/w/{workspace_id}"
    agent = team.get(core, workspace_id, member)
    on = agent is not None and agent.on
    model = agent_profiles.model_of(core, workspace_id, agent) if agent is not None else None
    items = [
        _item(
            "model",
            "model",
            # The one Hermes runs it on: its own (the hire's choice), else the workspace's.
            f"Model: {rules.model_line({'model': model[1], 'effort': model[2]})}"
            + ("" if agent is not None and agent.model else " (the workspace's)")
            if model
            else "Model",
            model is not None,
            "No model to run it on: pick one in Edit, or the workspace's model in Settings.",
            action="edit",
            owner=True,
        )
    ]
    if kit.get("telegram_topic"):
        items.append(
            _item(
                "topic",
                "topic",
                "Telegram topic",
                _topic(core, workspace_id, member),
                "Its topic in the team group wasn't made (connect the bot and pick the team "
                "group in Settings → Channels, then Make topic).",
                action="make_topic",
                owner=True,
                href=f"{base}/settings/channels",
            )
        )
    lead = agent.reports_to if agent is not None else ""
    lead_on = not lead or lead in agent_profiles.team_names(core, workspace_id)
    items.append(
        _item(
            "team",
            "team",
            f"Team: reports to {'@' + lead if lead else 'the Co-Founder'}",
            on and lead_on,
            "It is off the team: turn it on in Hierarchy."
            if not on
            else f"Its lead @{lead} isn't on the team: move it under another lead in Hierarchy.",
            action="edit",
            owner=True,
        )
    )
    loaded = set(agent.skills) if agent is not None else set()
    for s in kit.get("skills") or []:
        here = proposals._skill_here(core, workspace_id, s["name"])
        if here:
            how = "In the library: AGOS gives it to the member now."
            action = "wait"
        elif s["source"] == "write":
            how = "To write: the Co-Founder writes it, then it can be tried in Skill Studio."
            action = "write_skill"
        else:
            how = "To find: the Co-Founder searches Hermes's skills hub and the Brain."
            action = "find_skill"
        items.append(
            _item(
                rules.skill_item(s["name"]),
                "skill",
                f"Skill {s['name']}",
                here and s["name"] in loaded,
                how,
                action=action,
                href=f"{base}/settings/learned" if here else None,
            )
        )
    tools = kit.get("tools") or []
    connected = _connected(core, workspace_id) if any(t.get("connector") for t in tools) else set()
    keys = _keys(core, workspace_id) if any(t.get("key") for t in tools) else set()
    for t in tools:
        path = rules.tool_path(t)
        if path == "connector":
            items.append(
                _item(
                    rules.tool_item(t["name"]),
                    "tool",
                    f"{t['name']} (connector {t['connector']})",
                    t["connector"] in connected,
                    f"Connect {t['name']} for this workspace (Settings → Connectors).",
                    action="connect",
                    owner=True,
                    href=f"{base}/settings/connectors",
                )
            )
        elif path == "key":
            items.append(
                _item(
                    rules.tool_item(t["name"]),
                    "tool",
                    f"{t['name']} (API key {t['key']})",
                    t["key"] in keys,
                    f"Needs its API key: add it in Settings → Keys under the name {t['key']}; "
                    "then the member may get a small tool script for it.",
                    action="add_key",
                    owner=True,
                    href=f"{base}/settings/keys",
                )
            )
        else:
            items.append(
                _item(
                    rules.tool_item(t["name"]),
                    "tool",
                    t["name"],
                    False,
                    (
                        f"No connector or API. Proposed: {t['alternative']}"
                        if t.get("alternative")
                        else "No connector or API: the Co-Founder proposes another way, or a task for you."
                    ),
                    action="alternative",
                    owner=True,
                )
            )
    files = _files(core, workspace_id)
    for d in kit.get("docs") or []:
        if d.get("url") and not d.get("path"):
            items.append(_item(rules.doc_item(d), "doc", f"Link: {d['title']}", True, ""))
            continue
        target = _inside(files, rules.doc_target(member, d))
        source = _inside(files, str(d.get("path") or ""))
        has_source = source is not None and source.exists()
        items.append(
            _item(
                rules.doc_item(d),
                "doc",
                f"{'Example' if d.get('kind') == 'example' else 'Doc'}: {d['title']}",
                target is not None and target.exists(),
                "In the workspace's files: AGOS copies it into the member's folder now."
                if has_source
                else f"Not in the workspace's files ({d.get('path')}): the Co-Founder asks you "
                "for it; answer in your Inbox.",
                action="wait" if has_source else "answer",
                owner=not has_source,
                href=None if has_source else f"{base}/inbox",
            )
        )
    return items


def readiness(core: Core, workspace_id: str, member: str) -> dict[str, Any] | None:
    """The member's checklist, each item checked now (None: hired without a kit).
    Reads files and the board's database only: safe in any page view."""
    kit = kit_of(core, workspace_id, member)
    if kit is None or core.engine is None:
        return None
    from agos_core.actions import team

    choices = _choices(core, workspace_id, member)
    items = _items(core, workspace_id, member, kit)
    gaps = _cards(core, workspace_id, f"{READY_KEY}{member}:")
    routes: dict[str, dict[str, str]] = {}
    for card in gaps:
        if card["status"] == "done":
            routes.update(rules.parse_routes(str(card.get("result") or "")))
    for i in items:
        i["route"] = routes.get(i["id"])
        mark = choices.get(i["id"])
        if not i["ok"] and mark is not None and str(mark["choice"]) == "not_needed":
            i["state"], i["reason"], i["owner"], i["action"] = (
                "not_needed",
                str(mark["reason"]),
                False,
                "none",
            )
    missing = [i for i in items if i["state"] == "missing"]
    onboarding = _onboarding(core, workspace_id, member, kit, choices)
    started = "member" in choices and str(choices["member"]["choice"]) == "start_anyway"
    if started:
        state = "ready"
    elif missing:
        state = "not_ready"
    elif onboarding is not None and not (onboarding["passed"] or onboarding["skipped"]):
        state = "onboarding"
    else:
        state = "ready"
    open_gap = next((c for c in reversed(gaps) if c["status"] not in _CLOSED), None)
    return {
        "member": member,
        "title": team.title_of(core, workspace_id, member),
        "state": state,
        "startedAnyway": started,
        "items": items,
        "onboarding": onboarding,
        "gapCard": str(open_gap["id"]) if open_gap else None,
        "kit": kit,
    }


def _onboarding(
    core: Core,
    workspace_id: str,
    member: str,
    kit: dict[str, Any],
    choices: dict[str, Any],
) -> dict[str, Any] | None:
    test = kit.get("onboarding") or {}
    if not str(test.get("task") or "").strip():
        return None
    tries: list[dict[str, Any]] = []
    for card in _cards(core, workspace_id, f"{ONBOARD_KEY}{member}:"):
        grade = choices.get(f"onboard:{card['id']}")
        tries.append(
            {
                "card": str(card["id"]),
                "n": _try_number(card),
                "status": str(card["status"]),
                "grade": str(grade["choice"]) if grade is not None else None,
                "notes": str(grade["reason"]) if grade is not None else "",
            }
        )
    tries.sort(key=lambda t: int(t["n"]))
    failed = sum(1 for t in tries if t["grade"] == "failed")
    last = tries[-1] if tries else None
    skipped = "onboarding" in choices and str(choices["onboarding"]["choice"]) == "skip_test"
    return {
        "task": str(test["task"]),
        "criteria": list(test.get("criteria") or []),
        "tries": tries,
        "passed": any(t["grade"] == "passed" for t in tries),
        "skipped": skipped,
        # Failed every try it gets: the owner decides (Retry, Skip test, Start anyway).
        "escalated": failed >= rules.MAX_TRIES and last is not None and last["grade"] == "failed",
    }


def state_of(
    core: Core, workspace_id: str, member: str
) -> Literal["not_ready", "onboarding", "ready"] | None:
    """not_ready / onboarding / ready (None: no kit)."""
    view = readiness(core, workspace_id, member)
    if view is None:
        return None
    state = str(view["state"])
    if state == "not_ready":
        return "not_ready"
    if state == "onboarding":
        return "onboarding"
    return "ready"


def held(core: Core, workspace_id: str, member: str) -> bool:
    """Kept from work: Hermes's dispatcher starts none of its cards (not ready yet)."""
    return (
        _has_kit(core, workspace_id, member) and state_of(core, workspace_id, member) == "not_ready"
    )


def held_names(core: Core, workspace_id: str, names: list[str]) -> set[str]:
    return {n for n in names if held(core, workspace_id, n)}


def busy_only_onboarding(core: Core, workspace_id: str, member: str) -> bool:
    """Not ready for real work yet (not ready, or still taking its test)."""
    return _has_kit(core, workspace_id, member) and state_of(core, workspace_id, member) in (
        "not_ready",
        "onboarding",
    )
