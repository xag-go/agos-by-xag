"""Workspaces are fully isolated: a library row of workspace B is never read or changed
through workspace A's routes, whatever id A sends (workspace-scope scan, lane p2)."""

from typing import Any

from test_library import env, mcp, ws  # noqa: F401 - fixture


def test_another_workspaces_mcp_server_has_no_sign_in_here(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    theirs = mcp(client, b, "wiki", {"url": "https://wiki.example.com/mcp"})
    token = core.engine.profile_home(a) / "mcp-tokens" / "wiki.json"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("{}")  # A's own sign-in to a server of the same name
    # A can neither read the sign-in state of B's server by its id...
    assert client.get(f"/workspaces/{a}/connectors/{theirs}/signin").status_code == 404
    # ... nor sign out with it (that removed A's own token of that name).
    assert client.delete(f"/workspaces/{a}/connectors/{theirs}/signin").status_code == 404
    assert token.is_file()
    # B itself still reads it.
    assert client.get(f"/workspaces/{b}/connectors/{theirs}/signin").status_code == 200
