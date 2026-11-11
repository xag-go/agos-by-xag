"""The Co-Founder's skill, library item and doc actions, and their Undo.
Must not: hold the library logic (actions/library.py does).

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import library as library_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.services.cofounder.chat_mode import _edited, _existing
from agos_core.actions.services.cofounder.merges import merged_reads
from agos_core.context import Core
from agos_core.db import agent_versions as versions_repo
from agos_core.db import library as library_repo
from agos_core.domain.workspace import workspace_id_from_name
from agos_core.engine.library import readable_title, reports_to

__all__ = [
    "rename_item",
    "restore_item",
    "save_library_item",
    "undo_skill_here",
    "write_rule_doc",
]


def _skill_here(core: Core, workspace_id: str, row: Any, p: dict[str, Any]) -> dict[str, Any]:
    """The Co-Founder changes one of this workspace's skills: its one folder, which the
    Co-Founder and every member of the team read (actions/workspace_skills.py), so the
    whole team has the change from its next session. No other workspace has it.
    The change is Hermes's own skill_manage in the workspace's root (only SKILL.md
    and the files named change); the card keeps only Hermes's skill-ledger ids,
    and its Undo is Hermes's rollback_entry."""
    from agos_core.actions import skill_writes, workspace_skills
    from agos_core.engine.library import parse_skill, skill_template

    name = str(row["name"])
    folder = workspace_skills.existing_dir(core, workspace_id, name)
    if core.engine is None or folder is None:
        raise ActionError(f"The skill {name} has nothing in it yet: send create_skill.")
    home = core.engine.profile_home(workspace_id)
    head, body = parse_skill((folder / "SKILL.md").read_text())
    description = str(p.get("description") or head.get("description") or row["summary"] or "")
    files = {str(k): str(v) for k, v in (p.get("files") or {}).items()}
    entries = skill_writes.write(
        core,
        home,
        name,
        folder,
        skill_template(name, description, _edited(body, p)),
        files,
        actor="agent",
    )
    library_actions.apply_workspace(core, workspace_id)  # its playbooks show it
    return {
        "copy": name,
        "own": True,
        "ledger": {"skills": [name], "entries": entries},
        "updated": True,
        "kind": "skill",
    }


def save_library_item(
    core: Core, workspace_id: str, kind: str, p: dict[str, Any], *, creating: bool = False
) -> dict[str, Any]:
    """Creates it, or — when it already exists — updates it in place (same ID, so
    every workspace, chat and task that uses it keeps working). Undo restores it.
    A skill that exists changes in this workspace's one folder (_skill_here)."""
    from agos_core.actions import workspace_skills

    current = _existing(core, workspace_id, kind, str(p.get("name") or ""))
    if kind == "skill" and current is not None and workspace_skills.never_written(core, current):
        # The empty card of an earlier create Hermes refused: nothing to change in
        # it; a create makes the skill now under its name (the card goes then).
        if not creating:
            raise ActionError(
                f"The skill {current['name']} was never written (an earlier create of it "
                "failed), so there is nothing to update: send create_skill with its name, "
                "description and instructions."
            )
        p = {**p, "name": str(current["name"])}
        current = None
    if kind == "skill" and current is not None:
        return _skill_here(core, workspace_id, current, p)
    if kind == "agent" and current is None:
        # Never a new member from here: a new agent is a hire card the owner approves.
        raise ActionError(
            f"This team has no agent named “{p.get('name')}”: a new agent is a hire "
            "(hire_agent with its full kit and model), the owner approves it in his Inbox.",
            404,
        )
    name = (
        str(current["name"])
        if current
        # Per workspace: another project's item of the same name is a different one.
        else workspace_id_from_name(str(p.get("name") or ""))
    )
    old_def = library_repo.definition(current) if current else {}
    title = (
        str(p.get("title") or "").strip()
        or (str(current["title"]) if current else "")
        or readable_title(name)
    )
    summary = str(
        p.get("summary") or p.get("description") or (current["summary"] if current else "") or ""
    )
    if kind == "skill":  # a new one (an existing one changes here: _skill_here)
        from agos_core.engine.library import skill_template

        description = str(p.get("description") or summary)
        definition: dict[str, Any] = {
            "text": skill_template(name, description, _edited("", p)),
            "files": {str(k): str(v) for k, v in (p.get("files") or {}).items() if v != ""},
        }
    elif kind == "agent":
        definition = {
            **old_def,
            "instructions": _edited(str(old_def.get("instructions") or ""), p),
        }
        if "model" in p:
            from agos_core.actions import hire_model

            # Its own model (Hermes's model.* in its profile), checked like a hire's.
            definition["model"] = hire_model.member_model(core, workspace_id, p["model"])
        if "reports_to" in p:
            # The org chart: "" / "cofounder" = under the Co-Founder, else a member's
            # ID (checked when saved: in this workspace, never itself, never a loop).
            definition["reports_to"] = reports_to(p.get("reports_to"))
        if isinstance(p.get("reads"), list) or isinstance(p.get("remove_reads"), list):
            # Added to its list (same path = that one changes); only the paths
            # named in remove_reads go. Never a wipe of what wasn't named.
            definition["reads"] = merged_reads(
                list(old_def.get("reads") or []) if current else [],
                list(p.get("reads") or []),
                [str(x) for x in p.get("remove_reads") or []],
            )
    else:
        definition = {
            **old_def,
            "transport": "http",
            "url": str(p.get("url") or old_def.get("url") or ""),
        }
    before: dict[str, Any] | None = (
        {
            "title": str(current["title"]),
            "summary": str(current["summary"]),
            "definition": old_def,
        }
        if current
        else None
    )
    had: int | None = None
    if kind == "agent" and current is not None:
        # A member's role is its Hermes SOUL.md: AGOS's identity history keeps the
        # one before (team.save -> docs.keep_agent_version; Hermes keeps none), so
        # the card keeps only that row's id.
        had = _last_version(core, workspace_id, name)
    from agos_core.actions import agent_revisions

    with agent_revisions.by("cofounder", "a Co-Founder action card"):
        item_id = library_actions.save_item(
            core,
            int(current["id"]) if current else None,
            kind=kind,  # type: ignore[arg-type]
            name=name,
            title=title,
            summary=summary,
            definition=definition,
            source="created",
            workspace_id=workspace_id,
        )
    if kind == "agent" and current is not None:
        made = _last_version(core, workspace_id, name)
        before = {"version": made if made != had else None}
        was = reports_to(old_def.get("reports_to"))
        if was != reports_to(definition.get("reports_to")):
            before["reports_to"] = was  # Undo puts it back under its old lead
    mine = library_actions.switches(core, workspace_id).get(item_id)
    was_on = bool(mine and mine.on)
    if not was_on:
        library_actions.set_connector(
            core, workspace_id, item_id, on=True, allowed_tools=[], local=""
        )
    return {"item_id": item_id, "before": before, "was_on": was_on, "kind": kind, "name": name}


def _last_version(core: Core, workspace_id: str, name: str) -> int | None:
    return versions_repo.last_id(core.db, workspace_id, name)


def restore_item(core: Core, workspace_id: str, result: dict[str, Any]) -> None:
    """Undo of a create-or-update: back to exactly what it was."""
    item_id = int(result["item_id"])
    before = result.get("before")
    if before is None:
        library_actions.delete_item(core, item_id)
        return
    if "kept_in" in before:
        raise ActionError(
            "The copy this Undo needed was moved to the backups folder "
            f"({before['kept_in']}); it can't be undone from here."
        )
    if "version" in before:
        # A member's role back from AGOS's identity history (which keeps the one
        # it replaces too).
        if before["version"] is not None:
            from agos_core.actions import docs

            docs.restore_agent(core, workspace_id, int(before["version"]))
        if "reports_to" in before:
            from agos_core.actions import team

            team.set_reports_to(core, workspace_id, str(result["name"]), before["reports_to"])
    else:
        library_actions.save_item(
            core,
            item_id,
            kind=str(result["kind"]),  # type: ignore[arg-type]
            name=str(result["name"]),
            title=str(before["title"]),
            summary=str(before["summary"]),
            definition=dict(before["definition"]),
        )
    if not result.get("was_on"):
        library_actions.set_connector(
            core, workspace_id, item_id, on=False, allowed_tools=[], local=""
        )


def write_rule_doc(core: Core, workspace_id: str, p: dict[str, Any]) -> dict[str, Any]:
    """Writes a rule file (a version and a CHANGES.md line); Undo puts it back."""
    from agos_core.actions import docs

    path = str(p["path"]).strip().removeprefix("/workspace/").removeprefix("playbooks/")
    target = docs.folder(core, workspace_id) / path
    before = target.read_text() if target.is_file() else None
    if p.get("text"):
        text = str(p["text"])
    else:
        text = _edited(
            before or "", {"replace": p.get("replace"), "add_instructions": p.get("add")}
        )
    docs.save_doc(core, workspace_id, path, text, str(p["why"]), who="Co-Founder")
    return {"path": path, "before": before}


def _find_item(core: Core, workspace_id: str, kind: str, name: str) -> Any:
    if kind not in ("agent", "skill", "mcp"):
        raise ActionError("Only agents, skills and MCP servers can be renamed this way.")
    row = _existing(core, workspace_id, kind, name)
    if row is None:
        raise ActionError(f"This workspace has no {kind} named “{name}”.", 404)
    return row


def rename_item(core: Core, workspace_id: str, kind: str, name: str, title: str) -> dict[str, Any]:
    row = _find_item(core, workspace_id, kind, name)
    before = str(row["title"])
    library_actions.rename_item(core, int(row["id"]), title, workspace_id)
    return {"item_id": int(row["id"]), "before": before}


def undo_skill_here(core: Core, workspace_id: str, result: dict[str, Any]) -> None:
    """A skill change taken back: Hermes's rollback_entry of the ledger entries the
    change made (refused when the skill changed again since)."""
    if core.engine is None:
        raise ActionError("The engine isn't available.", 503)
    name = str(result["copy"])
    home = core.engine.profile_home(workspace_id)
    ledger = result.get("ledger")
    if not isinstance(ledger, dict):
        kept = (
            (result.get("before") or {}).get("kept_in")
            if isinstance(result.get("before"), dict)
            else None
        )
        raise ActionError(
            f"The copy this Undo needed was moved to the backups folder ({kept}); "
            "it can't be undone from here."
            if kept
            else "This change was made before AGOS kept the skill ledger for it; "
            "there is nothing to roll back with."
        )
    from agos_core.actions import skill_writes

    skill_writes.rollback(
        core,
        home,
        [str(s) for s in ledger.get("skills") or [name]],
        [str(e) for e in ledger.get("entries") or []],
    )
    library_actions.apply_workspace(core, workspace_id)
