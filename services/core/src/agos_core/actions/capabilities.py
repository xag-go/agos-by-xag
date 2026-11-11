"""Capability requests: the Co-Founder asks from a chat, the owner decides.

The Co-Founder's agos_capability tool runs behind Hermes's own approval gate: in
"ask" mode the agos-guard plugin makes Hermes show its Allow / Deny before the
tool runs (hermes_channel.tool_check). What stays here is the record (the card
in the chat) and an app's login, which only the owner can do.

Approve: the thing is turned on/off in the workspace's Capabilities (the same
action as the owner's own switch). An app that isn't connected yet starts its
login first; it is turned on when the login finishes. Then the Co-Founder is told
in the chat and carries on.
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions import apps as apps_actions
from agos_core.actions import library as library_actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import capability_requests as requests_repo
from agos_core.db import library as library_repo
from agos_core.db.records import CapabilityRequestView, Record
from agos_core.db.rows import now
from agos_core.engine import capabilities as eng

log = logging.getLogger("agos.capabilities")

MAX_PER_TURN = 1_000  # no real cap: every request of the turn is kept
LAST_REDIRECT_KEY = "connectors.redirect_uri"
DEFAULT_REDIRECT = "http://localhost:3001/connectors/callback"


class Decision(Record):
    request: CapabilityRequestView
    login_url: str | None = None  # an app to log in to first


def choices(core: Core, workspace_id: str) -> list[eng.Choice]:
    out = [
        eng.Choice(
            kind="app",
            name=a.name,
            title=a.title,
            on=a.on,
            connected=a.connected,
            locked=a.locked,
        )
        for a in apps_actions.workspace_apps(core, workspace_id)
    ]
    out += [
        eng.Choice(
            kind=c.kind,
            name=c.name,
            title=c.title,
            on=c.on,
            connected=True,
            locked=c.locked,
        )
        # This workspace's own agents and MCP servers and the owner's shared library
        # (skills, tools, plugins); another workspace's are never listed here.
        for c in library_actions.list_connectors(core, workspace_id)
    ]
    return out


def instructions(core: Core, workspace_id: str) -> str:
    try:
        return eng.request_instructions(choices(core, workspace_id))
    except (ActionError, OSError) as error:  # never block an answer on this list
        log.warning("capabilities of %s not listed: %s", workspace_id, error)
        return ""


def save(
    core: Core, workspace_id: str, chat_id: int, turn_id: int, asks: list[eng.Ask]
) -> list[int]:
    """Stores what can be asked; anything unknown, locked or already so is dropped."""
    known = {(c.kind, c.name): c for c in choices(core, workspace_id)}
    pending = {
        (r["kind"], r["name"], bool(r["turn_on"]))
        for r in requests_repo.pending(core.db, workspace_id)
    }
    saved: list[int] = []
    for ask in asks:
        choice = known.get((ask.kind, ask.name))
        if choice is None or len(saved) >= MAX_PER_TURN:
            continue
        if (ask.on and choice.locked) or choice.on == ask.on:
            continue
        if (ask.kind, ask.name, ask.on) in pending:
            continue
        made = requests_repo.insert(
            core.db,
            workspace_id,
            chat_id,
            turn_id,
            kind=ask.kind,
            name=ask.name,
            title=choice.title,
            turn_on=ask.on,
            reason=ask.why,
        )
        pending.add((ask.kind, ask.name, ask.on))
        saved.append(made)
    return saved


def _view(r: Any) -> CapabilityRequestView:
    return CapabilityRequestView(
        id=r["id"],
        kind=r["kind"],
        name=r["name"],
        title=r["title"],
        turn_on=bool(r["turn_on"]),
        reason=r["reason"],
        status=r["status"],
        error=r["error"],
    )


def of_turn(db: Any, turn_id: int) -> list[CapabilityRequestView]:
    return [_view(r) for r in requests_repo.of_turn(db, turn_id)]


def _row(core: Core, workspace_id: str, request_id: int) -> Any:
    row = requests_repo.get(core.db, workspace_id, request_id)
    if row is None:
        raise NotFoundError("This request")
    return row


def _set(core: Core, request_id: int, **fields: Any) -> None:
    fields.setdefault("decided_at", now())
    requests_repo.set_fields(core.db, request_id, fields)


def _switch(core: Core, row: Any) -> None:
    """The owner's own switch in Capabilities, for this one thing."""
    workspace_id, kind, name, on = (
        row["workspace_id"],
        row["kind"],
        row["name"],
        bool(row["turn_on"]),
    )
    if kind == "app":
        apps_actions.set_workspace_app(core, workspace_id, name, on=on)
        return
    item = library_repo.find_item(core.db, kind, name, workspace_id)
    if item is None:
        raise ActionError(f"{row['title']} isn't in the library any more.", 409)
    from agos_core.actions import workspace_skills

    if kind == "skill" and workspace_skills.never_written(core, item):
        raise ActionError(
            f"{row['title']} has nothing in it: it was never written (an earlier create "
            "of it failed). Create it again first.",
            409,
        )
    mine = library_actions.switches(core, workspace_id).get(int(item["id"]))
    library_actions.set_connector(
        core,
        workspace_id,
        int(item["id"]),
        on=on,
        allowed_tools=list(mine.allowed_tools) if mine else [],
        local=mine.local if mine else "",
    )


def _tell_cofounder(core: Core, row: Any) -> None:
    """A short note in the chat, so the Co-Founder continues with the new tool."""
    if row["chat_id"] is None:
        return
    from agos_core.actions import chat as chat_actions

    what = f"{row['title']} ({row['kind']})"
    body = (
        f"✅ {what} is now on in this workspace. Carry on with what I asked."
        if row["turn_on"]
        else f"✅ {what} is now off in this workspace."
    )
    try:
        chat_actions.post_message(core, row["workspace_id"], int(row["chat_id"]), body)
    except ActionError as error:  # the chat was deleted meanwhile
        log.info("request %s: chat not told (%s)", row["id"], error.message)


def _finish(core: Core, row: Any, *, tell: bool = True) -> None:
    try:
        _switch(core, row)
    except ActionError as error:
        _set(core, int(row["id"]), status="failed", error=error.message[:300])
        return
    _set(core, int(row["id"]), status="done", error=None)
    if tell:
        _tell_cofounder(core, row)


def redirect_uri(core: Core) -> str:
    from agos_core.db.app_settings import get_setting

    value = get_setting(core.db, LAST_REDIRECT_KEY, None)
    return value if isinstance(value, str) and value else DEFAULT_REDIRECT


def remember_redirect(core: Core, uri: str) -> None:
    from agos_core.db.app_settings import set_setting

    set_setting(core.db, LAST_REDIRECT_KEY, uri)


def decide(
    core: Core,
    workspace_id: str,
    request_id: int,
    approve: bool,
    redirect: str | None = None,
) -> Decision:
    require_workspace(core, workspace_id)
    row = _row(core, workspace_id, request_id)
    if row["status"] not in ("proposed", "connecting", "failed"):
        return Decision(request=_view(row))
    if not approve:
        _set(core, request_id, status="rejected", error=None)
        return Decision(request=_view(_row(core, workspace_id, request_id)))
    login_url = None
    if row["kind"] == "app" and row["turn_on"] and row["name"] != apps_actions.NOUS_APP:
        app = apps_actions.catalog(core).get(row["name"])
        if app is None:
            _set(core, request_id, status="failed", error="This app isn't available any more.")
        elif app.locked:
            _set(core, request_id, status="failed", error=app.locked)
        elif not apps_actions._is_connected(core, workspace_id, app):
            uri = apps_actions.check_redirect(redirect or redirect_uri(core))
            if redirect:
                remember_redirect(core, redirect)
            try:
                flow = apps_actions.start_connect(core, workspace_id, row["name"], uri)
                flow = _until_login_page(flow.id)
            except ActionError as error:
                _set(core, request_id, status="failed", error=error.message[:300])
            else:
                if flow.status == "connected":
                    _finish(core, _row(core, workspace_id, request_id))
                elif flow.url:
                    login_url = flow.url
                    _set(core, request_id, status="connecting", flow_id=flow.id, error=None)
                else:
                    _set(
                        core,
                        request_id,
                        status="failed",
                        error=(flow.error or "The login didn't start.")[:300],
                    )
        else:
            _finish(core, row)
    else:
        _finish(core, row)
    return Decision(request=_view(_row(core, workspace_id, request_id)), login_url=login_url)


def _until_login_page(flow_id: str, timeout: float = 20) -> apps_actions.Flow:
    """The login helper needs a moment to give its login page."""
    import time

    deadline = time.monotonic() + timeout
    flow = apps_actions.get_flow(flow_id)
    while flow.status == "starting" and time.monotonic() < deadline:
        time.sleep(0.2)
        flow = apps_actions.get_flow(flow_id)
    return flow


def after_login(
    core: Core, workspace_id: str, app: str, connected: bool, error: str | None
) -> None:
    """A workspace's app login ended: its requests waiting on it go on (or say why not)."""
    for row in requests_repo.connecting_for_app(core.db, workspace_id, app):
        if connected:
            _finish(core, row)
        else:
            _set(
                core,
                int(row["id"]),
                status="failed",
                error=(error or "The login didn't finish.")[:300],
            )
