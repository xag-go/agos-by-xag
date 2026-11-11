"""The core HTTP API. Internal only: reachable by the web app on the private
network, never published (ADR 0009)."""

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from agos_core.actions import chat, diagnostics, system_log
from agos_core.actions.services.system import startup
from agos_core.api import agos_update as agos_update_api
from agos_core.api import (
    apps,
    automations,
    backups,
    browse,
    capabilities,
    channels,
    chats,
    cofounder_actions,
    error_bodies,
    hermes_bridge,
    identity,
    library,
    models,
    overview,
    preferences,
    workers,
    workspaces,
)
from agos_core.api import artifacts as artifacts_api
from agos_core.api import card_docs as card_docs_api
from agos_core.api import card_services as card_services_api
from agos_core.api import connections as connections_api
from agos_core.api import docs as docs_api
from agos_core.api import errors as errors_api
from agos_core.api import folders as folders_api
from agos_core.api import founder as founder_api
from agos_core.api import hermes_update as hermes_update_api
from agos_core.api import inbox as inbox_api
from agos_core.api import kanban as kanban_api
from agos_core.api import log as log_api
from agos_core.api import office as office_api
from agos_core.api import ongoing as ongoing_api
from agos_core.api import ops as ops_api
from agos_core.api import pipelines as pipelines_api
from agos_core.api import portability as portability_api
from agos_core.api import proactive as proactive_api
from agos_core.api import push as push_api
from agos_core.api import read_vs_act as read_vs_act_api
from agos_core.api import remote_access as remote_access_api
from agos_core.api import routines as routines_api
from agos_core.api import screen as screen_api
from agos_core.api import search as search_api
from agos_core.api import skill_growth as skill_growth_api
from agos_core.api import skill_studio as skill_studio_api
from agos_core.api import tool_keys as tool_keys_api
from agos_core.api import updates as updates_api
from agos_core.api import vision as vision_api
from agos_core.api import work_hours as work_hours_api
from agos_core.api.deps import require_internal
from agos_core.config import Settings, load_settings
from agos_core.context import open_core

log = logging.getLogger("agos")

# Every router behind the internal token (create_app mounts each with it).
_PROTECTED_API_MODULES = (
    workspaces,
    chats,
    automations,
    overview,
    models,
    identity,
    library,
    preferences,
    channels,
    backups,
    workers,
    apps,
    capabilities,
    browse,
    cofounder_actions,
    log_api,
    docs_api,
    errors_api,
    screen_api,
    tool_keys_api,
    proactive_api,
    ongoing_api,
    kanban_api,
    card_docs_api,
    artifacts_api,
    inbox_api,
    office_api,
    hermes_update_api,
    agos_update_api,
    updates_api,
    push_api,
    skill_studio_api,
    routines_api,
    vision_api,
    search_api,
    portability_api,
    pipelines_api,
    card_services_api,
    connections_api,
    skill_growth_api,
    founder_api,
    remote_access_api,
    work_hours_api,
    folders_api,
    read_vs_act_api,
    ops_api,
)


def create_app(settings: Settings | None = None, *, background: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        core = open_core(settings or load_settings())
        app.state.core = core
        # AGOS's own warnings and errors go to the workspace Log as well; each error
        # is counted on its issue (Settings → Errors) and a new one is told to him.
        from agos_core.actions import error_alerts

        alerts = error_alerts.Alerts(core)
        log_handler = system_log.install(core, alerts)
        # A Hermes internal AGOS relies on that broke: the owner hears it too.
        from agos_core.actions import contract_alert

        contract_alert.install(core)
        tasks_at_start = await startup.once_at_start(core, background=background)
        tasks = startup.loops(core, background=background)
        app.state.loops = tasks
        log.info("core started")
        yield
        for task in tasks + tasks_at_start:
            task.cancel()
        await chat.shutdown(core)
        contract_alert.uninstall()
        system_log.uninstall(log_handler)
        alerts.stop()
        startup.stop_reads()
        core.db.close()

    app = FastAPI(
        title="AGOS core",
        version="0.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        # One schema per model, so the generated TypeScript types stay simple.
        separate_input_output_schemas=False,
    )

    for error, handler in error_bodies.error_handlers().items():
        app.add_exception_handler(error, handler)

    @app.get("/health", tags=["health"], response_model=dict[str, bool])
    async def health(request: Request, deep: bool = False) -> Any:
        """Liveness (`{"ok": true}`); `?deep=1`: the database answers, the data disk
        isn't full and no background loop died (503 when not)."""
        if not deep:
            return {"ok": True}
        found = diagnostics.deep(request.app, request.app.state.core)
        return JSONResponse(found, status_code=200 if found["ok"] else 503)

    # Webhooks from outside apps: checked by their secret address + signature.
    # Each workspace's Hermes → AGOS's Google server: checked by that workspace's own key.
    # Each workspace's Hermes (Telegram on its own gateway) → AGOS: its own bridge key.
    app.include_router(hermes_bridge.router)
    app.include_router(read_vs_act_api.bridge_router)

    protected = [Depends(require_internal)]
    for module in _PROTECTED_API_MODULES:
        app.include_router(module.router, dependencies=protected)
    return app
