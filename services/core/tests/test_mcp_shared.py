"""Settings → Connectors: shared MCP definitions; each workspace adds its own copy,
with its own switch, key and sign-in, written only into its own Hermes."""

import json
from typing import Any

import pytest
from test_engine_sync import profile_dir
from test_library import env, mcp, turn_off, ws  # noqa: F401 - the fixture

CRM = {
    "url": "https://crm.example.com/mcp",
    "auth_header": "Authorization",
    "auth_scheme": "Bearer",
}


class _NoCatalog:
    """Hermes's own catalog is read by Hermes; these tests only need ours."""

    def machine_mcp(self) -> list[Any]:
        return []


@pytest.fixture(autouse=True)
def _no_hermes_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from agos_core.actions import library
    from agos_core.actions.services.library import sources as library_sources

    for mod in (library, library_sources):  # the facade and its home
        monkeypatch.setattr(mod, "_sources", lambda core: _NoCatalog())


def shared(client: Any, name: str = "crm", definition: dict[str, Any] | None = None) -> int:
    r = client.post(
        "/library/mcp",
        json={"name": name, "title": "Our CRM", "definition": definition or CRM},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def servers(runner: Any, w: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(runner.config.get(f"agos-{w}", {}).get("mcp_servers", "{}"))
    return found


def add(client: Any, w: str, template: int) -> Any:
    return client.post(f"/workspaces/{w}/mcp/machine", json={"origin": f"template:{template}"})


def test_shared_definition_is_in_no_workspace_until_one_adds_it(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    tid = shared(client)
    listed = client.get("/library", params={"kind": "mcp"}).json()
    assert [(i["name"], i["title"], i["usedBy"], i["workspaceId"]) for i in listed] == [
        ("crm", "Our CRM", [], None)
    ]
    assert listed[0]["definition"]["url"] == "https://crm.example.com/mcp"
    assert servers(runner, a) == {} and servers(runner, b) == {}
    # Each workspace's Add list offers it, marked as the owner's own.
    found = {f["origin"]: f for f in client.get(f"/workspaces/{a}/mcp/machine").json()}
    assert found[f"template:{tid}"]["trust"] == "Yours"
    assert found[f"template:{tid}"]["importable"]
    # Settings can't add it to itself.
    r = client.post("/library/mcp/machine", json={"origin": f"template:{tid}"})
    assert r.status_code == 400

    r = add(client, a, tid)
    assert r.status_code == 201, r.text
    copy = int(r.json()["id"])
    assert copy != tid
    assert servers(runner, a)["crm"]["url"] == "https://crm.example.com/mcp"
    assert servers(runner, a)["crm"]["enabled"] is True
    assert servers(runner, b) == {}
    # It is A's own server now: listed in A, not in B; Settings says who has it.
    assert [m["name"] for m in client.get(f"/workspaces/{a}/mcp").json()] == ["crm"]
    assert client.get(f"/workspaces/{b}/mcp").json() == []
    assert client.get("/library", params={"kind": "mcp"}).json()[0]["usedBy"] == [a]
    # Already in A: not offered again there; still offered in B.
    in_a = {f["origin"]: f for f in client.get(f"/workspaces/{a}/mcp/machine").json()}
    assert in_a[f"template:{tid}"]["inLibrary"] is True
    in_b = {f["origin"]: f for f in client.get(f"/workspaces/{b}/mcp/machine").json()}
    assert in_b[f"template:{tid}"]["inLibrary"] is False
    assert add(client, a, tid).status_code == 409

    # Its key is A's own: in A's .env only, never in the shared definition.
    r = client.put(f"/workspaces/{a}/connectors/{copy}/secret", json={"value": "sk-alpha-1234"})
    assert r.status_code == 204
    assert "AGOS_MCP_CRM=sk-alpha-1234" in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    assert "sk-alpha" not in client.get("/library", params={"kind": "mcp"}).text
    row = core.db.execute("SELECT definition FROM library_items WHERE id = ?", (tid,)).fetchone()
    assert "sk-alpha" not in row["definition"]

    # B adds it too, with its own key: two copies, two keys, nothing shared.
    copy_b = int(add(client, b, tid).json()["id"])
    client.put(f"/workspaces/{b}/connectors/{copy_b}/secret", json={"value": "sk-beta-9999"})
    env_b = (profile_dir(home, f"agos-{b}") / ".env").read_text()
    assert "sk-beta-9999" in env_b and "sk-alpha" not in env_b
    assert "sk-beta" not in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    assert client.get("/library", params={"kind": "mcp"}).json()[0]["usedBy"] == sorted([a, b])


def test_editing_the_shared_definition_updates_every_copy_keeping_its_own_state(
    env: Any,  # noqa: F811
) -> None:
    client, _core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    tid = shared(client)
    copy_a = int(add(client, a, tid).json()["id"])
    copy_b = int(add(client, b, tid).json()["id"])
    client.put(f"/workspaces/{a}/connectors/{copy_a}/secret", json={"value": "sk-alpha-1234"})
    r = client.put(
        f"/workspaces/{a}/connectors/{copy_a}", json={"on": True, "allowedTools": ["find"]}
    )
    assert r.status_code == 204
    assert turn_off(client, b, copy_b) == 204

    r = client.put(
        f"/library/mcp/{tid}",
        json={
            "name": "crm",
            "title": "CRM v2",
            "definition": {**CRM, "url": "https://crm2.example.com/mcp"},
        },
    )
    assert r.status_code == 200, r.text
    sa, sb = servers(runner, a)["crm"], servers(runner, b)["crm"]
    assert sa["url"] == sb["url"] == "https://crm2.example.com/mcp"
    assert sa["enabled"] is True and sa["tools"] == {"include": ["find"]}
    assert sa["headers"] == {"Authorization": "Bearer ${AGOS_MCP_CRM}"}
    assert sb["enabled"] is False and "headers" not in sb
    assert "sk-alpha-1234" in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    titles = {m["title"] for m in client.get(f"/workspaces/{a}/mcp").json()}
    assert titles == {"CRM v2"}
    # Changed from a workspace: the shared one changes, so every copy follows.
    r = client.put(
        f"/workspaces/{a}/mcp/{copy_a}",
        json={
            "name": "crm",
            "title": "CRM v3",
            "definition": {**CRM, "url": "https://crm3.example.com/mcp"},
        },
    )
    assert r.status_code == 204, r.text
    assert servers(runner, a)["crm"]["url"] == servers(runner, b)["crm"]["url"]
    assert servers(runner, b)["crm"]["url"] == "https://crm3.example.com/mcp"
    assert servers(runner, b)["crm"]["enabled"] is False
    listed = client.get("/library", params={"kind": "mcp"}).json()
    assert [(i["title"], i["definition"]["url"]) for i in listed] == [
        ("CRM v3", "https://crm3.example.com/mcp")
    ]


def test_removing_from_a_workspace_keeps_the_shared_one_deleting_it_removes_every_copy(
    env: Any,  # noqa: F811
) -> None:
    client, _core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    tid = shared(client)
    copy_a = int(add(client, a, tid).json()["id"])
    add(client, b, tid)
    client.put(f"/workspaces/{a}/connectors/{copy_a}/secret", json={"value": "sk-alpha-1234"})
    # A removes its copy: gone from A's Hermes and .env; B and the shared one stay.
    assert client.delete(f"/workspaces/{a}/mcp/{copy_a}").status_code == 204
    assert servers(runner, a) == {} and "crm" in servers(runner, b)
    assert "AGOS_MCP_CRM" not in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    assert client.get("/library", params={"kind": "mcp"}).json()[0]["usedBy"] == [b]
    # Deleting the shared one removes it from every workspace that added it.
    r = client.delete(f"/library/items/{tid}")
    assert r.status_code == 200 and r.json()["usedBy"] == [b]
    assert servers(runner, b) == {}
    assert client.get("/library", params={"kind": "mcp"}).json() == []
    assert client.get(f"/workspaces/{b}/mcp").json() == []
    assert add(client, a, tid).status_code == 404


def test_a_server_a_workspace_adds_itself_is_offered_to_the_others(env: Any) -> None:  # noqa: F811
    client, core, runner, home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    own = mcp(client, a, "crm", CRM)
    client.put(f"/workspaces/{a}/connectors/{own}/secret", json={"value": "sk-alpha-1234"})
    listed = client.get("/library", params={"kind": "mcp"})
    assert [(i["name"], i["usedBy"]) for i in listed.json()] == [("crm", [a])]
    assert "sk-alpha" not in listed.text
    tid = listed.json()[0]["id"]
    # Alpha's own server is that shared one's copy now: nothing changed for it.
    row = core.db.execute("SELECT source FROM library_items WHERE id = ?", (own,)).fetchone()
    assert row["source"] == f"template:{tid}"
    assert servers(runner, a)["crm"]["headers"] == {"Authorization": "Bearer ${AGOS_MCP_CRM}"}
    # Beta finds it in its Add list and adds it with its own key.
    offered = {f["origin"]: f for f in client.get(f"/workspaces/{b}/mcp/machine").json()}
    assert offered[f"template:{tid}"]["inLibrary"] is False
    copy_b = int(add(client, b, tid).json()["id"])
    client.put(f"/workspaces/{b}/connectors/{copy_b}/secret", json={"value": "sk-beta-9999"})
    assert "sk-alpha" not in (profile_dir(home, f"agos-{b}") / ".env").read_text()
    assert "sk-beta" not in (profile_dir(home, f"agos-{a}") / ".env").read_text()
    # The same name made again elsewhere with another address: a second entry.
    c = ws(client, "Gamma")
    mcp(client, c, "crm", {"url": "https://other.example.com/mcp"})
    names = {i["name"]: i["usedBy"] for i in client.get("/library", params={"kind": "mcp"}).json()}
    assert names == {"crm": sorted([a, b]), "crm-2": [c]}


def test_a_server_with_a_credential_in_its_address_stays_its_workspaces(
    env: Any,  # noqa: F811
) -> None:
    client, _core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    mcp(client, a, "leaky", {"url": "https://crm.example.com/mcp?api_key=abc"})
    mcp(client, a, "leaky2", {"url": "https://crm.example.com/mcp/" + "x" * 40})
    mcp(client, a, "fine", {"url": "https://fine.example.com/mcp?region=eu"})
    assert [i["name"] for i in client.get("/library", params={"kind": "mcp"}).json()] == ["fine"]
    offered = {f["name"] for f in client.get(f"/workspaces/{b}/mcp/machine").json()}
    assert offered == {"fine"}


def test_commands_with_a_credential_are_not_shared() -> None:
    from agos_core.actions.library import _shareable

    def cmd(c: str) -> dict[str, Any] | None:
        return _shareable({"transport": "command", "command": c})

    assert cmd("npx -y @scope/server /workspace") is not None
    assert cmd("npx srv --token abcdef") is None
    assert cmd("npx srv --api-key abcdef") is None
    assert cmd("env GITHUB_TOKEN=ghp_x npx srv") is None
    assert cmd("npx srv " + "a1" * 20) is None


def test_bad_shared_definitions_are_refused(env: Any) -> None:  # noqa: F811
    client, *_ = env
    for name, definition in (
        ("app-crm", CRM),
        ("crm", {"url": "http://localhost:9000/mcp"}),
        ("crm", {"url": "https://u:p@crm.example.com/mcp"}),
        ("Bad Name", CRM),
    ):
        r = client.post("/library/mcp", json={"name": name, "definition": definition})
        assert r.status_code in (400, 422), (name, r.text)
    shared(client)
    r = client.post("/library/mcp", json={"name": "crm", "definition": CRM})
    assert r.status_code == 409
