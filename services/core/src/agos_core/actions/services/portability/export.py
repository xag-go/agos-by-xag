"""Exporting a workspace: each piece read where it lives, every known secret turned into ${NAME}, the bundle's files and zip.
Must not: let a secret leave (only named fields are read).

Split out of agos_core.actions.portability (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db.activity import add_activity
from agos_core.engine import bundle as fmt
from agos_core.engine.hermes import EngineError

__all__ = [
    "SHORTEST_SECRET",
    "TELEGRAM",
    "export_files",
    "export_zip",
    "scrub",
]

log = logging.getLogger("agos.portability")
TELEGRAM = "TELEGRAM"  # a Telegram bot token is never exported, not even as an input
SHORTEST_SECRET = 8


# ---- export ----------------------------------------------------------------------------


def _agents(core: Core, workspace_id: str) -> list[fmt.Agent]:
    from agos_core.actions import agent_revisions, team

    return [
        fmt.Agent(
            name=a.name,
            title=a.title,
            summary=a.summary,
            instructions=a.instructions,
            notes=a.local,
            reports_to=a.reports_to,
            model=a.model,
            skills=list(a.skills),
            reads=[dict(r) for r in a.reads],
            on=a.on,
            heartbeat=agent_revisions.heartbeat_of(core, workspace_id, a.name),
        )
        for a in team.members(core, workspace_id)
    ]


def _skills(core: Core, workspace_id: str) -> list[fmt.Skill]:
    from agos_core.actions import workspace_skills

    out = []
    # AGOS's background skills are left out: every workspace gets its own from AGOS.
    for row in workspace_skills.shown(core, workspace_id):
        if workspace_skills.never_written(core, row):
            continue
        found = workspace_skills.definition(core, row)
        if str(found.get("text") or "").strip():
            out.append(
                fmt.Skill(str(row["name"]), str(found["text"]), dict(found.get("files") or {}))
            )
    return out


def _vision(core: Core, workspace_id: str) -> dict[str, Any] | None:
    from agos_core.actions import goals

    top = goals.top(core, workspace_id)
    if top is None:
        return None

    def kr(k: Any) -> dict[str, Any]:
        return {
            "title": k.title,
            "start": k.start,
            "current": k.current,
            "target": k.target,
            "unit": k.unit,
            "due_on": k.due_on,
        }

    def project(p: Any) -> dict[str, Any]:
        return {
            "title": p.title,
            "why": p.why,
            "owner": p.owner,
            "status": p.status,
            "project_kind": p.project_kind or "dated",
            "starts_on": p.starts_on,
            "ends_on": p.ends_on,
            "rhythm": p.rhythm,
        }

    return {
        "vision": {"title": top.title, "why": top.why, "strategy": top.strategy},
        "goals": [
            {
                "title": g.title,
                "why": g.why,
                "owner": g.owner,
                "status": g.status,
                "due_on": g.due_on,
                "key_results": [kr(k) for k in g.results],
                "projects": [project(p) for p in g.children if p.level == "project"],
            }
            for g in top.children
            if g.level == "goal"
        ],
    }


def _inputs(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Every key the workspace's tools use (Workspace → Keys) and every connector
    it has on: what the importer is asked for. Names only, never a value."""
    from agos_core.actions import apps, tool_keys

    out: list[dict[str, Any]] = []
    with contextlib.suppress(ActionError, OSError, EngineError):
        for key in tool_keys.read(core, workspace_id)["keys"]:
            if TELEGRAM in str(key["name"]).upper():
                continue
            out.append(
                {
                    "name": str(key["name"]),
                    "description": f"The key for {key['app']} (Workspace → Keys)",
                    "required": True,
                    "kind": "tool_key",
                    "app": str(key["app"]),
                }
            )
    with contextlib.suppress(ActionError, OSError, EngineError):
        for name in apps.enabled_apps(core, workspace_id):
            out.append(
                {
                    "name": name,
                    "description": f"Sign in to {name} again (Connectors)",
                    "required": False,
                    "kind": "connector",
                    "app": name,
                }
            )
    return out


def _known_values(core: Core, workspace_id: str) -> dict[str, str]:
    """Every value of the workspace's Hermes homes' .env files (the root and each
    member): the keys a text must never carry. value -> its name."""
    from agos_core.actions import team
    from agos_core.engine import config_file

    if core.engine is None:
        return {}
    homes = [core.engine.profile_home(workspace_id)]
    homes += [
        h for h in (team.home(core, workspace_id, n) for n in team.names(core, workspace_id)) if h
    ]
    out: dict[str, str] = {}
    for home in homes:
        for name, value in config_file.read_env(home).items():
            value = value.strip()
            if len(value) >= SHORTEST_SECRET and not value.isdigit():
                out.setdefault(value, name)
    return out


def scrub(files: dict[str, str], known: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """No secret in any file: a known key value becomes `${NAME}` (a Telegram
    token: a note), then Hermes's own masking runs over every text. Fails closed
    when Hermes can't check them. Returns (files, the paths that changed)."""
    from agos_core.engine import hermes_redact

    changed: list[str] = []
    out: dict[str, str] = {}
    for path, text in files.items():
        clean = text
        for value in sorted(known, key=len, reverse=True):
            if value in clean:
                name = known[value]
                shown = (
                    "(a Telegram bot token, never exported)"
                    if TELEGRAM in name.upper()
                    else ("${" + name + "}")
                )
                clean = clean.replace(value, shown)
        out[path] = clean
    paths = sorted(out)
    masked = hermes_redact.mask_many([out[p] for p in paths])
    for path, text in zip(paths, masked, strict=True):
        if out[path] and text == hermes_redact.HIDDEN:
            raise ActionError(
                "The engine couldn't check the bundle for secrets, so nothing was exported. "
                "Try again in a moment.",
                503,
            )
        if text != files[path]:
            changed.append(path)
        out[path] = text
    return out, changed


def export_files(core: Core, workspace_id: str) -> dict[str, str]:
    """The workspace as a bundle (path -> text), secrets out."""
    from agos_core.actions import reviews
    from agos_core.actions.engine import own_identity

    workspace = require_workspace(core, workspace_id)
    agents = _agents(core, workspace_id)
    skills = _skills(core, workspace_id)
    from agos_core.actions import automations as automation_actions
    from agos_core.db import automation_revisions

    listed = automation_actions.list_all(core, workspace_id)
    automations = [automation_revisions.snapshot_of(a) for a in listed]
    vision = _vision(core, workspace_id)
    inputs = _inputs(core, workspace_id)
    files: dict[str, str] = {}
    for agent in agents:
        files.update(fmt.agent_files(agent))
    for skill in skills:
        files[fmt.SKILL_FILE.format(skill.name)] = skill.text
        for rel, text in skill.files.items():
            files[f"skills/{skill.name}/{rel}"] = text
    taken: set[str] = set()
    for auto in automations:
        name = fmt.free_name(fmt.slug(str(auto.get("name") or "")), taken)
        taken.add(name)
        files[fmt.AUTOMATION_FILE.format(name)] = fmt._dump(auto)
    if vision is not None:
        files[fmt.VISION_FILE] = fmt.vision_md(vision)
    identity = own_identity(core, workspace_id)
    if identity.strip():
        files[fmt.COFOUNDER_SOUL] = identity.strip() + "\n"
    files[fmt.SETTINGS_FILE] = fmt._dump(
        {
            "schema": fmt.SCHEMA,
            "workspace": {"name": workspace.name, "description": workspace.description},
            "default_model": workspace.default_model.model_dump(),
            "review": reviews.defaults(core, workspace_id),
            "env_requires": inputs,
            "not_carried": list(fmt.NOT_CARRIED),
            **_folders(core, workspace_id, skills, {a.id: a.name for a in listed}),
        }
    )
    meta = {
        "kind": "workspace",
        "name": workspace.name,
        "slug": workspace_id,
        "description": workspace.description,
        "skills": [s.name for s in skills],
        "automations": [str(a.get("name") or "") for a in automations],
    }
    files[fmt.TEAM_FILE] = fmt.team_md(meta, agents, _extra(skills, automations, inputs))
    clean, _changed = scrub(files, _known_values(core, workspace_id))
    fmt.parse(clean)  # what was written is what an import reads (self-checked)
    return clean


def _folders(
    core: Core, workspace_id: str, skills: list[fmt.Skill], automations: dict[int, str]
) -> dict[str, Any]:
    """The lists' folders (actions/folders.py), each item named as the bundle names it:
    an automation and a skill by their name, a project by its title."""
    from agos_core.actions import folders
    from agos_core.db import library as library_repo

    carried = {s.name for s in skills}
    names: dict[str, dict[int, str]] = {
        "automation": automations,
        "skill": {
            int(r["id"]): str(r["name"])
            for r in library_repo.workspace_skills(core.db, workspace_id)
            if str(r["name"]) in carried
        },
        "project": dict(goals_repo.projects(core.db, workspace_id)),
    }
    found = folders.export(core, workspace_id, names)
    return {"folders": found} if found else {}


def _extra(
    skills: list[fmt.Skill], automations: list[dict[str, Any]], inputs: list[dict[str, Any]]
) -> dict[str, list[str]]:
    def described(skill: fmt.Skill) -> str:
        head, _body = fmt.frontmatter(skill.text)
        return f"- {skill.name} — {head.get('description') or ''}".rstrip(" —")

    return {
        "Skills": [described(s) for s in skills],
        "Automations": [
            f"- {a.get('name')} — {a.get('schedule') or 'on an event'}"
            f" (@{a.get('agent') or 'cofounder'})"
            for a in automations
        ],
        "What you'll be asked for": [
            f"- {i['name']}{'' if i['required'] else ' (optional)'} — {i['description']}"
            for i in inputs
        ],
    }


def export_zip(core: Core, workspace_id: str) -> tuple[str, bytes]:
    files = export_files(core, workspace_id)
    add_activity(core.db, workspace_id, kind="workspace.exported", text="Workspace exported")
    return f"agos-{workspace_id}.zip", fmt.to_zip(files, workspace_id)
