"""Read vs act and security events, over HTTP.

- `/hermes-bridge/<workspace>/taint` (the workspace's own bridge key): the agos-guard
  plugin says a session just read untrusted content (actions/read_vs_act.py); with no
  session, a job or a card a tainted session made. `/taint-of`: what a session or a
  run read (a run's memory writes, a card's result woken into a chat). Neither can
  remove a mark: it ends with its session.
- `/tool-check`, `/actions`, `/capability`, `/skill-request` (the bridge key): the
  Co-Founder's AGOS tools, behind the owner gate the core re-checks
  (actions/owner_gate.py; moved here from api/hermes_bridge.py).
- `/security/events` (the internal token): the web app says it refused a request
  (a Host or Origin it doesn't serve), for the System Log (actions/security_events.py).
"""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.actions import owner_gate, read_vs_act, security_events
from agos_core.api.bridge_access import ADDRESS, Auth, _checked
from agos_core.api.bridge_tools import SkillTest
from agos_core.api.deps import CoreDep

bridge_router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)
router = APIRouter(tags=["security"])


SESSION = Field(default="", max_length=200)  # Hermes's session (its top parent's)
ONCE = Field(default="", max_length=64)  # the tainted ask's nonce (owner_gate.tool_check)


class Taint(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    source: str = Field(min_length=1, max_length=200)
    session: str = SESSION


@bridge_router.post("/taint")
def taint(
    core: CoreDep, workspace_id: str, body: Taint, authorization: Auth = None
) -> dict[str, bool]:
    """This session of a conversation (or run) just read untrusted content: until it
    ends, its power actions wait for the owner's yes. No session: a job or a card a
    tainted session made (its whole address)."""
    ws = _checked(core, workspace_id, authorization)
    read_vs_act.mark(core, ws, body.chat, body.source, session=body.session)
    return {"ok": True}


class TaintOf(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    session: str = SESSION


@bridge_router.post("/taint-of")
async def taint_of(
    core: CoreDep, workspace_id: str, body: TaintOf, authorization: Auth = None
) -> dict[str, str]:
    """What untrusted content this session or run read ("" = none)."""
    ws = _checked(core, workspace_id, authorization)
    found = await asyncio.to_thread(read_vs_act.source_of, core, ws, body.chat, body.session)
    return {"untrusted": found}


class ToolCheck(BaseModel):
    tool: str = Field(max_length=60)
    args: dict[str, Any] = Field(default_factory=dict)
    chat: str = Field(default="", max_length=90)
    session: str = SESSION


@bridge_router.post("/tool-check")
async def tool_check(
    core: CoreDep, workspace_id: str, body: ToolCheck, authorization: Auth = None
) -> dict[str, Any]:
    """Before one of AGOS's tools runs: does Hermes ask the owner first."""
    ws = _checked(core, workspace_id, authorization)
    return await asyncio.to_thread(
        owner_gate.tool_check, core, body.tool, body.args, ws, body.chat, body.session
    )


class RunActions(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    actions: list[dict[str, Any]] = Field(max_length=1000)
    session: str = SESSION
    once: str = ONCE


@bridge_router.post("/actions")
async def run_actions(
    core: CoreDep, workspace_id: str, body: RunActions, authorization: Auth = None
) -> dict[str, Any]:
    """The Co-Founder's agos_action tool (refused when it needs the owner's yes and he
    was never asked: the core re-checks the gate the plugin applied)."""
    ws = _checked(core, workspace_id, authorization)
    args = {"actions": body.actions}
    refused = await asyncio.to_thread(
        owner_gate.gate_refusal, core, ws, body.chat, "agos_action", args, body.session, body.once
    )
    if refused:
        return {"error": refused}
    return await asyncio.to_thread(actions.run_actions, core, ws, body.chat, body.actions)


class AskCapability(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    kind: str = Field(default="app", max_length=10)
    name: str = Field(max_length=64)
    on: bool = True
    why: str = Field(default="", max_length=2000)
    session: str = SESSION
    once: str = ONCE


@bridge_router.post("/capability")
async def ask_capability(
    core: CoreDep, workspace_id: str, body: AskCapability, authorization: Auth = None
) -> dict[str, Any]:
    """The Co-Founder's agos_capability tool (the core re-checks the owner gate)."""
    ws = _checked(core, workspace_id, authorization)
    args = {"kind": body.kind, "name": body.name, "on": body.on}
    refused = await asyncio.to_thread(
        owner_gate.gate_refusal,
        core,
        ws,
        body.chat,
        "agos_capability",
        args,
        body.session,
        body.once,
    )
    if refused:
        return {"error": refused}
    return await asyncio.to_thread(
        actions.ask_capability, core, ws, body.chat, body.kind, body.name, body.on, body.why
    )


class SkillRequestCall(BaseModel):
    """An agent's agos_skill_request tool (the guard's skills.py)."""

    member: str = Field(default="", max_length=64, pattern=r"^[a-z0-9-]*$")
    action: str = Field(default="status", pattern=r"^(search|request|status)$")
    query: str = Field(default="", max_length=200)
    source: str = Field(default="", max_length=300)
    reason: str = Field(default="", max_length=1000)
    tests: list[SkillTest] = Field(default_factory=list, max_length=2)
    criteria: str = Field(default="", max_length=4000)
    chat: str = Field(default="", max_length=90)  # where it was asked from (read vs act)
    session: str = SESSION
    once: str = ONCE


@bridge_router.post("/skill-request")
async def skill_request_call(
    core: CoreDep, workspace_id: str, body: SkillRequestCall, authorization: Auth = None
) -> dict[str, Any]:
    """Find-skills (Step 63): search this workspace's skills and Hermes's hub, ask for
    a hub skill (installed through Hermes, tested, the owner asked when it carries
    scripts or the scan warns), or read where the agent's requests stand."""
    from agos_core.actions import skill_requests
    from agos_core.actions.errors import ActionError

    ws = _checked(core, workspace_id, authorization)
    gate = {"action": body.action, "source": body.source}
    refused = await asyncio.to_thread(
        owner_gate.gate_refusal,
        core,
        ws,
        body.chat,
        owner_gate.SKILL_REQUEST,
        gate,
        body.session,
        body.once,
    )
    if refused:
        return {"error": refused}
    try:
        if body.action == "search":
            return await asyncio.to_thread(skill_requests.search, core, ws, body.query)
        if body.action == "status":
            return await asyncio.to_thread(skill_requests.status, core, ws, body.member)
        return await asyncio.to_thread(
            lambda: skill_requests.request(
                core,
                ws,
                member=body.member,
                source=body.source,
                reason=body.reason,
                tests=[t.model_dump() for t in body.tests],
                criteria=body.criteria,
            )
        )
    except ActionError as error:
        return {"error": error.message}


class SecurityEvent(BaseModel):
    kind: Literal["host", "origin"]
    where: str = Field(default="", max_length=300)
    detail: str = Field(default="", max_length=300)


@router.post("/security/events", status_code=204)
def security_event(body: SecurityEvent) -> None:
    """A request the web app refused (rate-limited, no secrets: actions/security_events)."""
    security_events.record(body.kind, where=body.where, detail=body.detail)
