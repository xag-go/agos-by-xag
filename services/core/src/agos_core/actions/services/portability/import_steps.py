"""Importing each piece through the normal AGOS paths: folders, skills, agents, automations, Vision, keys.
Must not: run the whole import (apply does).

Split out of agos_core.actions.portability (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.portability.import_report import Plan, Report, _said
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import library as library_repo
from agos_core.domain.models import ModelSelection
from agos_core.engine import bundle as fmt
from agos_core.engine.hermes import EngineError

__all__ = [
    "import_agents",
    "import_automations",
    "import_folders",
    "import_keys",
    "import_skills",
    "import_vision",
]


def import_folders(core: Core, ws: str, found: fmt.Parsed, report: Report) -> None:
    """The bundle's folders: only what this import wrote moves into them."""
    from agos_core.actions import automations, folders
    from agos_core.db import library as library_repo

    given = found.settings.get("folders")
    if not isinstance(given, dict):
        return
    wrote = ("created", "renamed", "replaced")

    def written(kind: str) -> dict[str, str]:
        return {
            i["name"]: i["asName"]
            for i in report.items
            if i["kind"] == kind and i["result"] in wrote
        }

    autos = {a.name: a.id for a in automations.list_all(core, ws)} if written("automation") else {}
    ids: dict[str, dict[str, int]] = {
        "automation": {
            old: autos[new] for old, new in written("automation").items() if new in autos
        },
        "skill": {},
        "project": {},
    }
    for old, new in written("skill").items():
        row = library_repo.find_item(core.db, "skill", new, ws)
        if row is not None:
            ids["skill"][old] = int(row["id"])
    if written("vision"):
        ids["project"] = {title: i for i, title in goals_repo.projects(core.db, ws)}
    folders.apply_import(core, ws, given, ids)


def import_skills(
    core: Core, ws: str, found: fmt.Parsed, plan: Plan, report: Report
) -> dict[str, str]:
    """The bundle's skills through the workspace's own skill writers. Returns
    bundle name -> the name it has here (a renamed or skipped one included)."""
    from agos_core.actions import workspace_skills
    from agos_core.engine import library as lib

    have = workspace_skills.names(core, ws)
    names: dict[str, str] = {}
    for skill in found.skills:
        strategy = plan.strategies["skills"]
        name = skill.name
        try:
            if name in have and strategy == "skip":
                names[skill.name] = name
                report.add("skill", skill.name, "skipped", detail="kept the one this workspace has")
                continue
            given: dict[str, Any] = {"text": skill.text, "files": dict(skill.files)}
            if name in have and strategy == "replace":
                row = library_repo.find_item(core.db, "skill", name, ws)
                assert row is not None
                workspace_skills.save(core, ws, int(row["id"]), name=name, title="", given=given)
                names[skill.name] = name
                report.add("skill", skill.name, "replaced")
                continue
            if name in have:
                name = fmt.free_name(name, have)
                head, body = lib.parse_skill(skill.text)
                given["text"] = lib.skill_template(name, head.get("description", ""), body)
            workspace_skills.create(core, ws, name, title="", given=given, source="imported")
            have.add(name)
            names[skill.name] = name
            report.add("skill", skill.name, "renamed" if name != skill.name else "created", name)
        except (ActionError, lib.LibraryError, EngineError, OSError) as error:
            report.add("skill", skill.name, "failed", detail=_said(error))
    return names


def import_agents(
    core: Core, ws: str, found: fmt.Parsed, plan: Plan, report: Report, skills: dict[str, str]
) -> dict[str, str]:
    """The bundle's members through the team's own save (leads first). Returns
    bundle name -> the name it has here."""
    from agos_core.actions import agent_revisions, heartbeat, team
    from agos_core.actions import library as library_actions

    have = {a.name for a in team.members(core, ws)}
    names: dict[str, str] = {}
    in_bundle = {a.name for a in found.agents}
    for agent in fmt.leads_first(found.agents):
        strategy = plan.strategies["agents"]
        if agent.name in have and strategy == "skip":
            names[agent.name] = agent.name
            report.add("agent", agent.name, "skipped", detail="kept the member this workspace has")
            continue
        name = agent.name
        current = team.get(core, ws, name) if name in have and strategy == "replace" else None
        if name in have and current is None:
            name = fmt.free_name(name, have)
        boss = agent.reports_to
        if boss in in_bundle:
            boss = names.get(boss, "")
        elif boss and boss not in have:
            report.problems.append(
                f"@{agent.name}'s lead @{boss} isn't here: it reports to the top."
            )
            boss = ""
        if not boss:
            boss = plan.under
        missing = [s for s in agent.skills if s not in skills and not _has_skill(core, ws, s)]
        for skill in missing:
            report.problems.append(f"@{agent.name} uses the skill {skill}, which isn't here.")
        definition = {
            "instructions": agent.instructions or agent.title,
            "model": agent.model,
            "skills": [skills.get(s, s) for s in agent.skills if s not in missing],
            "reads": agent.reads,
            "reports_to": boss,
        }
        try:
            with agent_revisions.by(plan.who, plan.why):
                library_actions.save_item(
                    core,
                    current.id if current is not None else None,
                    kind="agent",
                    name=name,
                    title=agent.title or name,
                    summary=agent.summary,
                    definition=definition,
                    workspace_id=ws,
                )
                if agent.notes or not agent.on:
                    team.set_on(core, ws, name, on=agent.on, local=agent.notes)
                if agent.heartbeat in heartbeat.INTERVALS:
                    try:
                        heartbeat.set_heartbeat(core, ws, name, on=True, interval=agent.heartbeat)
                    except ActionError as error:
                        report.needs_owner.append(
                            {
                                "kind": "heartbeat",
                                "name": name,
                                "text": f"Turn @{name}'s heartbeat on ({agent.heartbeat}): {_said(error)}",
                            }
                        )
        except (ActionError, EngineError, OSError) as error:
            report.add("agent", agent.name, "failed", detail=_said(error))
            continue
        have.add(name)
        names[agent.name] = name
        result = (
            "replaced" if current is not None else "renamed" if name != agent.name else "created"
        )
        report.add("agent", agent.name, result, name)
    return names


def _has_skill(core: Core, ws: str, name: str) -> bool:
    from agos_core.actions import workspace_skills

    return name in workspace_skills.names(core, ws)


def _who(value: Any, agents: dict[str, str], team_here: set[str], under: str) -> str | None:
    """An automation's member as it is named here (None = the Co-Founder): the
    bundle's member as imported, a member this workspace has, else the lead the
    team went under."""
    name = str(value or "").strip()
    if not name:
        return None
    return agents.get(name) or (name if name in team_here else under) or None


def import_automations(
    core: Core, ws: str, found: fmt.Parsed, plan: Plan, report: Report, agents: dict[str, str]
) -> list[int]:
    from agos_core.actions import automations, hooks, team
    from agos_core.db.records import HookCondition

    workspace = require_workspace(core, ws)
    here = {a.name.strip().lower(): a for a in automations.list_all(core, ws)}
    taken = set(here)
    team_here = set(team.names(core, ws))

    def who(value: Any) -> str | None:
        return _who(value, agents, team_here, plan.under)

    made: list[int] = []
    for auto in found.automations:
        name = str(auto["name"]).strip()
        same = here.get(name.lower())
        strategy = plan.strategies["automations"]
        if same is not None and strategy == "skip":
            report.add("automation", name, "skipped", detail="kept the one this workspace has")
            continue
        as_name = name
        if same is not None and strategy == "rename":
            n = 2
            while f"{name} ({n})".lower() in taken:
                n += 1
            as_name = f"{name} ({n})"
        hook = auto.get("hook") if isinstance(auto.get("hook"), dict) else None
        steps = [
            {**s, "agent": who(s.get("agent"))}
            for s in auto.get("steps") or []
            if isinstance(s, dict)
        ]
        ticket = auto.get("ticket") if isinstance(auto.get("ticket"), dict) else None
        if ticket is not None:
            ticket = {**ticket, "member": who(ticket.get("member"))}
        try:
            model = (
                ModelSelection.model_validate(auto["model"])
                if isinstance(auto.get("model"), dict)
                else workspace.default_model
            )
            automation_id = automations.save(
                core,
                ws,
                same.id if same is not None and strategy == "replace" else None,
                name=as_name,
                instructions=str(auto.get("instructions") or ""),
                schedule=str(auto.get("schedule") or ""),
                model=model,
                on=bool(auto.get("on", True)),
                agent=who(auto.get("agent")),
                steps=steps,
                hook=hook is not None,
                check_first=bool(auto.get("check_first")),
                variables=list(auto.get("variables") or []),
                policy=str(auto.get("policy") or "skip_if_active"),
                ticket=ticket,
                who=plan.who,
            )
            if hook is not None:
                hooks.set_hook(
                    core,
                    ws,
                    automation_id,
                    on=True,
                    events=[str(e) for e in hook.get("events") or []],
                    conditions=[
                        HookCondition.model_validate(c) for c in hook.get("conditions") or []
                    ],
                )
                report.needs_owner.append(
                    {
                        "kind": "webhook",
                        "name": as_name,
                        "text": f"“{as_name}” has a new webhook address: give it to the sender.",
                    }
                )
        except (ActionError, EngineError, OSError, ValueError) as error:
            report.add("automation", name, "failed", detail=_said(error))
            continue
        made.append(automation_id)
        taken.add(as_name.lower())
        result = (
            "replaced"
            if same is not None and strategy == "replace"
            else "renamed"
            if as_name != name
            else "created"
        )
        report.add("automation", name, result, as_name)
    return made


def import_vision(
    core: Core, ws: str, found: fmt.Parsed, plan: Plan, report: Report, agents: dict[str, str]
) -> None:
    from agos_core.actions import goals

    vision = found.vision
    if vision is None:
        return
    had = goals.top(core, ws)
    if had is not None and plan.strategies["vision"] == "skip":
        report.add("vision", "Vision", "skipped", detail="kept this workspace's Vision")
        return
    top = vision.get("vision") or {}
    try:
        if top.get("title"):
            goals.set_vision(
                core,
                ws,
                title=str(top["title"]),
                why=str(top.get("why") or ""),
                strategy=str(top.get("strategy") or ""),
            )
        elif had is None:
            report.problems.append("The bundle's goals came without a Vision: none was set.")
            return
        titles = {g.title.strip().lower(): g for g in (goals.top(core, ws) or had).children}  # type: ignore[union-attr]
        for goal in vision.get("goals") or []:
            if not isinstance(goal, dict) or not str(goal.get("title") or "").strip():
                continue
            if str(goal["title"]).strip().lower() in titles:
                report.add(
                    "goal", str(goal["title"]), "skipped", detail="this goal is here already"
                )
                continue
            owner = agents.get(str(goal.get("owner") or ""), "")
            goal_id = goals.add_goal(
                core,
                ws,
                title=str(goal["title"]),
                why=str(goal.get("why") or ""),
                owner=owner,
                due_on=str(goal.get("due_on") or ""),
            )
            for kr in goal.get("key_results") or []:
                goals.add_result(
                    core,
                    ws,
                    goal_id,
                    title=str(kr.get("title") or ""),
                    start=kr.get("start", 0),
                    current=kr.get("current"),
                    target=kr.get("target"),
                    unit=str(kr.get("unit") or ""),
                    due_on=str(kr.get("due_on") or ""),
                )
            for project in goal.get("projects") or []:
                goals.add_project(
                    core,
                    ws,
                    goal_id,
                    title=str(project.get("title") or ""),
                    why=str(project.get("why") or ""),
                    owner=agents.get(str(project.get("owner") or ""), ""),
                    project_kind=str(project.get("project_kind") or "dated"),
                    starts_on=str(project.get("starts_on") or ""),
                    ends_on=str(project.get("ends_on") or ""),
                    rhythm=str(project.get("rhythm") or ""),
                )
            report.add("goal", str(goal["title"]), "created")
        report.add("vision", "Vision", "replaced" if had is not None else "created")
    except ActionError as error:
        report.problems.append(f"The Vision: {_said(error)}")


def import_keys(core: Core, ws: str, found: fmt.Parsed, plan: Plan, report: Report) -> None:
    """The keys the owner gave go into Workspace → Keys (Hermes's own writer);
    the rest (put off, connectors) are on the report's list."""
    from agos_core.actions import tool_keys

    for entry in found.inputs:
        value = str(plan.inputs.get(entry["name"]) or "").strip()
        if entry["kind"] == "tool_key" and value:
            try:
                tool_keys.save(core, ws, entry["app"], value, entry["name"])
                report.add("key", entry["name"], "created")
            except (ActionError, EngineError, OSError) as error:
                report.add("key", entry["name"], "failed", detail=_said(error))
                report.needs_owner.append(
                    {
                        "kind": "key",
                        "name": entry["name"],
                        "text": f"Add {entry['name']} in Workspace → Keys.",
                    }
                )
        elif entry["kind"] == "tool_key":
            report.needs_owner.append(
                {
                    "kind": "key",
                    "name": entry["name"],
                    "text": f"Add {entry['name']} in Workspace → Keys.",
                }
            )
        else:
            report.needs_owner.append(
                {
                    "kind": "connector",
                    "name": entry["name"],
                    "text": f"Turn on and sign in to {entry['app']} (Connectors).",
                }
            )
