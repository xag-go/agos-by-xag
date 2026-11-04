"""Connectors (apps): each workspace logs in with its own accounts and turns them ON/OFF."""

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import apps as actions
from agos_core.actions import composio
from agos_core.actions.apps import ComposioAccount, Flow, WorkspaceApp
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body

router = APIRouter(tags=["apps"])

AppName = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]*$")


class ConnectBody(Body):
    redirect_uri: str = Field(min_length=10, max_length=300)


class CallbackBody(Body):
    state: str = Field(min_length=8, max_length=500)
    code: str | None = Field(default=None, max_length=4000)
    error: str | None = Field(default=None, max_length=500)
    iss: str | None = Field(default=None, max_length=500)


class AppSwitch(Body):
    on: bool


@router.get("/apps/flows/{flow_id}")
def flow_status(flow_id: str) -> Flow:
    return actions.get_flow(flow_id)


@router.post("/apps/callback")
async def callback(core: CoreDep, body: CallbackBody) -> Flow:
    flow = actions.deliver_callback(body.state, body.code, body.error, body.iss, core)
    return await asyncio.to_thread(actions.wait_flow, flow.id, 90)


@router.post("/workspaces/{workspace_id}/apps/{name}/connect", status_code=201)
async def connect(core: CoreDep, workspace_id: str, name: str, body: ConnectBody) -> Flow:
    """Log this workspace in to an app with its own account."""
    flow = await asyncio.to_thread(
        actions.start_connect, core, workspace_id, name, body.redirect_uri
    )
    # The app's login page is ready within a few seconds (discovery + registration).
    for _ in range(60):
        flow = actions.get_flow(flow.id)
        if flow.status != "starting":
            break
        await asyncio.sleep(0.5)
    return flow


@router.delete("/workspaces/{workspace_id}/apps/{name}/login", status_code=204)
async def disconnect(core: CoreDep, workspace_id: str, name: str) -> None:
    """Forget this workspace's login to the app (other workspaces keep theirs)."""
    await asyncio.to_thread(actions.disconnect, core, workspace_id, name)


@router.get("/connectors/catalog")
async def catalog_rows(core: CoreDep) -> list[actions.CatalogRow]:
    """The shared list of apps (Settings → Connectors); each workspace connects its own."""
    return await asyncio.to_thread(actions.catalog_rows, core)


@router.get("/workspaces/{workspace_id}/apps")
async def workspace_apps(core: CoreDep, workspace_id: str) -> list[WorkspaceApp]:
    return await asyncio.to_thread(actions.workspace_apps, core, workspace_id)


@router.put("/workspaces/{workspace_id}/apps/{name}", status_code=204)
async def set_workspace_app(core: CoreDep, workspace_id: str, name: str, body: AppSwitch) -> None:
    await asyncio.to_thread(actions.set_workspace_app, core, workspace_id, name, on=body.on)


class ComposioKeyBody(Body):
    value: str = Field(min_length=1, max_length=500)


@router.put("/workspaces/{workspace_id}/composio/key", status_code=204)
async def set_composio_key(core: CoreDep, workspace_id: str, body: ComposioKeyBody) -> None:
    """This workspace's own Composio project key: checked, then Composio is on here.
    Apps are connected from AGOS, in this workspace's project only."""
    await asyncio.to_thread(actions.set_composio_key, core, workspace_id, body.value)


@router.get("/workspaces/{workspace_id}/composio/toolkits")
async def composio_toolkits(core: CoreDep, workspace_id: str) -> list[composio.ComposioToolkit]:
    """Composio's app list for the picker (cached a day)."""
    return await asyncio.to_thread(composio.catalog, core, workspace_id)


@router.get("/workspaces/{workspace_id}/composio/accounts")
async def composio_accounts(
    core: CoreDep, workspace_id: str, fresh: bool = False
) -> list[ComposioAccount]:
    """The last list Composio gave at once (asked again behind it); `fresh`
    (the page's Refresh) asks Composio now."""
    return await asyncio.to_thread(actions.composio_accounts, core, workspace_id, fresh=fresh)


class LinkBody(Body):
    toolkit: str = Field(min_length=1, max_length=63)


class LinkOut(Body):
    url: str


@router.post("/workspaces/{workspace_id}/composio/link")
async def composio_link(core: CoreDep, workspace_id: str, body: LinkBody) -> LinkOut:
    return LinkOut(
        url=await asyncio.to_thread(actions.composio_link, core, workspace_id, body.toolkit)
    )


@router.delete("/workspaces/{workspace_id}/composio/accounts/{account_id}", status_code=204)
async def composio_remove(core: CoreDep, workspace_id: str, account_id: str) -> None:
    await asyncio.to_thread(actions.composio_remove_account, core, workspace_id, account_id)


@router.get("/workspaces/{workspace_id}/composio/setup/{toolkit}")
async def composio_auth_setup(
    core: CoreDep, workspace_id: str, toolkit: str
) -> actions.ComposioAuthSetup:
    """What to type to set up an app Composio has no login app for."""
    return await asyncio.to_thread(actions.composio_auth_setup, core, workspace_id, toolkit)


class SetUpBody(Body):
    values: dict[str, str] = Field(max_length=20)


@router.post("/workspaces/{workspace_id}/composio/setup/{toolkit}", status_code=204)
async def composio_set_up(core: CoreDep, workspace_id: str, toolkit: str, body: SetUpBody) -> None:
    """The owner's own developer app for one app, in this workspace's Composio project."""
    await asyncio.to_thread(actions.composio_set_up, core, workspace_id, toolkit, body.values)
