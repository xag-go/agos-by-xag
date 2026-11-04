"""Composio: the workspace's key, its sessions and accounts, following its users, an app's auth set-up.
Must not: run Hermes's login flow (connect_flow does).

Split out of agos_core.actions.apps (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import hashlib
import threading
import time
import weakref

from agos_core.actions import composio as composio_actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.connector.app_catalog import (
    COMPOSIO,
    ComposioAccount,
    log,
    workspace_home,
)
from agos_core.actions.services.connector.workspace_apps import _key_session, _turn_on
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import workspace_app_logins as logins_repo
from agos_core.db.activity import add_activity
from agos_core.db.records import Record
from agos_core.db.rows import dump_json, load_json, now
from agos_core.db.workspaces import name_of
from agos_core.engine import apps as eng
from agos_core.engine import composio as cz
from agos_core.engine import read_cache

__all__ = [
    "FOLLOW_EVERY_S",
    "AuthSetupField",
    "ComposioAuthSetup",
    "composio_accounts",
    "composio_api",
    "composio_auth_setup",
    "composio_link",
    "composio_remove_account",
    "composio_set_up",
    "follow_composio_users",
    "read_ahead_composio_accounts",
    "set_composio_key",
]


def _resync(core: Core, name: str, users: list[str]) -> None:
    from agos_core.actions.library import apply_workspace

    for workspace_id in users:
        problem = apply_workspace(core, workspace_id)
        if problem:
            log.warning("app %s not applied to %s: %s", name, workspace_id, problem)


# ---- Composio by a key (each workspace = its own Composio project) -------------------

composio_api = cz  # tests replace this


def _end_key_session(core: Core, workspace_id: str, name: str) -> None:
    session = _key_session(core, workspace_id, name)
    value = composio_actions.key(core, workspace_id)
    if session is None or not value:
        return
    try:
        composio_api.delete_session(value, str(session.get("id") or ""))
    except cz.ComposioError as error:
        log.warning("composio session of %s not deleted: %s", workspace_id, error)


def _same_project_as(core: Core, workspace_id: str, value: str) -> str | None:
    """Another workspace already on this key's Composio project (its name), if any."""
    rows = logins_repo.key_sessions_elsewhere(core.db, COMPOSIO, workspace_id)
    for row in rows:
        other = composio_actions.key(core, str(row["workspace_id"]))
        session = load_json(row["session"]) if row["session"] else None
        if other == value:
            return name_of(core.db, str(row["workspace_id"]))
        if (
            isinstance(session, dict)
            and session.get("id")
            and composio_api.sees_session(value, str(session["id"]))
        ):
            return name_of(core.db, str(row["workspace_id"]))
    return None


def set_composio_key(core: Core, workspace_id: str, value: str) -> None:
    """This workspace's own Composio project key: checked with Composio, refused if
    another workspace already uses that project, then Composio is on here (its
    session = its MCP server, the key in its profile's .env only)."""
    workspace = require_workspace(core, workspace_id)
    value = composio_actions.clean(value)
    try:
        composio_api.check_key(value)
        taken = _same_project_as(core, workspace_id, value)
    except cz.ComposioError as error:
        raise ActionError(str(error)) from error
    if taken is not None:
        raise ActionError(
            f"This key is for the Composio project of {taken}. "
            "Make a separate project in Composio for this workspace and use its key.",
            409,
        )
    try:
        # The project's own user when it already has apps (connected in Composio).
        user = cz.project_user(composio_api.accounts(value)) or cz.user_id(workspace_id)
        session = composio_api.create_session(value, user)
    except cz.ComposioError as error:
        raise ActionError(str(error), 409) from error
    _end_key_session(core, workspace_id, COMPOSIO)
    eng.forget_login(workspace_home(core, workspace_id), COMPOSIO)  # a Composio login before
    composio_actions.store(core, workspace_id, value)
    stamp = now()
    logins_repo.save_key_session(
        core.db,
        workspace_id,
        COMPOSIO,
        dump_json({"id": session.id, "url": session.url, "user": user}),
        stamp,
    )
    _turn_on(core, workspace_id, COMPOSIO, strict=True)
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"Composio on for {workspace.name} (its own Composio project)",
    )
    from agos_core.actions import capabilities

    capabilities.after_login(core, workspace_id, COMPOSIO, True, None)


def _with_key(core: Core, workspace_id: str) -> tuple[str, dict[str, str]]:
    require_workspace(core, workspace_id)
    value = composio_actions.key(core, workspace_id)
    session = _key_session(core, workspace_id, COMPOSIO)
    if not value or session is None:
        raise ActionError("Add this workspace's Composio key first.", 409)
    return value, session


# Each workspace's Composio accounts as Composio lists them (over the network,
# 0.4-2.4 s), per core and key. The list moves in Composio (the owner connects
# apps there): the page gets the last list at once and it is asked again behind
# it each half minute; Refresh (fresh) and a removal ask Composio at once.
_ACCOUNTS: dict[int, read_cache.ReadCache[list[cz.Account]]] = {}
_ACCOUNTS_LOCK = threading.Lock()


def _accounts_cache(core: Core) -> read_cache.ReadCache[list[cz.Account]]:
    with _ACCOUNTS_LOCK:
        found = _ACCOUNTS.get(id(core))
        if found is None:
            found = _ACCOUNTS[id(core)] = read_cache.ReadCache("composio_accounts", max_entries=64)
            weakref.finalize(core, _ACCOUNTS.pop, id(core), None)
        return found


def _accounts(core: Core, workspace_id: str, *, fresh: bool) -> tuple[str, list[cz.Account]]:
    value, _ = _with_key(core, workspace_id)
    key = (workspace_id, hashlib.sha256(value.encode()).hexdigest())
    kept = _accounts_cache(core)

    def ask() -> list[cz.Account]:
        found = composio_api.accounts(value)
        _follow_user(core, workspace_id, value, found)
        return found

    if fresh:
        kept.drop(key)
    try:
        return value, kept.get(key, int(time.time() // 30), ask, stale_ok=not fresh)
    except cz.ComposioError as error:
        raise ActionError(str(error), 502) from error


def _forget_accounts(core: Core, workspace_id: str) -> None:
    kept = _accounts_cache(core)
    for key in [k for k in kept._entries if isinstance(k, tuple) and k[0] == workspace_id]:
        kept.drop(key)


def read_ahead_composio_accounts(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): each workspace's Composio
    accounts, for the workspaces that have a Composio key."""
    from agos_core.db.workspaces import list_workspaces

    for w in list_workspaces(core.db):
        try:
            _accounts(core, w.id, fresh=False)
        except (ActionError, OSError, ValueError) as error:
            log.debug("Composio accounts of %s not read ahead: %s", w.id, error)


def composio_accounts(
    core: Core, workspace_id: str, *, fresh: bool = False
) -> list[ComposioAccount]:
    """The apps connected in this workspace's Composio project (the owner adds and
    removes them in Composio). Reading them also puts the session on the project's
    user, so the agent uses exactly these accounts."""
    _value, found = _accounts(core, workspace_id, fresh=fresh)
    session = _key_session(core, workspace_id, COMPOSIO) or {}
    agent = str(session.get("user") or "")
    return [
        ComposioAccount(
            id=a.id,
            toolkit=a.toolkit,
            status=a.status,
            label=a.label,
            created_at=a.created_at,
            for_agent=not a.user or not agent or a.user == agent,
        )
        for a in found
    ]


def composio_link(core: Core, workspace_id: str, toolkit: str) -> str:
    """Composio's sign-in page for one app, in THIS workspace's own project (its
    session's user: the same one the agent uses)."""
    toolkit = toolkit.strip().lower()
    if not eng.APP_NAME.fullmatch(toolkit.replace("_", "-")):
        raise ActionError("Pick an app from the list.")
    value, session = _with_key(core, workspace_id)
    try:
        user = str(session.get("user") or cz.user_id(workspace_id))
        return composio_api.link(value, str(session["id"]), toolkit, user)
    except cz.ComposioError as error:
        raise ActionError(str(error), 409) from error


def composio_remove_account(core: Core, workspace_id: str, account_id: str) -> None:
    """Deletes one of THIS workspace's Composio accounts."""
    mine = {a.id: a for a in composio_accounts(core, workspace_id, fresh=True)}
    account = mine.get(account_id)
    if account is None:
        raise NotFoundError("This account")
    value, _ = _with_key(core, workspace_id)
    try:
        composio_api.delete_account(value, account_id)
    except cz.ComposioError as error:
        raise ActionError(str(error), 502) from error
    _forget_accounts(core, workspace_id)  # the page's next read asks Composio
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"Composio: {account.toolkit} account removed",
    )


def _follow_user(core: Core, workspace_id: str, value: str, found: list[cz.Account]) -> bool:
    """The session follows the project's user: apps connected in Composio's dashboard
    are its Playground user's (pg-test-…), so the session must be that user's for the
    agent to see them. A new session only when the user changed. True if changed."""
    session = _key_session(core, workspace_id, COMPOSIO)
    wanted = cz.project_user(found)
    if session is None or not wanted or session.get("user") == wanted:
        return False
    if any(a.user == session.get("user") and a.status == "ACTIVE" for a in found):
        return False  # the agent already has apps on its user: never drop them
    try:
        fresh = composio_api.create_session(value, wanted)
    except cz.ComposioError as error:
        log.warning("composio session of %s not moved to %s: %s", workspace_id, wanted, error)
        return False
    _end_key_session(core, workspace_id, COMPOSIO)
    logins_repo.set_session(
        core.db,
        workspace_id,
        COMPOSIO,
        dump_json({"id": fresh.id, "url": fresh.url, "user": wanted}),
    )
    _resync(core, COMPOSIO, [workspace_id])
    return True


FOLLOW_EVERY_S = 120
_followed: dict[str, float] = {}


def follow_composio_users(core: Core) -> int:
    """Background pass (idle loop): each workspace on Composio by key whose session
    isn't on its project's Composio user yet picks it up as soon as the owner
    connects a first app in Composio. Returns how many sessions moved."""
    moved = 0
    rows = logins_repo.key_sessions(core.db, COMPOSIO)
    for row in rows:
        workspace_id = str(row["workspace_id"])
        if time.monotonic() - _followed.get(workspace_id, -FOLLOW_EVERY_S) < FOLLOW_EVERY_S:
            continue
        _followed[workspace_id] = time.monotonic()
        value = composio_actions.key(core, workspace_id)
        if not value:
            continue
        try:
            found = composio_api.accounts(value)
        except cz.ComposioError:
            continue
        moved += int(_follow_user(core, workspace_id, value, found))
    return moved


class AuthSetupField(Record):
    name: str
    label: str
    description: str
    secret: bool


class ComposioAuthSetup(Record):
    toolkit: str
    fields: list[AuthSetupField]
    redirect_uri: str


def composio_auth_setup(core: Core, workspace_id: str, toolkit: str) -> ComposioAuthSetup:
    """What to type to set up an app Composio has no login app for (Shopify, X…)."""
    toolkit = _toolkit_slug(toolkit)
    value, _ = _with_key(core, workspace_id)
    try:
        found = composio_api.auth_setup(value, toolkit)
    except cz.ComposioError as error:
        raise ActionError(str(error), 502) from error
    return ComposioAuthSetup(
        toolkit=toolkit,
        fields=[
            AuthSetupField(name=f.name, label=f.label, description=f.description, secret=f.secret)
            for f in found.fields
        ],
        redirect_uri=found.redirect_uri,
    )


def composio_set_up(core: Core, workspace_id: str, toolkit: str, values: dict[str, str]) -> None:
    """Creates the owner's own developer app for one app in THIS workspace's Composio
    project; Connect then works for it. The values go to Composio only."""
    toolkit = _toolkit_slug(toolkit)
    value, _ = _with_key(core, workspace_id)
    try:
        setup = composio_api.auth_setup(value, toolkit)
        wanted = {f.name for f in setup.fields}
        clean = {k: v.strip() for k, v in values.items() if k in wanted and v.strip()}
        missing = [f.label for f in setup.fields if f.name not in clean]
        if missing:
            raise ActionError("Fill in: " + ", ".join(missing) + ".")
        composio_api.create_auth_config(value, toolkit, setup.scheme, clean)
    except cz.ComposioError as error:
        raise ActionError(str(error), 409) from error
    composio_actions.forget_own(core, workspace_id)  # the picker shows it ready at once
    add_activity(
        core.db,
        workspace_id,
        kind="connector.changed",
        text=f"Composio: {toolkit} set up with your own developer app",
    )


def _toolkit_slug(toolkit: str) -> str:
    toolkit = toolkit.strip().lower()
    if not eng.APP_NAME.fullmatch(toolkit.replace("_", "-")):
        raise ActionError("Pick an app from the list.")
    return toolkit
