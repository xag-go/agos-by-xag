"""Step 59: a card's runtime services and preview links (F49), and the live chips of
linked outside objects (F58).

Services: the worker's agos_service tool starts a Hermes background process and
AGOS records it (card, port, pid); the card lists it (running / answering), the
preview target is only a running service of that card, Stop ends the very process
(never a reused pid), and one workspace never sees or stops another's.
Chips: GitHub / Linear / Jira links resolve with the workspace's own keys, kept
briefly; unknown links stay links.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import Any

from test_automations import MODEL, env  # noqa: F401 - fixture

from agos_core.actions import card_services, external_objects, hermes_channel, tool_keys
from agos_core.hermes_plugin.agos_guard import services as guard_services


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _tool(client: Any, core: Any, ws: str, **body: Any) -> dict[str, Any]:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/service",
        json={"card": "t_1", **body},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _serve(port: int) -> subprocess.Popen[bytes]:
    proc = subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return proc
        time.sleep(0.05)
    proc.kill()
    raise AssertionError("the test server never answered")


def test_a_cards_service_is_listed_previewed_and_stopped(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    port = _free_port()
    proc = _serve(port)
    try:
        started = _tool(
            client,
            core,
            ws,
            action="started",
            profile="default",
            processId="proc_abc",
            pid=proc.pid,
            command="python -m http.server",
            port=port,
            label="site",
        )
        assert started["ok"] and started["preview"] == f"/preview/{ws}/t_1/{port}/"
        listed = client.get(f"/workspaces/{ws}/kanban/t_1/services").json()
        assert len(listed) == 1
        one = listed[0]
        assert (one["running"], one["answering"], one["label"]) == (True, True, "site")
        assert one["processId"] == "proc_abc" and one["preview"] == started["preview"]
        target = client.get(
            f"/workspaces/{ws}/preview-target", params={"card": "t_1", "port": port}
        )
        assert target.json() == {"host": "127.0.0.1", "port": port}
        # The agent's own list says the same.
        assert _tool(client, core, ws, action="list")["services"][0]["running"] is True
        # Another workspace sees nothing of it and can't stop it.
        other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()[
            "id"
        ]
        assert client.get(f"/workspaces/{other}/kanban/t_1/services").json() == []
        assert client.post(f"/workspaces/{other}/services/{one['id']}/stop").status_code == 404
        gone = client.get(
            f"/workspaces/{other}/preview-target", params={"card": "t_1", "port": port}
        )
        assert gone.status_code == 404
        stopped = client.post(f"/workspaces/{ws}/services/{one['id']}/stop").json()
        assert stopped["running"] is False and stopped["stoppedAt"]
        proc.wait(timeout=10)
        after = client.get(f"/workspaces/{ws}/preview-target", params={"card": "t_1", "port": port})
        assert after.status_code == 404
    finally:
        if proc.poll() is None:
            proc.kill()


def test_a_dead_or_reused_pid_is_never_running(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    port = _free_port()
    _tool(
        client,
        core,
        ws,
        action="started",
        profile="default",
        pid=os.getpid(),
        port=port,
        command="x",
    )
    row = core.db.execute("SELECT id FROM card_services WHERE workspace_id = ?", (ws,)).fetchone()
    # The same pid number now belongs to another process (its start time differs).
    core.db.execute("UPDATE card_services SET started_mark = 1 WHERE id = ?", (row["id"],))
    listed = client.get(f"/workspaces/{ws}/kanban/t_1/services").json()
    assert listed[0]["running"] is False and listed[0]["stoppedAt"]
    # Stop on it signals nothing (this test process is alive after it).
    client.post(f"/workspaces/{ws}/services/{row['id']}/stop")
    assert card_services._start_mark(os.getpid()) is not None


def test_the_tool_report_is_checked(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    assert "error" in _tool(client, core, ws, action="started", profile="default", port=80)
    refused = _tool(client, core, ws, action="started", profile="../other", port=5000, command="x")
    assert "not this workspace" in refused["error"]
    for n in range(card_services.MAX_RUNNING):
        _tool(client, core, ws, action="started", profile="default", port=5100 + n, command="x")
    full = _tool(client, core, ws, action="started", profile="default", port=5200, command="x")
    assert "already runs" in full["error"]


def test_the_guard_tool_starts_hermess_background_process() -> None:
    calls: list[dict[str, Any]] = []
    posted: list[tuple[str, dict[str, Any]]] = []

    def terminal(**kwargs: Any) -> str:
        calls.append(kwargs)
        return json.dumps(
            {"output": "Background process started", "session_id": "proc_1", "pid": 42}
        )

    def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        posted.append((path, body))
        if body.get("action") == "list":
            return {"services": [{"port": 5173, "processId": "proc_1", "running": True}]}
        return {"ok": True, "preview": "/preview/ws1/t_7/5173/"}

    import contextlib

    def guard(name: str) -> Any:
        return contextlib.suppress(Exception)

    args = {"action": "start", "command": "npm run dev", "port": 5173, "label": "web"}
    no_card = guard_services.service_tool(
        args, card="", profile="a-dev", workspace="ws1", task_id="s", post=post, guard=guard
    )
    assert "error" in json.loads(no_card)
    out = json.loads(
        guard_services.service_tool(
            args,
            card="t_7",
            profile="a-dev",
            workspace="ws1",
            task_id="sess",
            post=post,
            guard=guard,
            terminal=terminal,
        )
    )
    assert out["preview"] == "/preview/ws1/t_7/5173/" and out["processId"] == "proc_1"
    assert calls[0]["background"] is True and calls[0]["persist_on_release"] is True
    assert calls[0]["command"].startswith(
        "export PORT=5173 AGOS_PREVIEW_BASE=/preview/ws1/t_7/5173/;"
    )
    assert calls[0]["command"].endswith("npm run dev")
    started = posted[0][1]
    assert (started["action"], started["pid"], started["port"], started["profile"]) == (
        "started",
        42,
        5173,
        "a-dev",
    )
    stop = json.loads(
        guard_services.service_tool(
            {"action": "stop", "port": 5173},
            card="t_7",
            profile="a-dev",
            workspace="ws1",
            task_id="sess",
            post=post,
            guard=guard,
        )
    )
    assert stop == {"ok": True, "stopped": 1}
    assert posted[-1] == ("service", {"action": "stopped", "card": "t_7", "processId": "proc_1"})


# ---- external object chips ----------------------------------------------------------------


def test_links_become_live_chips_with_the_workspaces_own_keys(env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _core, _cron, ws = env
    external_objects._cache.clear()
    asked: list[tuple[str, str, dict[str, str]]] = []

    def fake(method: str, url: str, headers: dict[str, str], body: Any = None) -> tuple[int, Any]:
        asked.append((method, url, headers))
        if "pulls/12" in url:
            return 200, {"title": "Fix login", "state": "closed", "merged_at": "2026-10-01"}
        if "issues/3" in url:
            return 200, {"title": "Crash", "state": "open"}
        if "linear" in url:
            issue = {
                "identifier": "ENG-7",
                "title": "Ship it",
                "state": {"name": "In Progress", "type": "started"},
            }
            return 200, {"data": {"issue": issue}}
        if "atlassian" in url:
            fields = {
                "summary": "Billing",
                "status": {"name": "Done", "statusCategory": {"key": "done"}},
            }
            return 200, {"fields": fields}
        return 404, None

    monkeypatch.setattr(external_objects, "_get_json", fake)
    keys = {
        "TOOLS_GITHUB_TOKEN": "ghp_x",
        "LINEAR_API_KEY": "lin_x",
        "JIRA_EMAIL": "a@b.c",
        "JIRA_API_TOKEN": "j",
    }
    monkeypatch.setattr(tool_keys, "root_values", lambda core, w: keys if w == ws else {})
    urls = [
        "https://github.com/acme/app/pull/12",
        "https://github.com/acme/app/issues/3",
        "https://linear.app/acme/issue/ENG-7/ship-it",
        "https://acme.atlassian.net/browse/BIL-4",
        "https://example.com/not-a-ticket",
    ]
    r = client.post(f"/workspaces/{ws}/external-objects", json={"urls": urls})
    assert r.status_code == 200, r.text
    chips = {c["url"]: c for c in r.json()}
    assert "https://example.com/not-a-ticket" not in chips  # stays a plain link
    pr = chips[urls[0]]
    assert (pr["kind"], pr["state"], pr["done"], pr["key"]) == (
        "github_pr",
        "merged",
        True,
        "acme/app#12",
    )
    assert chips[urls[1]]["state"] == "open" and chips[urls[1]]["kind"] == "github_issue"
    assert chips[urls[2]]["stateLabel"] == "In Progress" and chips[urls[2]]["key"] == "ENG-7"
    assert chips[urls[3]]["state"] == "done" and chips[urls[3]]["title"] == "Billing"
    gh = [h for _m, u, h in asked if "github" in u]
    assert gh and all(h["Authorization"] == "Bearer ghp_x" for h in gh)
    assert next(h for _m, u, h in asked if "linear" in u)["Authorization"] == "lin_x"
    # Kept a short while: the same links again ask nothing.
    before = len(asked)
    client.post(f"/workspaces/{ws}/external-objects", json={"urls": urls})
    assert len(asked) == before
    # Another workspace has no keys: Linear says so, GitHub goes anonymous.
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": MODEL}).json()["id"]
    theirs = {
        c["url"]: c
        for c in client.post(f"/workspaces/{other}/external-objects", json={"urls": urls}).json()
    }
    assert theirs[urls[2]] == {**theirs[urls[2]], "ok": False, "why": "no_key"}
    assert "Authorization" not in next(h for _m, u, h in asked[before:] if "github" in u)


def test_a_private_or_unreached_object_is_a_plain_chip(monkeypatch: Any) -> None:
    external_objects._cache.clear()
    monkeypatch.setattr(external_objects, "_get_json", lambda *a, **k: (404, None))
    shown = external_objects._resolve_one("https://github.com/a/b/pull/1", dict)
    assert shown is not None and shown["ok"] is False and shown["why"] == "private"
    assert external_objects.kind_of("https://github.com/a/b/tree/main") is None
    assert external_objects.kind_of("https://evil.com/https://github.com/a/b/pull/1") is None
