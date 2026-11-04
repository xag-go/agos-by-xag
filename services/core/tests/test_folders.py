"""Folders on the Automations, Skills and Projects lists (actions/folders.py): made,
renamed and deleted (the items stay, back in "No folder"), items moved in and out,
one folder per item, per kind and per workspace, an item deleted elsewhere leaves no
broken row, the Co-Founder does the same from chat with Undo, and a workspace's
export / import carries them. Nothing of Hermes changes."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from test_automations import MODEL, env  # noqa: F401 - fixture
from test_cofounder_hermes import _run, _undo
from test_templates import _filled, _zip, ws_env  # noqa: F401 - fixture

from agos_core.actions import folders, goals


def _ws(client: Any, name: str) -> str:
    return str(client.post("/workspaces", json={"name": name, "defaultModel": MODEL}).json()["id"])


def _automation(client: Any, ws: str, name: str) -> int:
    r = client.post(
        f"/workspaces/{ws}/automations",
        json={
            "name": name,
            "instructions": "Do the thing.",
            "schedule": "0 9 * * 1",
            "model": MODEL,
            "on": True,
        },
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _skill(client: Any, ws: str, name: str) -> int:
    text = f"---\nname: {name}\ndescription: Does {name}.\n---\n\nDo it.\n"
    r = client.post(f"/workspaces/{ws}/skills", json={"name": name, "definition": {"text": text}})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _project(core: Any, ws: str, title: str) -> int:
    if goals.top(core, ws) is None:
        goals.set_vision(core, ws, title="Grow", why="", strategy="")
    goal = goals.add_goal(core, ws, title=f"Goal for {title}")
    return int(goals.add_project(core, ws, goal, title=title))


def _list(client: Any, ws: str, kind: str) -> list[dict[str, Any]]:
    r = client.get(f"/workspaces/{ws}/list-folders", params={"kind": kind})
    assert r.status_code == 200, r.text
    return list(r.json())


def _move(client: Any, ws: str, kind: str, item: int, folder: int | None) -> Any:
    return client.post(
        f"/workspaces/{ws}/list-folders/move", json={"kind": kind, "item": item, "folder": folder}
    )


def test_a_folder_is_made_renamed_and_deleted_and_its_items_stay(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    a1, a2 = _automation(client, ws, "Daily brief"), _automation(client, ws, "Weekly review")
    r = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "automation", "name": "  Reports "}
    )
    assert r.status_code == 201, r.text
    folder = r.json()
    assert (folder["name"], folder["kind"], folder["items"]) == ("Reports", "automation", [])
    # The same name twice (any case) is refused; an empty name too.
    again = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "automation", "name": "reports"}
    )
    assert again.status_code == 400 and "exists already" in again.text
    blank = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "automation", "name": "   "}
    )
    assert blank.status_code == 400
    # Items in; one folder per item (a second move takes it out of the first).
    assert _move(client, ws, "automation", a1, folder["id"]).status_code == 200
    assert _move(client, ws, "automation", a2, folder["id"]).status_code == 200
    [shown] = _list(client, ws, "automation")
    assert shown["items"] == sorted([a1, a2])
    other = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "automation", "name": "Ops"}
    )
    _move(client, ws, "automation", a2, other.json()["id"])
    by_name = {f["name"]: f["items"] for f in _list(client, ws, "automation")}
    assert by_name == {"Ops": [a2], "Reports": [a1]}  # sorted by name
    _move(client, ws, "automation", a2, None)
    assert {f["name"]: f["items"] for f in _list(client, ws, "automation")}["Ops"] == []
    # Renamed.
    r = client.put(f"/workspaces/{ws}/list-folders/{folder['id']}", json={"name": "Briefs"})
    assert r.status_code == 200 and r.json()["name"] == "Briefs" and r.json()["items"] == [a1]
    taken = client.put(f"/workspaces/{ws}/list-folders/{folder['id']}", json={"name": "ops"})
    assert taken.status_code == 400
    # Deleted: the automations are still there, in "No folder".
    assert client.delete(f"/workspaces/{ws}/list-folders/{folder['id']}").status_code == 204
    assert [f["name"] for f in _list(client, ws, "automation")] == ["Ops"]
    names = {a["name"] for a in client.get(f"/workspaces/{ws}/automations").json()}
    assert names == {"Daily brief", "Weekly review"}
    assert folders.folder_of(core, ws, "automation", a1) is None
    assert client.delete(f"/workspaces/{ws}/list-folders/{folder['id']}").status_code == 404


def test_folders_are_per_kind_and_per_workspace(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    skill = _skill(client, ws, "brief-writer")
    auto = _automation(client, ws, "Daily brief")
    project = _project(core, ws, "Reels")
    skills = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "skill", "name": "Writing"}
    )
    projects = client.post(
        f"/workspaces/{ws}/list-folders", json={"kind": "project", "name": "Writing"}
    )
    assert skills.status_code == projects.status_code == 201  # same name, another kind
    s_id, p_id = skills.json()["id"], projects.json()["id"]
    assert _move(client, ws, "skill", skill, s_id).status_code == 200
    assert _move(client, ws, "project", project, p_id).status_code == 200
    # A folder holds its own kind only; an item id of another kind is not found.
    wrong = _move(client, ws, "automation", auto, s_id)
    assert wrong.status_code == 400 and "holds skills" in wrong.text
    assert _move(client, ws, "skill", auto + 1000, s_id).status_code == 404
    assert _list(client, ws, "skill")[0]["items"] == [skill]
    assert _list(client, ws, "project")[0]["items"] == [project]
    assert _list(client, ws, "automation") == []
    # Another workspace sees none of it and can't touch it.
    other = _ws(client, "Beta")
    assert _list(client, other, "skill") == []
    assert (
        client.put(f"/workspaces/{other}/list-folders/{s_id}", json={"name": "x"}).status_code
        == 404
    )
    assert client.delete(f"/workspaces/{other}/list-folders/{s_id}").status_code == 404
    mine = client.post(f"/workspaces/{other}/list-folders", json={"kind": "skill", "name": "Mine"})
    # Its folder can't take this workspace's skill, nor this workspace's folder its item.
    assert _move(client, other, "skill", skill, mine.json()["id"]).status_code == 404
    other_skill = _skill(client, other, "notes")
    assert _move(client, other, "skill", other_skill, s_id).status_code == 404
    assert _list(client, ws, "skill")[0]["items"] == [skill]
    bad = client.get(f"/workspaces/{ws}/list-folders", params={"kind": "agent"})
    assert bad.status_code == 422


def test_an_item_deleted_elsewhere_leaves_no_broken_row(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    auto = _automation(client, ws, "Daily brief")
    skill = _skill(client, ws, "brief-writer")
    project = _project(core, ws, "Reels")
    ids = {}
    for kind, item in (("automation", auto), ("skill", skill), ("project", project)):
        made = client.post(
            f"/workspaces/{ws}/list-folders", json={"kind": kind, "name": "Box"}
        ).json()
        ids[kind] = made["id"]
        assert _move(client, ws, kind, item, made["id"]).status_code == 200
    assert client.delete(f"/workspaces/{ws}/automations/{auto}").status_code in (200, 204)
    assert client.delete(f"/workspaces/{ws}/skills/{skill}").status_code == 204
    assert client.delete(f"/workspaces/{ws}/vision/items/{project}").status_code == 204
    for kind in ids:
        [box] = _list(client, ws, kind)
        assert box["items"] == [], kind  # the folder stays, empty
    assert core.db.execute("SELECT COUNT(*) FROM folder_items").fetchone()[0] == 0
    # A whole workspace's delete takes its folders with it.
    core.db.execute("DELETE FROM workspaces WHERE id = ?", (ws,))
    assert core.db.execute("SELECT COUNT(*) FROM folders").fetchone()[0] == 0


def test_the_cofounder_does_folders_from_chat_and_each_has_undo(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    skill = _skill(client, ws, "brief-writer")
    auto = _automation(client, ws, "Daily brief")
    project = _project(core, ws, "Reels series")

    def shown(kind: str) -> dict[str, list[int]]:
        return {f["name"]: f["items"] for f in _list(client, ws, kind)}

    [made] = _run(core, ws, {"do": "create_folder", "kind": "skill", "name": "Writing"})
    assert made["status"] == "done" and made["canUndo"], made
    assert shown("skill") == {"Writing": []}
    [moved] = _run(
        core,
        ws,
        {"do": "move_to_folder", "kind": "skill", "item": "brief-writer", "folder": "writing"},
    )
    assert moved["status"] == "done" and moved["canUndo"], moved
    assert shown("skill") == {"Writing": [skill]}
    [renamed] = _run(
        core, ws, {"do": "rename_folder", "kind": "skill", "folder": "Writing", "new": "Words"}
    )
    assert renamed["status"] == "done" and shown("skill") == {"Words": [skill]}
    _undo(core, ws, renamed)
    assert shown("skill") == {"Writing": [skill]}
    # Delete: the skill stays; Undo brings the folder back with the skill in it.
    [gone] = _run(core, ws, {"do": "delete_folder", "kind": "skill", "folder": "Writing"})
    assert gone["status"] == "done" and gone["canUndo"], gone
    assert shown("skill") == {}
    assert skill in {s["id"] for s in client.get(f"/workspaces/{ws}/skills").json()}
    _undo(core, ws, gone)
    assert shown("skill") == {"Writing": [skill]}
    # Moving out ("" = No folder) and Undo puts it back.
    [out] = _run(core, ws, {"do": "move_to_folder", "kind": "skill", "item": skill, "folder": ""})
    assert out["status"] == "done" and shown("skill") == {"Writing": []}
    _undo(core, ws, out)
    assert shown("skill") == {"Writing": [skill]}
    # Automations by name, projects by title; Undo of the create takes the folder away.
    [box] = _run(core, ws, {"do": "create_folder", "kind": "automations", "name": "Daily"})
    _run(
        core,
        ws,
        {"do": "move_to_folder", "kind": "automation", "item": "daily brief", "folder": "Daily"},
    )
    assert shown("automation") == {"Daily": [auto]}
    _undo(core, ws, box)
    assert shown("automation") == {}
    _run(core, ws, {"do": "create_folder", "kind": "project", "name": "Video"})
    [p] = _run(
        core,
        ws,
        {"do": "move_to_folder", "kind": "project", "item": "Reels series", "folder": "Video"},
    )
    assert p["status"] == "done" and shown("project") == {"Video": [project]}
    # Wrong names fail plainly; another workspace's folder is unknown.
    [bad] = _run(
        core, ws, {"do": "move_to_folder", "kind": "skill", "item": "nope", "folder": "Writing"}
    )
    assert bad["status"] == "failed" and "no skill" in bad["error"]
    [kind] = _run(core, ws, {"do": "create_folder", "kind": "agents", "name": "X"})
    assert kind["status"] == "failed" and "automations, skills or projects" in kind["error"]
    other = _ws(client, "Beta")
    [theirs] = _run(core, other, {"do": "delete_folder", "kind": "skill", "folder": "Writing"})
    assert theirs["status"] == "failed" and "no skill folder" in theirs["error"]
    assert shown("skill") == {"Writing": [skill]}


def test_undo_of_a_move_whose_folder_went_meanwhile_goes_to_no_folder(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    skill = _skill(client, ws, "brief-writer")
    a = folders.create(core, ws, "skill", "A")
    folders.create(core, ws, "skill", "B")
    folders.move(core, ws, "skill", skill, int(a["id"]))
    [moved] = _run(
        core, ws, {"do": "move_to_folder", "kind": "skill", "item": skill, "folder": "B"}
    )
    folders.remove(core, ws, int(a["id"]))
    _undo(core, ws, moved)
    assert folders.folder_of(core, ws, "skill", skill) is None


def test_export_and_import_carry_the_folders(ws_env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = ws_env
    _filled(client, core, ws)
    [auto] = client.get(f"/workspaces/{ws}/automations").json()
    skill = next(
        s for s in client.get(f"/workspaces/{ws}/skills").json() if s["name"] == "brief-writer"
    )
    project = int(
        core.db.execute(
            "SELECT id FROM goals WHERE workspace_id = ? AND title = 'Reels series'", (ws,)
        ).fetchone()[0]
    )
    for kind, item, name in (
        ("automation", auto["id"], "Planning"),
        ("skill", skill["id"], "Writing"),
        ("project", project, "Video"),
    ):
        made = folders.create(core, ws, kind, name)  # type: ignore[arg-type]
        folders.move(core, ws, kind, int(item), int(made["id"]))  # type: ignore[arg-type]
    folders.create(core, ws, "skill", "Empty")
    data = _zip(client, ws)
    r = client.post("/import/preview", json={"data": base64.b64encode(data).decode()})
    key_name = next(i["name"] for i in r.json()["inputs"] if i["kind"] == "tool_key")
    r = client.post(
        "/import",
        json={
            "data": base64.b64encode(data).decode(),
            "name": "Copy",
            "defaultModel": MODEL,
            "inputs": {key_name: "pk-NEW-value-for-the-copy-1234"},
        },
    )
    assert r.status_code == 200, r.text
    new = r.json()["workspaceId"]

    def names(kind: str) -> dict[str, int]:
        return {f["name"]: len(f["items"]) for f in _list(client, new, kind)}

    assert names("automation") == {"Planning": 1}
    assert names("skill") == {"Empty": 0, "Writing": 1}
    assert names("project") == {"Video": 1}
    # The copy's folders hold the copy's own items, never the first workspace's.
    [copy_auto] = client.get(f"/workspaces/{new}/automations").json()
    assert _list(client, new, "automation")[0]["items"] == [copy_auto["id"]] != [auto["id"]]


@pytest.mark.parametrize("name", ["x" * 41, "a\x01b"])
def test_a_folder_name_is_one_short_line(ws_env: Any, name: str) -> None:  # noqa: F811
    client, _core, _cron, ws = ws_env
    r = client.post(f"/workspaces/{ws}/list-folders", json={"kind": "skill", "name": name})
    assert r.status_code == 400
