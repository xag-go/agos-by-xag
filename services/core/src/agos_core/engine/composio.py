"""Composio's REST API (backend.composio.dev), with the owner's ONE project key.

The key is for AGOS as a whole (one Composio project, "AGOS"); each workspace is
its own Composio user in that project, so its connected accounts are its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

API = "https://backend.composio.dev/api/v3.1"
TIMEOUT_S = 20


class ComposioError(ValueError):
    """The message is safe to show to the owner."""


def _client(key: str) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={"x-api-key": key, "accept": "application/json"},
        timeout=TIMEOUT_S,
        follow_redirects=False,
    )


def _answer(response: httpx.Response) -> Any:
    if response.status_code in (401, 403):
        raise ComposioError("Composio refused this key. Copy a Project API key (ak_…) again.")
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except ValueError:
            detail = None
        raise ComposioError(f"Composio answered {response.status_code}: {detail or 'error'}"[:300])
    try:
        return response.json()
    except ValueError as error:
        raise ComposioError("Composio's answer couldn't be read.") from error


def check_key(key: str, client: httpx.Client | None = None) -> None:
    """A real call with the key (read-only); raises ComposioError if it doesn't work."""
    if not key.startswith("ak_"):
        raise ComposioError(
            "That isn't a Composio Project API key (it starts with ak_). "
            "Composio → your project → Settings → API Keys."
        )
    try:
        with client or _client(key) as http:
            _answer(http.get("/connected_accounts", params={"limit": 1}))
    except httpx.HTTPError as error:
        raise ComposioError("Composio didn't answer; try again.") from error


def user_id(workspace_id: str) -> str:
    """The session's user until the project's own user is known (each workspace is
    its own Composio project, so the user doesn't separate workspaces)."""
    return f"agos-{workspace_id}"


PLAYGROUND_PREFIX = "pg-test-"  # the project's user for accounts connected in Composio


@dataclass(frozen=True)
class Session:
    id: str
    url: str


@dataclass(frozen=True)
class Account:
    id: str
    toolkit: str
    status: str
    label: str
    created_at: str
    user: str = ""


def _call(key: str, method: str, path: str, client: httpx.Client | None, **kw: Any) -> Any:
    try:
        if client is not None:  # the caller's client: it stays open for its next call
            return _answer(client.request(method, path, **kw))
        with _client(key) as http:
            return _answer(http.request(method, path, **kw))
    except httpx.HTTPError as error:
        raise ComposioError("Composio didn't answer; try again.") from error


def create_session(key: str, user: str, client: httpx.Client | None = None) -> Session:
    """A session for one user of the project: its MCP server (Composio's meta tools;
    the agent asks for a login link itself when an app isn't connected yet)."""
    data = _call(
        key,
        "POST",
        "/tool_router/session",
        client,
        json={"user_id": user, "manage_connections": {"enable": True}},
    )
    sid = str(data.get("session_id") or "")
    mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    url = str(mcp.get("url") or "")
    if not sid or not url.startswith("https://"):
        raise ComposioError("Composio gave no session for this workspace.")
    return Session(sid, url)


def delete_session(key: str, session_id: str, client: httpx.Client | None = None) -> None:
    _call(key, "DELETE", f"/tool_router/session/{session_id}", client)


def accounts(key: str, client: httpx.Client | None = None) -> list[Account]:
    """Every connected account of the key's project (= this workspace's own)."""
    data = _call(key, "GET", "/connected_accounts", client, params={"limit": 200})
    result = []
    for item in data.get("items") or []:
        toolkit = item.get("toolkit") if isinstance(item.get("toolkit"), dict) else {}
        result.append(
            Account(
                id=str(item.get("id") or ""),
                toolkit=str(toolkit.get("slug") or ""),
                status=str(item.get("status") or ""),
                label=str(item.get("alias") or item.get("word_id") or ""),
                created_at=str(item.get("created_at") or ""),
                user=str(item.get("user_id") or ""),
            )
        )
    return [a for a in result if a.id]


def link(
    key: str,
    session_id: str,
    toolkit: str,
    user: str = "",
    client: httpx.Client | None = None,
) -> str:
    """Composio's own page where the owner signs in to one app for this workspace."""
    try:
        data = _call(
            key,
            "POST",
            f"/tool_router/session/{session_id}/link",
            client,
            json={"toolkit": toolkit},
        )
    except ComposioError as error:
        if "does not manage auth" not in str(error) and "auth config" not in str(error):
            raise
        # The owner's own developer app for it (Set up): Composio's page for that
        # login, which also asks what the app needs (a Shopify store's name…).
        try:
            config = _own_auth_config(key, toolkit, client)
        except ComposioError:
            config = None
        if not config or not user:
            raise ComposioError(
                f"{toolkit} needs your own developer app first: add its client ID and "
                "secret here (Set up), then Connect."
            ) from error
        data = _call(
            key,
            "POST",
            "/connected_accounts/link",
            client,
            json={"auth_config_id": config, "user_id": user},
        )
    url = str(data.get("redirect_url") or "")
    if not url.startswith("https://"):
        raise ComposioError("Composio gave no sign-in page for this app.")
    return url


def _own_auth_config(key: str, toolkit: str, client: httpx.Client | None) -> str | None:
    data = _call(key, "GET", "/auth_configs", client, params={"toolkit_slug": toolkit})
    for item in data.get("items") or []:
        if str(item.get("status") or "ENABLED").upper() != "DISABLED" and item.get("id"):
            return str(item["id"])
    return None


def delete_account(key: str, account_id: str, client: httpx.Client | None = None) -> None:
    _call(key, "DELETE", f"/connected_accounts/{account_id}", client)


# Logins that need a developer app (client id/secret) when Composio has none.
_OWN_APP_SCHEMES = {"OAUTH2", "OAUTH1", "S2S_OAUTH2", "SAML"}


@dataclass(frozen=True)
class Toolkit:
    slug: str
    name: str
    description: str
    logo: str
    categories: tuple[str, ...]
    # Connectable as is: Composio has its own login app for it, or the owner just
    # types the app's key/password on Composio's page. False = an OAuth app with no
    # Composio login app: it needs the owner's own developer app (an auth config in
    # his Composio project) first.
    ready: bool


def toolkits(key: str, client: httpx.Client | None = None) -> list[Toolkit]:
    """Composio's whole app list (about 1600), in its own order (popular first)."""
    found: list[Toolkit] = []
    cursor: str | None = None
    with client or _client(key) as http:
        for _ in range(10):
            params: dict[str, Any] = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            try:
                data = _answer(http.get("/toolkits", params=params))
            except httpx.HTTPError as error:
                raise ComposioError("Composio didn't answer; try again.") from error
            for item in data.get("items") or []:
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                slug = str(item.get("slug") or "")
                if not slug or item.get("no_auth") or item.get("is_local_toolkit"):
                    continue
                logo = str(meta.get("logo") or "")
                found.append(
                    Toolkit(
                        slug=slug,
                        name=str(item.get("name") or slug)[:80],
                        description=" ".join(str(meta.get("description") or "").split())[:240],
                        logo=logo if logo.startswith("https://") else "",
                        categories=tuple(
                            str(c.get("name") or "")
                            for c in meta.get("categories") or []
                            if isinstance(c, dict)
                        )[:4],
                        ready=bool(item.get("composio_managed_auth_schemes"))
                        or not set(item.get("auth_schemes") or []) <= _OWN_APP_SCHEMES,
                    )
                )
            cursor = data.get("next_cursor")
            if not cursor:
                break
    return found


def sees_session(key: str, session_id: str, client: httpx.Client | None = None) -> bool:
    """True when this key's project holds that session (so: the same project)."""
    try:
        with client or _client(key) as http:
            answer = http.get(f"/tool_router/session/{session_id}")
    except httpx.HTTPError as error:
        raise ComposioError("Composio didn't answer; try again.") from error
    return answer.status_code < 400


def project_user(found: list[Account]) -> str | None:
    """The user the project's apps are connected for: the one with the most working
    accounts (Composio's own pg-test-… user on a tie: the dashboard's)."""
    users = [a.user for a in found if a.user and a.status == "ACTIVE"]
    if not users:
        return None
    return max(set(users), key=lambda u: (users.count(u), u.startswith(PLAYGROUND_PREFIX), u))


def auth_config_toolkits(key: str, client: httpx.Client | None = None) -> set[str]:
    """Apps the owner set up a login for in this project (Composio → Auth Configs):
    those connect from AGOS even when Composio has no login app of its own."""
    data = _call(key, "GET", "/auth_configs", client, params={"limit": 500})
    found = set()
    for item in data.get("items") or []:
        toolkit = item.get("toolkit") if isinstance(item.get("toolkit"), dict) else {}
        if toolkit.get("slug") and str(item.get("status") or "ENABLED").upper() != "DISABLED":
            found.add(str(toolkit["slug"]))
    return found


@dataclass(frozen=True)
class AuthField:
    name: str
    label: str
    description: str
    secret: bool


@dataclass(frozen=True)
class AuthSetup:
    """What the owner's own developer app for one app needs (Composio → Auth Configs)."""

    toolkit: str
    scheme: str
    fields: tuple[AuthField, ...]
    redirect_uri: str


def auth_setup(key: str, toolkit: str, client: httpx.Client | None = None) -> AuthSetup:
    """The fields to create a login for an app Composio has no login app for."""
    data = _call(key, "GET", f"/toolkits/{toolkit}", client)
    details = [d for d in data.get("auth_config_details") or [] if isinstance(d, dict)]
    order = ["OAUTH2", "OAUTH1", "S2S_OAUTH2"]
    details.sort(key=lambda d: order.index(str(d.get("mode"))) if d.get("mode") in order else 9)
    if not details:
        raise ComposioError(f"Composio has no setup for {toolkit}.")
    mode = details[0]
    creation = (mode.get("fields") or {}).get("auth_config_creation") or {}
    fields = []
    for f in creation.get("required") or []:
        name = str(f.get("name") or "")
        if not name:
            continue
        fields.append(
            AuthField(
                name=name,
                label=str(f.get("displayName") or name)[:80],
                description=" ".join(str(f.get("description") or "").split())[:200],
                secret="secret" in name.lower() or "password" in name.lower(),
            )
        )
    redirect = next(
        (
            str(f.get("default") or "")
            for f in creation.get("optional") or []
            if f.get("name") == "oauth_redirect_uri"
        ),
        "",
    )
    return AuthSetup(toolkit, str(mode.get("mode") or ""), tuple(fields), redirect)


def create_auth_config(
    key: str,
    toolkit: str,
    scheme: str,
    credentials: dict[str, str],
    client: httpx.Client | None = None,
) -> str:
    """The owner's own developer app for one app, in the key's project. Returns its id."""
    data = _call(
        key,
        "POST",
        "/auth_configs",
        client,
        json={
            "toolkit": {"slug": toolkit},
            "auth_config": {
                "type": "use_custom_auth",
                "authScheme": scheme,
                "credentials": credentials,
            },
        },
    )
    config = data.get("auth_config") if isinstance(data.get("auth_config"), dict) else {}
    return str(config.get("id") or "")
