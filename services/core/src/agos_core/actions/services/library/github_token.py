"""The GitHub token Hermes's Skills Hub reads, and the library read-ahead.
Must not: log or return the token itself (only its state).

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import time

from agos_core.actions.errors import ActionError
from agos_core.actions.services.library.apply import agent_text
from agos_core.actions.services.library.records import library_home, log, workspace_skills_module
from agos_core.actions.services.library.workspace_state import switches
from agos_core.context import Core
from agos_core.db.records import Record
from agos_core.engine import read_cache
from agos_core.engine.github_token import GithubToken, TokenProblem, TokenStatus
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import process as hermes_process

__all__ = [
    "GithubTokenState",
    "check_agent",
    "github_token_status",
    "read_ahead",
    "read_ahead_connectors",
    "remove_github_token",
    "save_github_token",
]

# ---- the GitHub token Hermes's Skills Hub reads (Settings → Tools) ---------------


class GithubTokenState(Record):
    saved: bool
    method: str
    limit: int | None = None
    remaining: int | None = None
    reset: int | None = None
    error: str | None = None


def _github_token(core: Core) -> GithubToken:
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    return GithubToken(core.engine.settings, library_home(core))


# Hermes's GitHub state per library home, keyed on what the .env files its skills
# commands load hold (a new or removed token is asked for before the page shows).
# GitHub's hourly numbers in it move all the time: the page gets the last answer
# at once and they are asked again behind it every minute.
_TOKEN_STATES: read_cache.ReadCache[TokenStatus] = read_cache.ReadCache(
    "github_token", max_entries=8
)


def _token_status(core: Core, *, kept: bool) -> TokenStatus:
    token = _github_token(core)
    held = (token.library_home / ".env", token.engine.managed_home / ".env")
    return _TOKEN_STATES.get(
        (str(token.library_home), read_cache.content_stamp(*held)),
        int(time.time() // 60),
        token.status,
        stale_ok=kept,
    )


def _token_state(status: TokenStatus) -> GithubTokenState:
    return GithubTokenState(
        saved=status.saved,
        method=status.method,
        limit=status.limit,
        remaining=status.remaining,
        reset=status.reset,
        error=status.error,
    )


def github_token_status(core: Core) -> GithubTokenState:
    try:
        return _token_state(_token_status(core, kept=True))
    except (RuntimeError, ValueError, hermes_process.TimeoutExpired) as error:
        raise ActionError("Hermes didn't answer about GitHub. Try again.", 502) from error


def save_github_token(core: Core, token: str) -> GithubTokenState:
    try:
        state = _token_state(_github_token(core).save(token))
    except TokenProblem as error:
        raise ActionError(str(error), 400) from error
    except (RuntimeError, ValueError, hermes_process.TimeoutExpired) as error:
        raise ActionError("Hermes did not save the token. Try again.", 502) from error
    log.info("GitHub token for the skills hub saved in Hermes")
    return state


def remove_github_token(core: Core) -> None:
    try:
        _github_token(core).remove()
    except (RuntimeError, hermes_process.TimeoutExpired) as error:
        raise ActionError("Hermes did not remove the token. Try again.", 502) from error
    log.info("GitHub token for the skills hub removed from Hermes")


def read_ahead_connectors(core: Core) -> None:
    """After the core starts (engine/read_ahead.py AT_START): each workspace's tool
    check that its Capabilities page waits for (which service-backed tools really
    work, asked in its Hermes's runtime: ~1 s cold), so the first open after a
    restart finds Hermes's answer kept (engine.tool_readiness keeps it a few
    minutes)."""
    from agos_core.db import workspaces as workspaces_repo

    engine = core.engine
    if engine is None:
        return
    for ws in workspaces_repo.list_workspaces(core.db):
        if not (engine.profile_home(ws.id) / "config.yaml").is_file():
            continue  # no Hermes root yet: nothing to ask
        try:
            if any(c.on for c in switches(core, ws.id).values()):  # as list_connectors
                engine.tool_readiness(ws.id)
        except (EngineError, OSError, ValueError, ActionError) as error:
            log.info("tool check of %s not read ahead: %s", ws.id, error)


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): what Library → tools and the
    GitHub token card ask Hermes, one Hermes run at a time (each profile's tool
    services, Hermes's GitHub state)."""
    from agos_core.actions import tool_services

    engine = core.engine
    if engine is None:
        return
    for _label, home in tool_services.homes(core):
        try:
            engine.tool_services_in(home)
        except (EngineError, OSError, ValueError) as error:
            log.info("tool services of %s not read ahead: %s", home, error)
    try:
        _token_status(core, kept=False)
    except (ActionError, RuntimeError, ValueError, hermes_process.TimeoutExpired) as error:
        log.info("Hermes's GitHub state not read ahead: %s", error)
    # Each workspace's Skills: Hermes's update check of its hub skills (the slowest).
    workspace_skills_module().read_ahead(core)


def _with_github_limit(core: Core, message: str) -> str:
    """A hub lookup failed: when GitHub's hourly limit is the reason, say so."""
    try:
        status = _github_token(core).status()
    except (ActionError, RuntimeError, ValueError, hermes_process.TimeoutExpired):
        return message
    if status.remaining != 0:
        return message
    when = (
        time.strftime("%H:%M UTC", time.gmtime(status.reset)) if status.reset else "within the hour"
    )
    if status.method == "anonymous":
        return (
            f"GitHub's limit for this server is used up (60 an hour without a token); it comes "
            f"back at {when}. Add a GitHub token in Settings → Tools to raise it to 5,000."
        )
    return f"GitHub's hourly limit for the saved token is used up; it comes back at {when}."


def check_agent(core: Core, workspace_id: str, name: str | None) -> str | None:
    """A task or chat may only pick an agent that is on in its workspace."""
    if not name:
        return None
    if agent_text(core, workspace_id, name) is None:
        raise ActionError("That agent isn't on in this workspace (Connectors).")
    return name
