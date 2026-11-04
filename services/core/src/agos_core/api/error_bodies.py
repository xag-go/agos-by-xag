"""The API's error answers: every error body is `{"detail", "code", "help"}` (plus
`requestId` when AGOS logged it), with the plain words of domain/errors.py.

Owns: the exception handlers the app installs (ActionError, ValueError, anything
else) and the body they answer with. Must not: decide which status an action's
error gets (the action does) or word the texts (domain/errors.py does).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from agos_core.actions.errors import CAGE_DOWN, HERMES_DOWN, HERMES_RETRY_AFTER, ActionError
from agos_core.domain.errors import ErrorCode, help_for

__all__ = ["body", "error_handlers"]

log = logging.getLogger("agos")

_WORKSPACE_PATH = re.compile(r"^/workspaces/([^/]+)")

Handler = Callable[[Request, Any], Awaitable[JSONResponse]]


def body(detail: str, code: str, **extra: str) -> dict[str, str]:
    """An error body: the message, its typed code and what to do about it."""
    return {"detail": detail, "code": code, "help": help_for(code), **extra}


async def action_error(_: Request, error: ActionError) -> JSONResponse:
    return JSONResponse(body(error.message, error.code), status_code=error.status)


async def value_error(request: Request, error: Exception) -> JSONResponse:
    log.warning(
        "invalid value on %s %s: %s", request.method, request.url.path, type(error).__name__
    )
    found = body("The request contains an invalid value.", ErrorCode.INVALID_VALUE)
    return JSONResponse(found, status_code=400)


async def unhandled_error(request: Request, error: Exception) -> JSONResponse:
    """Any error no route handled: in the System Log and Settings → Errors (route,
    workspace, type, message and traceback, secrets wiped), and a typed answer
    with a reference the owner can match to it."""
    ref = uuid.uuid4().hex[:12]
    route = getattr(request.scope.get("route"), "path", "") or request.url.path
    found = _WORKSPACE_PATH.match(request.url.path)
    if isinstance(error, HERMES_DOWN):  # not AGOS's bug: Hermes is down or slow
        log.warning("%s on %s %s (ref %s)", error.code, request.method, route, ref)
        return JSONResponse(
            body(str(error), error.code, requestId=ref),
            status_code=503,
            headers={"Retry-After": HERMES_RETRY_AFTER},
        )
    if isinstance(error, CAGE_DOWN):  # the machine's cage, already told (engine/cage.py)
        log.warning("%s on %s %s (ref %s)", error.code, request.method, route, ref)
        return JSONResponse(body(str(error), error.code, requestId=ref), status_code=503)
    logging.getLogger("agos.api").error(
        "unhandled error on %s %s (ref %s)",
        request.method,
        route,
        ref,
        exc_info=error,
        extra={
            "agos_route": f"{request.method} {route}",
            "agos_request": ref,
            "agos_workspace": found.group(1) if found else None,
        },
    )
    detail = f"AGOS hit an internal error (ref {ref}). It is in Settings → Errors."
    return JSONResponse(body(detail, ErrorCode.INTERNAL_ERROR, requestId=ref), status_code=500)


def error_handlers() -> dict[type[Exception], Handler]:
    """What the app installs, most specific first."""
    return {ActionError: action_error, ValueError: value_error, Exception: unhandled_error}
