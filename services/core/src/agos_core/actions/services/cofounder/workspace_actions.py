"""The Co-Founder's actions for the workspace: Vision rhythm and notes, work hours, docs, agent history, owner rules, Brain methods.
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.cofounder.action_args import (
    Fields,
    Result,
    flag_arg,
    int_arg,
    member_arg,
    text_arg,
)
from agos_core.actions.services.cofounder.skill_actions import _item
from agos_core.context import Core

__all__ = [
    "do_agent_revision",
    "do_delete_doc",
    "do_delete_method",
    "do_delete_owner_rule",
    "do_edit_method",
    "do_edit_owner_rule",
    "do_latin",
    "do_method_here",
    "do_notes",
    "do_organize",
    "do_restore_agent",
    "do_restore_doc",
    "do_rhythm",
    "do_stay_on",
    "do_tick",
    "do_wake_now",
    "do_work_hours",
    "undo_agent_revision",
    "undo_delete_method",
    "undo_delete_owner_rule",
    "undo_doc_text",
    "undo_edit_method",
    "undo_edit_owner_rule",
    "undo_latin",
    "undo_method_here",
    "undo_notes",
    "undo_restore_agent",
    "undo_rhythm",
    "undo_stay_on",
    "undo_work_hours",
]

# ---- workspace: vision, docs, rules -----------------------------------------------------


def do_rhythm(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import rhythm

    which = text_arg(p, "which")
    found = next((j for j in rhythm.list_all(core, ws) if j.get("which") == which), None)
    if found is None:
        raise ActionError("which is daily, recap or weekly.")
    time = str(found.get("time") or "")
    day = int(found["day"]) if found.get("day") is not None else None
    before: dict[str, Any] = {"on": bool(found.get("on")), "time": time, "day": day}
    rhythm.set_job(
        core,
        ws,
        which,
        on=flag_arg(p.get("on")),
        time=text_arg(p, "time") or time,
        day=int_arg(p["day"], "the day") if text_arg(p, "day") else day,
    )
    return {"which": which, "before": before}


def undo_rhythm(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import rhythm

    b = r["before"]
    rhythm.set_job(core, ws, str(r["which"]), on=bool(b["on"]), time=str(b["time"]), day=b["day"])


def do_work_hours(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import work_hours

    before = work_hours.schedule(core, ws)
    days = p.get("days") if isinstance(p.get("days"), dict) else before["days"]
    work_hours.save(core, ws, {"on": flag_arg(p.get("on"), before["on"]), "days": days})
    return {"before": before}


def undo_work_hours(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import work_hours

    work_hours.save(core, ws, dict(r["before"]))


def do_stay_on(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import work_hours

    before = work_hours.view(core, ws)["stay"]
    given = p.get("agents")
    agents = given if isinstance(given, list) else [a for a in str(given or "").split(",") if a]
    work_hours.set_stay(core, ws, [member_arg(a) for a in agents])
    return {"before": before}


def undo_stay_on(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import work_hours

    work_hours.set_stay(core, ws, list(r["before"]))


def do_wake_now(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import work_hours

    before = work_hours.view(core, ws)["stay"]
    work_hours.wake(core, ws, member_arg(p.get("agent")))
    return {"before": before}


def do_notes(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import vision_notes

    before = str(vision_notes.read(core, ws).get("text") or "")
    vision_notes.save(core, ws, str(p["text"]), who="the Co-Founder")
    return {"before": before}


def undo_notes(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import vision_notes

    vision_notes.save(core, ws, str(r["before"]), who="the Co-Founder", why="undo")


def do_organize(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import vision_notes

    found = vision_notes.organize(core, ws)
    return {"report": json.dumps(found, ensure_ascii=False)[:4000]}


def do_tick(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import today

    today.check(core, ws, text_arg(p, "card"))
    return {}


def do_delete_doc(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import docs

    path = text_arg(p, "path").removeprefix("/workspace/").removeprefix("playbooks/")
    before = str(docs.get_doc(core, ws, path).get("text") or "")
    docs.delete_doc(core, ws, path, text_arg(p, "why"))
    return {"path": path, "before": before}


def do_restore_doc(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import docs

    version = int_arg(p["version"], "the version")
    path = str(docs.version_diff(core, ws, version).get("path") or "")
    before = str(docs.get_doc(core, ws, path).get("text") or "") if path else None
    docs.restore(core, ws, version, text_arg(p, "why"), who="Co-Founder")
    return {"path": path, "before": before}


def undo_doc_text(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import docs

    if r.get("before") is None or not r.get("path"):
        raise ActionError("This file had no text before.")
    docs.save_doc(core, ws, str(r["path"]), str(r["before"]), "undo of the Co-Founder's change")


def do_restore_agent(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import docs
    from agos_core.actions.cofounder_actions import _last_version

    version = int_arg(p["version"], "the version")
    name = next(
        (str(v["name"]) for v in docs.agent_versions(core, ws) if int(v["id"]) == version), ""
    )
    if not name:
        raise NotFoundError("This version")
    before = _last_version(core, ws, name)
    docs.restore_agent(core, ws, version)
    return {"before": before}


def undo_restore_agent(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import docs

    if r.get("before") is None:
        raise ActionError("The agent had no kept version before.")
    docs.restore_agent(core, ws, int(r["before"]))


def do_agent_revision(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import agent_revisions

    agent = member_arg(p["agent"])
    _item(core, ws, "agent", agent)
    before = max((r.n for r in agent_revisions.list_for(core, ws, agent)), default=0)
    agent_revisions.restore(core, ws, agent, int_arg(p["revision"], "the revision"), "cofounder")
    return {"agent": agent, "before": before}


def undo_agent_revision(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import agent_revisions

    if not r.get("before"):
        raise ActionError("No revision was kept before.")
    agent_revisions.restore(core, ws, str(r["agent"]), int(r["before"]), "cofounder")


def do_latin(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import docs

    before = docs.latin_only(core, ws)
    docs.set_latin_only(core, ws, flag_arg(p.get("on")))
    return {"before": before}


def undo_latin(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import docs

    docs.set_latin_only(core, ws, bool(r["before"]))


def _rule_text(core: Core, rule: int) -> str:
    from agos_core.actions import owner_rules

    found = next((r for r in owner_rules.list_rules(core) if int(r["id"]) == rule), None)
    if found is None:
        raise NotFoundError("This rule")
    return str(found["text"])


def do_edit_owner_rule(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import owner_rules

    rule = int_arg(p["rule"], "the rule")
    before = owner_rules.edit(core, rule, text_arg(p, "text"))
    return {"rule": owner_rules.rule_id(text_arg(p, "text")), "before": before}


def undo_edit_owner_rule(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import owner_rules

    owner_rules.edit(core, int(r["rule"]), str(r["before"]))


def do_delete_owner_rule(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import owner_rules

    rule = int_arg(p["rule"], "the rule")
    before = _rule_text(core, rule)
    owner_rules.delete(core, rule)
    return {"before": before}


def undo_delete_owner_rule(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import owner_rules

    owner_rules.add(core, str(r["before"]), from_workspace=ws)


def _method_text(core: Core, method: int) -> str:
    from agos_core.actions import brain

    found = next((m for m in brain.list_methods(core) if int(m["id"]) == method), None)
    if found is None:
        raise NotFoundError("This method")
    return str(found["text"])


def do_edit_method(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import brain

    method = int_arg(p["method"], "the method")
    before = _method_text(core, method)
    brain.edit(core, method, text_arg(p, "text"))
    return {"method": method, "before": before}


def undo_edit_method(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import brain

    brain.edit(core, int(r["method"]), str(r["before"]))


def do_delete_method(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import brain

    method = int_arg(p["method"], "the method")
    before = _method_text(core, method)
    brain.delete(core, method)
    return {"before": before}


def undo_delete_method(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import brain

    brain.add(core, str(r["before"]), from_workspace=ws)


def do_method_here(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import brain

    method = int_arg(p["method"], "the method")
    before = next(
        (bool(m["usedHere"]) for m in brain.list_methods(core, ws) if int(m["id"]) == method),
        None,
    )
    if before is None:
        raise NotFoundError("This method")
    brain.set_used_here(core, ws, method, flag_arg(p.get("used")))
    return {"method": method, "before": before}


def undo_method_here(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import brain

    brain.set_used_here(core, ws, int(r["method"]), bool(r["before"]))
