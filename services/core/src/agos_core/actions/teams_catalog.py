"""Ready-made teams (Step 56, F91): a few team bundles shipped with AGOS
(catalog/teams/<slug>/, the same readable format as an export, engine/bundle.py),
installed into a new workspace ("New workspace from template") or into the current
one under the Co-Founder or a lead ("Add team"). Installing IS an import
(actions/portability.py): every member, skill and automation is made through the
normal AGOS paths, so Hermes gets its profiles, SOUL.md, skills and cron jobs the
normal way. Paperclip installs its catalog teams the same way (through its import)
and measures drift with a content hash; AGOS keeps, per install, the bundle's hash
and what each of its items became (template_installs), and shows what in the
workspace now differs from the template it came from.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from agos_core.actions import portability
from agos_core.actions.errors import NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import template_installs as installs
from agos_core.db.connection import transaction
from agos_core.domain.models import ModelSelection
from agos_core.engine import bundle as fmt

CATALOG = Path(__file__).resolve().parents[1] / "catalog" / "teams"
COMPARED = ("title", "summary", "instructions", "skills", "reports_to", "on", "heartbeat")


@cache
def team_files(slug: str) -> dict[str, str]:
    """One shipped team's files (read once per process: they ship with the code)."""
    folder = CATALOG / slug
    if not fmt.NAME.fullmatch(slug) or not (folder / fmt.TEAM_FILE).is_file():
        raise NotFoundError("This team")
    return {
        p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _summary(slug: str) -> dict[str, Any]:
    files = team_files(slug)
    found = fmt.parse(files)
    return {
        "slug": slug,
        "name": found.name,
        "description": str(found.meta.get("description") or ""),
        "tags": [str(t) for t in found.meta.get("tags") or []],
        "lead": str(found.meta.get("lead") or ""),
        "hash": fmt.content_hash(files),
        "trust": portability.trust(files),
        "agents": [
            {"name": a.name, "title": a.title, "summary": a.summary, "reportsTo": a.reports_to}
            for a in fmt.leads_first(found.agents)
        ],
        "skills": [s.name for s in found.skills],
        "automations": [
            {
                "name": str(a["name"]),
                "schedule": str(a.get("schedule") or ""),
                "agent": str(a.get("agent") or ""),
            }
            for a in found.automations
        ],
        "inputs": found.inputs,
    }


def teams() -> list[dict[str, Any]]:
    return [_summary(p.name) for p in sorted(CATALOG.iterdir()) if (p / fmt.TEAM_FILE).is_file()]


def install(
    core: Core,
    slug: str,
    *,
    workspace_id: str | None,
    name: str = "",
    default_model: ModelSelection | None = None,
    under: str = "",
    strategies: dict[str, str] | None = None,
    inputs: dict[str, str] | None = None,
    later: list[str] | None = None,
) -> dict[str, Any]:
    """The team into a new workspace (`workspace_id` None) or the given one,
    its top members under `under` ("" = the Co-Founder). Returns the import's
    fidelity report."""
    files = team_files(slug)
    title = fmt.parse(files).name
    report, found = portability.apply(
        core,
        files,
        workspace_id=workspace_id,
        name=name or title,
        default_model=default_model,
        strategies=strategies,
        inputs=inputs,
        later=later,
        under=under,
        who="template",
        why=f"from the {title} team template",
    )
    items: dict[str, Any] = {
        "agents": {},
        "skills": {},
        "automations": {},
        "under": under.strip().lstrip("@"),
    }
    for item in report.items:
        if item["result"] == "failed":
            continue
        if item["kind"] == "agent":
            items["agents"][item["name"]] = item["asName"]
        elif item["kind"] == "skill":
            items["skills"][item["name"]] = item["asName"]
        elif item["kind"] == "automation" and item["result"] != "skipped":
            items["automations"][item["name"]] = item["asName"]
    with transaction(core.db):
        installs.add(
            core.db,
            report.workspace_id,
            slug,
            found.name,
            fmt.content_hash(files),
            json.dumps(items),
        )
    return report.view()


# ---- drift: what differs from the template now ----------------------------------------


def _agent_drift(
    core: Core, ws: str, found: fmt.Parsed, items: dict[str, Any]
) -> list[dict[str, Any]]:
    from agos_core.actions import agent_revisions, team

    names: dict[str, str] = dict(items.get("agents") or {})
    skills: dict[str, str] = dict(items.get("skills") or {})
    under = str(items.get("under") or "")
    here = {a.name: a for a in team.members(core, ws)}
    out: list[dict[str, Any]] = []
    for agent in found.agents:
        mine = names.get(agent.name)
        if not mine:
            continue
        current = here.get(mine)
        if current is None:
            out.append({"kind": "agent", "name": mine, "change": "removed", "fields": []})
            continue
        wanted = {
            "title": agent.title,
            "summary": agent.summary,
            "instructions": agent.instructions.strip(),
            "skills": sorted(skills.get(s, s) for s in agent.skills),
            "reports_to": names.get(agent.reports_to, "") if agent.reports_to else under,
            "on": agent.on,
            "heartbeat": agent.heartbeat,
        }
        now_is = {
            "title": current.title,
            "summary": current.summary,
            "instructions": current.instructions.strip(),
            "skills": sorted(current.skills),
            "reports_to": current.reports_to,
            "on": current.on,
            "heartbeat": agent_revisions.heartbeat_of(core, ws, mine),
        }
        fields = [f for f in COMPARED if wanted[f] != now_is[f]]
        if fields:
            out.append({"kind": "agent", "name": mine, "change": "changed", "fields": fields})
    mine_all = set(names.values())
    for name, member in sorted(here.items()):
        if name not in mine_all and member.reports_to in mine_all:
            out.append({"kind": "agent", "name": name, "change": "added", "fields": []})
    return out


def _skill_drift(
    core: Core, ws: str, found: fmt.Parsed, items: dict[str, Any]
) -> list[dict[str, Any]]:
    from agos_core.actions import workspace_skills
    from agos_core.db import library as library_repo

    out: list[dict[str, Any]] = []
    for skill in found.skills:
        mine = dict(items.get("skills") or {}).get(skill.name)
        if not mine:
            continue
        row = library_repo.find_item(core.db, "skill", mine, ws)
        if row is None:
            out.append({"kind": "skill", "name": mine, "change": "removed", "fields": []})
            continue
        text = str(workspace_skills.definition(core, row).get("text") or "")
        if mine == skill.name and text.strip() != skill.text.strip():
            out.append({"kind": "skill", "name": mine, "change": "changed", "fields": ["text"]})
    return out


def _automation_drift(
    core: Core, ws: str, found: fmt.Parsed, items: dict[str, Any]
) -> list[dict[str, Any]]:
    from agos_core.actions import automations

    names: dict[str, str] = dict(items.get("agents") or {})
    here = {a.name: a for a in automations.list_all(core, ws)}
    out: list[dict[str, Any]] = []
    for auto in found.automations:
        mine = dict(items.get("automations") or {}).get(str(auto["name"]))
        if not mine:
            continue
        current = here.get(mine)
        if current is None:
            out.append({"kind": "automation", "name": mine, "change": "removed", "fields": []})
            continue
        agent = str(auto.get("agent") or "")
        wanted = {
            "instructions": str(auto.get("instructions") or "").strip(),
            "schedule": str(auto.get("schedule") or ""),
            "agent": names.get(agent, agent) or None,
            "on": bool(auto.get("on", True)),
        }
        now_is = {
            "instructions": current.instructions.strip(),
            "schedule": current.schedule,
            "agent": current.agent,
            "on": current.on,
        }
        fields = [f for f in wanted if wanted[f] != now_is[f]]
        if fields:
            out.append({"kind": "automation", "name": mine, "change": "changed", "fields": fields})
    return out


def installed(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The teams this workspace installed, each with what now differs from it."""
    require_workspace(core, workspace_id)
    out = []
    for row in installs.of_workspace(core.db, workspace_id):
        slug = str(row["slug"])
        items = json.loads(str(row["items"]) or "{}")
        try:
            files = team_files(slug)
        except NotFoundError:
            out.append(
                {
                    "id": int(row["id"]),
                    "slug": slug,
                    "name": str(row["title"]),
                    "installedAt": str(row["installed_at"]),
                    "templateChanged": True,
                    "drift": [],
                    "gone": True,
                }
            )
            continue
        found = fmt.parse(files)
        drift = [
            *_agent_drift(core, workspace_id, found, items),
            *_skill_drift(core, workspace_id, found, items),
            *_automation_drift(core, workspace_id, found, items),
        ]
        out.append(
            {
                "id": int(row["id"]),
                "slug": slug,
                "name": str(row["title"]),
                "installedAt": str(row["installed_at"]),
                "templateChanged": fmt.content_hash(files) != str(row["content_hash"]),
                "drift": drift,
                "gone": False,
            }
        )
    return out
