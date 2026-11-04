"""The Co-Founder's actions for the Automations page: pipeline rules, heartbeats, catch-up, hooks, watched folders.
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.automation import hooks_address
from agos_core.actions.services.cofounder.action_args import (
    Fields,
    Result,
    flag_arg,
    int_arg,
    member_arg,
    text_arg,
)
from agos_core.context import Core

__all__ = [
    "do_catch_up",
    "do_delete_rule",
    "do_hooks_address",
    "do_remove_job",
    "do_restore_automation",
    "do_save_rule",
    "do_set_heartbeat",
    "do_watch_tree",
    "undo_automation",
    "undo_catch_up",
    "undo_heartbeat",
    "undo_hooks_address",
    "undo_rule",
    "undo_watch_tree",
]

# ---- automations ------------------------------------------------------------------------


def _rule(core: Core, ws: str, ref: Any) -> dict[str, Any]:
    from agos_core.actions import pipelines

    wanted = str(ref or "").strip().lower().lstrip("#")
    for r in pipelines.rules(core, ws):
        if str(r["id"]) == wanted or str(r["name"]).strip().lower() == wanted:
            return r
    raise ActionError(f"There is no rule “{ref}” in this workspace.", 404)


_RULE_DATA = ("name", "trigger", "status", "goalId", "label", "action", "member")


def _rule_data(r: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: r.get(k) for k in _RULE_DATA},
        "automationId": r.get("automationId"),
        "text": r.get("text"),
        "enabled": r.get("enabled"),
    }


def do_save_rule(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import pipelines
    from agos_core.actions.cofounder_actions import automation_id_of

    current = _rule(core, ws, p["rule"]) if p.get("rule") else None
    data: dict[str, Any] = _rule_data(current) if current else {"enabled": True}
    for key in ("name", "trigger", "status", "label", "action", "text"):
        if key in p:
            data[key] = text_arg(p, key)
    if "member" in p:
        data["member"] = member_arg(p["member"])
    if "goal_id" in p:
        data["goalId"] = int_arg(p["goal_id"], "the goal") if text_arg(p, "goal_id") else None
    if p.get("automation"):
        data["automationId"] = automation_id_of(core, ws, str(p["automation"]))
    if "enabled" in p:
        data["enabled"] = flag_arg(p["enabled"])
    saved = pipelines.save(core, ws, int(current["id"]) if current else None, data)
    return {"rule": saved["id"], "before": _rule_data(current) if current else None}


def undo_rule(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import pipelines

    if r.get("before") is None:
        pipelines.delete(core, ws, int(r["rule"]))
    elif r.get("deleted"):
        pipelines.save(core, ws, None, dict(r["before"]))
    else:
        pipelines.save(core, ws, int(r["rule"]), dict(r["before"]))


def do_delete_rule(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import pipelines

    current = _rule(core, ws, p["rule"])
    pipelines.delete(core, ws, int(current["id"]))
    return {"rule": current["id"], "before": _rule_data(current), "deleted": True}


def _heartbeat_of(core: Core, ws: str, agent: str) -> dict[str, Any]:
    from agos_core.actions import heartbeat

    for h in heartbeat.list_all(core, ws):
        if h.agent == agent:
            return {"on": h.on, "interval": h.interval or ""}
    raise ActionError(f"There is no member @{agent} in this workspace.", 404)


def _agent_key(value: Any) -> str:
    name = member_arg(value)
    return "" if name.lower() in ("cofounder", "manager", "you", "") else name


def do_set_heartbeat(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import heartbeat

    agent = _agent_key(p["agent"])
    before = _heartbeat_of(core, ws, agent)
    on = flag_arg(p.get("on"))
    interval = text_arg(p, "interval") or str(before["interval"] or "")
    if on and not interval:
        raise ActionError("Give the interval (15m, 1h, 4h or daily).")
    # Off needs no interval (the page keeps its select's value; nothing runs).
    heartbeat.set_heartbeat(core, ws, agent, on=on, interval=interval or "1h")
    return {"agent": agent, "before": before}


def undo_heartbeat(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import heartbeat

    b = r["before"]
    heartbeat.set_heartbeat(
        core, ws, str(r["agent"]), on=bool(b["on"]), interval=str(b["interval"] or "1h")
    )


def do_restore_automation(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import automations
    from agos_core.actions.cofounder_actions import automation_id_of, automation_snapshot

    automation_id = automation_id_of(core, ws, str(p["automation"]))
    before = automation_snapshot(core, ws, automation_id)
    automations.restore(
        core, ws, automation_id, int_arg(p["revision"], "the revision"), "cofounder"
    )
    return {"automation_id": automation_id, "before": before}


def undo_automation(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions.cofounder_actions import automation_snapshot, save_automation

    automation_id = int(r["automation_id"])
    current = automation_snapshot(core, ws, automation_id)
    save_automation(core, ws, automation_id, {**current, **r["before"]})


def do_catch_up(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import catch_up
    from agos_core.actions.cofounder_actions import automation_id_of

    automation_id = automation_id_of(core, ws, str(p["automation"]))
    given = text_arg(p, "catch_up").lower()
    value = "skip" if given in ("skip", "skip it", "no", "false", "off") else given
    value = "once" if value in ("once", "run once", "run it once", "yes", "true", "on") else value
    before = catch_up.set_choice(core, ws, automation_id, value)
    return {"automation_id": automation_id, "before": before}


def undo_catch_up(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import catch_up

    catch_up.set_choice(core, ws, int(r["automation_id"]), str(r["before"]))


def do_remove_job(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import ongoing

    ongoing.remove_job(core, ws, text_arg(p, "job"))
    return {"job": text_arg(p, "job")}


def do_hooks_address(core: Core, ws: str, p: Fields) -> Result:
    before = hooks_address.hooks_address(core)
    hooks_address.save_hooks_address(core, text_arg(p, "url"))
    return {"before": before}


def undo_hooks_address(core: Core, ws: str, r: Result) -> None:
    hooks_address.save_hooks_address(core, str(r["before"] or ""))


def do_watch_tree(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import watchdogs

    card = text_arg(p, "card")
    was = card in watchdogs.by_card(core, ws)
    watchdogs.watch(core, ws, card, on=flag_arg(p.get("on")))
    return {"card": card, "before": was}


def undo_watch_tree(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import watchdogs

    watchdogs.watch(core, ws, str(r["card"]), on=bool(r["before"]))
