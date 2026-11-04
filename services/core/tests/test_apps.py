"""Connectors (apps): connected once in Settings, ON/OFF per workspace."""

import io
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import profile_dir
from test_library import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import apps
from agos_core.actions.services.connector import connect_flow as connector_connect_flow
from agos_core.actions.services.connector import nous_apps as connector_nous_apps
from agos_core.engine import apps as eng

NOTION = eng.CatalogApp(
    name="notion", description="Pages", url="https://mcp.notion.com/mcp", auth="oauth"
)
DOCS = eng.CatalogApp(
    name="deepwiki", description="Docs", url="https://mcp.deepwiki.com/mcp", auth="none"
)
ASANA = eng.CatalogApp(
    name="asana",
    description="Tasks",
    url="https://mcp.asana.com/v2/mcp",
    auth="oauth",
    locked="Needs your own developer app or key for it; not available yet.",
)


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    apps._catalog_cache["apps"] = {a.name: a for a in [NOTION, DOCS, ASANA]}
    monkeypatch.setattr(
        connector_nous_apps, "nous_status", lambda core, fresh=False: (False, "Log in first.")
    )


class FakeLogin:
    """Stands in for connect_helper.py: prints the login page, waits for the
    browser's return on stdin, then writes the token file like Hermes does."""

    def __init__(self, home: Path, name: str, *, fail: bool = False) -> None:
        self.home, self.name, self.fail = home, name, fail
        self._out_r, self._out_w = io.StringIO(), None
        self.lines: list[str] = []
        self.ready = threading.Event()
        self.killed = False
        self.stdin = self
        self.stdout = self._gen()
        self._got: str | None = None
        self._cond = threading.Condition()

    def _gen(self) -> Any:
        yield json.dumps(
            {"event": "authorize", "url": "https://mcp.notion.com/authorize?state=STATE123abc&x=1"}
        )
        with self._cond:
            self._cond.wait_for(lambda: self._got is not None or self.killed, timeout=10)
        if self.killed or self._got is None:
            return
        data = json.loads(self._got)
        if self.fail or data.get("error"):
            yield json.dumps({"event": "error", "message": "access_denied"})
            return
        folder = self.home / "mcp-tokens"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{self.name}.json").write_text('{"access_token": "x"}')
        yield json.dumps({"event": "done", "tools": [{"name": "search", "description": "Find"}]})

    def write(self, text: str) -> None:
        with self._cond:
            self._got = text
            self._cond.notify_all()

    def flush(self) -> None:
        pass

    def poll(self) -> int | None:
        return None

    def kill(self) -> None:
        with self._cond:
            self.killed = True
            self._cond.notify_all()


def fake_spawn(monkeypatch: pytest.MonkeyPatch, *, fail: bool = False) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []

    def spawn(core: Any, workspace_id: str, job: dict[str, Any]) -> FakeLogin:
        jobs.append({**job, "workspace": workspace_id})
        return FakeLogin(apps.workspace_home(core, workspace_id), job["name"], fail=fail)

    monkeypatch.setattr(connector_connect_flow, "spawn", spawn)
    return jobs


def ws(client: Any, name: str) -> str:
    return str(client.post("/workspaces", json={"name": name, "defaultModel": MODEL}).json()["id"])


REDIRECT = {"redirectUri": "http://localhost:3001/connectors/callback"}


def connect(client: Any, w: str, app: str = "notion") -> dict[str, Any]:
    r = client.post(f"/workspaces/{w}/apps/{app}/connect", json=REDIRECT)
    assert r.status_code == 201, r.text
    flow = r.json()
    assert flow["status"] == "authorize" and flow["workspaceId"] == w
    done = client.post("/apps/callback", json={"state": "STATE123abc", "code": "abc"})
    assert done.status_code == 200, done.text
    return dict(done.json())


def listed(client: Any, w: str) -> dict[str, Any]:
    return {x["name"]: x for x in client.get(f"/workspaces/{w}/apps").json()}


def servers(runner: Any, w: str) -> dict[str, Any]:
    return dict(json.loads(runner.config.get(f"agos-{w}", {}).get("mcp_servers", "{}")))


def test_catalog_lists_apps_and_nous_row(env: Any) -> None:  # noqa: F811
    client, *_ = env
    a = ws(client, "Alpha")
    got = listed(client, a)
    assert got["nous"]["kind"] == "nous" and got["nous"]["connected"] is False
    assert got["nous"]["locked"] == "Log in first."
    assert got["notion"]["connected"] is False and got["notion"]["login"] == "oauth"
    assert got["deepwiki"]["connected"] is True  # no login needed
    assert got["asana"]["locked"]
    # The old shared list is gone: logins are per workspace only.
    assert client.get("/apps").status_code in (404, 405)


def test_shared_list_says_which_workspaces_use_an_app_and_holds_no_login(
    env: Any,  # noqa: F811
) -> None:
    client, *_ = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    rows = {r["name"]: r for r in client.get("/connectors/catalog").json()}
    assert set(rows) >= {"nous", "notion", "deepwiki", "asana", "composio"}
    assert rows["notion"]["login"] == "oauth" and rows["notion"]["source"] == "hermes"
    assert rows["composio"]["source"] == "agos"
    assert rows["asana"]["locked"] and rows["nous"]["locked"] == "Log in first."
    assert all(r["usedBy"] == [] for r in rows.values())
    assert client.put(f"/workspaces/{a}/apps/deepwiki", json={"on": True}).status_code == 204
    rows = {r["name"]: r for r in client.get("/connectors/catalog").json()}
    assert rows["deepwiki"]["usedBy"] == [a] and rows["notion"]["usedBy"] == []
    assert client.put(f"/workspaces/{b}/apps/deepwiki", json={"on": True}).status_code == 204
    rows = {r["name"]: r for r in client.get("/connectors/catalog").json()}
    assert rows["deepwiki"]["usedBy"] == sorted([a, b])
    # Only names and who uses what: no account, token or key in the list.
    assert set(rows["notion"]) == {
        "name",
        "title",
        "description",
        "login",
        "source",
        "usedBy",
        "locked",
    }


def test_each_workspace_has_its_own_login(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, runner, hermes_home = env
    jobs = fake_spawn(monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")

    # Not connected yet: can't be turned on.
    assert client.put(f"/workspaces/{a}/apps/notion", json={"on": True}).status_code == 409

    assert connect(client, a)["status"] == "connected"
    assert jobs[0]["name"] == "app-notion" and jobs[0]["url"] == NOTION.url
    assert jobs[0]["workspace"] == a
    # Connected from Alpha = on in Alpha at once; Beta has nothing.
    assert listed(client, a)["notion"]["connected"] and listed(client, a)["notion"]["on"]
    assert listed(client, a)["notion"]["tools"][0]["name"] == "search"
    assert not listed(client, b)["notion"]["connected"]
    assert client.put(f"/workspaces/{b}/apps/notion", json={"on": True}).status_code == 409
    # The login lives in Alpha's own folder, never the owner's ~/.hermes.
    token_a = apps.workspace_home(core, a) / "mcp-tokens" / "app-notion.json"
    assert token_a.is_file() and hermes_home not in token_a.parents
    assert not (apps.workspace_home(core, b) / "mcp-tokens" / "app-notion.json").exists()
    assert servers(runner, a)["app-notion"] == {"url": NOTION.url, "auth": "oauth", "enabled": True}
    assert "app-notion" not in servers(runner, b)
    # On = its entry in the workspace's Hermes config; AGOS keeps no switch of its own.
    link = profile_dir(hermes_home, f"agos-{a}") / "mcp-tokens"
    assert link.is_symlink() and link.readlink() == apps.workspace_home(core, a) / "mcp-tokens"
    link_b = profile_dir(hermes_home, f"agos-{b}") / "mcp-tokens"
    assert link_b.readlink() == apps.workspace_home(core, b) / "mcp-tokens"

    # Beta connects its OWN account: a second login, in Beta's folder.
    assert connect(client, b)["status"] == "connected"
    assert jobs[1]["workspace"] == b
    assert (apps.workspace_home(core, b) / "mcp-tokens" / "app-notion.json").is_file()

    # Off in Alpha: its server goes, its login stays (on again needs no new login).
    assert client.put(f"/workspaces/{a}/apps/notion", json={"on": False}).status_code == 204
    assert "app-notion" not in servers(runner, a) and token_a.is_file()
    assert client.put(f"/workspaces/{a}/apps/notion", json={"on": True}).status_code == 204
    assert "app-notion" in servers(runner, a)

    # Disconnect Alpha: Beta keeps its own login and its tool.
    assert client.delete(f"/workspaces/{a}/apps/notion/login").status_code == 204
    assert not token_a.exists() and "app-notion" not in servers(runner, a)
    assert not listed(client, a)["notion"]["connected"] and not listed(client, a)["notion"]["on"]
    assert listed(client, b)["notion"]["connected"] and "app-notion" in servers(runner, b)


def test_failed_login_and_bad_state(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, *_ = env
    fake_spawn(monkeypatch, fail=True)
    a = ws(client, "Alpha")
    r = client.post(f"/workspaces/{a}/apps/notion/connect", json=REDIRECT)
    assert r.status_code == 201
    assert (
        client.post("/apps/callback", json={"state": "WRONGSTATE", "code": "x"}).status_code == 404
    )
    done = client.post("/apps/callback", json={"state": "STATE123abc", "code": "abc"}).json()
    assert done["status"] == "error" and "access_denied" in done["error"]
    assert not listed(client, a)["notion"]["connected"]
    # The same state can't be used twice.
    assert (
        client.post("/apps/callback", json={"state": "STATE123abc", "code": "x"}).status_code == 404
    )


def test_refusals(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, *_ = env
    fake_spawn(monkeypatch)
    a = ws(client, "Alpha")
    bad = {"redirectUri": "http://evil.example/connectors/callback"}
    assert client.post(f"/workspaces/{a}/apps/notion/connect", json=bad).status_code == 400
    assert client.post(f"/workspaces/{a}/apps/asana/connect", json=REDIRECT).status_code == 409
    assert client.post(f"/workspaces/{a}/apps/deepwiki/connect", json=REDIRECT).status_code == 409
    assert client.post(f"/workspaces/{a}/apps/nope/connect", json=REDIRECT).status_code == 404
    assert client.post("/workspaces/nope/apps/notion/connect", json=REDIRECT).status_code == 404
    assert client.put(f"/workspaces/{a}/apps/asana", json={"on": True}).status_code == 409
    # Nous apps need the owner's Nous login first.
    r = client.put(f"/workspaces/{a}/apps/nous", json={"on": True})
    assert r.status_code == 409 and "Log in" in r.json()["detail"]


def test_no_login_app_and_nous_toolset(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _, runner, _ = env
    a = ws(client, "Alpha")
    assert client.put(f"/workspaces/{a}/apps/deepwiki", json={"on": True}).status_code == 204
    assert servers(runner, a)["app-deepwiki"] == {"url": DOCS.url, "enabled": True}
    disabled = json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])
    assert "connections" in disabled

    monkeypatch.setattr(connector_nous_apps, "nous_status", lambda core, fresh=False: (True, None))
    assert client.put(f"/workspaces/{a}/apps/nous", json={"on": True}).status_code == 204
    disabled = json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])
    assert "connections" not in disabled
    assert client.put(f"/workspaces/{a}/apps/nous", json={"on": False}).status_code == 204
    assert "connections" in json.loads(runner.config[f"agos-{a}"]["agent.disabled_toolsets"])


def test_link_moves_the_profiles_own_signins(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    (profile / "mcp-tokens").mkdir(parents=True)
    (profile / "mcp-tokens" / "own.json").write_text("{}")
    eng.link_tokens(profile, tmp_path / "login")
    assert (profile / "mcp-tokens").is_symlink()
    assert (tmp_path / "login" / "mcp-tokens" / "own.json").is_file()
    # A clash keeps both files where they are.
    other = tmp_path / "other"
    (other / "mcp-tokens").mkdir(parents=True)
    (other / "mcp-tokens" / "own.json").write_text('{"x": 1}')
    with pytest.raises(eng.AppError):
        eng.link_tokens(other, tmp_path / "login")
    assert (other / "mcp-tokens" / "own.json").read_text() == '{"x": 1}'


def test_parse_catalog_locks() -> None:
    rows: list[dict[str, Any]] = [
        {"name": "a", "transport": "http", "url": "https://a.example/mcp", "auth": "oauth"},
        {"name": "b", "transport": "stdio", "url": "", "auth": "none"},
        {"name": "c", "transport": "http", "url": "https://c/mcp", "auth": "oauth", "env": ["X"]},
        {"name": "d", "transport": "http", "url": "http://127.0.0.1:8000/mcp", "auth": "none"},
        {"name": "Bad Name", "transport": "http", "url": "https://x/mcp", "auth": "none"},
    ]
    got = {a.name: a for a in eng.parse_catalog(rows)}
    assert set(got) == {"a", "b", "c", "d"}
    assert got["a"].locked is None
    assert got["b"].locked and got["c"].locked and got["d"].locked


def test_composio_connects_per_workspace(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _core, runner, _ = env
    jobs = fake_spawn(monkeypatch)
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    row = listed(client, a)["composio"]
    assert row["login"] == "oauth" and row["connected"] is False and not row["locked"]
    assert connect(client, a, "composio")["status"] == "connected"
    assert jobs[0] == {
        "name": "app-composio",
        "url": "https://connect.composio.dev/mcp",
        "redirect_uri": "http://localhost:3001/connectors/callback",
        "workspace": a,
    }
    assert servers(runner, a)["app-composio"] == {
        "url": "https://connect.composio.dev/mcp",
        "auth": "oauth",
        "enabled": True,
    }
    assert "app-composio" not in servers(runner, b)


def test_deleted_workspace_forgets_its_logins(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, core, _, _ = env
    fake_spawn(monkeypatch)
    a = ws(client, "Alpha")
    connect(client, a)
    home = apps.workspace_home(core, a)
    apps.forget_workspace(core, a)
    assert not home.exists()
    assert (
        core.db.execute(
            "SELECT COUNT(*) FROM workspace_app_logins WHERE workspace_id = ?", (a,)
        ).fetchone()[0]
        == 0
    )
