"""The Office: each agent's look (pet, colour, desk item), per workspace."""

import test_api
from fastapi.testclient import TestClient

client = test_api.client  # the API tests' fixture


def _workspace(client: TestClient) -> str:
    return test_api.create_workspace(client, "Office Test")


def test_every_agent_starts_with_its_own_look_and_keeps_the_owners_choice(
    client: TestClient,
) -> None:
    ws = _workspace(client)
    looks = client.get(f"/workspaces/{ws}/office").json()["looks"]
    assert set(looks) == {"cofounder"}
    assert looks["cofounder"]["pet"] == "cat"

    mine = {"pet": "dog", "petName": "  Rex ", "colour": "teal", "item": "trophy"}
    assert client.put(f"/workspaces/{ws}/office/cofounder", json=mine).status_code == 204
    assert client.get(f"/workspaces/{ws}/office").json()["looks"]["cofounder"] == {
        "pet": "dog",
        "petName": "Rex",
        "colour": "teal",
        "item": "trophy",
    }


def test_only_real_agents_and_known_looks_are_saved(client: TestClient) -> None:
    ws = _workspace(client)
    good = {"pet": "cat", "colour": "rose", "item": "lamp"}
    assert client.put(f"/workspaces/{ws}/office/stranger", json=good).status_code == 404
    bad = {"pet": "dragon", "colour": "rose", "item": "lamp"}
    assert client.put(f"/workspaces/{ws}/office/cofounder", json=bad).status_code == 422
    assert client.get("/workspaces/nope/office").status_code == 404
