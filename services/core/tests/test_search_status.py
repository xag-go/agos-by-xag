"""Step 55: workspace search, status cards and the attributed activity feed.

- Search reads every type where it lives (Hermes's board for cards / comments /
  files, the workspace folder for documents, the team's profiles, the plan rows,
  the skill folder) with an excerpt and the matched words' places; never another
  workspace's; fast on a big board; the agents get the same search (agos_search).
- Status cards: a scope + the Co-Founder's summary; a Hermes monitor job per card
  (schedule, prompt, monitor script) that wakes only when the scope's facts
  changed or the owner asked; Refresh now; the summary's revisions.
- The Log says who did each thing (owner / Co-Founder / member / automation) and
  filters by who, by area and by date.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_team_hierarchy import _agent

from agos_core.actions import agent_profiles, docs, goals, hermes_channel, search, status_cards
from agos_core.db import library as library_repo
from agos_core.db.activity import add_activity
from agos_core.hermes_plugin.agos_guard import search as guard_search
from agos_core.storage.layout import workspace_paths

BOARD = """
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT,
  assignee TEXT, status TEXT NOT NULL, created_by TEXT, created_at INTEGER NOT NULL,
  started_at INTEGER, completed_at INTEGER, result TEXT, block_kind TEXT,
  idempotency_key TEXT, goal_mode INTEGER, model_override TEXT);
CREATE TABLE IF NOT EXISTS task_comments (id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL, author TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
  run_id INTEGER, kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS task_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
  profile TEXT, status TEXT NOT NULL, started_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS task_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL, filename TEXT NOT NULL, stored_path TEXT NOT NULL, content_type TEXT,
  size INTEGER NOT NULL DEFAULT 0, uploaded_by TEXT, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS task_links (parent_id TEXT, child_id TEXT);
"""


def _board(core: Any, ws: str) -> sqlite3.Connection:
    """Hermes's board of the workspace (hermes_cli/kanban_db.py's tables AGOS reads)."""
    folder = agent_profiles.board_home(core, ws)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "kanban.db")
    db.executescript(BOARD)
    return db


def _card(
    db: sqlite3.Connection,
    card: str,
    title: str,
    body: str = "",
    *,
    status: str = "todo",
    assignee: str = "",
    created_by: str = "owner",
    at: int = 1_790_000_000,
    key: str = "",
) -> None:
    db.execute(
        """INSERT OR REPLACE INTO tasks (id, title, body, assignee, status, created_by, created_at,
             idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (card, title, body, assignee or None, status, created_by, at, key or None),
    )
    db.commit()


def _marked(result: dict[str, Any]) -> list[str]:
    return [result["excerpt"][a:b].lower() for a, b in result["marks"]]


def _find(client: Any, ws: str, q: str, types: str = "") -> dict[str, Any]:
    r = client.get(f"/workspaces/{ws}/search", params={"q": q, "types": types})
    assert r.status_code == 200, r.text
    return dict(r.json())


# ---- search -----------------------------------------------------------------------------------


def _argan_everywhere(client: Any, core: Any, ws: str) -> None:
    db = _board(core, ws)
    _card(db, "t_launch", "Launch the Argan campaign", "Write the brief about argan oil for May.")
    _card(db, "t_other", "Photos for the shop", "Shoot the new bottles.")
    db.execute(
        "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        ("t_other", "owner", "Use the argan field at sunset, please.", 1_790_000_100),
    )
    db.execute(
        """INSERT INTO task_attachments (task_id, filename, stored_path, size, created_at)
           VALUES ('t_other', 'argan-field.png', '/x/argan-field.png', 10, 1790000200)""",
    )
    db.commit()
    db.close()
    files = workspace_paths(core.layout, ws).files
    (files / "cards" / "t_launch").mkdir(parents=True, exist_ok=True)
    (files / "cards" / "t_launch" / "notes.md").write_text("# Notes\n\nArgan prices went up.\n")
    folder = docs.folder(core, ws)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "brand.md").write_text("# Brand\n\nWe always say argan, never argane.\n")
    _agent(client, ws, "writer", instructions="Writes every argan post in French.")
    vision = goals.set_vision(
        core, ws, title="The first argan brand of Agadir", why="", strategy=""
    )
    del vision
    goal = goals.add_goal(core, ws, title="Sell more oil", why="argan is our core", owner="")
    goals.add_result(core, ws, goal, title="Argan bottles sold", start=0, current=10, target=100)
    skill_id = library_repo.insert_item(
        core.db,
        kind="skill",
        name="argan-copy",
        title="Argan copy",
        summary="",
        definition={},
        source="created",
        workspace_id=ws,
    )
    del skill_id
    from agos_core.actions import workspace_skills

    base = workspace_skills.folder(core, ws)
    assert base is not None
    (base / "argan-copy").mkdir(parents=True, exist_ok=True)
    (base / "argan-copy" / "SKILL.md").write_text(
        "---\nname: argan-copy\ndescription: How we write about argan.\n---\n\nSteps.\n"
    )


def test_search_finds_each_type_with_excerpts_and_links(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _argan_everywhere(client, core, ws)
    found = _find(client, ws, "ARGAN")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in found["results"]:
        by_type.setdefault(r["type"], []).append(r)
    assert set(by_type) >= {"card", "comment", "artifact", "document", "agent", "goal", "skill"}
    assert found["counts"]["card"] == 1 and found["counts"]["comment"] == 1
    card = by_type["card"][0]
    assert card["href"] == f"/w/{ws}/kanban?card=t_launch" and card["title"].startswith("Launch")
    assert "argan" in _marked(card)
    comment = by_type["comment"][0]
    assert comment["href"] == f"/w/{ws}/kanban?card=t_other" and "You" in comment["where"]
    assert _marked(comment) == ["argan"]
    assert by_type["artifact"][0]["title"] == "argan-field.png"
    docs_found = {r["id"]: r for r in by_type["document"]}
    assert docs_found["doc:brand.md"]["href"] == f"/w/{ws}/docs?f=brand.md"
    assert (
        docs_found["card-doc:t_launch:notes"]["href"] == f"/w/{ws}/kanban?card=t_launch&doc=notes"
    )
    # "argane" holds "argan": every match is marked, never a word cut in two.
    assert _marked(docs_found["doc:brand.md"]) == ["argan", "argan"]
    assert by_type["agent"][0]["id"] == "writer"
    assert {r["id"].split(":")[0] for r in by_type["goal"]} == {"goal", "kr"}
    assert all(r["href"].startswith(f"/w/{ws}/vision#goal-") for r in by_type["goal"])
    assert by_type["skill"][0]["href"].startswith(f"/w/{ws}/settings/capabilities/skills/")
    # Every word must match; a type filter keeps only that type.
    assert _find(client, ws, "argan sunset")["counts"]["comment"] == 1
    assert _find(client, ws, "argan sunset")["counts"]["card"] == 0
    only = _find(client, ws, "argan", "card,goal")
    assert {r["type"] for r in only["results"]} == {"card", "goal"}
    assert _find(client, ws, '"argan oil"')["counts"]["card"] == 1
    assert _find(client, ws, "   ")["results"] == []


def test_excerpt_is_cut_around_the_first_match() -> None:
    text = ("lorem ipsum " * 40) + "the ARGAN harvest " + ("dolor sit " * 40)
    shown, marks = search.excerpt(text, ["argan"])
    assert shown.startswith("…") and shown.endswith("…") and len(shown) <= 190
    assert [shown[a:b] for a, b in marks] == ["ARGAN"]
    assert search.terms('Argan  "harvest plan" argan') == ["argan", "harvest plan"]


def test_search_never_crosses_workspaces(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _argan_everywhere(client, core, ws)
    other = client.post(
        "/workspaces", json={"name": "Other", "defaultModel": _model(client, ws)}
    ).json()["id"]
    db = _board(core, other)
    _card(db, "t_b", "Argan for the other shop")
    db.close()
    mine = {r["id"] for r in _find(client, ws, "argan")["results"]}
    theirs = {r["id"] for r in _find(client, other, "argan")["results"]}
    assert "t_b" not in mine and "t_launch" in mine
    assert theirs == {"t_b"}
    # The agents' tool, through each workspace's own bridge key.
    key = hermes_channel.bridge_key(core, other)
    r = client.post(
        f"/hermes-bridge/{other}/search",
        json={"query": "argan"},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200 and "t_launch" not in r.json()["found"]
    # One workspace's key on the other's bridge: refused.
    assert (
        client.post(
            f"/hermes-bridge/{ws}/search",
            json={"query": "argan"},
            headers={"authorization": f"Bearer {key}"},
        ).status_code
        == 401
    )


def _model(client: Any, ws: str) -> dict[str, Any]:
    from test_automations import MODEL

    return dict(MODEL)


def test_agos_search_tool_gives_short_lines(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _argan_everywhere(client, core, ws)
    key = hermes_channel.bridge_key(core, ws)

    def post(path: str, body: dict[str, Any], _wait: float) -> dict[str, Any]:
        r = client.post(
            f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
        )
        assert r.status_code == 200, r.text
        return dict(r.json())

    said = guard_search.search_tool(
        {"query": "argan", "types": ["card", "nope"]}, member="", post=post
    )
    lines = said.splitlines()
    assert lines[0] == "Search “argan” in this workspace:"
    assert lines[1].startswith("- [card] Launch the Argan campaign") and lines[1].endswith(
        "t_launch"
    )
    assert all(len(line) < 400 for line in lines)
    assert "Matches per type: card 1." in said
    assert "Nothing found." in guard_search.search_tool({"query": "zzz"}, member="", post=post)
    assert "AGOS can't be reached" in guard_search.search_tool(
        {"query": "x"}, member="", post=lambda *a: None
    )
    # Registered as Hermes tools of the agos toolset.
    registered: list[dict[str, Any]] = []

    class Ctx:
        def register_tool(self, **kw: Any) -> None:
            registered.append(kw)

    import contextlib

    guard_search.register(
        Ctx(), member_of=lambda: "", post=post, guard=lambda _n: contextlib.nullcontext()
    )
    assert [t["name"] for t in registered] == ["agos_search", "agos_status_card"]
    assert {t["toolset"] for t in registered} == {"agos"}


def test_search_is_fast_on_a_big_board(env: Any, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    """Thousands of cards, comments and card documents: an answer well under 300 ms."""
    client, core, _cron, ws = env
    db = _board(core, ws)
    words = ["brief", "reel", "photo", "launch", "budget", "invoice", "caption", "story"]
    db.executemany(
        "INSERT INTO tasks (id, title, body, status, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                f"t_{i:05d}",
                f"Card {i} {words[i % 8]} for client {i % 97}",
                f"Write the {words[(i + 3) % 8]} with care. " * 20
                + ("Needle here." if i == 4321 else ""),
                "done" if i % 3 else "todo",
                "owner",
                1_790_000_000 + i,
            )
            for i in range(5000)
        ],
    )
    db.executemany(
        "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        [
            (
                f"t_{i % 5000:05d}",
                "owner",
                f"Comment {i} about the {words[i % 8]}",
                1_790_000_000 + i,
            )
            for i in range(10000)
        ],
    )
    db.commit()
    db.close()
    files = workspace_paths(core.layout, ws).files / "cards"
    for i in range(1000):
        (files / f"t_{i:05d}").mkdir(parents=True, exist_ok=True)
        (files / f"t_{i:05d}" / "notes.md").write_text(f"# Notes {i}\n\n" + "Some words. " * 200)
    timings = []
    for q in ("needle", "budget client", "caption", "needle"):
        started = time.perf_counter()
        found = _find(client, ws, q)
        timings.append((q, round((time.perf_counter() - started) * 1000, 1), found["tookMs"]))
    with capsys.disabled():
        print(
            f"\nsearch timings on 5000 cards / 10000 comments / 1000 docs (q, http ms, core ms): {timings}"
        )
    assert _find(client, ws, "needle")["counts"]["card"] == 1
    # The first answer reads every document once; the next ones only stat them.
    assert all(core_ms < 300 for _q, _http, core_ms in timings[1:]), timings
    assert all(http < 300 for _q, http, _core in timings[1:]), timings


# ---- status cards -----------------------------------------------------------------------------


def _bridge(client: Any, core: Any, ws: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _plan(core: Any, ws: str) -> tuple[int, int]:
    goals.set_vision(core, ws, title="Grow", why="", strategy="")
    goal = goals.add_goal(core, ws, title="Launch", why="", owner="")
    goals.add_result(core, ws, goal, title="Shops", start=0, current=2, target=10)
    project = goals.add_project(core, ws, goal, title="Spring launch", why="", owner="")
    return goal, project


def _root_jobs(core: Any, cron: Any, ws: str) -> dict[str, dict[str, Any]]:
    home = str(core.engine.profile_home(ws))
    return {j["spec"].name: j for j in cron.jobs.values() if j["home"] == home}


def test_status_card_is_a_hermes_monitor_job_and_its_revisions(env: Any) -> None:  # noqa: F811
    client, core, cron, ws = env
    _agent(client, ws, "writer")
    goal, project = _plan(core, ws)
    db = _board(core, ws)
    _card(
        db,
        "t_a",
        "Shoot the reel",
        f"## Goal\nProject #{project}: Spring launch\n\nThe spring reel.",
        status="running",
    )
    _card(db, "t_b", "Not in it")
    db.close()

    r = client.post(
        f"/workspaces/{ws}/status-cards",
        json={
            "title": "Spring",
            "scope": "project",
            "scopeRef": str(project),
            "policy": "daily",
            "time": "07:30",
        },
    )
    assert r.status_code == 201, r.text
    card = r.json()
    assert (card["scopeLabel"], card["policy"], card["time"], card["revision"]) == (
        "project “Spring launch”",
        "daily",
        "07:30",
        0,
    )
    job = _root_jobs(core, cron, ws)[f"AGOS status card {card['id']}"]
    spec = job["spec"]
    assert spec.schedule == "30 7 * * *" and spec.monitor_script == f"agos-status-{card['id']}.py"
    assert spec.script is None and spec.enabled
    assert "agos_status_card" in spec.prompt and "Nothing to do." in spec.prompt
    script = core.engine.profile_home(ws) / "scripts" / f"agos-status-{card['id']}.py"
    compile(script.read_text(), str(script), "exec")  # Hermes runs it as Python
    assert "/status-card" in script.read_text() and "agos-bridge.json" in script.read_text()

    # The monitor's facts: only the scope's cards, stable while nothing moves.
    first = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert "card t_a | running" in first and "t_b" not in first
    again = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert again == first
    db = _board(core, ws)
    db.execute("UPDATE tasks SET status = 'done' WHERE id = 't_a'")
    db.commit()
    db.close()
    moved = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert moved != first and "card t_a | done" in moved

    # The Co-Founder reads and writes; a member may not write.
    read = _bridge(client, core, ws, "status-card", {"action": "read", "card": card["id"]})["read"]
    assert "No summary yet" in read and "t_a" in read
    refused = _bridge(
        client,
        core,
        ws,
        "status-card",
        {"action": "write", "card": card["id"], "summary": "x", "member": "writer"},
    )
    assert "Only the Co-Founder" in refused["error"]
    one = _bridge(
        client,
        core,
        ws,
        "status-card",
        {"action": "write", "card": card["id"], "summary": "On track: t_a done."},
    )
    assert one == {"card": card["id"], "saved": True, "revision": 1}
    same = _bridge(
        client,
        core,
        ws,
        "status-card",
        {"action": "write", "card": card["id"], "summary": "On track: t_a done."},
    )
    assert same["saved"] is False
    two = _bridge(
        client,
        core,
        ws,
        "status-card",
        {
            "action": "write",
            "card": card["id"],
            "summary": "At risk: waiting on photos.",
            "why": "photos late",
        },
    )
    assert two["revision"] == 2
    read = _bridge(client, core, ws, "status-card", {"action": "read", "card": card["id"]})["read"]
    assert "Nothing moved on the board since your last summary (v2" in read
    assert "At risk: waiting on photos." in read

    page = client.get(f"/workspaces/{ws}/status-cards").json()
    shown = page["cards"][0]
    assert shown["summary"] == "At risk: waiting on photos." and shown["revision"] == 2
    assert [(v["n"], v["who"], v["why"]) for v in shown["revisions"]] == [
        (2, "Co-Founder", "photos late"),
        (1, "Co-Founder", "the scheduled update"),
    ]
    assert {p["title"] for p in page["plan"]} == {"Launch", "Spring launch"}
    assert page["members"] == [{"name": "writer", "title": "Writer"}]
    rev = client.get(f"/workspaces/{ws}/status-cards/{card['id']}/revisions/2").json()
    assert rev["content"].strip() == "At risk: waiting on photos." and "-On track" in rev["diff"]
    files = workspace_paths(core.layout, ws).files / "status" / str(card["id"])
    assert (files / "summary.md").read_text() == "At risk: waiting on photos.\n"
    assert (files / ".revisions" / "summary" / "v1.md").is_file()
    # Searchable like any document.
    hit = _find(client, ws, "photos", "document")["results"]
    assert hit and hit[0]["href"] == f"/w/{ws}/status#card-{card['id']}"

    # Refresh now: marked (the monitor's output changes) and fired on Hermes's next tick.
    before = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    r = client.post(f"/workspaces/{ws}/status-cards/{card['id']}/refresh")
    assert r.status_code == 200 and r.json()["refreshAskedAt"]
    assert cron.fired == [job["id"]]
    after = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert after != before and "Refresh asked by the owner" in after
    # The next summary clears it.
    _bridge(
        client,
        core,
        ws,
        "status-card",
        {"action": "write", "card": card["id"], "summary": "Fresh."},
    )
    assert client.get(f"/workspaces/{ws}/status-cards").json()["cards"][0]["refreshAskedAt"] is None

    # Weekly, then on demand: an on-demand card's monitor shows only its refresh line.
    r = client.put(
        f"/workspaces/{ws}/status-cards/{card['id']}",
        json={
            "title": "Spring",
            "scope": "goal",
            "scopeRef": str(goal),
            "policy": "weekly",
            "time": "16:00",
            "day": 5,
        },
    )
    assert r.status_code == 200, r.text
    assert (
        _root_jobs(core, cron, ws)[f"AGOS status card {card['id']}"]["spec"].schedule
        == "0 16 * * 5"
    )
    weekly = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert (
        "card t_a" in weekly and "key result" in weekly
    )  # a goal: its projects' cards + its numbers
    client.put(
        f"/workspaces/{ws}/status-cards/{card['id']}",
        json={"title": "Spring", "scope": "goal", "scopeRef": str(goal), "policy": "manual"},
    )
    manual = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": card["id"]})[
        "monitor"
    ]
    assert manual.count("\n") == 1 and "card t_a" not in manual

    # Delete: its Hermes job and its script go.
    assert client.delete(f"/workspaces/{ws}/status-cards/{card['id']}").status_code == 204
    assert f"AGOS status card {card['id']}" not in _root_jobs(core, cron, ws)
    assert not script.exists()
    assert client.get(f"/workspaces/{ws}/status-cards").json()["cards"] == []


def test_status_card_scopes_are_checked_and_kept_per_workspace(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "writer")
    goal, project = _plan(core, ws)

    def add(**body: Any) -> Any:
        return client.post(f"/workspaces/{ws}/status-cards", json={"title": "X", **body})

    assert add(scope="project", scopeRef=str(goal)).status_code == 400  # a goal, not a project
    assert add(scope="member", scopeRef="nobody").status_code == 400
    assert add(scope="query", scopeRef="  ").status_code == 400
    assert add(scope="workspace", policy="weekly", day=None).status_code == 400
    member = add(scope="member", scopeRef="writer").json()
    query = add(scope="query", scopeRef="reel").json()
    db = _board(core, ws)
    writer = core.engine.hermes_name(agent_profiles.key(ws, "writer"))
    _card(db, "t_w", "Edit the reel", assignee=writer)
    _card(db, "t_x", "Pay the invoice")
    db.close()
    mine = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": member["id"]})[
        "monitor"
    ]
    assert "card t_w" in mine and "@writer" in mine and "t_x" not in mine
    words = _bridge(client, core, ws, "status-card", {"action": "monitor", "card": query["id"]})[
        "monitor"
    ]
    assert "card t_w" in words and "t_x" not in words
    listed = _bridge(client, core, ws, "status-card", {"action": "list"})["cards"]
    assert [c["card"] for c in listed] == [member["id"], query["id"]]
    other = client.post(
        "/workspaces", json={"name": "Other", "defaultModel": _model(client, ws)}
    ).json()["id"]
    assert (
        client.post(f"/workspaces/{other}/status-cards/{member['id']}/refresh").status_code == 404
    )
    assert "error" in _bridge(
        client, core, other, "status-card", {"action": "read", "card": member["id"]}
    )
    assert status_cards.titles(core, other) == {}
    del project


# ---- activity attribution ---------------------------------------------------------------------


def test_the_log_says_who_did_what_and_filters_by_who_and_date(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "writer")
    writer = core.engine.hermes_name(agent_profiles.key(ws, "writer"))
    cofounder = core.engine.hermes_name(ws)
    db = _board(core, ws)
    _card(db, "t_1", "Write the brief", created_by="owner")
    _card(db, "t_2", "Nightly report", created_by=cofounder, key="agos-automation:7:1:team:0")
    db.execute(
        "INSERT INTO task_runs (id, task_id, profile, status, started_at) VALUES (1, 't_1', ?, 'done', 1)",
        (writer,),
    )
    events = [
        ("t_1", None, "created", {}, 1_790_000_000),
        ("t_1", 1, "claimed", {}, 1_790_000_010),
        ("t_1", None, "commented", {"author": "owner", "len": 4}, 1_790_000_020),
        ("t_1", 1, "completed", {"summary": "brief written"}, 1_790_000_030),
        ("t_2", None, "created", {}, 1_790_100_000),
        ("t_1", None, "assigned", {"assignee": writer}, 1_790_000_040),
    ]
    db.executemany(
        "INSERT INTO task_events (task_id, run_id, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        [(t, r, k, json.dumps(p), at) for t, r, k, p, at in events],
    )
    db.commit()
    db.close()
    assert client.put(f"/workspaces/{ws}/vision", json={"title": "Grow"}).status_code == 200
    add_activity(
        core.db, ws, kind="status.written", text="Status card “Spring”: summary v1 by Co-Founder"
    )

    page = client.get(f"/workspaces/{ws}/log").json()
    by_id = {e["id"]: e for e in page["entries"]}
    kanban = {
        (e["text"].split(":")[0], e["actor"], e["actor_key"])
        for e in page["entries"]
        if e["id"].startswith("kanban:")
    }
    assert ("Created", "You", "owner") in kanban
    assert ("Started", "@writer", "member:writer") in kanban
    assert ("Done", "@writer", "member:writer") in kanban
    assert ("Commented", "You", "owner") in kanban
    assert ("Created", "Automation 7", "automation:7") in kanban
    assigned = next(e for e in page["entries"] if e["text"].startswith("Assigned"))
    assert assigned["text"] == "Assigned: to @writer" and assigned["actor"] == "Kanban"
    vision = next(e for e in page["entries"] if e["where"] == "goal.changed")
    assert (vision["area"], vision["actor_kind"], vision["text"]) == (
        "goal",
        "owner",
        "Vision set: Grow",
    )
    written = next(e for e in page["entries"] if e["where"] == "status.written")
    assert written["actor_kind"] == "cofounder" and written["area"] == "status"
    assert {a["key"] for a in page["actors"]} >= {
        "owner",
        "cofounder",
        "member:writer",
        "automation:7",
    }
    del by_id

    def log(**params: str) -> list[dict[str, Any]]:
        r = client.get(f"/workspaces/{ws}/log", params=params)
        assert r.status_code == 200, r.text
        return list(r.json()["entries"])

    assert {e["actor_key"] for e in log(actor="member:writer")} == {"member:writer"}
    assert {e["actor_kind"] for e in log(actor="member")} == {"member"}
    assert {e["actor_key"] for e in log(actor="automation")} == {"automation:7"}
    assert all(e["actor_kind"] == "owner" for e in log(actor="owner"))
    assert {e["area"] for e in log(area="goal")} == {"goal"}
    # Dates: 1_790_000_000 is 2026-09-21; the automation's card came a day later.
    day = [e["id"] for e in log(since="2026-09-22", until="2026-09-22", area="task")]
    assert day and all(i.startswith("kanban:") for i in day)
    assert len(day) == 1
    assert client.get(f"/workspaces/{ws}/log", params={"actor": "bad key!"}).status_code == 422


def test_activity_sources_are_kept_out_of_another_workspace(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    db = _board(core, ws)
    _card(db, "t_1", "Write the brief")
    db.execute(
        "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES ('t_1', 'created', '{}', 1)"
    )
    db.commit()
    db.close()
    other = client.post(
        "/workspaces", json={"name": "Other", "defaultModel": _model(client, ws)}
    ).json()["id"]
    assert not any(
        e["id"].startswith("kanban:")
        for e in client.get(f"/workspaces/{other}/log").json()["entries"]
    )
    assert {a["key"] for a in client.get(f"/workspaces/{other}/log").json()["actors"]} <= {
        "owner",
        "system",
    }


def test_the_status_page_and_search_are_tabs() -> None:
    from agos_core.api.preferences import TABS

    assert "status" in TABS and "search" in TABS
    assert Path(status_cards.__file__).name == "status_cards.py"
