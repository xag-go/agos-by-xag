"""Feature flags (actions/flags.py, api/flags.py): a typed registry with defaults,
the owner's value in app_settings, an env override, and the Co-Founder's set_flag."""

from typing import Any

import pytest
import test_api
from fastapi.testclient import TestClient

from agos_core.actions import cofounder_prefs, flags
from agos_core.actions.errors import ActionError

client = test_api.client  # the API tests' fixture


def core_of(c: TestClient) -> Any:
    return c.app.state.core  # type: ignore[attr-defined]


@pytest.fixture
def two_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        flags,
        "FLAGS",
        {
            "new_board": flags.Flag(default=False, title="New board", about="A test flag."),
            "fast_chat": flags.Flag(default=True, title="Fast chat", about="On by default."),
        },
    )


def test_a_flag_is_its_default_until_the_owner_sets_it(client: TestClient, two_flags: None) -> None:
    core = core_of(client)
    assert flags.on(core, "new_board") is False
    assert flags.on(core, "fast_chat") is True
    flags.set_flag(core, "new_board", True)
    flags.set_flag(core, "fast_chat", False)
    assert flags.on(core, "new_board") is True
    assert flags.on(core, "fast_chat") is False


def test_an_unknown_flag_is_refused_and_reads_off(client: TestClient, two_flags: None) -> None:
    core = core_of(client)
    with pytest.raises(ActionError):
        flags.set_flag(core, "nope", True)
    assert flags.on(core, "nope") is False


def test_the_env_override_wins_over_the_owner(
    client: TestClient, two_flags: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = core_of(client)
    flags.set_flag(core, "new_board", False)
    monkeypatch.setenv("AGOS_FLAG_NEW_BOARD", "1")
    assert flags.on(core, "new_board") is True
    shown = {f.name: f for f in flags.listed(core)}["new_board"]
    assert shown.on is True and shown.forced is True


def test_the_api_lists_and_sets_flags(client: TestClient, two_flags: None) -> None:
    listed = client.get("/flags").json()
    assert [(f["name"], f["on"], f["default"]) for f in listed] == [
        ("fast_chat", True, True),
        ("new_board", False, False),
    ]
    r = client.put("/flags/new_board", json={"on": True})
    assert r.status_code == 200, r.text
    assert r.json()["before"] is False
    assert {f["name"]: f["on"] for f in client.get("/flags").json()}["new_board"] is True
    assert client.put("/flags/nope", json={"on": True}).status_code == 404


def test_the_cofounder_sets_a_flag_and_undo_puts_the_old_value_back(
    client: TestClient, two_flags: None
) -> None:
    core = core_of(client)
    done = cofounder_prefs.DOES["set_flag"](core, "ws", {"flag": "new_board", "on": "true"})
    assert flags.on(core, "new_board") is True
    cofounder_prefs.UNDOES["set_flag"](core, "ws", done)
    assert flags.on(core, "new_board") is False


def test_undo_puts_back_the_owners_saved_value_not_the_forced_one(
    client: TestClient, two_flags: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's Low item: with AGOS_FLAG_ forcing a switch on, undo of the
    Co-Founder's change must not save "on" for good."""
    core = core_of(client)
    monkeypatch.setenv("AGOS_FLAG_NEW_BOARD", "1")
    done = cofounder_prefs.DOES["set_flag"](core, "ws", {"flag": "new_board", "on": "false"})
    cofounder_prefs.UNDOES["set_flag"](core, "ws", done)
    monkeypatch.delenv("AGOS_FLAG_NEW_BOARD")
    assert flags.on(core, "new_board") is False  # its default, as before
    assert "new_board" not in flags._saved(core)


def test_undo_puts_back_a_saved_value(client: TestClient, two_flags: None) -> None:
    core = core_of(client)
    flags.set_flag(core, "fast_chat", False)
    done = cofounder_prefs.DOES["set_flag"](core, "ws", {"flag": "fast_chat", "on": "yes"})
    assert flags.on(core, "fast_chat") is True
    cofounder_prefs.UNDOES["set_flag"](core, "ws", done)
    assert flags._saved(core) == {"fast_chat": False}


def test_a_value_that_is_not_on_or_off_is_refused(client: TestClient, two_flags: None) -> None:
    core = core_of(client)
    flags.set_flag(core, "fast_chat", True)
    for odd in ("maybe", "", None, "enable it"):
        with pytest.raises(ActionError):
            cofounder_prefs.DOES["set_flag"](core, "ws", {"flag": "fast_chat", "on": odd})
    assert flags.on(core, "fast_chat") is True  # never quietly "off"
    for text, value in (("TRUE", True), ("off", False), (True, True), ("0", False)):
        assert flags.parse_on(text) is value


def test_the_registry_holds_typed_flags() -> None:
    assert flags.FLAGS, "at least one flag (the Labs card shows them)"
    for name, flag in flags.FLAGS.items():
        assert name.isidentifier() and name == name.lower()
        assert isinstance(flag.default, bool) and flag.title and flag.about
