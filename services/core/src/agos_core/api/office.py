"""The Office: how each agent of a workspace looks there (pet, colour, desk item).

Only looks are kept (actions/services/team/office_looks.py); what an agent is
doing comes live from Hermes (the board and the chats), never stored twice.
"""

import asyncio
import hashlib
import json
from typing import Any

from fastapi import APIRouter

from agos_core.actions.services.team import office_looks as office_look_rows
from agos_core.actions.services.team import office_stamps
from agos_core.actions.services.team.office_looks import COLOURS as COLOURS
from agos_core.actions.services.team.office_looks import ITEMS as ITEMS
from agos_core.actions.services.team.office_looks import PETS as PETS
from agos_core.actions.services.team.office_looks import Colour as Colour
from agos_core.actions.services.team.office_looks import DeskItem as DeskItem
from agos_core.actions.services.team.office_looks import OfficeLook as OfficeLook
from agos_core.actions.services.team.office_looks import Pet as Pet
from agos_core.actions.services.team.office_looks import look_of as look_of
from agos_core.actions.services.team.office_looks import save_look as save_look
from agos_core.actions.workers import Team, team
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.kanban_schemas import KanbanBoard
from agos_core.db.records import Record

router = APIRouter(tags=["office"])


class OfficeLooks(Record):
    # "cofounder" = the workspace's Co-Founder; the others by their agent name.
    looks: dict[str, OfficeLook]


def office_looks(core: object, workspace_id: str, of: Team | None = None) -> OfficeLooks:
    """Each agent's look (`of`: the team, when the caller has read it already)."""
    return OfficeLooks(looks=office_look_rows.looks(core, workspace_id, of))


@router.get("/workspaces/{workspace_id}/office")
def get_office(core: CoreDep, workspace_id: str) -> OfficeLooks:
    require_workspace(core, workspace_id)
    return office_looks(core, workspace_id)


class OfficeStamp(Record):
    # A fingerprint of what the Office shows (the team, Hermes's board, the looks):
    # its live refresh re-renders the page only when this moved.
    stamp: str


class OfficeView(Record):
    """Everything the Office page renders from, read together, and its fingerprint
    (what its live refresh compares: the page and the stamp agree by construction)."""

    team: Team
    board: KanbanBoard | None  # None: Hermes's board can't be read now
    looks: dict[str, OfficeLook]
    stamp: str


def _read(core: Any, workspace_id: str) -> OfficeView:
    """The team (read once: the looks reuse it), Hermes's board and the looks."""
    from agos_core.actions import kanban_board

    crew = team(core, workspace_id)
    try:
        board: KanbanBoard | None = KanbanBoard.model_validate(
            kanban_board.board(core, workspace_id)
        )
    except Exception:  # noqa: BLE001 — the page shows no board then (as getKanban: null)
        board = None
    looks = office_looks(core, workspace_id, crew).looks
    shown = {
        "team": crew.model_dump(mode="json"),
        "board": board.model_dump(mode="json") if board is not None else None,
        "looks": {k: v.model_dump(mode="json") for k, v in looks.items()},
    }
    raw = json.dumps(shown, sort_keys=True, default=str).encode()
    return OfficeView(
        team=crew, board=board, looks=looks, stamp=hashlib.sha256(raw).hexdigest()[:32]
    )


def office_view(core: Any, workspace_id: str) -> OfficeView:
    """The page's read; its fingerprint is kept for the live refresh's next asks."""
    stamp = office_stamps.inputs(core, workspace_id)  # before the reads: a change moves it
    view = _read(core, workspace_id)
    office_stamps.remember(workspace_id, stamp, view.stamp)
    return view


def office_stamp(core: Any, workspace_id: str) -> str:
    """The fingerprint; read again only when a store it comes from moved (the stamp
    is taken before the reads, so a change during them is read at the next ask)."""
    stamp = office_stamps.inputs(core, workspace_id)
    return office_stamps.kept(workspace_id, stamp, lambda: _read(core, workspace_id).stamp)


@router.get("/workspaces/{workspace_id}/office/view")
async def get_office_view(core: CoreDep, workspace_id: str) -> OfficeView:
    await asyncio.to_thread(require_workspace, core, workspace_id)
    return await asyncio.to_thread(office_view, core, workspace_id)


@router.get("/workspaces/{workspace_id}/office/stamp")
async def get_office_stamp(core: CoreDep, workspace_id: str) -> OfficeStamp:
    await asyncio.to_thread(require_workspace, core, workspace_id)
    return OfficeStamp(stamp=await asyncio.to_thread(office_stamp, core, workspace_id))


@router.put("/workspaces/{workspace_id}/office/{member}", status_code=204)
async def put_look(core: CoreDep, workspace_id: str, member: str, body: OfficeLook) -> None:
    save_look(core, workspace_id, member, body.model_dump())
