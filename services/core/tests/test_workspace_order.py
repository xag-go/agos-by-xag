"""The owner's order of the workspaces (dragged on the rail)."""

import test_api
from fastapi.testclient import TestClient

client = test_api.client  # the API tests' fixture


def _ids(client: TestClient) -> list[str]:
    return [w["id"] for w in client.get("/workspaces").json()]


def test_workspaces_follow_the_dragged_order(client: TestClient) -> None:
    a = test_api.create_workspace(client, "Alpha")
    b = test_api.create_workspace(client, "Beta")
    c = test_api.create_workspace(client, "Gamma")
    assert _ids(client) == [a, b, c]  # nothing dragged yet: oldest first

    put = client.put("/preferences/workspace-order", json={"order": [c, a, b]})
    assert put.status_code == 204
    assert _ids(client) == [c, a, b]

    # Unknown ids and repeats are dropped; a workspace left out keeps its age order
    # after the placed ones, and a new workspace goes at the end.
    client.put("/preferences/workspace-order", json={"order": ["nope", b, b]})
    assert _ids(client) == [b, a, c]
    d = test_api.create_workspace(client, "Delta")
    assert _ids(client) == [b, a, c, d]

    # A workspace in the trash leaves the list; the others keep their places.
    assert client.post(f"/workspaces/{a}/delete", json={"confirm": a}).status_code == 200
    assert _ids(client) == [b, c, d]
