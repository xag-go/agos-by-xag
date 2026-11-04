"""The owner's order of the workspace tabs."""

import test_api
from fastapi.testclient import TestClient

client = test_api.client  # the API tests' fixture


def test_tabs_order_default_save_and_clean(client: TestClient) -> None:
    default = [
        "dashboard",
        "office",
        "kanban",
        "inbox",
        "sessions",
        "hierarchy",
        "vision",
        "status",
        "messages",
        "automations",
        "docs",
        "artifacts",
        "screen",
        "log",
        "search",
    ]
    assert client.get("/preferences/tabs").json()["order"] == default
    mine = [
        "messages",
        "kanban",
        "dashboard",
        "hierarchy",
        "sessions",
        "automations",
        "docs",
        "screen",
        "log",
    ]
    assert client.put("/preferences/tabs", json={"order": mine}).status_code == 204
    # The Office came later: it goes right after the Dashboard; the Inbox after the
    # Kanban; the Artifacts after the Documentation; the Vision (once Goals) after the Hierarchy;
    # the Status cards after the Vision (step 55); the Search, new, at the end.
    assert client.get("/preferences/tabs").json()["order"] == [
        mine[0],
        "kanban",
        "inbox",
        "dashboard",
        "office",
        mine[3],
        "vision",
        "status",
        *mine[4:7],
        "artifacts",
        *mine[7:],
        "search",
    ]
    # Unknown or repeated tabs are dropped; a missing one comes back at the end.
    client.put("/preferences/tabs", json={"order": ["kanban", "hack", "kanban", "messages"]})
    assert client.get("/preferences/tabs").json()["order"] == [
        "kanban",
        "inbox",
        "messages",
        "dashboard",
        "office",
        "sessions",
        "hierarchy",
        "vision",
        "status",
        "automations",
        "docs",
        "artifacts",
        "screen",
        "log",
        "search",
    ]


def test_a_saved_goals_tab_is_the_vision_tab_in_its_place(client: TestClient) -> None:
    """Step 53: the Goals tab became the Vision page; an order saved before keeps it
    where the owner put it."""
    from agos_core.db.app_settings import set_setting

    core = client.app.state.core  # type: ignore[attr-defined]
    set_setting(core.db, "tabs", ["goals", "board", "dashboard"])
    order = client.get("/preferences/tabs").json()["order"]
    assert order[:3] == ["vision", "status", "kanban"] and "goals" not in order
    client.put("/preferences/tabs", json={"order": ["board", "goals"]})
    assert client.get("/preferences/tabs").json()["order"][:4] == [
        "kanban",
        "inbox",
        "vision",
        "status",
    ]


def test_a_saved_board_tab_is_the_kanban_tab_in_its_place(client: TestClient) -> None:
    """The Board tab became the Kanban (its page moved from /board to /kanban): an
    order saved before keeps it where the owner put it, once, and no "board" tab is
    left in the order."""
    from agos_core.db.app_settings import set_setting

    core = client.app.state.core  # type: ignore[attr-defined]
    set_setting(core.db, "tabs", ["messages", "board", "dashboard", "kanban"])
    order = client.get("/preferences/tabs").json()["order"]
    assert order[:3] == ["messages", "kanban", "inbox"]
    assert "board" not in order and order.count("kanban") == 1
