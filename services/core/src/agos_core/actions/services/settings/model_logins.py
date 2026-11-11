"""Settings → Models: the subscription logins Hermes makes (Claude, ChatGPT, Copilot,
Nous, xAI Grok, Hermes's other providers with a sign-in), in the shared home or in
one workspace's own Hermes root (ADR 0020), and the account limits Hermes reads
from each logged-in provider.

Owns the login flows (start, its state, the code, cancel, logout), which provider
and workspace a login may be made for, and forgetting the kept limits when a login
changes. Must not: run the login itself (Hermes's own, engine/provider_login.py) or
pick HTTP statuses (an ActionError carries its status).
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions import apps, general_sync
from agos_core.actions.errors import ActionError
from agos_core.actions.services.settings import model_catalog
from agos_core.context import Core
from agos_core.engine import limits
from agos_core.engine.models import hermes_python, per_workspace
from agos_core.engine.provider_login import SLUGS, ProviderLogins, slug_of

__all__ = [
    "account_limits",
    "cancel",
    "logins",
    "logout",
    "provider_of",
    "send_code",
    "start",
    "status",
    "workspace_of",
]

log = logging.getLogger("agos.models")


def logins(core: Core) -> ProviderLogins:
    """The engine's one ProviderLogins (made at the first login)."""
    if core.engine is None:
        raise ActionError(model_catalog.ENGINE_OFF, 503)
    found: ProviderLogins | None = getattr(core.engine, "provider_logins", None)
    if found is None:
        catalog = model_catalog.catalog_of(core)
        engine = core.engine

        def is_connected(provider: str, workspace: str | None) -> bool:
            if workspace:  # Hermes's own `auth list` in that workspace's root
                return slug_of(provider) in catalog.root_logins(engine.root(workspace))
            if provider == "xai":
                return _xai_signed_in(core)
            if provider == "nous":
                return apps.nous_signed_in(core)
            rows = catalog.load(refresh=True)["providers"]
            return any(r["id"] == provider and r["cli"]["account"] for r in rows)

        def on_connected(_provider: str, workspace: str | None) -> None:
            # The root has its own login now: Hermes stops borrowing Claude Code's
            # file there (its own setting, in the root and every member).
            if workspace:
                general_sync.own_logins_only(core, workspace)
            catalog.load(refresh=True)
            limits.forget()  # the new login's limits show at the next view

        found = ProviderLogins(engine.settings, is_connected, on_connected, home_of=engine.root)
        engine.provider_logins = found  # type: ignore[attr-defined]
    return found


def _xai_signed_in(core: Core) -> bool:
    """Hermes saved its xAI Grok login in the shared home (Grok tool services):
    Hermes's own get_provider_auth_state, read in its runtime."""
    assert core.engine is not None
    found = general_sync.hermes_logins(core.engine, core.engine.settings.hermes_home)
    return "xai-oauth" in ((found or {}).get("signed_in_state") or [])


def provider_of(provider: str, core: Core | None = None) -> str:
    """The provider, when it has a subscription login (one of Hermes's own five, or
    one of its other providers with a sign-in)."""
    if provider in SLUGS:
        return provider
    if core is not None:  # one of Hermes's other providers with a sign-in
        rows = model_catalog.catalog_of(core).load()["providers"]
        if any(r["id"] == provider and r.get("more") and r["cli"]["installed"] for r in rows):
            return provider
    raise ActionError("This provider has no subscription login.", 404)


def workspace_of(core: Core, workspace_id: str, provider: str) -> str:
    """A workspace on its own root, for a subscription it signs in to itself."""
    if not any(ws == workspace_id for ws, _, _ in model_catalog.roots(core)):
        raise ActionError("No such workspace on any root.", 404)
    try:
        slug = slug_of(provider)
    except ValueError as error:
        raise ActionError(str(error), 404) from error
    if not per_workspace(slug, "oauth_external"):
        raise ActionError("This login is made once in General Settings.", 409)
    return workspace_id


def start(core: Core, provider: str, workspace: str | None = None) -> dict[str, Any]:
    """Starts Hermes's own login (the shared home, or the workspace's root)."""
    found = logins(core)
    try:
        view: dict[str, Any] = (
            found.start(provider, workspace) if workspace else found.start(provider)
        )
    except (OSError, RuntimeError, ValueError) as error:
        if workspace:
            log.warning("login start failed for %s in %s: %s", provider, workspace, error)
        else:
            log.warning("login start failed for %s: %s", provider, error)
        raise ActionError("The engine could not start the login.", 503) from error
    return view


def status(core: Core, provider: str, workspace: str | None = None) -> dict[str, Any]:
    found = logins(core)
    view: dict[str, Any] = found.get(provider, workspace) if workspace else found.get(provider)
    return view


def send_code(core: Core, provider: str, code: str, workspace: str | None = None) -> dict[str, Any]:
    """Claude only: the code its page shows after Allow, handed to Hermes."""
    found = logins(core)
    try:
        view: dict[str, Any] = (
            found.send_code(provider, code, workspace)
            if workspace
            else found.send_code(provider, code)
        )
    except ValueError as error:
        raise ActionError(str(error), 409) from error
    return view


def cancel(core: Core, provider: str, workspace: str | None = None) -> dict[str, Any]:
    found = logins(core)
    view: dict[str, Any] = (
        found.cancel(provider, workspace) if workspace else found.cancel(provider)
    )
    return view


def logout(core: Core, provider: str, workspace: str | None = None) -> None:
    """Removes this login from Hermes (the shared home, or only that workspace's
    root: the other workspaces keep theirs); its kept limits and catalog follow."""
    found = logins(core)
    try:
        if workspace:
            found.logout(provider, workspace)
        else:
            found.logout(provider)
    except (OSError, RuntimeError, ValueError) as error:
        if workspace:
            log.warning("logout failed for %s in %s: %s", provider, workspace, error)
        else:
            log.warning("logout failed for %s: %s", provider, error)
        raise ActionError("The engine did not log out.", 503) from error
    limits.forget()
    model_catalog.load(core, True)


def account_limits(core: Core) -> list[Any]:
    """The subscription/account limits Hermes reads from each provider (real, not
    estimated). Empty when none is logged in."""
    if core.engine is None:
        return []
    try:
        python = hermes_python(core.engine.settings)
    except (RuntimeError, OSError):
        return []
    return list(limits.account_limits(core.engine.settings, python, kept=True))
