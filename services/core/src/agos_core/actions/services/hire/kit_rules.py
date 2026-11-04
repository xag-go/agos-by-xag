"""What a kit holds: filling it from the catalog, its problems, the required items, the team section of a hire.
Must not: write anything.

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions.services.hire.kit_store import kit_of
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.engine import hire_kit as rules

__all__ = [
    "fill",
    "kit_problems",
    "library_skills",
    "required_problems",
    "team_section",
]

log = logging.getLogger("agos.hire_kit")  # the old module's logger (one name)


def _catalog(core: Core) -> dict[str, str]:
    """Hermes's connector catalog (its optional-mcps apps, AGOS's apps): name -> title.
    {} when it can't be read (no engine): tools then keep what the agent named."""
    from agos_core.actions import apps

    try:
        return {name: str(app.description or name) for name, app in apps.catalog(core).items()}
    except Exception:  # a kit never fails on the catalog
        log.info("connector catalog not read", exc_info=True)
        return {}


def fill(core: Core, workspace_id: str, kit: dict[str, Any]) -> dict[str, Any]:
    """The kit as AGOS keeps it: each tool mapped to Hermes's connector when the
    catalog has one; a 'library' skill this workspace doesn't have becomes one to
    find (never a refusal: finding it is the readiness card's work)."""
    from agos_core.actions import proposals

    kit = rules.clean_kit(kit)
    if any(not t["connector"] for t in kit["tools"]):
        catalog = _catalog(core)
        for t in kit["tools"]:
            if not t["connector"] and not t["key"]:
                t["connector"] = rules.match_app(t["name"], catalog)
    for s in kit["skills"]:
        if s["source"] == "library" and not proposals._skill_here(core, workspace_id, s["name"]):
            s["source"] = "find"
    return kit


def kit_problems(core: Core, workspace_id: str, kit: dict[str, Any]) -> list[str]:
    from agos_core.actions import workspace_skills

    out = rules.kit_problems(kit)
    background = [
        s["name"] for s in kit.get("skills") or [] if s["name"] in workspace_skills.agos_owned()
    ]
    if background:
        out.append(
            f"kit skills only the Co-Founder uses: {', '.join(background)}: drop them from the kit"
        )
    return out


def required_problems(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """What a hire lacks of its whole kit (rules.kit_missing): tools, docs, an
    onboarding task with its criteria, and at least one skill this workspace's
    library has (its `skills` or the kit's library ones). [] = complete."""
    from agos_core.actions import agos_skills, proposals

    raw = payload.get("kit")
    kit = rules.clean_kit(raw) if isinstance(raw, dict) else None
    named = [str(s) for s in payload.get("skills") or []]
    named += [s["name"] for s in (kit or {}).get("skills") or [] if s["source"] == "library"]
    # AGOS's own shared skills (every profile reads them) are no skill of the role.
    have = {
        s
        for s in named
        if s not in agos_skills.SKILLS and proposals._skill_here(core, workspace_id, s)
    }
    return rules.kit_missing(kit, len(have))


def library_skills(core: Core, workspace_id: str, kit: dict[str, Any]) -> list[str]:
    """The kit's skills this workspace's library has now (installed into the member)."""
    from agos_core.actions import proposals

    return [
        s["name"]
        for s in kit.get("skills") or []
        if proposals._skill_here(core, workspace_id, s["name"])
    ]


# ---- the 'Your team' section of the member's SOUL.md --------------------------------------


def team_section(core: Core, workspace_id: str, member: str) -> str:
    """'Your team' for a member with a kit ('' without one): its lead, who it works
    with and their roles, the project / goal, its files."""
    from agos_core.actions import team

    kit = kit_of(core, workspace_id, member)
    if not kit:
        return ""
    bosses = team._bosses(core, workspace_id)
    lead_name = bosses.get(member, "")
    listed = list((kit.get("team") or {}).get("works_with") or [])
    peers = [n for n, b in bosses.items() if n != member and b in (lead_name, member)]
    names = list(dict.fromkeys([*listed, *peers]))[: rules.MAX_ITEMS]
    agents = {a.name: a for a in team.members(core, workspace_id, on_only=True)}
    lead = (lead_name, agents[lead_name].title) if lead_name in agents else None
    return rules.team_section(
        member=member,
        lead=lead,
        peers=[(n, agents[n].title, (agents[n].summary or "")[:160]) for n in names if n in agents],
        project=str((kit.get("team") or {}).get("project") or ""),
        goal=_goal_words(core, workspace_id, kit.get("goal_id")),
        docs=list(kit.get("docs") or []),
    )


def _goal_words(core: Core, workspace_id: str, goal_id: Any) -> str:
    if not isinstance(goal_id, int) or isinstance(goal_id, bool):
        return ""
    row = goals_repo.get(core.db, workspace_id, goal_id)
    if row is None:
        return ""
    kind = "project" if str(row["level"] or "") == "project" else "goal"
    return f"{kind} #{goal_id} '{row['title']}'"
