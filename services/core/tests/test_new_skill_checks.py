"""A new skill the Co-Founder (or the owner) makes in its workspace: Hermes's own checks
of a new skill come first, so a refusal comes back at once with Hermes's reason and
leaves nothing behind (no empty card, nothing written); an empty card left from before
is made over under its own name; and the Co-Founder's tool tells "AGOS is still working
on it" apart from "AGOS can't be reached"."""

import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run

from agos_core.actions import capabilities, cofounder_actions, workspace_skills
from agos_core.actions import library as library_actions
from agos_core.actions.errors import ActionError
from agos_core.actions.services.library import apply as library_apply
from agos_core.actions.services.library import lifecycle as library_lifecycle
from agos_core.db.rows import now

LONG = (
    "Use when editing a talking-head video: cuts, captions, b-roll, music, pacing, "
    "hooks and the export settings for every platform."
)
SHORT = "Use when editing a talking-head video."


def _skills(client: Any, ws: str) -> list[str]:
    return [i["name"] for i in client.get(f"/workspaces/{ws}/skills").json()]


def _written(core: Any, ws: str, name: str) -> bool:
    return workspace_skills.existing_dir(core, ws, name) is not None


def _on(client: Any, ws: str) -> set[tuple[str, str]]:
    return {
        (c["kind"], c["name"]) for c in client.get(f"/workspaces/{ws}/connectors").json() if c["on"]
    }


def _empty_card(core: Any, ws: str, name: str, title: str) -> int:
    """What a create Hermes refused used to leave: the skill's row, no SKILL.md."""
    cur = core.db.execute(
        "INSERT INTO library_items (kind, name, title, summary, definition, source,"
        " created_at, updated_at, workspace_id)"
        " VALUES ('skill', ?, ?, '', '{}', 'created', ?, ?, ?)",
        (name, title, now(), now(), ws),
    )
    return int(cur.lastrowid)


def test_the_cofounders_instructions_say_hermess_rule_for_a_new_skill(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    said = cofounder_actions.instructions(core, ws)
    assert "at most 60 characters" in said and "no length limit" in said


def test_a_too_long_description_is_refused_at_once_and_leaves_nothing(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _cron, ws = env
    written: list[str] = []
    applied = library_actions.apply_workspace

    def apply(c: Any, workspace_id: str, *a: Any, **k: Any) -> Any:
        written.append(workspace_id)
        return applied(c, workspace_id, *a, **k)

    # Every module that calls it (the library service is split in parts).
    for mod in (library_actions, library_apply, library_lifecycle):
        monkeypatch.setattr(mod, "apply_workspace", apply)
    skill = {"do": "create_skill", "name": "talking-head-editing", "instructions": "Cut."}
    [card] = _run(core, ws, {**skill, "description": LONG})
    assert card["status"] == "failed", card
    assert card["error"].startswith("Hermes refused it: Description is"), card
    # Hermes's whole reason reaches the Co-Founder: it says how to fix it.
    assert "60-char" in card["error"] and "Move detail into the skill body." in card["error"]
    assert "talking-head-editing" not in _skills(client, ws)
    assert written == []  # no workspace was written for it
    # The Co-Founder fixes it from that reason: the same name, made at once.
    [card] = _run(core, ws, {**skill, "description": SHORT})
    assert card["status"] == "done", card
    assert _skills(client, ws).count("talking-head-editing") == 1
    assert ("skill", "talking-head-editing") in _on(client, ws)
    assert _written(core, ws, "talking-head-editing")
    assert set(written) == {ws}  # only its own workspace


def test_a_create_hermes_refuses_after_the_check_leaves_no_empty_card(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever Hermes's create refuses (a check this Hermes lacks, its scan…): the
    card goes too, so the same name works next time (no "-2" copy, no "isn't in
    the library")."""
    from agos_core.engine.hermes import HermesEngine

    client, core, _cron, ws = env
    monkeypatch.setattr(
        HermesEngine, "skill_check", lambda self, home, name, text, files=None: {"ok": True}
    )
    skill = {"do": "create_skill", "name": "video-editing", "instructions": "Cut."}
    [card] = _run(core, ws, {**skill, "description": LONG})
    assert card["status"] == "failed" and "Hermes refused it" in card["error"], card
    assert "video-editing" not in _skills(client, ws)
    [card] = _run(core, ws, {**skill, "description": SHORT})
    assert card["status"] == "done", card
    assert [n for n in _skills(client, ws) if n.startswith("video-editing")] == ["video-editing"]


@pytest.mark.parametrize("on_here", [True, False])
def test_an_empty_card_from_before_is_made_over_under_its_name(
    env: Any,  # noqa: F811
    on_here: bool,
) -> None:
    client, core, _cron, ws = env
    ghost = _empty_card(core, ws, "talking-head-editing", "Talking-Head Video Editing")
    if on_here:  # he had turned it on: the Co-Founder finds it by its title
        library_actions.set_connector(core, ws, ghost, on=True, allowed_tools=[], local="")
    [card] = _run(
        core,
        ws,
        {
            "do": "create_skill",
            "name": "Talking-Head Video Editing" if on_here else "talking-head-editing",
            "description": SHORT,
            "instructions": "Cut on breaths.",
        },
    )
    assert card["status"] == "done", card
    made = [n for n in _skills(client, ws) if n.startswith("talking-head")]
    assert made == ["talking-head-editing"]
    rows = core.db.execute(
        "SELECT COUNT(*) AS n FROM library_items WHERE kind = 'skill' AND name LIKE 'talking-head%'"
    ).fetchone()
    assert rows["n"] == 1  # the empty card went; the new one holds the name
    assert _written(core, ws, "talking-head-editing")
    assert ("skill", "talking-head-editing") in _on(client, ws)


def test_an_empty_card_has_nothing_to_update_or_turn_on(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    ghost = _empty_card(core, ws, "video-editing", "Video Editing")
    library_actions.set_connector(core, ws, ghost, on=True, allowed_tools=[], local="")
    [card] = _run(
        core, ws, {"do": "update_skill", "name": "video-editing", "add_instructions": "x"}
    )
    assert card["status"] == "failed", card
    assert "never written" in card["error"] and "create_skill" in card["error"], card
    row = {"workspace_id": ws, "kind": "skill", "name": "video-editing", "turn_on": 1}
    with pytest.raises(ActionError, match="nothing in it"):
        capabilities._switch(core, {**row, "title": "Video Editing"})


def _bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    from agos_core.hermes_plugin.agos_guard import bridge

    monkeypatch.setattr(
        bridge, "bridge", lambda: {"core": "http://127.0.0.1:8766", "workspace": "w", "key": "k"}
    )
    monkeypatch.setattr(bridge, "_address_of_session", lambda session_id: "agos:1")
    return bridge


def test_the_cofounders_tool_waits_and_never_says_nothing_was_done_when_it_may_be(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = _bridge(monkeypatch)
    waited: list[float] = []

    def slow(request: Any, timeout: float = 0) -> Any:
        waited.append(timeout)
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", slow)
    said = json.loads(bridge.action_tool({"actions": [{"do": "create_skill"}]}, session_id="s"))
    assert "still working on it" in said["error"] and "don't send it again" in said["error"]
    assert "nothing was done" not in said["error"]
    assert waited == [bridge.TOOL_WAIT_S] and bridge.TOOL_WAIT_S >= 600

    def down(request: Any, timeout: float = 0) -> Any:
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(urllib.request, "urlopen", down)
    said = json.loads(bridge.action_tool({"actions": [{"do": "create_skill"}]}, session_id="s"))
    assert said == {"error": "AGOS can't be reached; nothing was done."}
    said = json.loads(bridge.capability_tool({"kind": "skill", "name": "x"}, session_id="s"))
    assert said == {"error": "AGOS can't be reached; nothing changed."}
