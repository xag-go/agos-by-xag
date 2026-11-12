"""Running a Co-Founder action card: do, Undo, bundles, the owner's decision on a card.
Must not: hold any kind's logic (the *_kinds modules and page_actions do).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, Literal

from agos_core.actions import automations as automation_actions
from agos_core.actions import library as library_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.owner_gate import fields_of
from agos_core.actions.services.cofounder import base_ops
from agos_core.actions.services.cofounder.action_cards import _KINDS, _UNDO, _row, _set, _view
from agos_core.actions.services.cofounder.automation_kinds import (
    automation_id_of,
    automation_snapshot,
    changed_automation,
    how_it_runs,
    new_automation,
    put_back,
    save_automation,
)
from agos_core.actions.services.cofounder.chat_mode import _existing
from agos_core.actions.services.cofounder.merges import _changed
from agos_core.actions.services.cofounder.skill_kinds import (
    rename_item,
    restore_item,
    save_library_item,
    undo_skill_here,
    write_rule_doc,
)
from agos_core.actions.services.cofounder.team_kinds import (
    _file,
    _founder,
    _hire,
    _team_file,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.records import CofounderActionView
from agos_core.db.rows import load_json
from agos_core.engine import cofounder_actions as rules

__all__ = [
    "decide",
]

log = logging.getLogger("agos.cofounder_actions")  # the old module's logger (one name)


def _bundle(core: Core, workspace_id: str, p: dict[str, Any]) -> dict[str, Any]:
    """All the card's changes, in order; one fails → the done ones are taken back."""
    done: list[dict[str, Any]] = []
    for item in p.get("items") or []:
        do, fields = str(item["do"]), dict(item.get("fields") or {})
        try:
            result = _do(core, workspace_id, do, fields)
        except Exception as error:
            for d in reversed(done):
                with contextlib.suppress(Exception):
                    _undo(core, workspace_id, d["do"], d["result"])
            what = rules.title_of(rules.Action(do, fields))
            message = error.message if isinstance(error, ActionError) else str(error)
            raise ActionError(f"{what}: {message} — nothing of this card was applied.") from error
        done.append({"do": do, "result": result})
    return {"items": done}


def _do(core: Core, workspace_id: str, action: str, p: dict[str, Any]) -> dict[str, Any]:
    """Runs one action; returns what Undo needs."""
    if action == rules.BUNDLE:
        return _bundle(core, workspace_id, p)
    from agos_core.actions import cofounder_hermes

    if action in (*cofounder_hermes.DOES, *cofounder_hermes.REPORTS):
        return cofounder_hermes.do(core, workspace_id, action, p)
    from agos_core.actions import cofounder_more

    if action in cofounder_more.KINDS and action not in base_ops.NAMES:
        return cofounder_more.do(core, workspace_id, action, p)
    if action == "hire_agent":
        return _hire(core, workspace_id, p)
    if action == "create_agent":
        # The old way to a new agent (a name and a text). An agent of that name is
        # changed as before; a NEW one is the same hire card now, with the same
        # checks (its text is the hire's role).
        if _existing(core, workspace_id, "agent", str(p.get("name") or "")) is not None:
            return save_library_item(core, workspace_id, "agent", p, creating=True)
        role = p.get("role") or p.get("instructions") or ""
        return _hire(core, workspace_id, {**p, "role": role}, old=True)
    if action in ("assign_founder", "founder_done"):
        return _founder(core, workspace_id, action, p)
    if action == "update_doc":
        return write_rule_doc(core, workspace_id, p)
    if action == "update_file":
        return _file(core, workspace_id, p)
    if action == "add_owner_rule":
        from agos_core.actions import owner_rules

        new = owner_rules.add(core, str(p["text"]), from_workspace=workspace_id)
        return {"rule_id": new, "rule_key": owner_rules.key_of(core, new)}
    if action == "add_method":
        from agos_core.actions import brain

        return {"method_id": brain.add(core, str(p["text"]), from_workspace=workspace_id)}
    if action == "create_automation":
        spec = new_automation(core, workspace_id, p)
        new_id = save_automation(core, workspace_id, None, spec)
        return {"automation_id": new_id, "report": how_it_runs(core, workspace_id, new_id)}
    if action.startswith(("create_", "update_")) and action.split("_", 1)[1] in _KINDS:
        return save_library_item(
            core,
            workspace_id,
            action.split("_", 1)[1],
            p,
            creating=action.startswith("create_"),
        )
    if action == "rename":
        return rename_item(core, workspace_id, str(p["kind"]), str(p["name"]), str(p["title"]))
    automation_id = automation_id_of(core, workspace_id, str(p["automation"]))
    before = automation_snapshot(core, workspace_id, automation_id)
    kept: dict[str, Any] = before  # a delete: the whole job (H: cron/jobs.py remove_job)
    if action == "update_automation":
        after = changed_automation(before, p)
        if after == before:
            # Never a "done" card for a change that changed nothing.
            raise ActionError(
                f"Nothing changed in “{before.get('name')}”: it is already like this, "
                "or the change wasn't readable."
            )
        save_automation(core, workspace_id, automation_id, after)
        return {
            "automation_id": automation_id,
            "before": _changed(before, after),
            "report": how_it_runs(core, workspace_id, automation_id),
        }
    elif action in ("pause_automation", "resume_automation"):
        automation_actions.toggle(core, workspace_id, automation_id, action == "resume_automation")
        kept = {"on": before.get("on")}
    elif action == "run_automation":
        automation_actions.run_now(core, workspace_id, automation_id)
        return {"automation_id": automation_id}
    elif action == "delete_automation":
        automation_actions.delete(core, workspace_id, automation_id)
    return {"automation_id": automation_id, "before": kept}


def _undo(core: Core, workspace_id: str, action: str, result: dict[str, Any]) -> None:
    if action == rules.BUNDLE:
        for d in reversed(result.get("items") or []):
            if d["do"] in _UNDO:
                _undo(core, workspace_id, str(d["do"]), d["result"])
        return
    from agos_core.actions import cofounder_hermes

    if action in cofounder_hermes.DOES:
        cofounder_hermes.undo(core, workspace_id, action, result)
        return
    from agos_core.actions import cofounder_more

    if action in cofounder_more.KINDS and action not in base_ops.NAMES:
        cofounder_more.undo(core, workspace_id, action, result)
        return
    if action == "assign_founder":
        from agos_core.actions import kanban_board

        # The task taken back: Hermes's archive of its card (gone from his lists).
        kanban_board.act(core, workspace_id, str(result["card"]), "archive")
        return
    automation_id = result.get("automation_id")
    if action == "add_owner_rule":
        from agos_core.actions import owner_rules

        owner_rules.delete_by_key(core, str(result.get("rule_key") or ""), int(result["rule_id"]))
        return
    if action == "add_method":
        from agos_core.actions import brain

        brain.delete(core, int(result["method_id"]))
        return
    if action == "hire_agent" or (action == "create_agent" and result.get("proposed")):
        from agos_core.actions import proposals

        if result.get("proposed") or not result.get("member_id"):
            raise ActionError("A proposal isn't undone: reject it in the Inbox.", 409)
        proposals.unhire(core, workspace_id, result)
        return
    if action == "update_file":
        target = _team_file(core, workspace_id, str(result["path"]))
        if result.get("before") is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(str(result["before"]))
        return
    if action == "update_doc":
        from agos_core.actions import docs

        path = str(result["path"])
        if result.get("before") is None:
            docs.delete_doc(core, workspace_id, path, "undo of the Co-Founder's change")
        else:
            docs.save_doc(
                core, workspace_id, path, str(result["before"]), "undo of the Co-Founder's change"
            )
        return
    if action == "rename":
        library_actions.rename_item(core, int(result["item_id"]), str(result["before"]))
    elif action == "create_automation":
        automation_actions.delete(core, workspace_id, int(automation_id or 0))
    elif action.startswith(("create_", "update_")) and action.split("_", 1)[1] in _KINDS:
        if result.get("copy"):
            undo_skill_here(core, workspace_id, result)
        elif "kind" in result:
            restore_item(core, workspace_id, result)
        else:  # made before updates existed
            library_actions.delete_item(core, int(result["item_id"]))
    elif action == "update_automation":
        # The fields it changed, back onto the job as Hermes has it now.
        current = automation_snapshot(core, workspace_id, int(automation_id or 0))
        put_back(core, workspace_id, int(automation_id or 0), {**current, **result["before"]})
    elif action in ("pause_automation", "resume_automation"):
        automation_actions.toggle(
            core, workspace_id, int(automation_id or 0), bool(result["before"].get("on"))
        )
    elif action == "delete_automation":
        put_back(core, workspace_id, None, result["before"])


def _run(core: Core, row: Any) -> None:
    try:
        # What its card says it was held after (read vs act) is not one of its fields.
        given = fields_of(load_json(row["payload"]) or {})
        result = _do(core, str(row["workspace_id"]), str(row["action"]), given)
    except ActionError as error:
        # Kept whole enough for Hermes's own reasons (they say how to fix it).
        _set(core, int(row["id"]), status="failed", error=error.message[:2000])
        return
    except Exception as error:  # an action must never break the chat
        log.exception("cofounder action %s failed", row["id"])
        _set(core, int(row["id"]), status="failed", error=f"It couldn't be done: {error}"[:600])
        return
    fields: dict[str, Any] = {"status": "done", "error": None, "result": json.dumps(result)}
    if str(row["action"]).startswith("create_") and (
        result.get("before") is not None or result.get("updated")
    ):
        # It already existed and was updated: the card says so.
        fields["title"] = str(row["title"]).replace("Create ", "Update ", 1)
    _set(core, int(row["id"]), **fields)


def _learn(core: Core, workspace_id: str, row: Any, kind: str) -> None:
    from agos_core.actions import proactive

    proactive.record(
        core,
        workspace_id,
        kind=f"{kind} the Co-Founder's action",
        subject=str(row["title"]),
        ref=f"cofounder_action:{row['id']}",
    )


def decide(
    core: Core,
    workspace_id: str,
    action_id: int,
    choice: Literal["approve", "reject", "undo"],
) -> CofounderActionView:
    require_workspace(core, workspace_id)
    row = _row(core, workspace_id, action_id)
    status = row["status"]
    if choice == "undo":
        if status != "done" or row["action"] not in _UNDO:
            raise ActionError("This can't be undone.", 409)
        try:
            _undo(core, workspace_id, str(row["action"]), load_json(row["result"]) or {})
        except ActionError as error:
            raise ActionError(f"Undo didn't work: {error.message}", error.status) from error
        _set(core, action_id, status="undone", error=None)
        _learn(core, workspace_id, row, "undid")
    elif status in ("proposed", "failed"):
        if choice == "reject":
            _set(core, action_id, status="rejected", error=None)
            _learn(core, workspace_id, row, "rejected")
        else:
            _run(core, row)
    return _view(_row(core, workspace_id, action_id))


base_ops.bind(_do, _undo)  # the base kinds also run through the registry
