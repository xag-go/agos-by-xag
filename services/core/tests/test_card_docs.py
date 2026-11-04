"""Step 49: a card's documents as files in the workspace folder with a revision per
save and a revision check (409 with the words that say how to go on), restore as a
new revision, passage comments anchored again on every revision, the Artifacts
gallery (Hermes's card files + the documents) with its review state and Promote,
and the owner's 👍 / 👎 said into Hermes's learning conversation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_engine_sync import MODEL, env  # noqa: F401 - fixture
from test_kanban_direct import _board

from agos_core.actions import card_docs, feedback, hermes_channel, learning
from agos_core.engine import card_docs as rules
from agos_core.hermes_plugin.agos_guard import documents as guard_docs
from agos_core.storage.layout import workspace_paths

TEXT = "# Launch plan\n\nWe launch on Monday.\n\nThe budget is 300.\n\nSam writes the post.\n"


@pytest.fixture
def space(env: Any) -> tuple[Any, Any, str]:  # noqa: F811
    client, _runner, _tmp = env
    ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
    return client, client.app.state.core, str(ws)


def _folder(core: Any, ws: str, card: str) -> Path:
    return workspace_paths(core.layout, ws).files / "cards" / card


# ---- documents: files, revisions, the revision check, restore ---------------------------------


def test_a_save_is_a_file_the_agents_see_and_a_revision_file(space: tuple[Any, Any, str]) -> None:
    client, core, ws = space
    r = client.put(f"/workspaces/{ws}/kanban/t_1/docs/plan", json={"content": TEXT, "why": "first"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "saved": True,
        "revision": 1,
        "annotations": {"active": 0, "stale": 0, "orphaned": 0},
    }
    folder = _folder(core, ws, "t_1")
    assert (folder / "plan.md").read_text() == TEXT
    assert (folder / ".revisions" / "plan" / "v1.md").read_text() == TEXT
    changes = (folder / ".revisions" / "plan" / "CHANGES.md").read_text()
    assert changes.startswith("# Changes: plan.md\n") and "| Owner | first" in changes
    # Listed with the card and alone; the text comes on open.
    listed = client.get(f"/workspaces/{ws}/kanban/t_1/docs").json()
    assert [(d["key"], d["revision"], d["who"], d["openAnnotations"]) for d in listed] == [
        ("plan", 1, "Owner", 0)
    ]
    opened = client.get(f"/workspaces/{ws}/kanban/t_1/docs/plan").json()
    assert opened["content"] == TEXT and opened["revision"] == 1 and opened["dirty"] is False
    assert [(v["n"], v["who"], v["why"]) for v in opened["revisions"]] == [(1, "Owner", "first")]
    # The card's page lists them too (one call for the modal).
    _board(core.engine.root(ws))
    card = client.get(f"/workspaces/{ws}/kanban/t_1").json()
    assert [d["key"] for d in card["documents"]] == ["plan"]
    # A key that isn't one, a document that isn't there.
    assert (
        client.put(f"/workspaces/{ws}/kanban/t_1/docs/a.b", json={"content": "x"}).status_code
        == 400
    )
    assert client.get(f"/workspaces/{ws}/kanban/t_1/docs/nope").status_code == 404


def test_a_save_on_a_moved_document_is_refused_with_the_way_out(
    space: tuple[Any, Any, str],
) -> None:
    client, core, ws = space
    url = f"/workspaces/{ws}/kanban/t_1/docs/plan"
    client.put(url, json={"content": TEXT, "why": "first"})
    # The owner edits from revision 1 -> revision 2.
    r = client.put(url, json={"content": TEXT + "\nMore.\n", "why": "more", "baseRevision": 1})
    assert r.status_code == 200 and r.json()["revision"] == 2
    # An editor still on revision 1: refused, told the current one.
    r = client.put(url, json={"content": TEXT + "\nOther.\n", "why": "late", "baseRevision": 1})
    assert r.status_code == 409
    assert r.json()["detail"] == card_docs.STALE.format(n=2)
    # A new-document save (no base) on one that exists: refused the same way.
    r = client.put(url, json={"content": "fresh"})
    assert r.status_code == 409 and "revision 2" in r.json()["detail"]
    # Nothing was written by the refused saves.
    assert (_folder(core, ws, "t_1") / "plan.md").read_text() == TEXT + "\nMore.\n"
    assert not (_folder(core, ws, "t_1") / ".revisions" / "plan" / "v3.md").exists()
    # The same text again: no new revision.
    r = client.put(url, json={"content": TEXT + "\nMore.\n", "baseRevision": 2})
    assert r.json() == {"saved": False, "revision": 2, "annotations": {}}


def test_a_file_tool_write_becomes_a_revision_and_moves_the_document(
    space: tuple[Any, Any, str],
) -> None:
    """An agent wrote the file directly (its file tools): what is on disk is kept
    as a revision first, so a save from the old revision is refused."""
    client, core, ws = space
    url = f"/workspaces/{ws}/kanban/t_1/docs/plan"
    client.put(url, json={"content": TEXT, "why": "first"})
    (_folder(core, ws, "t_1") / "plan.md").write_text(TEXT + "\nWritten by a tool.\n")
    assert client.get(url).json()["dirty"] is True
    r = client.put(url, json={"content": TEXT + "\nMine.\n", "baseRevision": 1})
    assert r.status_code == 409 and r.json()["detail"] == card_docs.STALE.format(n=2)
    opened = client.get(url).json()
    assert [(v["n"], v["who"]) for v in opened["revisions"]] == [(2, "a file tool"), (1, "Owner")]
    assert opened["dirty"] is False


def test_restore_is_a_new_revision_with_the_old_text(space: tuple[Any, Any, str]) -> None:
    client, _core, ws = space
    url = f"/workspaces/{ws}/kanban/t_1/docs/plan"
    client.put(url, json={"content": TEXT, "why": "first"})
    client.put(url, json={"content": "# Rewritten\n", "why": "second", "baseRevision": 1})
    r = client.post(f"{url}/restore", json={"revision": 1})
    assert r.status_code == 200 and r.json()["revision"] == 3
    opened = client.get(url).json()
    assert opened["content"] == TEXT and opened["revision"] == 3
    assert [(v["n"], v["why"]) for v in opened["revisions"]] == [
        (3, "restored from v1"),
        (2, "second"),
        (1, "first"),
    ]
    # Each revision is readable with what it changed.
    second = client.get(f"{url}/revisions/2").json()
    assert second["content"] == "# Rewritten\n" and "-# Launch plan" in second["diff"]
    assert client.get(f"{url}/revisions/9").status_code == 404
    assert client.post(f"{url}/restore", json={"revision": 9}).status_code == 404


# ---- the agents' tool -----------------------------------------------------------------------------


def _tool(client: Any, core: Any, ws: str, **body: Any) -> dict[str, Any]:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/card-document",
        json={"member": "", "card": "t_1", **body},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_the_agents_tool_writes_with_the_revision_check(space: tuple[Any, Any, str]) -> None:
    client, core, ws = space
    first = _tool(client, core, ws, key="notes", content="# Notes\n", why="draft")
    assert (first["saved"], first["revision"], first["key"]) == (True, 1, "notes")
    read = _tool(client, core, ws, key="notes", action="read")
    assert (read["content"], read["revision"], read["openAnnotations"]) == ("# Notes\n", 1, [])
    # The owner moves it meanwhile.
    client.put(
        f"/workspaces/{ws}/kanban/t_1/docs/notes",
        json={"content": "# Notes\n\nOwner's line.\n", "why": "mine", "baseRevision": 1},
    )
    stale = _tool(client, core, ws, key="notes", content="# Notes\n\nAgent.\n", base_revision=1)
    assert stale == {
        "error": "document moved to revision 2 since you read it; read it again and resend "
        "with base_revision=2",
        "current_revision": 2,
    }
    again = _tool(
        client,
        core,
        ws,
        key="notes",
        content="# Notes\n\nAgent.\n",
        base_revision=2,
        member="editor",
    )
    assert again["saved"] is True and again["revision"] == 3
    opened = client.get(f"/workspaces/{ws}/kanban/t_1/docs/notes").json()
    assert [(v["n"], v["who"]) for v in opened["revisions"]] == [
        (3, "editor"),
        (2, "Owner"),
        (1, "Co-Founder"),
    ]
    # No key: the card's documents.
    listed = _tool(client, core, ws, key="", action="read")
    assert [d["key"] for d in listed["documents"]] == ["notes"]
    # A bad key is a refusal the agent reads, not an HTTP error.
    assert "error" in _tool(client, core, ws, key="../x", content="x")
    # The wrong key: refused (401).
    r = client.post(f"/hermes-bridge/{ws}/card-document", json={"card": "t_1", "key": "n"})
    assert r.status_code == 401


def test_the_guard_tool_posts_the_call_and_reads_the_card_from_hermes(monkeypatch: Any) -> None:
    sent: list[tuple[str, dict[str, Any], float]] = []

    def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any] | None:
        sent.append((path, body, timeout))
        return {"error": card_docs.STALE.format(n=4), "current_revision": 4}

    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_7")
    said = json.loads(
        guard_docs.document_tool(
            {"key": "plan", "content": "x", "base_revision": 3, "why": "w"},
            member="editor",
            post=post,
        )
    )
    assert said["current_revision"] == 4 and "resend with base_revision=4" in said["error"]
    assert sent == [
        (
            "card-document",
            {
                "member": "editor",
                "card": "t_7",
                "key": "plan",
                "action": "write",
                "content": "x",
                "base_revision": 3,
                "why": "w",
            },
            guard_docs.TOOL_WAIT_S,
        )
    ]
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    assert "error" in json.loads(guard_docs.document_tool({"key": "plan"}, member="", post=post))
    registered: list[dict[str, Any]] = []

    class Ctx:
        def register_tool(self, **kw: Any) -> None:
            registered.append(kw)

    import contextlib

    guard_docs.register(
        Ctx(), member_of=lambda: "editor", post=post, guard=lambda _n: contextlib.nullcontext()
    )
    assert [r["name"] for r in registered] == ["agos_card_document"]
    assert registered[0]["schema"]["parameters"]["required"] == ["key"]


# ---- passage comments ---------------------------------------------------------------------------------


def test_a_comment_finds_its_passage_again_or_says_it_cant() -> None:
    text = "One. The budget is 300 dirhams. Two. Three."
    start = text.index("budget is 300")
    anchor = rules.anchor_of(text, start, start + len("budget is 300"))
    assert anchor is not None and anchor.quote == "budget is 300"
    # Moved as is: active, new positions.
    moved = "Zero. One. The budget is 300 dirhams. Two."
    found = rules.reanchor(anchor, moved)
    assert (found.state, moved[found.start : found.end]) == ("active", "budget is 300")
    # Twice in the text: the context tells them apart.
    twice = "The budget is 300 euros. One. The budget is 300 dirhams. Two."
    found = rules.reanchor(anchor, twice)
    assert found.state == "active" and twice[found.end :].startswith(" dirhams")
    # Changed a little: stale, pointing at the new words.
    changed = "One. The budget is 350 dirhams. Two. Three."
    found = rules.reanchor(anchor, changed)
    assert found.state == "stale" and "350" in changed[found.start : found.end]
    # Gone: orphaned (old positions kept).
    gone = "Nothing of it is left here."
    found = rules.reanchor(anchor, gone)
    assert (found.state, found.start, found.end) == ("orphaned", anchor.start, anchor.end)
    assert rules.anchor_of(text, 3, 3) is None and rules.anchor_of(text, 0, 999) is None


def test_comments_are_anchored_again_on_every_revision(space: tuple[Any, Any, str]) -> None:
    client, core, ws = space
    url = f"/workspaces/{ws}/kanban/t_1/docs/plan"
    client.put(url, json={"content": TEXT, "why": "first"})
    at = TEXT.index("budget is 300")
    r = client.post(f"{url}/annotations", json={"start": at, "end": at + 13, "body": "Too much?"})
    assert r.status_code == 201, r.text
    made = r.json()
    assert (made["quote"], made["anchor"], made["revision"], made["resolved"]) == (
        "budget is 300",
        "active",
        1,
        False,
    )
    at2 = TEXT.index("Sam writes")
    client.post(f"{url}/annotations", json={"start": at2, "end": at2 + 10, "body": "Not Sam."})
    assert client.get(f"/workspaces/{ws}/kanban/t_1/docs").json()[0]["openAnnotations"] == 2
    # Revision 2: the budget line changed a little, Sam's line is gone, a line was added above.
    text2 = "# Launch plan\n\nNew intro.\n\nWe launch on Monday.\n\nThe budget is 320.\n\nAgency: the launch copy.\n"
    r = client.put(url, json={"content": text2, "why": "second", "baseRevision": 1})
    assert r.json()["annotations"] == {"active": 0, "stale": 1, "orphaned": 1}
    opened = client.get(url).json()
    by_body = {a["body"]: a for a in opened["annotations"]}
    budget = by_body["Too much?"]
    assert budget["anchor"] == "stale" and budget["anchoredRevision"] == 2
    assert "320" in text2[budget["start"] : budget["end"]]
    assert by_body["Not Sam."]["anchor"] == "orphaned"
    # Revision 3 brings the budget line back as it was: active again.
    text3 = text2.replace("320", "300")
    client.put(url, json={"content": text3, "why": "third", "baseRevision": 2})
    opened = client.get(url).json()
    budget = next(a for a in opened["annotations"] if a["body"] == "Too much?")
    assert (
        budget["anchor"] == "active" and text3[budget["start"] : budget["end"]] == "budget is 300"
    )
    # Resolve (no longer open, no longer re-anchored), reopen, delete.
    aid = budget["id"]
    assert (
        client.post(f"{url}/annotations/{aid}/resolve", json={"resolved": True}).status_code == 204
    )
    assert client.get(f"/workspaces/{ws}/kanban/t_1/docs").json()[0]["openAnnotations"] == 1
    assert (
        client.post(f"{url}/annotations/{aid}/resolve", json={"resolved": False}).status_code == 204
    )
    assert client.delete(f"{url}/annotations/{aid}").status_code == 204
    assert client.delete(f"{url}/annotations/{aid}").status_code == 404
    # The agent sees the open ones in a short list.
    short = _tool(client, core, ws, key="plan", action="annotations")
    assert [(a["body"], a["anchor"]) for a in short["annotations"]] == [("Not Sam.", "orphaned")]
    # A comment needs a passage and words.
    for bad in ({"start": 5, "end": 5, "body": "x"}, {"start": 5, "end": 4000, "body": "x"}):
        assert client.post(f"{url}/annotations", json=bad).status_code == 400
    assert (
        client.post(f"{url}/annotations", json={"start": 0, "end": 3, "body": " "}).status_code
        == 400
    )


# ---- the Artifacts gallery --------------------------------------------------------------------------


def test_the_gallery_lists_hermess_files_and_the_documents_with_reviews(
    space: tuple[Any, Any, str],
) -> None:
    client, core, ws = space
    root = core.engine.root(ws)
    _board(root)
    files = root / "kanban" / "attachments" / "t_1"
    (files / "brief.md").write_text("# Brief\n\nThe brief.\n")
    (files / "chart.png").write_bytes(b"\x89PNG")
    import contextlib
    import sqlite3

    with contextlib.closing(sqlite3.connect(root / "kanban.db")) as db:
        db.executemany(
            "INSERT INTO task_attachments (task_id, filename, stored_path, content_type,"
            " size, uploaded_by, created_at) VALUES (?,?,?,?,?,?,?)",
            [
                ("t_1", "brief.md", str(files / "brief.md"), "text/markdown", 20, "default", 1_800_000_700),
                ("t_0", "chart.png", str(files / "chart.png"), "image/png", 4, "owner", 1_800_000_800),
            ],
        )  # fmt: skip
        db.commit()
    client.put(f"/workspaces/{ws}/kanban/t_2/docs/plan", json={"content": TEXT, "why": "first"})
    page = client.get(f"/workspaces/{ws}/artifacts").json()
    assert page["note"] == ""
    rows = {i["ref"]: i for i in page["items"]}
    assert set(rows) == {
        "attachment:t_1:1",
        "attachment:t_1:2",
        "attachment:t_0:3",
        "document:t_2:plan",
    }
    assert (rows["attachment:t_0:3"]["kind"], rows["attachment:t_0:3"]["member"]) == (
        "image",
        "You",
    )
    assert rows["attachment:t_0:3"]["cardTitle"] == "Research"
    assert (rows["attachment:t_1:1"]["kind"], rows["attachment:t_1:1"]["name"]) == (
        "other",
        "notes.txt",
    ) or (rows["attachment:t_1:1"]["kind"] == "md")
    assert (
        rows["attachment:t_1:2"]["kind"] == "md"
        and rows["attachment:t_1:2"]["member"] == "Co-Founder"
    )
    doc = rows["document:t_2:plan"]
    assert (doc["source"], doc["kind"], doc["key"], doc["revision"], doc["member"]) == (
        "document",
        "md",
        "plan",
        1,
        "Owner",
    )
    assert all(i["review"] == "" for i in page["items"])
    # Review state: approved / needs work with a note / taken back.
    assert (
        client.put(
            f"/workspaces/{ws}/artifacts/review",
            json={"artifact": "attachment:t_0:3", "state": "needs_work", "note": "blurry"},
        ).status_code
        == 204
    )
    client.put(
        f"/workspaces/{ws}/artifacts/review",
        json={"artifact": "document:t_2:plan", "state": "approved"},
    )
    rows = {i["ref"]: i for i in client.get(f"/workspaces/{ws}/artifacts").json()["items"]}
    assert (rows["attachment:t_0:3"]["review"], rows["attachment:t_0:3"]["reviewNote"]) == (
        "needs_work",
        "blurry",
    )
    assert rows["document:t_2:plan"]["review"] == "approved"
    client.put(
        f"/workspaces/{ws}/artifacts/review", json={"artifact": "document:t_2:plan", "state": ""}
    )
    rows = {i["ref"]: i for i in client.get(f"/workspaces/{ws}/artifacts").json()["items"]}
    assert rows["document:t_2:plan"]["review"] == ""
    assert (
        client.put(
            f"/workspaces/{ws}/artifacts/review", json={"artifact": "x:1", "state": "approved"}
        ).status_code
        == 404
    )
    # Promote: the markdown attachment becomes a document of its card (first revision).
    r = client.post(f"/workspaces/{ws}/artifacts/promote", json={"card": "t_1", "attachment": 2})
    assert r.status_code == 201, r.text
    assert r.json() == {"card": "t_1", "key": "brief", "revision": 1}
    opened = client.get(f"/workspaces/{ws}/kanban/t_1/docs/brief").json()
    assert opened["content"] == "# Brief\n\nThe brief.\n"
    assert opened["revisions"][0]["why"] == "promoted from the attachment brief.md"
    # Again under the same key: refused; a picture: refused; a file that isn't there: 404.
    r = client.post(f"/workspaces/{ws}/artifacts/promote", json={"card": "t_1", "attachment": 2})
    assert r.status_code == 400 and "already has a document brief" in r.json()["detail"]
    r = client.post(f"/workspaces/{ws}/artifacts/promote", json={"card": "t_0", "attachment": 3})
    assert r.status_code == 400
    assert (
        client.post(
            f"/workspaces/{ws}/artifacts/promote", json={"card": "t_1", "attachment": 9}
        ).status_code
        == 404
    )
    assert rules.slug("Launch plan v2.md") == "Launch-plan-v2" and rules.slug("***") == "document"


def test_the_gallery_says_when_the_board_cant_be_read(space: tuple[Any, Any, str]) -> None:
    client, _core, ws = space
    page = client.get(f"/workspaces/{ws}/artifacts").json()
    assert page["items"] == [] and "can't be listed" in page["note"]


# ---- 👍 / 👎 ------------------------------------------------------------------------------------------


def test_a_vote_is_kept_and_said_into_hermess_learning(
    space: tuple[Any, Any, str], monkeypatch: Any
) -> None:
    client, core, ws = space
    said: list[tuple[str, str]] = []
    monkeypatch.setattr(learning, "say", lambda _core, w, text: said.append((w, text)))
    client.put(f"/workspaces/{ws}/kanban/t_1/docs/plan", json={"content": TEXT, "why": "first"})
    r = client.post(
        f"/workspaces/{ws}/feedback",
        json={
            "kind": "revision",
            "ref": "t_1:plan:1",
            "vote": -1,
            "note": "too long",
            "subject": "Launch plan",
        },
    )
    assert r.status_code == 200 and r.json() == {"vote": -1}
    assert said == [
        (
            ws,
            "The owner disliked: revision v1 of document plan on card t_1 — Launch plan\n"
            "He said: too long",
        )
    ]
    opened = client.get(f"/workspaces/{ws}/kanban/t_1/docs/plan").json()
    assert opened["revisions"][0]["vote"] == -1
    # A 👍 replaces it (one row per item); a reply vote is said with the chat message.
    client.post(
        f"/workspaces/{ws}/feedback", json={"kind": "revision", "ref": "t_1:plan:1", "vote": 1}
    )
    assert client.get(f"/workspaces/{ws}/kanban/t_1/docs/plan").json()["revisions"][0]["vote"] == 1
    client.post(
        f"/workspaces/{ws}/feedback",
        json={"kind": "reply", "ref": "12:345", "vote": 1, "subject": "Here is the plan..."},
    )
    assert said[-1] == (
        ws,
        "The owner liked: your reply — Here is the plan... (chat message 12:345)",
    )
    assert feedback.votes_of(core, ws, "reply", "12:") == {"12:345": 1}
    assert feedback.votes_of(core, ws, "reply", "1:") == {}
    rows = core.db.execute(
        "SELECT kind, ref, vote, note FROM feedback_votes WHERE workspace_id = ? ORDER BY id",
        (ws,),
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("revision", "t_1:plan:1", 1, ""),
        ("reply", "12:345", 1, ""),
    ]
    # Taken back: the row goes, nothing is said.
    before = len(said)
    client.post(f"/workspaces/{ws}/feedback", json={"kind": "reply", "ref": "12:345", "vote": 0})
    assert feedback.votes_of(core, ws, "reply", "12:") == {} and len(said) == before
    # Hermes's own learning reader still parses what was said (actions/learning.py).
    found = learning._DECISION.match(said[0][1])
    assert found is not None and found[1] == "disliked" and found[4] == "too long"
