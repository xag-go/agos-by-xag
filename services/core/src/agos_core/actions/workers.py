"""Workers: the workspace's team (like Slack/Teams).

The Co-Founder is the workspace's own agent; members are its root's member profiles
on the team (actions/team.py). Hierarchy = who they are and what they
do; conversations = direct messages (one per member) and groups.
"""

from typing import Literal

from pydantic import Field

from agos_core.actions import team as team_actions
from agos_core.actions.chat import team_members
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.identity import get_identity
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import chats as repo
from agos_core.db.connection import transaction
from agos_core.db.records import Chat, Record


class Worker(Record):
    # None = the Co-Founder (the workspace's own agent).
    name: str | None
    title: str
    role: str
    summary: str
    dm_chat_id: int | None = None
    working: bool = False
    # The Co-Founder is the agent of the workspace's own Hermes profile.
    profile: str | None = None
    # Step 62: its Readiness (not_ready / onboarding / ready); None = hired without a kit.
    readiness: Literal["not_ready", "onboarding", "ready"] | None = None
    # Its kit: none (hired before kits) / incomplete (a part missing) / whole; None =
    # the Co-Founder. `kit_card`: the card already carrying a kit for it (the
    # Co-Founder's open ask, or its proposal waiting in the Inbox).
    kit: Literal["none", "incomplete", "whole"] | None = None
    kit_card: str | None = None
    # Work hours (actions/work_hours.py): on / off / staying (on today by his pick) /
    # finishing (past check-out, ending its card); None = the workspace has no hours.
    shift: Literal["on", "off", "staying", "finishing"] | None = None


class ChainLink(Record):
    name: str
    title: str


class Stalled(Record):
    lead: str
    why: str  # paused | missing | stuck | loop
    words: str


class OrgEntry(Record):
    """A member's place in the org chart (actions/org.py): its chain of command up
    to the Co-Founder, the lead that stalls it, whom it stalls, its stuck cards."""

    chain: list[ChainLink]
    stalled: Stalled | None = None
    stalls: list[str]
    stuck_cards: int = 0


class Team(Record):
    cofounder: Worker
    members: list[Worker]
    groups: list[Chat]
    dms: list[Chat]
    # Every member profile (paused ones too) by name.
    org: dict[str, OrgEntry] = Field(default_factory=dict)


def _first_lines(text: str, limit: int = 400) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    out = " ".join(lines)
    return out[:limit] + ("…" if len(out) > limit else "")


def team(core: Core, workspace_id: str) -> Team:
    workspace = require_workspace(core, workspace_id)
    dms = chat_view.list_chats(core.db, workspace_id, ("dm",))
    dm_by_agent = {c.agent: c for c in dms}
    identity = get_identity(core, workspace_id)
    lead_dm = dm_by_agent.get(None)
    from agos_core.actions import work_hours

    hours = work_hours.enabled(core, workspace_id)
    cofounder = Worker(
        name=None,
        title="Co-Founder",
        role="Leads the project",
        summary=_first_lines(identity.identity or workspace.description or ""),
        profile=core.engine.profile(workspace_id) if core.engine is not None else None,
        dm_chat_id=lead_dm.id if lead_dm else None,
        working=bool(lead_dm and lead_dm.working),
        shift=work_hours.agent_state(core, workspace_id, work_hours.COFOUNDER) if hours else None,
    )
    from agos_core.actions import hire_kit, member_kits

    members = []
    kit_cards = member_kits.open_cards(core, workspace_id)
    for agent in team_actions.members(core, workspace_id, on_only=True):
        kit = member_kits.state(core, workspace_id, agent.name, agent.skills)
        dm = dm_by_agent.get(agent.name)
        members.append(
            Worker(
                name=agent.name,
                title=agent.title,
                role=agent.summary or "Member",
                summary=_first_lines(agent.instructions),
                dm_chat_id=dm.id if dm else None,
                working=bool(dm and dm.working),
                readiness=hire_kit.state_of(core, workspace_id, agent.name),
                kit="none" if kit == "none" else "incomplete" if kit == "incomplete" else "whole",
                kit_card=kit_cards.get(agent.name),
                shift=work_hours.agent_state(core, workspace_id, agent.name) if hours else None,
            )
        )
    from agos_core.actions import blocked, org

    attention = blocked.attention(core, workspace_id)
    health = org.health(core, workspace_id, org.stuck_from_attention(core, workspace_id, attention))
    return Team(
        cofounder=cofounder,
        members=members,
        groups=chat_view.list_chats(core.db, workspace_id, ("group",)),
        dms=dms,
        org={n: OrgEntry.model_validate(org.member_view(health, n)) for n in health.people},
    )


def open_dm(core: Core, workspace_id: str, agent: str | None) -> int:
    """The DM with this member (None = the Co-Founder), created on first use.
    A hidden DM comes back with its whole history."""
    require_workspace(core, workspace_id)
    if agent and not team_members(core, workspace_id, [agent]):
        raise ActionError("That agent isn't on in this workspace (Connectors).")
    from agos_core.actions import chat_store
    from agos_core.db import hermes_switches

    with transaction(core.db):
        row = repo.dm_row(core.db, workspace_id, agent)
        if row is None:
            return repo.insert_chat(
                core.db,
                workspace_id=workspace_id,
                title="",  # its name is its partner's (db/chats.py dm_title)
                channel="web",
                kind="dm",
                agent=agent,
            )
        hidden = hermes_switches.hidden(
            int(row["id"]), str(row["workspace_id"]), str(row["kind"]), row["deleted_at"]
        )
    if hidden:
        # Bringing it back runs Hermes (its archive): after the transaction, so the
        # shared connection is not held while Hermes works (every page and gateway
        # call waited behind it).
        chat_store.unhide(core, row)
    return int(row["id"])


def _check_members(core: Core, workspace_id: str, names: list[str]) -> list[str]:
    wanted = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    ok = [m.name for m in team_members(core, workspace_id, wanted)]
    missing = [n for n in wanted if n not in ok]
    if missing:
        raise ActionError(f"Not on in this workspace (Connectors): {', '.join(missing)}.")
    return ok


def create_group(core: Core, workspace_id: str, title: str, members: list[str]) -> int:
    require_workspace(core, workspace_id)
    name = title.strip()
    if not name:
        raise ActionError("Give the group a name.")
    ok = _check_members(core, workspace_id, members)
    with transaction(core.db):
        return repo.insert_chat(
            core.db,
            workspace_id=workspace_id,
            title=name,
            channel="web",
            kind="group",
            members=ok,
        )


def set_group_members(core: Core, workspace_id: str, chat_id: int, members: list[str]) -> None:
    ok = _check_members(core, workspace_id, members)
    with transaction(core.db):
        if not repo.set_members(core.db, workspace_id, chat_id, ok):
            raise NotFoundError("This group")
    from agos_core.actions import rooms

    # A group on its own Hermes root: its room follows (disbanded and made again,
    # the chat keeps its history).
    rooms.members_changed(core, workspace_id, chat_id)
