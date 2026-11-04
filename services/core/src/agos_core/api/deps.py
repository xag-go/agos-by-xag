"""Shared dependencies: the core context and the internal-token check."""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from agos_core.context import Core
from agos_core.domain.secrets import same_secret


def get_core(request: Request) -> Core:
    core: Core = request.app.state.core
    return core


def require_internal(
    request: Request, x_agos_internal: Annotated[str | None, Header()] = None
) -> None:
    """Only the web app (which already checked who is asking) may call the API."""
    core: Core = request.app.state.core
    if not x_agos_internal or not same_secret(x_agos_internal, core.internal_token):
        from agos_core.actions import security_events

        said = "missing" if not x_agos_internal else "wrong"
        security_events.record("internal_token", where=request.url.path, detail=said)
        raise HTTPException(status_code=401, detail="Not allowed")


CoreDep = Annotated[Core, Depends(get_core)]
