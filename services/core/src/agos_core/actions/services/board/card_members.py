"""Who a Kanban card is with: the Hermes profile behind each team member, the
Co-Founder and the Founder (the owner himself), and the name AGOS shows for a card's
assignee and creator.

Split out of agos_core.actions.kanban_board (its `_members`, `_profile_of`, `_creator`,
`_shown_members`, `_legacy_member` and `latest_of`).

Owns: the profile <-> member mapping of a workspace's board.
Must not: run Hermes's Kanban CLI (kanban_cli.py) or shape a card for the page
(card_shape.py).
"""

from __future__ import annotations

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board import kanban_db
from agos_core.context import Core

__all__ = [
    "COFOUNDER",
    "OWNER",
    "creator",
    "latest_of",
    "legacy_member",
    "members",
    "profile_of",
    "shown_members",
]

OWNER = "owner"
COFOUNDER = "cofounder"  # the Co-Founder as a card's assignee (the workspace's own profile)


def members(core: Core, workspace_id: str) -> dict[str, dict[str, str]]:
    """Profile name → the member (name and job title)."""
    from agos_core.actions import agent_profiles, team

    found = {}
    for name in agent_profiles.team_names(core, workspace_id):
        found[
            core.engine.hermes_name(agent_profiles.key(workspace_id, name)) if core.engine else name
        ] = {"name": name, "title": team.title_of(core, workspace_id, name)}
    if core.engine is not None:
        # The Co-Founder works cards too (its own profile, the workspace's Hermes).
        found[core.engine.hermes_name(workspace_id)] = {"name": COFOUNDER, "title": "Co-Founder"}
    return found


def legacy_member(assignee: str, members: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """A card Hermes still has under a member's old profile name
    ('agos-<ws>--a-<name>', from before each workspace had its own root) is that
    member's: its name, never the profile name, is what a card chat keeps."""
    from agos_core.actions import agent_profiles

    found = agent_profiles.split_key(assignee)
    if found is None:
        return None
    return next((m for m in members.values() if m["name"] == found[1]), None)


def profile_of(core: Core, workspace_id: str, member: str, *, founder: bool = False) -> str:
    """The Hermes assignee for a member. `founder` (the owner himself, a person:
    actions/founder.py) only where the caller is the owner or the Co-Founder."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.founder import FOUNDER

    if not member:
        return "none"
    if member == FOUNDER:
        if not founder:
            raise ActionError(
                "Only the Co-Founder gives the Founder (the owner) a task. Ask your lead "
                "or the Co-Founder for what you need from him (agos_ask_owner)."
            )
        return FOUNDER
    if member == COFOUNDER and core.engine is not None:
        return core.engine.hermes_name(workspace_id)
    if member not in agent_profiles.team_names(core, workspace_id):
        raise ActionError("Pick a member of this workspace's team.")
    assert core.engine is not None
    return core.engine.hermes_name(agent_profiles.key(workspace_id, member))


def creator(who: str, members: dict[str, dict[str, str]], cofounder: str) -> str:
    if who in (OWNER, "user", ""):
        return "You"
    if who in members:
        return members[who]["title"]
    return "Co-Founder" if who == cofounder else who


def shown_members(core: Core, workspace_id: str) -> dict[str, dict[str, str]]:
    """The members a card may show: the team, the Co-Founder, and the Founder (the
    owner himself: his cards' assignee, actions/founder.py)."""
    from agos_core.actions import founder

    return {
        **members(core, workspace_id),
        founder.FOUNDER: founder.member_entry(core, workspace_id),
    }


def latest_of(core: Core, workspace_id: str, member: str, limit: int = 10) -> list[dict[str, str]]:
    """A member's newest cards (id, title, status, its result's first line), read
    from the board's own database (read only; [] when there is none yet)."""
    from agos_core.actions import agent_profiles

    if core.engine is None or not agent_profiles.board_db(core, workspace_id).is_file():
        return []
    try:
        profile = profile_of(core, workspace_id, member)
    except ActionError:
        return []
    return kanban_db.latest_by(core, workspace_id, profile, limit)
