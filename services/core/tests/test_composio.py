"""Composio by key: each workspace pastes the key of its OWN Composio project.

A project's key reaches only that project, so no workspace can see another's
accounts. The key is checked, sealed per workspace and never shown again."""

from typing import Any

import pytest
from test_apps import NOTION, listed, servers, ws
from test_engine_sync import profile_dir
from test_library import env  # noqa: F401 - fixture

from agos_core.actions import apps, composio
from agos_core.actions.services.connector import composio as connector_composio
from agos_core.actions.services.connector import nous_apps as connector_nous_apps
from agos_core.engine import composio as cz


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    apps._catalog_cache["apps"] = {a.name: a for a in [NOTION]}
    monkeypatch.setattr(
        connector_nous_apps, "nous_status", lambda core, fresh=False: (False, "Log in first.")
    )


class FakeComposio:
    """Composio's API: one project per key; sessions and accounts per project."""

    def __init__(self) -> None:
        self.project_of = {
            "ak_content_1111": "p-content",
            "ak_content_2nd_2222": "p-content",  # a 2nd key of the same project
            "ak_rap_3333": "p-rap",
        }
        self.sessions: dict[str, tuple[str, str]] = {}  # id -> (project, user)
        self.by_project: dict[str, list[cz.Account]] = {}
        self.made = 0
        self.links: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []
        self.needs_setup = {"shopify"}
        self.set_up: dict[str, dict[str, dict[str, str]]] = {}

    def check_key(self, key: str) -> None:
        if key not in self.project_of:
            raise cz.ComposioError("Composio refused this key.")

    def sees_session(self, key: str, session_id: str) -> bool:
        found = self.sessions.get(session_id)
        return bool(found and found[0] == self.project_of.get(key))

    def create_session(self, key: str, user: str) -> cz.Session:
        self.made += 1
        sid = f"trs_{self.made}"
        self.sessions[sid] = (self.project_of[key], user)
        return cz.Session(sid, f"https://backend.composio.dev/tool_router/{sid}/mcp")

    def delete_session(self, key: str, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    def accounts(self, key: str) -> list[cz.Account]:
        return list(self.of(self.project_of[key]))

    def of(self, project: str) -> list[cz.Account]:
        return self.by_project.setdefault(project, [])

    def link(self, key: str, session_id: str, toolkit: str, user: str) -> str:
        project, session_user = self.sessions[session_id]
        assert project == self.project_of[key] and user == session_user
        if toolkit in self.needs_setup and toolkit not in self.set_up.get(project, {}):
            raise cz.ComposioError(f"{toolkit} needs your own developer app first.")
        self.links.append((project, user, toolkit))
        return f"https://connect.composio.dev/link/lk_{toolkit}"

    def delete_account(self, key: str, account_id: str) -> None:
        self.deleted.append(account_id)
        for items in self.by_project.values():
            items[:] = [a for a in items if a.id != account_id]

    def auth_setup(self, key: str, toolkit: str) -> cz.AuthSetup:
        return cz.AuthSetup(
            toolkit,
            "OAUTH2",
            (
                cz.AuthField("client_id", "Client id", "", False),
                cz.AuthField("client_secret", "Client secret", "", True),
            ),
            "https://backend.composio.dev/api/v1/auth-apps/add",
        )

    def create_auth_config(
        self, key: str, toolkit: str, scheme: str, credentials: dict[str, str]
    ) -> str:
        self.set_up.setdefault(self.project_of[key], {})[toolkit] = dict(credentials)
        return "ac_1"

    def user_of(self, url: str) -> str:
        return self.sessions[url.split("/tool_router/")[1].split("/")[0]][1]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeComposio:
    api = FakeComposio()
    monkeypatch.setattr(connector_composio, "composio_api", api)
    return api


def put_key(client: Any, w: str, value: str) -> Any:
    return client.put(f"/workspaces/{w}/composio/key", json={"value": value})


def test_each_workspace_its_own_project(env: Any, fake: FakeComposio) -> None:  # noqa: F811
    client, core, runner, hermes_home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    r = put_key(client, a, "ak_wrong")
    assert r.status_code == 400 and "refused" in r.json()["detail"]
    assert put_key(client, a, " ak_content_1111 ").status_code == 204
    row = listed(client, a)["composio"]
    assert row["connected"] and row["on"] and row["via"] == "key"
    assert row["account"] == "key ••••1111"
    assert not listed(client, b)["composio"]["connected"]
    # Sealed per workspace: the key is in no database row, and never sent back.
    assert "ak_content_1111" not in "\n".join(core.db.iterdump())
    assert "ak_content" not in client.get(f"/workspaces/{a}/apps").text
    # Alpha's Hermes: its session, its project's key only as ${…} (value in its .env).
    entry = servers(runner, a)["app-composio"]
    assert entry["url"].startswith("https://backend.composio.dev/tool_router/trs_")
    assert entry["headers"] == {"x-api-key": "${AGOS_MCP_APP_COMPOSIO}"}
    assert "ak_content" not in runner.config[f"agos-{a}"]["mcp_servers"]
    env_a = (profile_dir(hermes_home, f"agos-{a}") / ".env").read_text()
    assert "AGOS_MCP_APP_COMPOSIO=ak_content_1111" in env_a
    assert "app-composio" not in servers(runner, b)
    env_b = (profile_dir(hermes_home, f"agos-{b}") / ".env").read_text()
    assert "AGOS_MCP_APP_COMPOSIO" not in env_b

    # Beta can't take Alpha's project (same key, or another key of that project).
    for same in ("ak_content_1111", "ak_content_2nd_2222"):
        r = put_key(client, b, same)
        assert r.status_code == 409 and "Alpha" in r.json()["detail"], same
    assert put_key(client, b, "ak_rap_3333").status_code == 204
    assert servers(runner, b)["app-composio"]["url"] != entry["url"]
    assert sorted(p for p, _ in fake.sessions.values()) == ["p-content", "p-rap"]

    # Off: server and key leave Alpha's profile; on again needs nothing new.
    assert client.put(f"/workspaces/{a}/apps/composio", json={"on": False}).status_code == 204
    assert "app-composio" not in servers(runner, a)
    env_a = (profile_dir(hermes_home, f"agos-{a}") / ".env").read_text()
    assert "AGOS_MCP_APP_COMPOSIO" not in env_a
    assert client.put(f"/workspaces/{a}/apps/composio", json={"on": True}).status_code == 204
    assert servers(runner, a)["app-composio"]["url"] == entry["url"]

    # Accounts: each workspace sees and removes only its own project's.
    fake.of("p-content").append(cz.Account("ca_a", "instagram", "ACTIVE", "", "t"))
    fake.of("p-rap").append(cz.Account("ca_b", "instagram", "ACTIVE", "", "t"))
    assert [x["id"] for x in client.get(f"/workspaces/{a}/composio/accounts").json()] == ["ca_a"]
    assert client.delete(f"/workspaces/{a}/composio/accounts/ca_b").status_code == 404
    assert fake.deleted == []
    assert client.delete(f"/workspaces/{a}/composio/accounts/ca_a").status_code == 204
    assert fake.deleted == ["ca_a"] and [x.id for x in fake.of("p-rap")] == ["ca_b"]
    # Connect from AGOS: in Alpha's own project, for the user its agent uses.
    r = client.post(f"/workspaces/{a}/composio/link", json={"toolkit": "Instagram"})
    assert r.status_code == 200 and r.json()["url"].endswith("lk_instagram")
    assert fake.links == [
        ("p-content", fake.user_of(servers(runner, a)["app-composio"]["url"]), "instagram")
    ]

    # Disconnect Alpha: its session and its key go; Beta keeps its own.
    assert client.delete(f"/workspaces/{a}/apps/composio/login").status_code == 204
    assert not listed(client, a)["composio"]["connected"]
    assert composio.key(core, a) is None
    assert "app-composio" not in servers(runner, a)
    assert [p for p, _ in fake.sessions.values()] == ["p-rap"]
    assert "app-composio" in servers(runner, b)
    assert client.get(f"/workspaces/{a}/composio/accounts").status_code == 409


def test_apps_connected_in_composio_reach_the_agent(env: Any, fake: FakeComposio) -> None:  # noqa: F811
    """The owner connects apps in Composio's dashboard: they are its Playground
    user's (pg-test-…). The workspace's session follows that user, so its agent
    uses exactly those accounts, without any Connect in AGOS."""
    client, core, runner, _ = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    # A project with an app already: the session starts on its user.
    fake.of("p-rap").append(cz.Account("ca_r", "gmail", "ACTIVE", "", "t", "pg-test-rap"))
    put_key(client, b, "ak_rap_3333")
    assert fake.user_of(servers(runner, b)["app-composio"]["url"]) == "pg-test-rap"
    # An empty project: a placeholder user until the first app is connected.
    put_key(client, a, "ak_content_1111")
    first = servers(runner, a)["app-composio"]["url"]
    assert fake.user_of(first) == cz.user_id(a)
    assert apps.follow_composio_users(core) == 0  # nothing connected yet
    apps._followed.clear()
    fake.of("p-content").append(cz.Account("ca_g", "gmail", "ACTIVE", "", "t", "pg-test-abc"))
    assert apps.follow_composio_users(core) == 1
    moved = servers(runner, a)["app-composio"]["url"]
    assert moved != first and fake.user_of(moved) == "pg-test-abc"
    assert first.split("/tool_router/")[1].split("/")[0] not in fake.sessions  # old one ended
    # Once the agent has apps on its user it stays there: an app connected later
    # for another user is listed as not the agent's (connect it from AGOS).
    fake.of("p-content").append(cz.Account("ca_x", "slack", "ACTIVE", "", "t", "pg-test-zzz"))
    fake.of("p-content").append(cz.Account("ca_y", "notion", "ACTIVE", "", "t", "pg-test-zzz"))
    apps._followed.clear()
    assert apps.follow_composio_users(core) == 0
    listed_a = client.get(f"/workspaces/{a}/composio/accounts").json()
    assert {x["id"]: x["forAgent"] for x in listed_a} == {
        "ca_g": True,
        "ca_x": False,
        "ca_y": False,
    }
    fake.of("p-content")[:] = [x for x in fake.of("p-content") if x.id == "ca_g"]
    # Reading the list follows too (Refresh asks Composio now); Beta untouched.
    listed_a = client.get(f"/workspaces/{a}/composio/accounts?fresh=true").json()
    assert [x["id"] for x in listed_a] == ["ca_g"]
    assert fake.user_of(servers(runner, b)["app-composio"]["url"]) == "pg-test-rap"


def test_purged_workspace_forgets_its_key(env: Any, fake: FakeComposio) -> None:  # noqa: F811
    client, core, _, _ = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    put_key(client, a, "ak_content_1111")
    put_key(client, b, "ak_rap_3333")
    fake.of("p-content").append(cz.Account("ca_a", "gmail", "ACTIVE", "", "t"))
    apps.forget_workspace(core, a)
    # The owner's apps in his Composio project stay; AGOS only forgets the key.
    assert [x.id for x in fake.of("p-content")] == ["ca_a"] and composio.key(core, a) is None
    assert composio.key(core, b) == "ak_rap_3333"
    assert [p for p, _ in fake.sessions.values()] == ["p-rap"]


def test_key_shape_is_checked_before_any_call() -> None:
    with pytest.raises(cz.ComposioError, match="ak_"):
        cz.check_key("uak_user_key")


def test_project_user_prefers_composios_own() -> None:
    def acc(user: str) -> cz.Account:
        return cz.Account("ca", "gmail", "ACTIVE", "", "t", user)

    assert cz.project_user([]) is None
    assert cz.project_user([acc("agos-x"), acc("pg-test-1")]) == "pg-test-1"
    assert cz.project_user([acc("agos-x"), acc("agos-x"), acc("pg-test-1")]) == "agos-x"
    assert cz.project_user([acc("agos-x")]) == "agos-x"


def test_app_picker_lists_composio_apps(env: Any, fake: FakeComposio, monkeypatch: Any) -> None:  # noqa: F811
    client, *_ = env
    a = ws(client, "Alpha")
    assert client.get(f"/workspaces/{a}/composio/toolkits").status_code == 409  # no key yet
    put_key(client, a, "ak_content_1111")
    calls: list[str] = []

    def toolkits(key: str) -> list[cz.Toolkit]:
        calls.append(key)
        return [
            cz.Toolkit(
                "instagram",
                "Instagram",
                "Photos",
                "https://logos.composio.dev/api/instagram",
                ("social",),
                True,
            ),
            cz.Toolkit("jira", "Jira", "Issues", "", (), False),
        ]

    monkeypatch.setattr(composio, "fetch_toolkits", toolkits)
    own: set[str] = set()
    monkeypatch.setattr(composio, "fetch_auth_configs", lambda key: set(own))
    composio._catalog.clear()
    got = client.get(f"/workspaces/{a}/composio/toolkits").json()
    assert [t["slug"] for t in got] == ["instagram", "jira"]
    assert got[0]["ready"] and not got[1]["ready"]
    # Once the owner set Jira up through AGOS (Auth Configs), it is ready here at once.
    body = {"values": {"client_id": "id1", "client_secret": "s1"}}
    assert client.post(f"/workspaces/{a}/composio/setup/jira", json=body).status_code == 204
    own.add("jira")
    got = client.get(f"/workspaces/{a}/composio/toolkits").json()
    assert got[1]["ready"]
    assert calls == ["ak_content_1111"]  # the list is read once, then cached


def test_the_app_picker_never_waits_on_composio(
    env: Any,  # noqa: F811
    fake: FakeComposio,
    monkeypatch: Any,
) -> None:
    """Step 41: the picker's ready marks come from Composio's Auth Configs list
    (a network call). It was asked on every view; now the last answer comes at
    once and Composio is asked again behind it each half minute (like the accounts
    list), the read-ahead asks first, and a new key never gets the old key's list."""
    import threading
    import time

    from agos_core.engine.read_cache import ReadCache

    client, core, _runner, _ = env
    a = ws(client, "Alpha")
    put_key(client, a, "ak_content_1111")
    monkeypatch.setattr(
        composio, "fetch_toolkits", lambda key: [cz.Toolkit("jira", "Jira", "", "", (), False)]
    )
    composio._catalog.clear()
    asked: list[str] = []
    own: set[str] = set()
    gate = threading.Event()
    gate.set()

    def auth_configs(key: str) -> set[str]:
        asked.append(key)
        assert gate.wait(10), "Composio never answered"
        return set(own)

    monkeypatch.setattr(composio, "fetch_auth_configs", auth_configs)
    url = f"/workspaces/{a}/composio/toolkits"
    composio.read_ahead(core)  # after the start: Composio asked before the page
    assert asked == ["ak_content_1111"]
    assert not client.get(url).json()[0]["ready"]
    assert asked == ["ak_content_1111"]  # kept: the page asked nobody
    # Half a minute later Composio is slow (the stand-in waits until let go): the
    # page answers at once with the last list, Composio asked again behind it.
    own.add("jira")
    gate.clear()
    for entry in composio._own_cache(core)._entries.values():
        entry.stamp = -1
    started = time.monotonic()
    assert not client.get(url).json()[0]["ready"]
    assert time.monotonic() - started < 2
    gate.set()
    assert ReadCache.settle(10)
    assert client.get(url).json()[0]["ready"]  # Composio's new answer shows
    assert len(asked) == 2
    # Another key (another project): its own answer, never the old key's list.
    own.clear()
    composio.store(core, a, "ak_content_2nd_2222")
    assert not client.get(url).json()[0]["ready"]
    assert asked[-1] == "ak_content_2nd_2222"


def test_which_apps_connect_as_is() -> None:
    """API-key apps connect on Composio's page (the owner types the key there); only
    OAuth apps Composio has no login app for need his own developer app first."""
    import httpx

    items = [
        {"slug": "gmail", "auth_schemes": ["OAUTH2"], "composio_managed_auth_schemes": ["OAUTH2"]},
        {"slug": "perplexityai", "auth_schemes": ["API_KEY"], "composio_managed_auth_schemes": []},
        {"slug": "twitter", "auth_schemes": ["OAUTH2"], "composio_managed_auth_schemes": []},
        {"slug": "notion2", "auth_schemes": ["DCR_OAUTH"], "composio_managed_auth_schemes": []},
        {"slug": "local", "is_local_toolkit": True, "auth_schemes": ["API_KEY"]},
        {"slug": "free", "no_auth": True},
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"items": items}))
    client = httpx.Client(base_url=cz.API, transport=transport)
    got = {t.slug: t.ready for t in cz.toolkits("ak_x", client=client)}
    assert got == {"gmail": True, "perplexityai": True, "twitter": False, "notion2": True}


def test_link_for_an_app_with_no_login_app_says_what_to_do() -> None:
    import httpx

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Composio does not manage auth for toolkit twitter"}}
        )

    client = httpx.Client(base_url=cz.API, transport=httpx.MockTransport(answer))
    with pytest.raises(cz.ComposioError, match="Set up"):
        cz.link("ak_x", "trs_1", "twitter", client=client)


def test_set_up_an_app_with_no_composio_login(env: Any, fake: FakeComposio) -> None:  # noqa: F811
    """Shopify: AGOS shows its developer-app fields and creates the login in THIS
    workspace's project only; then Connect works there (and not in another)."""
    client, _, _, _ = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    put_key(client, a, "ak_content_1111")
    put_key(client, b, "ak_rap_3333")
    r = client.post(f"/workspaces/{a}/composio/link", json={"toolkit": "shopify"})
    assert r.status_code == 409 and "developer app" in r.json()["detail"]
    form = client.get(f"/workspaces/{a}/composio/setup/shopify").json()
    assert [f["name"] for f in form["fields"]] == ["client_id", "client_secret"]
    assert form["fields"][1]["secret"] and form["redirectUri"].startswith("https://")
    r = client.post(f"/workspaces/{a}/composio/setup/shopify", json={"values": {"client_id": "x"}})
    assert r.status_code == 400 and "Client secret" in r.json()["detail"]
    assert fake.set_up == {}
    body = {"values": {"client_id": " id1 ", "client_secret": "s1", "extra": "no"}}
    assert client.post(f"/workspaces/{a}/composio/setup/shopify", json=body).status_code == 204
    assert fake.set_up == {"p-content": {"shopify": {"client_id": "id1", "client_secret": "s1"}}}
    assert (
        client.post(f"/workspaces/{a}/composio/link", json={"toolkit": "shopify"}).status_code
        == 200
    )
    assert (
        client.post(f"/workspaces/{b}/composio/link", json={"toolkit": "shopify"}).status_code
        == 409
    )
    assert client.get(f"/workspaces/{a}/composio/setup/../x").status_code == 404


def test_link_falls_back_to_the_owners_own_login() -> None:
    """Shopify after Set up: the session can't make its link (the login needs the
    store's name), so Composio's page for that login is used, for the same user."""
    import json

    import httpx

    seen: list[tuple[str, str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path.endswith("/link") and "tool_router" in request.url.path:
            return httpx.Response(
                400, json={"error": {"message": "no auth config without required fields"}}
            )
        if request.url.path.endswith("/auth_configs"):
            return httpx.Response(200, json={"items": [{"id": "ac_9", "status": "ENABLED"}]})
        return httpx.Response(200, json={"redirect_url": "https://connect.composio.dev/link/lk_s"})

    client = httpx.Client(base_url=cz.API, transport=httpx.MockTransport(answer))
    assert cz.link("ak_x", "trs_1", "shopify", "pg-test-1", client=client).endswith("lk_s")
    assert seen[-1][2] == {"auth_config_id": "ac_9", "user_id": "pg-test-1"}


def test_the_accounts_list_never_waits_on_composio(env: Any, fake: FakeComposio) -> None:  # noqa: F811
    """Step 38: Composio's list (0.4-2.4 s over the network) comes at once from the
    last answer and is asked again behind the page each half minute; Refresh
    (fresh) and a removal ask Composio now, and a new key is never answered
    with the old key's list."""
    from agos_core.engine.read_cache import ReadCache

    client, core, _runner, _ = env
    a = ws(client, "Alpha")
    put_key(client, a, "ak_content_1111")
    fake.of("p-content").append(cz.Account("ca_1", "gmail", "ACTIVE", "", "t"))
    asked: list[str] = []
    real = fake.accounts

    def counted(key: str) -> list[cz.Account]:
        asked.append(key)
        return real(key)

    fake.accounts = counted  # type: ignore[method-assign]
    url = f"/workspaces/{a}/composio/accounts"
    assert [x["id"] for x in client.get(url).json()] == ["ca_1"]
    fake.of("p-content").append(cz.Account("ca_2", "slack", "ACTIVE", "", "t"))
    assert [x["id"] for x in client.get(url).json()] == ["ca_1"]  # kept: no ask
    assert len(asked) == 1
    for entry in apps._accounts_cache(core)._entries.values():
        entry.stamp = -1  # half a minute later
    assert [x["id"] for x in client.get(url).json()] == ["ca_1"]  # at once
    assert ReadCache.settle(10)
    assert [x["id"] for x in client.get(url).json()] == ["ca_1", "ca_2"]
    fake.of("p-content").append(cz.Account("ca_3", "notion", "ACTIVE", "", "t"))
    ids = [x["id"] for x in client.get(url + "?fresh=true").json()]
    assert ids == ["ca_1", "ca_2", "ca_3"]  # Refresh
    assert client.delete(f"{url}/ca_3").status_code == 204
    assert [x["id"] for x in client.get(url).json()] == ["ca_1", "ca_2"]  # the removal shows
    apps.read_ahead_composio_accounts(core)  # the warmer: a workspace with no key is skipped
