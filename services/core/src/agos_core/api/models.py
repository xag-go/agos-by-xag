"""Models and usage: what the owner can pick, and what the agent has used."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field, model_validator

from agos_core.actions import key_pools
from agos_core.actions.services.settings import model_catalog, model_keys, model_logins
from agos_core.actions.services.settings.model_catalog import read_ahead as read_ahead
from agos_core.api.deps import CoreDep
from agos_core.db.records import Record
from agos_core.domain.models import ModelSelection

router = APIRouter(tags=["models"])


class CatalogModel(Record):
    id: str
    label: str
    modes: list[Literal["cli", "api"]]
    efforts: list[str]
    default_effort: str


class CatalogProvider(Record):
    id: str
    label: str
    models: list[CatalogModel]
    # Hermes's provider name for each way in (mode → e.g. "openai-codex"): the
    # core's own mapping (engine/models.py hermes_slug), so the web never repeats it.
    hermes_providers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _hermes_names(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("hermes_providers"):
            modes = {
                str(m)
                for model in data.get("models") or []
                for m in (model.get("modes") if isinstance(model, dict) else model.modes) or []
            }
            data = {
                **data,
                "hermes_providers": model_catalog.hermes_providers(str(data.get("id")), modes),
            }
        return data


class CliConnection(Record):
    tool: str
    installed: bool
    account: str | None
    login_command: str


class ApiConnection(Record):
    last4: str
    # How the key did when Hermes last used it (its credential pool's last_status:
    # "ok", "exhausted", "dead"…; "" = not used yet), when, and Hermes's error.
    status: str = ""
    status_at: str = ""
    problem: str = ""


class WorkspaceLogin(Record):
    id: str
    name: str
    connected: bool


class ProviderConnection(Record):
    id: str
    name: str
    cli: CliConnection
    api: ApiConnection | None
    api_key: bool
    key_env: str | None = None  # Hermes's own variable for its key
    more: bool = False  # one of Hermes's other providers (not the five always shown)
    # A subscription each workspace signs in to in its own Hermes root (ADR 0020).
    per_workspace: bool = False
    workspaces: list[WorkspaceLogin] = Field(default_factory=list)


@router.get("/models/catalog")
async def catalog(core: CoreDep, refresh: bool = False) -> list[CatalogProvider]:
    """Logged-in providers' models; Hermes's own default model first (hermes_first)."""
    found = await asyncio.to_thread(model_catalog.shown, core, refresh)
    return [CatalogProvider.model_validate(p) for p in found]


@router.get("/models/default")
async def default_model(core: CoreDep) -> ModelSelection | None:
    """The model a new workspace starts on: the shared Hermes home's own model
    (null when Hermes has none there)."""
    return await asyncio.to_thread(model_catalog.default_model, core)


@router.get("/models/providers")
async def providers(core: CoreDep) -> list[ProviderConnection]:
    rows = await asyncio.to_thread(model_keys.providers, core)
    return [ProviderConnection.model_validate(p) for p in rows]


class KeyBody(Record):
    key: str


class KeyResult(Record):
    ok: bool
    message: str


@router.put("/models/providers/{provider}/key")
async def save_key(core: CoreDep, provider: str, body: KeyBody) -> KeyResult:
    """Hermes tests the key, then saves it for every workspace."""
    found = await asyncio.to_thread(model_keys.save_key, core, provider, body.key)
    return KeyResult.model_validate(found)


@router.post("/models/providers/{provider}/key/test")
async def test_key(core: CoreDep, provider: str) -> KeyResult:
    return KeyResult.model_validate(await asyncio.to_thread(model_keys.test_key, core, provider))


@router.delete("/models/providers/{provider}/key", status_code=204)
async def remove_key(core: CoreDep, provider: str) -> None:
    await asyncio.to_thread(model_keys.remove_key, core, provider)


class ProviderLogin(Record):
    provider: str
    workspace: str | None = None
    status: Literal["idle", "starting", "waiting", "checking", "done", "failed", "cancelled"]
    url: str | None
    user_code: str | None
    needs_code: bool
    message: str


class LoginCode(Record):
    code: str


@router.post("/models/providers/{provider}/login", status_code=201)
def login_start(core: CoreDep, provider: str) -> ProviderLogin:
    """Starts Hermes's own login in the shared home (tool services, Copilot, Nous)."""
    name = model_logins.provider_of(provider, core)
    return ProviderLogin.model_validate(model_logins.start(core, name))


@router.get("/models/providers/{provider}/login")
def login_status(core: CoreDep, provider: str) -> ProviderLogin:
    name = model_logins.provider_of(provider, core)
    return ProviderLogin.model_validate(model_logins.status(core, name))


@router.post("/models/providers/{provider}/login/code")
def login_code(core: CoreDep, provider: str, body: LoginCode) -> ProviderLogin:
    """Claude only: the code its page shows after Allow, handed to Hermes."""
    name = model_logins.provider_of(provider, core)
    view = model_logins.send_code(core, name, body.code)
    return ProviderLogin.model_validate(view)


@router.delete("/models/providers/{provider}/login")
def login_cancel(core: CoreDep, provider: str) -> ProviderLogin:
    name = model_logins.provider_of(provider, core)
    return ProviderLogin.model_validate(model_logins.cancel(core, name))


@router.post("/models/providers/{provider}/logout", status_code=204)
def logout(core: CoreDep, provider: str) -> None:
    """Removes this login from the shared home's Hermes."""
    name = model_logins.provider_of(provider, core)
    model_logins.logout(core, name)


# ---- a workspace's own subscription login (its Hermes root) ------------------------


def _in_root(core: CoreDep, workspace_id: str, provider: str) -> str:
    return model_logins.workspace_of(core, workspace_id, model_logins.provider_of(provider, core))


@router.post("/workspaces/{workspace_id}/models/providers/{provider}/login", status_code=201)
def workspace_login_start(core: CoreDep, workspace_id: str, provider: str) -> ProviderLogin:
    """Hermes's own `hermes auth add` in this workspace's root: the page to open."""
    ws = _in_root(core, workspace_id, provider)
    view = model_logins.start(core, provider, ws)
    return ProviderLogin.model_validate(view)


@router.get("/workspaces/{workspace_id}/models/providers/{provider}/login")
def workspace_login_status(core: CoreDep, workspace_id: str, provider: str) -> ProviderLogin:
    ws = _in_root(core, workspace_id, provider)
    return ProviderLogin.model_validate(model_logins.status(core, provider, ws))


@router.post("/workspaces/{workspace_id}/models/providers/{provider}/login/code")
def workspace_login_code(
    core: CoreDep, workspace_id: str, provider: str, body: LoginCode
) -> ProviderLogin:
    ws = _in_root(core, workspace_id, provider)
    view = model_logins.send_code(core, provider, body.code, ws)
    return ProviderLogin.model_validate(view)


@router.delete("/workspaces/{workspace_id}/models/providers/{provider}/login")
def workspace_login_cancel(core: CoreDep, workspace_id: str, provider: str) -> ProviderLogin:
    ws = _in_root(core, workspace_id, provider)
    return ProviderLogin.model_validate(model_logins.cancel(core, provider, ws))


@router.post("/workspaces/{workspace_id}/models/providers/{provider}/logout", status_code=204)
def workspace_logout(core: CoreDep, workspace_id: str, provider: str) -> None:
    """Hermes's logout in this workspace's root (the other workspaces keep theirs)."""
    ws = _in_root(core, workspace_id, provider)
    model_logins.logout(core, provider, ws)


class LimitWindow(Record):
    label: str
    used_percent: float | None
    reset_at: str | None


class AccountLimit(Record):
    provider: str
    label: str
    windows: list[LimitWindow]
    details: list[str]
    warning: bool


@router.get("/usage/limits")
def account_limits(core: CoreDep) -> list[AccountLimit]:
    """The subscription/account limits Hermes reads from each provider (real,
    not estimated). Empty when none is logged in."""
    return [
        AccountLimit(
            provider=a.provider,
            label=a.label,
            windows=[
                LimitWindow(label=w.label, used_percent=w.used_percent, reset_at=w.reset_at)
                for w in a.windows
            ],
            details=a.details,
            warning=a.warning,
        )
        for a in model_logins.account_limits(core)
    ]


class PoolEntry(Record):
    label: str
    auth_type: str
    # manual (added here: a numbered line of Hermes's managed .env, or an old
    # hand-added copy), env:<VAR> (Settings → Models), a sign-in
    source: str
    priority: int
    preview: str  # Hermes's own redacted preview
    requests: int
    status: str  # Hermes's last_status ("" = not used yet)
    status_at: str
    problem: str
    removable: bool
    movable: bool  # changes places with the keys added here (their numbers swap)


class PoolProvider(Record):
    provider: str  # Hermes's provider id
    strategy: str  # credential_pool_strategies.<provider>
    entries: list[PoolEntry]


class RootPoolEntry(Record):
    label: str
    auth_type: str
    source: str  # Hermes's own source (env:<VAR>, manual, a sign-in)
    priority: int
    preview: str  # Hermes's own redacted preview
    status: str  # Hermes's last_status in that root ("" = not used yet)


class RootPoolProvider(Record):
    provider: str
    entries: list[RootPoolEntry]


class WorkspacePool(Record):
    """One workspace's pool as its root's Hermes has it (read only)."""

    workspace_id: str
    name: str
    providers: list[RootPoolProvider]
    problem: str  # why its root's pool couldn't be read ("" = it was)


class KeyPools(Record):
    providers: list[PoolProvider]
    strategies: list[str]  # Hermes's own (SUPPORTED_POOL_STRATEGIES)
    workspaces: list[WorkspacePool] = Field(default_factory=list)  # each root's own pool (GET only)


class PoolAdd(Record):
    key: str


class PoolMove(Record):
    priority: int


class PoolStrategy(Record):
    strategy: str


@router.get("/models/key-pools")
async def get_key_pools(core: CoreDep) -> KeyPools:
    return KeyPools.model_validate(await asyncio.to_thread(key_pools.read, core, kept=True))


@router.post("/models/key-pools/{provider}")
async def add_pool_key(core: CoreDep, provider: str, body: PoolAdd) -> KeyPools:
    found = await asyncio.to_thread(key_pools.add, core, provider, body.key)
    return KeyPools.model_validate(found)


@router.delete("/models/key-pools/{provider}/{label}")
async def remove_pool_key(core: CoreDep, provider: str, label: str) -> KeyPools:
    return KeyPools.model_validate(await asyncio.to_thread(key_pools.remove, core, provider, label))


@router.put("/models/key-pools/{provider}/{label}/priority")
async def move_pool_key(core: CoreDep, provider: str, label: str, body: PoolMove) -> KeyPools:
    found = await asyncio.to_thread(key_pools.move, core, provider, label, body.priority)
    return KeyPools.model_validate(found)


@router.put("/models/key-pools/{provider}/strategy")
async def set_pool_strategy(core: CoreDep, provider: str, body: PoolStrategy) -> KeyPools:
    found = await asyncio.to_thread(key_pools.set_strategy, core, provider, body.strategy)
    return KeyPools.model_validate(found)
