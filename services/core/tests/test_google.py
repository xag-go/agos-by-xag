"""Google (Drive, Docs, Sheets): one MCP server (workspace-mcp) run by each
workspace's Hermes in that workspace's MCP container, on THAT workspace's own
Google login (each workspace signs in with its own account)."""

import json
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from test_apps import NOTION, servers, ws
from test_engine_sync import profile_dir
from test_library import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import apps
from agos_core.actions.services.connector import nous_apps as connector_nous_apps
from agos_core.engine import google as gg

REDIRECT = "https://agos.example.ts.net/connectors/callback"


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    apps._catalog_cache["apps"] = {a.name: a for a in [NOTION]}
    monkeypatch.setattr(
        connector_nous_apps, "nous_status", lambda core, fresh=False: (False, "Log in first.")
    )


def put_client(core: Any) -> None:
    folder = apps.connectors_home(core) / "google"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "client.json").write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "cid.apps.googleusercontent.com",
                    "client_secret": "shh",
                    "redirect_uris": [REDIRECT],
                }
            }
        )
    )


def fake_google(monkeypatch: pytest.MonkeyPatch, *, scopes: str | None = None) -> list[Any]:
    """Google's token endpoint."""
    calls: list[Any] = []
    payload = json.dumps({"email": "owner@gmail.com"}).encode()
    import base64

    id_token = "x." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".y"

    def post(url: str, data: dict[str, str]) -> dict[str, Any]:
        calls.append((url, dict(data)))
        if data.get("grant_type") == "authorization_code":
            return {
                "access_token": "AT1",
                "expires_in": 3600,
                "refresh_token": "RT1",
                "scope": scopes if scopes is not None else " ".join(gg.SCOPES),
                "id_token": id_token,
            }
        if data.get("grant_type") == "refresh_token":
            return {"access_token": "AT2", "expires_in": 3600}
        return {}

    monkeypatch.setattr(gg, "_post_form", post)
    return calls


def connect(client: Any, w: str, app: str = "google-sheets") -> dict[str, Any]:
    r = client.post(f"/workspaces/{w}/apps/{app}/connect", json={"redirectUri": REDIRECT})
    assert r.status_code == 201, r.text
    flow = r.json()
    assert flow["status"] == "authorize"
    query = parse_qs(urlsplit(flow["url"]).query)
    assert query["redirect_uri"] == [REDIRECT] and query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"] and "drive" in query["scope"][0]
    done = client.post("/apps/callback", json={"state": query["state"][0], "code": "CODE"})
    assert done.status_code == 200, done.text
    return dict(done.json())


def listed(client: Any, w: str) -> dict[str, Any]:
    return {x["name"]: x for x in client.get(f"/workspaces/{w}/apps").json()}


def test_locked_until_the_google_app_file_is_there(env: Any) -> None:  # noqa: F811
    client, core, *_ = env
    a = ws(client, "Alpha")
    got = listed(client, a)
    assert "google" not in got  # AGOS's own Google server is gone
    assert got["google-drive"]["locked"] and not got["google-drive"]["connected"]
    put_client(core)
    got = listed(client, a)
    assert got["google-drive"]["locked"] is None and got["google-drive"]["login"] == "oauth"


def test_disconnecting_one_google_app_cancels_the_login_for_all(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """Drive, Sheets and Docs share the workspace's one Google login: disconnecting any
    of them revokes it at Google and turns all three off there (none left on a dead
    login). Another workspace's Google login is not touched."""
    client, core, runner, _ = env
    put_client(core)
    calls = fake_google(monkeypatch)
    fake_containers(monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    assert connect(client, a)["status"] == "connected"
    assert connect(client, b)["status"] == "connected"
    for name in ("google-drive", "google-docs"):
        assert client.put(f"/workspaces/{a}/apps/{name}", json={"on": True}).status_code == 204
    assert client.delete(f"/workspaces/{a}/apps/google-docs/login").status_code == 204
    assert calls[-1][0] == gg.REVOKE_URL
    assert not (apps.workspace_home(core, a) / "google" / "token.json").exists()
    got = listed(client, a)
    assert not any(got[n]["connected"] for n in ("google-drive", "google-sheets", "google-docs"))
    assert not any(got[n]["on"] for n in ("google-drive", "google-sheets", "google-docs"))
    assert "app-google" not in servers(runner, a)
    assert (apps.workspace_home(core, b) / "google" / "token.json").is_file()
    assert listed(client, b)["google-sheets"]["connected"]
    # A cancelled login is an error, and a callback state works once.
    r = client.post(f"/workspaces/{a}/apps/google-drive/connect", json={"redirectUri": REDIRECT})
    state = parse_qs(urlsplit(r.json()["url"]).query)["state"][0]
    done = client.post("/apps/callback", json={"state": state, "error": "access_denied"}).json()
    assert done["status"] == "error" and "cancelled" in done["error"]
    assert client.post("/apps/callback", json={"state": state, "code": "x"}).status_code == 404


def test_missing_scope_is_refused(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, *_ = env
    put_client(core)
    fake_google(monkeypatch, scopes="openid email https://www.googleapis.com/auth/drive")
    a = ws(client, "Alpha")
    done = connect(client, a)
    assert done["status"] == "error" and "documents" in done["error"]
    assert not (apps.workspace_home(core, a) / "google" / "token.json").exists()


def fake_containers(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from agos_core.engine import mcp_runner

    started: dict[str, Any] = {}

    def ensure(docker: Any, **kw: Any) -> str:
        started[kw["profile"]] = kw
        return "http://127.0.0.1:41234/mcp"  # mcp_runner.ensure: the relay's loopback port

    monkeypatch.setattr(mcp_runner, "ensure", ensure)
    monkeypatch.setattr(mcp_runner, "running_names", lambda docker, profile: set())
    return started


def test_google_is_one_mcp_server_in_the_workspaces_container(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    """Drive, Sheets and Docs: one Google server in the workspace's own MCP container,
    run by Hermes; the login goes in as that container's env (never the profile or
    the sandbox); only the services ON there; other workspaces get nothing."""
    client, core, runner, hermes_home = env
    put_client(core)
    fake_google(monkeypatch)
    started = fake_containers(monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    got = listed(client, a)
    assert {"google-drive", "google-sheets", "google-docs"} <= set(got)
    assert got["google-sheets"]["locked"] is None and not got["google-sheets"]["connected"]
    assert connect(client, a)["status"] == "connected"
    got = listed(client, a)
    assert all(got[n]["connected"] for n in ("google-drive", "google-sheets", "google-docs"))
    assert got["google-sheets"]["on"] and not got["google-docs"]["on"]  # the one connected from
    assert got["google-sheets"]["account"] == "owner@gmail.com"
    assert not listed(client, b)["google-sheets"]["connected"]  # Beta signs in itself
    for name in ("google-sheets", "google-drive"):
        assert client.put(f"/workspaces/{a}/apps/{name}", json={"on": True}).status_code == 204
    entry = servers(runner, a)["app-google"]
    assert entry == {
        "url": "http://127.0.0.1:41234/mcp",
        "enabled": True,
        # Its relay lets Hermes in with the relay's own token, from the profile's .env.
        "headers": {"Authorization": "Bearer ${AGOS_MCP__RELAY_GOOGLE}"},
        # Which Google apps the one server serves: in its Hermes entry, nowhere else.
        "agos": {"apps": ["google-drive", "google-sheets"]},
    }
    assert not [n for n in servers(runner, b) if n.startswith("app-google")]
    run = started[f"agos-{a}"]
    assert run["env_key"] == "AGOS_GOOGLE" and f"agos-{b}" not in started
    from agos_core.actions import mcp_relays

    assert run["token"] == mcp_relays.token(core, a, "google")  # the relay's own bearer
    env_text = (core.engine.profile_home(a) / ".env").read_text()
    assert f"AGOS_MCP__RELAY_GOOGLE={run['token']}" in env_text
    login = json.loads(run["secret"])
    assert login["creds"]["refresh_token"] == "RT1" and login["email"] == "owner@gmail.com"  # noqa: S105
    assert login["creds"]["client_id"] == "cid.apps.googleusercontent.com"
    command = run["command"]
    assert apps.WORKSPACE_MCP in command and "--single-user" in command
    assert "--tools drive sheets" in command and "docs" not in command.split("--tools")[1]
    assert "/tmp/agos-google" in command and "RT1" not in command  # noqa: S108
    assert "\n" not in command  # it travels in a docker env file
    profile = profile_dir(hermes_home, f"agos-{a}")
    assert "RT1" not in "".join(
        p.read_text(errors="ignore")
        for p in profile.rglob("*")
        if p.is_file() and not p.is_symlink()
    )
    assert not (profile / "mcp-tokens" / "token.json").exists()
    # Off everywhere: no Google server left.
    for name in ("google-sheets", "google-drive"):
        assert client.put(f"/workspaces/{a}/apps/{name}", json={"on": False}).status_code == 204
    assert not [n for n in servers(runner, a) if n.startswith("app-google")]


def test_trashing_through_an_update_is_a_delete() -> None:
    from agos_core.hermes_plugin.agos_guard import action_of

    tool = "mcp__app_google__update_drive_file"
    assert action_of(tool, {"file_id": "x", "trashed": True}) == "apps_delete"
    assert action_of(tool, {"file_id": "x", "add_parents": "f"}) == "apps_change"
    assert action_of("mcp__app_google__search_drive_files", {}) is None
