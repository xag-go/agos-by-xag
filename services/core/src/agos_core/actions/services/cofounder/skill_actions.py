"""The Co-Founder's actions for Skill Studio and the Library: items, versions, test inputs and runs, MCP sign-in.
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
from agos_core.context import Core

__all__ = [
    "do_add_input",
    "do_apply_update",
    "do_auto_update",
    "do_delete_input",
    "do_delete_item",
    "do_duplicate",
    "do_github_token",
    "do_grade_test",
    "do_install_skill",
    "do_mcp_sign_in",
    "do_mcp_sign_out",
    "do_request_limit",
    "do_rerun_test",
    "do_restore_version",
    "do_run_test",
    "do_skill_review",
    "do_test_settings",
    "do_update_input",
    "undo_add_input",
    "undo_auto_update",
    "undo_delete_input",
    "undo_duplicate",
    "undo_request_limit",
    "undo_skill_review",
    "undo_test_settings",
    "undo_update_input",
    "undo_version",
]

# ---- skills -----------------------------------------------------------------------------


def _item(core: Core, ws: str, kind: str, name: Any) -> Any:
    from agos_core.actions.cofounder_actions import _existing

    if kind not in ("skill", "agent", "mcp"):
        raise ActionError("kind is skill, agent or mcp.")
    row = _existing(core, ws, kind, str(name or ""))
    if row is None:
        raise ActionError(f"This workspace has no {kind} named “{name}”.", 404)
    return row


def _skill_id(core: Core, ws: str, name: Any) -> int:
    return int(_item(core, ws, "skill", name)["id"])


def do_delete_item(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import library, workspace_skills

    kind = text_arg(p, "kind").lower()
    row = _item(core, ws, kind, p["name"])
    if kind == "skill":
        workspace_skills.delete(core, ws, int(row["id"]))
    else:
        library.delete_item(core, int(row["id"]), ws)
    return {"kind": kind, "name": str(row["name"])}


def do_duplicate(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import workspace_skills

    new = workspace_skills.duplicate(
        core, ws, _skill_id(core, ws, p["name"]), text_arg(p, "new_name")
    )
    return {"item_id": new}


def undo_duplicate(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import workspace_skills

    workspace_skills.delete(core, ws, int(r["item_id"]))


def do_apply_update(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_versions, workspace_skills

    row = _item(core, ws, "skill", p["name"])
    before = skill_versions.current(core, ws, str(row["name"]))
    workspace_skills.apply_update(core, ws, int(row["id"]))
    return {"item_id": int(row["id"]), "before": before}


def do_restore_version(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_versions

    row = _item(core, ws, "skill", p["name"])
    before = skill_versions.current(core, ws, str(row["name"]))
    skill_versions.restore(core, ws, int(row["id"]), int_arg(p["version"], "the version"))
    return {"item_id": int(row["id"]), "before": before}


def undo_version(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_versions

    if not r.get("before"):
        raise ActionError("No version was known before: pick one in its Versions.")
    skill_versions.restore(core, ws, int(r["item_id"]), int(r["before"]))


def do_auto_update(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_updates
    from agos_core.db import library as library_repo

    item_id = _skill_id(core, ws, p["name"])
    before = skill_updates.is_on(library_repo.get_item(core.db, item_id))
    skill_updates.set_flag(core, ws, item_id, flag_arg(p.get("on")))
    return {"item_id": item_id, "before": before}


def undo_auto_update(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_updates

    skill_updates.set_flag(core, ws, int(r["item_id"]), bool(r["before"]))


def do_test_settings(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests
    from agos_core.db import skill_tests as repo

    item_id = _skill_id(core, ws, p["name"])
    before = dict(repo.settings(core.db, item_id))
    skill_tests.save_settings(
        core,
        ws,
        item_id,
        template=text_arg(p, "template", before["template"]),
        checklist=text_arg(p, "checklist", before["checklist"]),
    )
    return {"item_id": item_id, "before": before}


def undo_test_settings(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_tests

    b = r["before"]
    skill_tests.save_settings(
        core, ws, int(r["item_id"]), template=str(b["template"]), checklist=str(b["checklist"])
    )


def _input_of(core: Core, item_id: int, input_id: int) -> dict[str, str]:
    from agos_core.db import skill_tests as repo

    for i in repo.inputs(core.db, item_id):
        if int(i["id"]) == input_id:
            return {
                "name": str(i["name"]),
                "text": str(i["text"]),
                "expected": str(i["expected"] or ""),
            }
    raise NotFoundError("This test input")


def do_add_input(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    item_id = _skill_id(core, ws, p["name"])
    new = skill_tests.add_input(
        core,
        ws,
        item_id,
        name=text_arg(p, "input_name"),
        text=text_arg(p, "text"),
        expected=text_arg(p, "expected"),
    )
    return {"item_id": item_id, "input": new}


def undo_add_input(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_tests

    skill_tests.delete_input(core, ws, int(r["item_id"]), int(r["input"]))


def do_update_input(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    item_id = _skill_id(core, ws, p["name"])
    input_id = int_arg(p["input"], "the input")
    before = _input_of(core, item_id, input_id)
    skill_tests.update_input(
        core,
        ws,
        item_id,
        input_id,
        name=text_arg(p, "input_name", before["name"]),
        text=text_arg(p, "text", before["text"]),
        expected=text_arg(p, "expected", before["expected"]),
    )
    return {"item_id": item_id, "input": input_id, "before": before}


def undo_update_input(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_tests

    b = r["before"]
    skill_tests.update_input(
        core,
        ws,
        int(r["item_id"]),
        int(r["input"]),
        name=str(b["name"]),
        text=str(b["text"]),
        expected=str(b["expected"]),
    )


def do_delete_input(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    item_id = _skill_id(core, ws, p["name"])
    input_id = int_arg(p["input"], "the input")
    before = _input_of(core, item_id, input_id)
    skill_tests.delete_input(core, ws, item_id, input_id)
    return {"item_id": item_id, "before": before}


def undo_delete_input(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_tests

    b = r["before"]
    skill_tests.add_input(
        core,
        ws,
        int(r["item_id"]),
        name=str(b["name"]),
        text=str(b["text"]),
        expected=str(b["expected"]),
    )


def do_run_test(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    run = skill_tests.run(
        core,
        ws,
        _skill_id(core, ws, p["name"]),
        input_id=int_arg(p["input"], "the input"),
        member=member_arg(p.get("member")) or "cofounder",
    )
    return {"report": f"Test run {run} started on its own card; grade it when it is done."}


def do_rerun_test(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    run = skill_tests.rerun(core, ws, _skill_id(core, ws, p["name"]), int_arg(p["run"], "the run"))
    return {"report": f"Test run {run} started again on a new card."}


def do_grade_test(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_tests

    found = skill_tests.regrade(
        core, ws, _skill_id(core, ws, p["name"]), int_arg(p["run"], "the run")
    )
    return {"report": json.dumps(found, ensure_ascii=False)[:4000]}


def do_request_limit(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_requests

    before = skill_requests.limit(core, ws)
    skill_requests.set_limit(core, ws, int_arg(p["limit"], "the limit"))
    return {"before": before}


def undo_request_limit(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_requests

    skill_requests.set_limit(core, ws, int(r["before"]))


def do_skill_review(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import skill_growth

    job = skill_growth.job(core, ws)
    time, day = str(job["time"]), int(job["day"])
    before: dict[str, Any] = {"on": bool(job["on"]), "time": time, "day": day}
    skill_growth.set_job(
        core,
        ws,
        on=flag_arg(p.get("on")),
        time=text_arg(p, "time") or time,
        day=int_arg(p["day"], "the day") if text_arg(p, "day") else day,
    )
    return {"before": before}


def undo_skill_review(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import skill_growth

    b = r["before"]
    skill_growth.set_job(core, ws, on=bool(b["on"]), time=str(b["time"]), day=int(b["day"]))


def do_install_skill(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import workspace_skills

    done = workspace_skills.install_web(
        core, ws, text_arg(p, "identifier"), force=flag_arg(p.get("force"), default=False)
    )
    return {"report": json.dumps(done.model_dump(by_alias=True), ensure_ascii=False)[:2000]}


def _mcp_id(core: Core, ws: str, name: Any) -> int:
    return int(_item(core, ws, "mcp", name)["id"])


def do_mcp_sign_in(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import mcp_signin

    found = mcp_signin.start(core, ws, _mcp_id(core, ws, p["name"]))
    if found.get("url"):
        return {"report": f"Send the owner this sign-in page: {found['url']}"}
    return {"report": str(found.get("error") or found.get("status") or "")}


def do_mcp_sign_out(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import mcp_signin

    mcp_signin.sign_out(core, ws, _mcp_id(core, ws, p["name"]))
    return {}


def do_github_token(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import library

    library.remove_github_token(core)
    return {}
