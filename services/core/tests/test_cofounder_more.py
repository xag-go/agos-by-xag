"""The Co-Founder's chat actions for the rest of the owner's pages (engine/
cofounder_parity/, actions/cofounder_more.py): each runs the page's own code, its
card's Undo puts back what it found, a risky one waits for the owner's yes, and
nothing reaches another workspace. Hermes is the FakeRunner (test_engine_sync)."""

from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_cofounder_hermes import _run, _undo
from test_library import env, skill, ws  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions, hermes_channel
from agos_core.actions.errors import ActionError
from agos_core.db.app_settings import get_setting

# ---- automations ------------------------------------------------------------------------


def test_a_card_move_rule_is_made_changed_paused_and_deleted_each_with_undo(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [made] = _run(
        core,
        a,
        {
            "do": "save_pipeline_rule",
            "name": "Tell me",
            "trigger": "review_approved",
            "action": "notify",
            "text": "A review passed.",
        },
    )
    assert made["status"] == "done" and made["canUndo"], made
    [rule] = client.get(f"/workspaces/{a}/pipelines").json()
    assert (rule["name"], rule["action"], rule["enabled"]) == ("Tell me", "notify", True)
    # Paused by name (the same page code, its other fields kept), then Undo.
    [paused] = _run(core, a, {"do": "save_pipeline_rule", "rule": "tell me", "enabled": False})
    assert paused["status"] == "done", paused
    assert client.get(f"/workspaces/{a}/pipelines").json()[0]["enabled"] is False
    _undo(core, a, paused)
    [back] = client.get(f"/workspaces/{a}/pipelines").json()
    assert back["enabled"] is True and back["text"] == "A review passed."
    # Deleted, and its Undo makes it again.
    [gone] = _run(core, a, {"do": "delete_pipeline_rule", "rule": str(rule["id"])})
    assert gone["status"] == "done" and client.get(f"/workspaces/{a}/pipelines").json() == []
    _undo(core, a, gone)
    assert [r["name"] for r in client.get(f"/workspaces/{a}/pipelines").json()] == ["Tell me"]
    # The page's own checks answer the Co-Founder too; another workspace's rule is unknown.
    [bad] = _run(core, a, {"do": "save_pipeline_rule", "trigger": "nope", "action": "notify"})
    assert bad["status"] == "failed" and "when the rule acts" in bad["error"]
    b = ws(client, "Beta")
    [other] = _run(core, b, {"do": "delete_pipeline_rule", "rule": "Tell me"})
    assert other["status"] == "failed" and "no rule" in other["error"]


def test_the_webhook_address_is_checked_like_the_page_and_undo_puts_it_back(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [card] = _run(core, a, {"do": "set_hooks_address", "url": "https://hooks.example.com/"})
    assert card["status"] == "done", card
    assert client.get("/settings/hooks").json()["publicUrl"] == "https://hooks.example.com"
    [bad] = _run(core, a, {"do": "set_hooks_address", "url": "http://plain"})
    assert bad["status"] == "failed" and "https://" in bad["error"]
    _undo(core, a, card)
    assert client.get("/settings/hooks").json()["publicUrl"] == ""


# ---- team -------------------------------------------------------------------------------


def test_groups_and_office_looks_change_from_chat_with_undo(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    [group] = _run(core, a, {"do": "create_group", "title": "Desk", "members": ["writer"]})
    assert group["status"] == "done", group
    [members] = _run(
        core, a, {"do": "set_group_members", "group": "desk", "members": ["writer", "editor"]}
    )
    assert members["status"] == "done", members
    groups = client.get(f"/workspaces/{a}/workers").json()["groups"]
    assert sorted(groups[0]["members"]) == ["editor", "writer"]
    _undo(core, a, members)
    assert client.get(f"/workspaces/{a}/workers").json()["groups"][0]["members"] == ["writer"]
    # A look: only the page's own fields and values.
    [look] = _run(
        core, a, {"do": "set_office_look", "member": "writer", "look": {"pet_name": " Rex "}}
    )
    assert look["status"] == "done", look
    assert client.get(f"/workspaces/{a}/office").json()["looks"]["writer"]["petName"] == "Rex"
    [bad] = _run(core, a, {"do": "set_office_look", "member": "writer", "look": {"hat": "x"}})
    assert bad["status"] == "failed"
    _undo(core, a, look)
    assert client.get(f"/workspaces/{a}/office").json()["looks"]["writer"]["petName"] == ""
    _undo(core, a, group)
    assert client.get(f"/workspaces/{a}/workers").json()["groups"] == []


# ---- skills -----------------------------------------------------------------------------


def test_skill_studio_inputs_settings_and_the_request_limit_change_with_undo(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    sid = skill(client, a)

    def tests() -> dict[str, Any]:
        r = client.get(f"/workspaces/{a}/skills/{sid}/tests")
        assert r.status_code == 200, r.text
        return dict(r.json())

    [add] = _run(
        core,
        a,
        {"do": "add_skill_test_input", "name": "invoice-check", "input_name": "big", "text": "9"},
    )
    assert add["status"] == "done", add
    [one] = tests()["inputs"]
    [change] = _run(
        core,
        a,
        {
            "do": "update_skill_test_input",
            "name": "invoice-check",
            "input": one["id"],
            "text": "10",
        },
    )
    assert change["status"] == "done" and tests()["inputs"][0]["text"] == "10"
    _undo(core, a, change)
    assert tests()["inputs"][0]["text"] == "9"
    [drop] = _run(
        core, a, {"do": "delete_skill_test_input", "name": "invoice-check", "input": one["id"]}
    )
    assert drop["status"] == "done" and tests()["inputs"] == []
    _undo(core, a, drop)
    assert [i["name"] for i in tests()["inputs"]] == ["big"]
    [settings] = _run(
        core, a, {"do": "save_skill_test_settings", "name": "invoice-check", "checklist": "- total"}
    )
    assert settings["status"] == "done" and tests()["checklist"] == "- total"
    _undo(core, a, settings)
    assert tests()["checklist"] != "- total"
    # Skill growth: the new-skill requests per day.
    [limit] = _run(core, a, {"do": "set_skill_request_limit", "limit": 7})
    assert limit["status"] == "done", limit
    assert client.get(f"/workspaces/{a}/skill-growth").json()["limit"] == 7
    _undo(core, a, limit)
    assert client.get(f"/workspaces/{a}/skill-growth").json()["limit"] != 7
    # Another workspace's skill is not found.
    b = ws(client, "Beta")
    [other] = _run(
        core,
        b,
        {"do": "add_skill_test_input", "name": "invoice-check", "input_name": "x", "text": "y"},
    )
    assert other["status"] == "failed" and "no skill" in other["error"]


# ---- board ------------------------------------------------------------------------------


def test_labels_views_and_review_settings_change_with_undo(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")

    def labels() -> list[dict[str, Any]]:
        return list(client.get(f"/workspaces/{a}/labels").json())

    [made] = _run(
        core, a, {"do": "create_label", "name": "urgent", "color": "red", "folder": "Prio"}
    )
    assert made["status"] == "done" and made["canUndo"], made
    [changed] = _run(core, a, {"do": "update_label", "label": "urgent", "color": "green"})
    assert changed["status"] == "done" and labels()[0]["color"] == "green"
    _undo(core, a, changed)
    assert labels()[0]["color"] == "red"
    [moved] = _run(core, a, {"do": "rename_label_folder", "folder": "Prio", "new": "Now"})
    assert moved["status"] == "done" and labels()[0]["folder"] == "Now"
    _undo(core, a, moved)
    assert labels()[0]["folder"] == "Prio"
    _undo(core, a, made)
    assert labels() == []
    # A saved view by name, then deleted, and its Undo makes it again.
    [view] = _run(core, a, {"do": "save_board_view", "name": "Mine", "layout": "list"})
    assert view["status"] == "done", view
    [gone] = _run(core, a, {"do": "delete_board_view", "view": "mine"})
    assert gone["status"] == "done" and client.get(f"/workspaces/{a}/board-views").json() == []
    _undo(core, a, gone)
    [back] = client.get(f"/workspaces/{a}/board-views").json()
    assert (back["name"], back["layout"]) == ("Mine", "list")
    # The workspace's review rounds.
    before = client.get(f"/workspaces/{a}/review-settings").json()
    [rev] = _run(core, a, {"do": "save_review_settings", "cap": 5})
    assert rev["status"] == "done", rev
    assert client.get(f"/workspaces/{a}/review-settings").json()["cap"] == 5
    _undo(core, a, rev)
    assert client.get(f"/workspaces/{a}/review-settings").json()["cap"] == before["cap"]


def test_a_delete_or_an_import_waits_for_the_owner_even_in_direct_mode(
    env: Any,  # noqa: F811
) -> None:
    _client, core, _runner, _home = env
    assert cofounder_actions.mode(core) == "direct"
    for args, ask in (
        ({"do": "delete_label", "label": "urgent"}, True),
        ({"do": "import_bundle", "path": "team.zip"}, True),
        ({"do": "run_updates"}, True),
        ({"do": "approve_person", "request": "ABC123"}, True),
        ({"do": "create_label", "name": "urgent"}, False),
        ({"do": "card_action", "card": "t_1", "action": "archive"}, True),
        ({"do": "card_action", "card": "t_1", "action": "unblock"}, False),
    ):
        said = hermes_channel.tool_check(core, "agos_action", {"actions": [args]})
        assert said["ask"] is ask, (args, said)


# ---- workspace --------------------------------------------------------------------------


def test_docs_rules_notifications_and_the_team_group_change_with_undo(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [latin] = _run(core, a, {"do": "set_latin_only", "on": True})
    assert latin["status"] == "done", latin
    from agos_core.actions import docs

    assert docs.latin_only(core, a) is True
    _undo(core, a, latin)
    assert docs.latin_only(core, a) is False
    # The owner's rule for every workspace: changed and deleted, each with Undo.
    r = client.post("/owner-rules", json={"text": "Answer in Darija."})
    assert r.status_code in (200, 201, 204), r.text
    [rule] = client.get("/owner-rules").json()
    [edit] = _run(
        core, a, {"do": "edit_owner_rule", "rule": rule["id"], "text": "Answer in English."}
    )
    assert edit["status"] == "done", edit
    assert [x["text"] for x in client.get("/owner-rules").json()] == ["Answer in English."]
    _undo(core, a, edit)
    assert [x["text"] for x in client.get("/owner-rules").json()] == ["Answer in Darija."]
    [rule] = client.get("/owner-rules").json()
    [drop] = _run(core, a, {"do": "delete_owner_rule", "rule": rule["id"]})
    assert drop["status"] == "done" and client.get("/owner-rules").json() == []
    _undo(core, a, drop)
    assert [x["text"] for x in client.get("/owner-rules").json()] == ["Answer in Darija."]
    # Notifications: only the page's events and deliveries.
    [note] = _run(core, a, {"do": "set_notifications", "rules": {"task.waiting": "silent"}})
    assert note["status"] == "done", note
    assert get_setting(core.db, "notifications", {})["task.waiting"] == "silent"
    _undo(core, a, note)
    assert get_setting(core.db, "notifications", {})["task.waiting"] == "instant"
    # The Telegram team group (checked like the page), for this workspace only.
    [group] = _run(core, a, {"do": "set_team_group", "group": "-1001234567890"})
    assert group["status"] == "done", group
    assert hermes_channel.team_groups(core, a)["teamGroup"] == "-1001234567890"
    [bad] = _run(core, a, {"do": "set_team_group", "group": "my group"})
    assert bad["status"] == "failed"
    _undo(core, a, group)
    assert hermes_channel.team_groups(core, a)["teamGroup"] == ""


def test_a_card_says_what_a_once_kind_answered_and_has_no_undo(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [card] = _run(core, a, {"do": "test_tool_key", "name": "NOTION_API_KEY"})
    assert card["canUndo"] is False
    assert card["status"] in ("done", "failed"), card
    with pytest.raises(ActionError, match="can't be undone"):
        cofounder_actions.decide(core, a, int(card["id"]), "undo")


# ---- found by the real-chat A/B run (Co-Founder on a real model) -------------------------


def test_a_status_card_on_some_words_and_a_heartbeat_off_without_interval(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    from agos_core.actions import cofounder_more, heartbeat

    # The model says "search" or "words": the page's "some words" scope (status_cards'
    # query); the card itself runs on Hermes's cron (the real-chat run made one).
    for said in ("search", "words", "query"):
        assert cofounder_more._status_args({"scope": said}, {})["scope"] == "query"
    # Off needs no interval (none was ever set); Undo puts back what it found.
    calls: list[tuple[bool, str]] = []
    monkeypatch.setattr(
        heartbeat,
        "set_heartbeat",
        lambda core, ws, agent, *, on, interval: calls.append((on, interval)),
    )
    [off] = _run(core, a, {"do": "set_heartbeat", "agent": "writer", "on": False})
    assert off["status"] == "done", off.get("error")
    _undo(core, a, off)
    assert calls == [(False, "1h"), (False, "1h")]
    [bad] = _run(core, a, {"do": "set_heartbeat", "agent": "writer", "on": True})
    assert bad["status"] == "failed" and "15m, 1h, 4h or daily" in bad["error"]


def test_the_default_model_changes_from_chat_like_the_settings_page_with_undo(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    before = client.get(f"/workspaces/{a}").json()["defaultModel"]
    [card] = _run(core, a, {"do": "set_workspace_settings", "model": "claude-sonnet-5"})
    assert card["status"] == "done", card
    now = client.get(f"/workspaces/{a}").json()
    assert now["defaultModel"]["model"] == "claude-sonnet-5"
    assert now["defaultModel"]["provider"] == before["provider"]
    assert now["chatAccess"] == client.get(f"/workspaces/{a}").json()["chatAccess"]
    _undo(core, a, card)
    assert client.get(f"/workspaces/{a}").json()["defaultModel"] == before
    [empty] = _run(core, a, {"do": "set_workspace_settings"})
    assert empty["status"] == "failed", empty


def test_a_restart_asked_inside_the_cofounders_turn_waits_for_the_turn_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remove_tool_key (and any page code that restarts the gateway with wait=True)
    used to stop the very gateway whose turn waited on the tool call: Hermes drained
    60 s, then cut the owner's answer off."""
    import sqlite3
    import threading
    import time
    from types import SimpleNamespace

    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE TABLE chat_turns (id INTEGER, workspace_id TEXT, status TEXT)")
    db.execute("INSERT INTO chat_turns VALUES (1, 'alpha', 'running')")
    stopped = threading.Event()
    engine = SimpleNamespace(
        split=lambda w: (w.split("--")[0], None),
        is_running=lambda w: True,
        stop=lambda w: stopped.set(),
        start=lambda w: None,
    )
    core = SimpleNamespace(db=db, engine=engine)
    monkeypatch.setattr(time, "sleep", lambda s: stopped.wait(0.01))
    with hermes_channel.inside_turn():
        hermes_channel.restart_gateway(core, "alpha", wait=True)  # type: ignore[arg-type]
    assert not stopped.wait(0.3)  # returned at once, nothing stopped under the turn
    db.execute("UPDATE chat_turns SET status = 'completed'")
    assert stopped.wait(5)  # the turn ended: now it restarts


def test_the_workspace_exports_from_chat_into_its_files_like_the_export_page(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zipfile

    from test_templates import _hermes_masks

    from agos_core.engine import hermes_redact
    from agos_core.storage.layout import workspace_paths

    monkeypatch.setattr(hermes_redact, "mask_many", _hermes_masks)  # Hermes's own redact

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [card] = _run(core, a, {"do": "export_bundle"})
    assert card["status"] == "done" and card["canUndo"] is False, card.get("error")
    made = workspace_paths(core.layout, a).files / "exports" / f"agos-{a}.zip"
    assert zipfile.is_zipfile(made) and "/workspace/exports/" in card["detail"]
    [bad] = _run(core, a, {"do": "export_bundle", "path": "../../out.zip"})
    assert bad["status"] == "failed"


def test_a_hermes_key_an_agos_card_owns_names_the_cofounders_own_action(
    env: Any,  # noqa: F811
) -> None:
    from agos_core.engine import hermes_schema as hs

    client, core, _runner, _home = env
    fields = hs.build({}, {"model": {"default": "", "provider": ""}}, "", set())
    core.engine.config_schema = lambda: fields
    a = ws(client, "Alpha")
    [card] = _run(
        core,
        a,
        {"do": "change_hermes_setting", "key": "model.default", "value": "x", "only_here": True},
    )
    assert card["status"] == "failed", card
    assert "agos_action set_workspace_settings (model)" in card["error"], card["error"]
