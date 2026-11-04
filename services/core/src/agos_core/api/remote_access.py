"""Settings → Access → "Use AGOS from other devices" (actions/remote_access.py)."""

import asyncio
from dataclasses import asdict

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import remote_access as actions
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["remote-access"])


class RemoteAccess(Record):
    """The card's state: not-installed, no-daemon, needs-operator, off,
    waiting-login, needs-https, on or error, with the words to show."""

    state: str
    message: str = ""
    command: str = ""
    login_url: str = ""
    address: str = ""
    user: str = ""
    also_allow: list[str] = Field(default_factory=list)
    warning: str = ""


class ActivateBody(Body):
    """The port the web listens on (what `tailscale serve` points at)."""

    port: int = Field(default=3000, ge=1, le=65535)


class AlsoAllowBody(Body):
    logins: list[str] = Field(default_factory=list, max_length=50)


def _out(found: actions.View) -> RemoteAccess:
    return RemoteAccess(**asdict(found))


@router.get("/remote-access")
def read(core: CoreDep) -> RemoteAccess:
    """The card's state; while it waits for a login, polling it finishes the job."""
    return _out(actions.view(core))


@router.post("/remote-access/activate")
async def activate(core: CoreDep, body: ActivateBody) -> RemoteAccess:
    """Activate: log in to Tailscale if needed, then serve AGOS on the tailnet."""
    return _out(await asyncio.to_thread(actions.activate, core, body.port))


@router.post("/remote-access/off")
async def turn_off(core: CoreDep) -> RemoteAccess:
    """Turn off: stop serving AGOS on the tailnet and forget who was allowed."""
    return _out(await asyncio.to_thread(actions.turn_off, core))


@router.put("/remote-access/also-allow")
def also_allow(core: CoreDep, body: AlsoAllowBody) -> RemoteAccess:
    """More Tailscale logins let in (family, team)."""
    return _out(actions.set_also_allow(core, body.logins))
