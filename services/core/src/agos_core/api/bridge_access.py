"""Who may call the bridge API: the workspace's own bridge key (agos-bridge.json in its
profile, 0600) checked on every call, the address format a call may name, and the gateway that
asks (Taker).

Owns: the key check (a refusal is a security event), ADDRESS and Taker.
Must not: hold routes.

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.actions import security_events
from agos_core.context import Core
from agos_core.domain.workspace import require_workspace_id

__all__ = [
    "ADDRESS",
    "Auth",
    "Taker",
]


# A Telegram chat, optionally with its topic: "<chat id>[:<topic id>]" (no topic = ":0").
ADDRESS = r"^(-?\d{1,20}(:\d{1,20})?|agos:\d{1,12}(\.[A-Za-z0-9_-]{1,64})?|agos:l\d{1,12}|cron:[A-Za-z0-9_-]{1,64}|kanban:[A-Za-z0-9_-]{1,64}|room:\d{1,12})$"


def _checked(core: Core, workspace_id: str, authorization: str | None) -> str:
    workspace_id = require_workspace_id(workspace_id)
    said = authorization or ""
    given = said[7:].strip() if said.lower().startswith("bearer ") else ""
    if not actions.key_ok(core, workspace_id, given):
        security_events.record("bridge_key", where="hermes-bridge", workspace_id=workspace_id)
        raise HTTPException(status_code=401, detail="Not allowed")
    return workspace_id


Auth = Annotated[str | None, Header()]


class Taker(BaseModel):
    """Who asks: the workspace's gateway (""), or a team member's own gateway."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    # A newer plugin's one platform-next for every profile its gateway serves ("": the
    # workspace's own); each item then says whose it is.
    members: list[str] | None = Field(default=None, max_length=64)
