"""What the plugin asks for its own upkeep: the digest Hermes's cron job prints, the
owner's rules as system-prompt sections, and a Hermes internal that broke.

Owns: those three routes.
Must not: change any setting.

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.api.bridge_access import Auth, _checked
from agos_core.api.deps import CoreDep

__all__ = [
    "ContractBroken",
    "contract_broken",
    "digest_now",
    "owner_rules_section",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


class ContractBroken(BaseModel):
    """A Hermes internal the agos-guard plugin uses failed inside Hermes (it failed
    closed there): `name` is the contract entry (engine/hermes_contract.py)."""

    name: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z_][\w.]*$")
    error: str = Field(default="", max_length=2000)
    gateway: str = Field(default="", max_length=80)


@router.post("/digest")
async def digest_now(
    core: CoreDep, workspace_id: str, authorization: Auth = None
) -> dict[str, str]:
    """Hermes's digest job (a no-agent cron job in the root) takes the held lines:
    what it prints, Hermes delivers to the Co-Founder's Telegram place."""
    from agos_core.actions import digest

    ws = _checked(core, workspace_id, authorization)
    return {"text": await asyncio.to_thread(digest.take, core, ws)}


@router.post("/owner-rules")
async def owner_rules_section(
    core: CoreDep, workspace_id: str, authorization: Auth = None
) -> dict[str, Any]:
    """The owner's rules for every workspace, as the agos-guard plugin's system-prompt
    sections (read when a session starts): "parts", one per section ([] when there
    are none or they don't fit Hermes's caps: then they are in every USER.md);
    "text" is the first one (an older plugin's single section)."""
    from agos_core.actions import owner_rules

    _checked(core, workspace_id, authorization)
    rules = await asyncio.to_thread(owner_rules.texts, core)
    parts = owner_rules.section_parts(rules)
    return {"text": parts[0] if parts else "", "parts": parts}


@router.post("/contract-broken")
async def contract_broken(
    core: CoreDep, workspace_id: str, body: ContractBroken, authorization: Auth = None
) -> dict[str, bool]:
    """Told to the owner (Log + his phone), once per name per gateway start."""
    from agos_core.actions import contract_alert

    ws = _checked(core, workspace_id, authorization)
    told = await asyncio.to_thread(
        contract_alert.tell, core, ws, body.name, body.error, body.gateway or "gateway"
    )
    return {"ok": True, "told": told}
