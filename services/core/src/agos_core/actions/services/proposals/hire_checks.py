"""What a hire proposal must pass before it reaches the owner: its lead, goal and skills.
Must not: record or decide a proposal.

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.services.proposals.proposal_states import _goals_of, _json
from agos_core.context import Core
from agos_core.db import kanban_asks
from agos_core.engine import proposals as rules

__all__ = [
    "OPEN_GOALS",
    "check_new",
    "hire_goal_problems",
    "hire_lead_problems",
    "hire_skill_problems",
]


def check_new(
    core: Core,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    member: str = "",
    kept_ok: bool = False,
) -> list[str]:
    """What keeps a new proposal from being made: its shape (engine/proposals.py),
    a hire's why (the team-design skill, installed for the Co-Founder here), its
    lead, the goal it serves, its skills, its full kit (tools, skills, docs,
    onboarding) and its whole model (an exact version from Hermes's catalog, an
    effort, model_why in its own field); a goal change against the goals as they
    are. Only for NEW proposals: a round already waiting is decided as made.
    `kept_ok`: a whole model stands while Hermes can't list the catalog (a card
    AGOS itself just wrote, read back by the block's hook)."""
    out = rules.proposing_problems(kind, payload)
    if kind == "hire":
        from agos_core.actions import team_design

        team_design.ensure(core, workspace_id)
        from agos_core.actions import agent_profiles

        if payload.get("name") and payload["name"] in agent_profiles.team_names(core, workspace_id):
            out.append(
                f"name: @{payload['name']} is already on the team: change it with "
                "update_agent, or hire under another name"
            )
        out += hire_lead_problems(core, workspace_id, payload)
        out += hire_goal_problems(core, workspace_id, payload)
        out += hire_skill_problems(core, workspace_id, payload)
        from agos_core.actions import hire_kit, hire_model

        # Its model: one the workspace's provider offers (resolved in place), and why.
        out += hire_model.check(core, workspace_id, payload, kept_ok=kept_ok, hire=True)
        if isinstance(payload.get("kit"), dict):
            # Step 62: tools mapped to Hermes's connectors, unknown library skills
            # become ones to find (the payload is the one propose() sends on).
            payload["kit"] = hire_kit.fill(core, workspace_id, payload["kit"])
            out += hire_kit.kit_problems(core, workspace_id, payload["kit"])
        # Its whole kit: nothing is proposed with a part left empty.
        out += hire_kit.required_problems(core, workspace_id, payload)
    if kind == "kit":
        from agos_core.actions import member_kits

        out += member_kits.problems(core, workspace_id, payload, kept_ok=kept_ok, new=True)
    if kind == "goal":
        from agos_core.actions import goals

        out = list(dict.fromkeys([*out, *goals.check_change(core, workspace_id, payload)]))
    return out


def hire_lead_problems(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """A hire's reports_to: a member of THIS team, never the new member itself or a
    lead that (through others) already reports to it (a loop, any length)."""
    from agos_core.actions import team

    name, lead = str(payload.get("name") or ""), str(payload.get("reports_to") or "")
    if not lead:
        return []
    if lead == name:
        return ["reports_to can't be the new member itself"]
    bosses = team._bosses(core, workspace_id)
    pending = {
        str(_json(r["payload"]).get("name") or ""): str(_json(r["payload"]).get("reports_to") or "")
        for r in kanban_asks.waiting_payloads(core.db, workspace_id, "hire")
    }
    if lead not in bosses and lead not in pending:
        return [f"reports_to: there is no member named {lead} in this workspace"]
    leads = {**pending, **bosses, name: lead}
    seen = {name}
    walk = lead
    while walk:
        if walk in seen:
            return [
                f"reports_to: {lead} already reports to {name} (through the team): that would be a loop"
            ]
        seen.add(walk)
        walk = leads.get(walk, "")
    return []


# A goal or project a hire may still serve (done and dropped ones are closed).
OPEN_GOALS = ("active", "paused")


def hire_goal_problems(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """A hire names the goal or project it serves (goal_id) while the workspace has an
    open one; without any it may leave it out. A named one must be open and here."""
    known = _goals_of(core, workspace_id)
    open_ = {i: g for i, g in known.items() if g["level"] != "vision" and g["status"] in OPEN_GOALS}
    goal_id = payload.get("goal_id")
    pick = "; ".join(f"#{i} {g['title']}" for i, g in sorted(open_.items())[:12])
    if not isinstance(goal_id, int):
        if not open_:
            return []
        return [
            "goal_id is missing: name the goal or project this hire serves (its number from "
            f"agos_goals status: {pick}), then propose again"
        ]
    if goal_id in open_:
        return []
    if not open_:
        return [f"goal_id: #{goal_id} is not a goal of this workspace (it has none): leave it out"]
    return [
        f"goal_id: #{goal_id} is not an open goal or project of this workspace; pick the one "
        f"this hire serves ({pick})"
    ]


def _skill_here(core: Core, workspace_id: str, name: str) -> bool:
    """A skill a member of this workspace can load: the workspace's own (its library),
    AGOS's or the Brain's (the folders every profile reads)."""
    from agos_core.actions import agos_skills, brain, workspace_skills
    from agos_core.db import library as repo

    if workspace_skills.existing_dir(core, workspace_id, name) is not None:
        return True
    if repo.find_item(core.db, "skill", name, workspace_id) is not None:
        return True
    if name in agos_skills.SKILLS:
        return True
    return "/" not in name and (brain.skills_dir(core) / name / "SKILL.md").is_file()


def hire_skill_problems(core: Core, workspace_id: str, payload: dict[str, Any]) -> list[str]:
    """Each skill a hire asks for is one this workspace has (never a name to make up),
    and never one of AGOS's background skills (the Co-Founder's own, e.g. team-design)."""
    from agos_core.actions import workspace_skills

    asked = list(dict.fromkeys(str(x) for x in payload.get("skills") or []))
    background = [s for s in asked if s in workspace_skills.agos_owned()]
    missing = [s for s in asked if s not in background and not _skill_here(core, workspace_id, s)]
    out = []
    if missing:
        out.append(
            f"skills not in this workspace's library: {', '.join(missing)}: install each "
            "first (the Skills page, or ask the owner) or drop it from skills"
        )
    if background:
        out.append(
            f"skills only the Co-Founder uses (AGOS keeps them in the background): "
            f"{', '.join(background)}: drop it from skills"
        )
    return out
