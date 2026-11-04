"""A workspace's review defaults and its org: who reviews whom, the stage names and the answers AGOS gives.
Must not: move a card.

Split out of agos_core.actions.reviews (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.engine import reviews as rules

__all__ = [
    "CHECKED",
    "IN_REVIEW",
    "NOT_REVIEWER",
    "OWNER",
    "OWNER_ACTIONS",
    "OWN_RUN",
    "PLAN_FIRST",
    "PLAN_WAITING",
    "REVIEWING",
    "SETTING",
    "STUCK",
    "SUBMIT",
    "VERDICTS",
    "Org",
    "defaults",
    "label",
    "org",
    "reviewer_of",
    "save_defaults",
]

log = logging.getLogger("agos_core.actions.reviews")  # the old module's name

SETTING = "review.{}"
OWNER = rules.OWNER
# The agent tools the guard asks about (agos_guard review.py CHECKED).
CHECKED = ("kanban_complete", "kanban_request_review", "kanban_request_changes", "kanban_create")
VERDICTS = ("submit", "plan_ready", "approve", "changes")
OWNER_ACTIONS = ("approve", "changes", "reassign", "drop")

PLAN_FIRST = (
    "Plan first: this card needs a plan {who} accepts before the work. Write it as the card "
    "document 'plan' (agos_card_document key='plan'; a '## Tasks' list of '- <title> "
    "@<member>' lines becomes cards when it is accepted), then call "
    "agos_review(verdict='plan_ready') and stop."
)
PLAN_WAITING = (
    "The plan (v{n}) waits for {who} to accept it: stop here. The card comes back to you "
    "when it is accepted (then do the work) or sent back with notes."
)
SUBMIT = (
    "Review first: stage {k} of {n} on this card is {who}. Hand it over with "
    "agos_review(verdict='submit', summary='<what you did and how you checked it>') "
    "instead of {tool}: AGOS routes it."
)
REVIEWING = (
    "You are reviewing this card (stage {k} of {n}): answer with "
    "agos_review(verdict='approve', note=...) or agos_review(verdict='changes', "
    "note='<what to change>'), not {tool}."
)
NOT_REVIEWER = "You are not this card's reviewer now: stage {k} of {n} is {who}."
STUCK = "This card is stuck in review after {r} rounds and waits for the owner: stop here."
IN_REVIEW = "This card is in review (stage {k} of {n}, {who}): stop here; it comes back if changes are asked."
OWN_RUN = (
    "Answer from the card's own run: Hermes wakes you on card {card} (in Review for a "
    "reviewer); you are not working it now."
)


# ---- the workspace's defaults ------------------------------------------------------------


def defaults(core: Core, workspace_id: str) -> dict[str, Any]:
    return rules.clean_defaults(get_setting(core.db, SETTING.format(workspace_id), {}))


def save_defaults(core: Core, workspace_id: str, data: dict[str, Any]) -> dict[str, Any]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    clean = rules.clean_defaults(data)
    _check_names(core, workspace_id, [*clean["stages"], clean["planReviewer"]])
    set_setting(core.db, SETTING.format(workspace_id), clean)
    return clean


def _check_names(core: Core, workspace_id: str, stages: list[str]) -> None:
    from agos_core.actions import agent_profiles

    team = set(agent_profiles.team_names(core, workspace_id))
    unknown = [s for s in stages if s not in rules.STAGE_WORDS and s not in team]
    if unknown:
        raise ActionError(
            f"Unknown reviewer: {', '.join(unknown)} (use lead, cofounder, owner or a member)."
        )


# ---- who reviews -------------------------------------------------------------------------


@dataclass(frozen=True)
class Org:
    names: dict[str, str]  # profile -> member name ("cofounder" for the Co-Founder)
    titles: dict[str, str]  # profile -> job title
    profiles: dict[str, str]  # member name -> profile
    cofounder: str  # the Co-Founder's profile
    bosses: dict[str, str]  # member -> lead ("" = the Co-Founder)


def org(core: Core, workspace_id: str) -> Org:
    """The team as profiles (files only: never starts Hermes)."""
    from agos_core.actions import kanban_board, team

    members = kanban_board._members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""
    try:
        bosses = team._bosses(core, workspace_id) if core.engine else {}
    except (OSError, ValueError, AssertionError):
        bosses = {}
    return Org(
        names={p: m["name"] for p, m in members.items()},
        titles={p: m["title"] for p, m in members.items()},
        profiles={m["name"]: p for p, m in members.items()},
        cofounder=cofounder,
        bosses=bosses,
    )


def reviewer_of(stage: str, implementer: str, people: Org) -> str:
    """The profile that reviews `stage` for this implementer (`owner` for him; ""
    when nobody fits, a member that left: the stage is skipped)."""
    if stage == OWNER:
        return OWNER
    if stage == "cofounder":
        return people.cofounder
    if stage == "lead":
        if not implementer or implementer == people.cofounder:
            return OWNER  # the Co-Founder answers to the owner
        member = people.names.get(implementer, "")
        boss = people.bosses.get(member, "")
        return people.profiles.get(boss, "") if boss else people.cofounder
    return people.profiles.get(stage, "")


def label(stage: str, reviewer: str, people: Org) -> str:
    if reviewer == OWNER:
        return "the owner"
    if reviewer == people.cofounder:
        return "the Co-Founder" + (" (the lead)" if stage == "lead" else "")
    name = people.names.get(reviewer, reviewer)
    return f"your lead @{name}" if stage == "lead" else f"@{name}"
