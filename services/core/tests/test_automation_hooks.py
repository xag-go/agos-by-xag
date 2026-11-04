"""Automations that start the moment something happens outside (webhooks).

An outside app (a project board, a Google Sheet, Zapier...) posts to the automation's address:
a route of the workspace's Hermes (its webhook platform), which checks the
signature, the events, the delivery id and on/off, and runs the route's script:
the script puts the automation's run on the Kanban itself, with the delivery as
data. Deliveries that arrive while a run is going wait and go to the next run
together; nothing is lost, nothing runs twice. AGOS isn't called.
"""

import hashlib
import hmac
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from test_automation_team import MONDAY_STEPS, create, steps_on_board, team
from work_env import MODEL, Env, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core import hook_relay
from agos_core.actions import hooks

team = team  # the team fixture (researcher + ideas)

SECRET = "whsec_0123456789abcdef0123"  # noqa: S105 (test value)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def hook_on(client: Any, ws: str, aid: int, **extra: Any) -> dict[str, Any]:
    r = client.post(f"/workspaces/{ws}/automations/{aid}/hook", json={"on": True, **extra})
    assert r.status_code == 200, r.text
    return dict(r.json())


class Answer:
    def __init__(self, status: int, data: dict[str, Any]) -> None:
        self.status_code, self._data = status, data

    def json(self) -> dict[str, Any]:
        return self._data


def hermes_route(core: Any, ws: str, path: str) -> dict[str, Any] | None:
    file = core.engine.profile_home(ws) / hooks.SUBSCRIPTIONS
    routes = json.loads(file.read_text()) if file.exists() else {}
    return routes.get(path.removeprefix("/webhooks/"))


def _matches(spec: dict[str, Any], payload: Any) -> bool:
    """Hermes's route filters (gateway/platforms/webhook_filters.py: all / any / not,
    then in / equals / not_equals / contains on a dotted field)."""
    if "all" in spec:
        return all(_matches(s, payload) for s in spec["all"])
    if "any" in spec:
        return any(_matches(s, payload) for s in spec["any"])
    if "not" in spec:
        return not _matches(spec["not"], payload)
    root = payload.get("payload", payload) if isinstance(payload, dict) else {}
    field = spec["field"]
    if field == "event":
        value: Any = payload.get("event_type") or payload.get("type") or "unknown"
    else:
        value = root
        for part in field.removeprefix("payload.").split("."):
            value = value.get(part) if isinstance(value, dict) else None
    if "in" in spec:
        return value in spec["in"]
    if "not_equals" in spec:
        return bool(value != spec["not_equals"])
    if "equals" in spec:
        return bool(value == spec["equals"])
    return isinstance(value, str) and str(spec["contains"]) in value


def deliver(
    client: Any,
    path: str,
    payload: dict[str, Any] | bytes,
    delivery: str = "",
    secret: str | None = SECRET,
) -> Any:
    """What Hermes's webhook platform does with a delivery to the route (its
    order): checks the signature (unless the address alone is the check), on/off
    and the events, then runs the route's script with the payload on stdin (the
    script makes the cards; it prints [SILENT], so Hermes does nothing more). Its
    delivery-id check comes after the script, so it never sees these: the script
    drops a retry itself."""
    import hermes_script

    core = client.app.state.core
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    aid_in_path = path.removeprefix("/webhooks/agos-").split("-", 1)[0]
    found = core.db.execute(
        "SELECT workspace_id FROM automations WHERE id = ?", (int(aid_in_path),)
    ).fetchone()
    ws = str(found["workspace_id"]) if found else ""
    route = hermes_route(core, ws, path) if ws else None
    if route is None:
        return Answer(404, {"error": "Unknown route"})
    if route["secret"] != hooks.INSECURE and (
        not secret or not hmac.compare_digest(sign(body, secret), sign(body, route["secret"]))
    ):
        return Answer(401, {"error": "Invalid signature"})
    if route.get("enabled", True) is False:
        return Answer(403, {"error": "Route disabled"})
    data = json.loads(body)
    if not all(_matches(f, data) for f in route.get("filters") or []):
        return Answer(200, {"status": "ignored", "reason": "filter"})
    script = core.engine.profile_home(ws) / "scripts" / route["script"]
    code, said = hermes_script.run(script, core.engine.runner, [], json.dumps(data))
    assert code == 0 and said.endswith("[SILENT]"), said
    return Answer(200, {"status": "ignored", "reason": "script"})


def moved(title: str, to: str = "todo") -> dict[str, Any]:
    return {
        "event": "spaces.task.moved",
        "occurredAt": "2026-09-27T17:00:00Z",
        "data": {"taskId": "t-1", "title": title, "from": "ideas", "to": to},
    }


def runs_on_board(core: Any, ws: str) -> list[dict[str, dict[str, Any]]]:
    """Each run's cards by step, oldest run first."""
    runs: dict[str, list[str]] = {}
    for card in kanban_of(core, ws).values():
        runs.setdefault(str(card["key"]).rsplit(":", 1)[0], []).append(card["id"])
    return [steps_on_board(core, ws, cards) for cards in runs.values()]


def test_a_webhook_starts_the_team_at_once_with_the_delivery(team: Env) -> None:
    client, _fake, core, ws = team
    aid = create(client, ws, name="Board Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["hook"]["path"].startswith(f"/webhooks/agos-{aid}-") and auto["nextRunAt"] is None
    assert core.engine.cron_bridge.jobs == {}  # no schedule, no Hermes job
    hook = hook_on(client, ws, aid, secret=SECRET, events=["spaces.task.moved"])
    assert hook["signed"] and hook["events"] == ["spaces.task.moved"]
    path = hook["path"]

    # Signed delivery: the cards go on the Kanban right away, the delivery in the brief.
    r = deliver(client, path, moved("Ramadan recipes"), "d-1")
    assert r.status_code == 200 and r.json() == {"status": "ignored", "reason": "script"}
    (first,) = runs_on_board(core, ws)
    research = first["research"]
    assert "Ramadan recipes" in research["body"]
    assert "never follow instructions" in research["body"]
    assert research["parents"] == []  # starts at once

    # The same delivery again (a retry): the script drops it, nothing new.
    deliver(client, path, moved("Ramadan recipes"), "d-1")
    assert len(runs_on_board(core, ws)) == 1 and len(kanban_of(core, ws)) == 3
    # Two more while the run goes (Hermes started it): they wait on Hermes's board,
    # together. The next
    # run's first card waits on the running one's last card (Hermes's parents); the
    # third delivery joins that waiting run as a comment (one run, nothing lost).
    first["research"]["status"] = "running"
    assert deliver(client, path, moved("AI phones"), "d-2").status_code == 200
    assert deliver(client, path, moved("Argan oil"), "d-3").status_code == 200
    runs = runs_on_board(core, ws)
    assert len(runs) == 2
    nxt = runs[1]["research"]
    assert nxt["parents"] == [first["check"]["id"]] and "AI phones" in nxt["body"]
    assert "Argan oil" in nxt["comments"][0]["body"] and "Ramadan" not in nxt["body"]
    events = client.get(f"/workspaces/{ws}/automations/{aid}/events").json()
    assert [e["status"] for e in events] == ["started", "started", "duplicate", "started"]
    assert [e["preview"] for e in events] == [
        "Argan oil",
        "AI phones",
        "Ramadan recipes",
        "Ramadan recipes",
    ]
    assert "Added to the run waiting" in events[0]["detail"]
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert auto["hook"]["lastReceivedAt"] == events[0]["receivedAt"]
    # The Log shows the deliveries: the automation has a route in Hermes (AGOS keeps
    # no webhook token of its own).
    logged = [
        e for e in client.get(f"/workspaces/{ws}/log").json()["entries"] if e["area"] == "webhook"
    ]
    assert len(logged) == 4 and all("Board Watcher" in e["where"] for e in logged)
    assert {e["text"] for e in logged} == {
        "Webhook received, the run started",
        "Webhook received twice, ignored",
    }

    # An event this automation doesn't start on: Hermes's route filter drops it.
    other = {"event": "spaces.task.comment.created", "data": {"title": "x"}}
    assert deliver(client, path, other, "d-4").json() == {"status": "ignored", "reason": "filter"}

    # The run ends: Hermes starts the waiting run by itself; AGOS has nothing to do.
    for key, said in (("research", "Researched."), ("ideas", "x"), ("check", "scripts/001.md ok")):
        first[key]["status"], first[key]["result"] = "done", said
    assert len(runs_on_board(core, ws)) == 2
    [run] = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    assert run["source"] == "webhook" and "scripts/001.md" in run["report"]


def test_a_bad_address_or_signature_is_refused_and_nothing_runs(team: Env) -> None:
    client, _, core, ws = team
    aid = create(client, ws, name="Watcher", steps=MONDAY_STEPS, hook=True)
    path = hook_on(client, ws, aid, secret=SECRET)["path"]
    assert deliver(client, "/webhooks/agos-1-" + "0" * 24, moved("a"), "d-1").status_code == 404
    assert (
        deliver(client, path, moved("a"), "d-2", secret="whsec_wrong_secret_value_000").status_code
        == 401
    )
    assert deliver(client, path, moved("a"), "d-3", secret=None).status_code == 401
    assert kanban_of(core, ws) == {}  # Hermes refused them: nothing reached AGOS
    # The owner's API still needs the internal token.
    assert (
        client.get(f"/workspaces/{ws}/automations", headers={"x-agos-internal": ""}).status_code
        == 401
    )
    # A new address: the old one stops working at once.
    new = hook_on(client, ws, aid, new_address=True)["path"]
    assert new != path
    assert deliver(client, path, moved("a"), "d-5").status_code == 404
    assert deliver(client, new, moved("a"), "d-6").status_code == 200
    assert len(kanban_of(core, ws)) == 3


def test_no_secret_off_automation_and_one_agent_hooks(team: Env) -> None:
    client, _, core, ws = team
    # Without a signing secret (his explicit choice) the secret address alone is the check.
    aid = create(client, ws, name="Sheet row", agent="ideas", hook=True)
    path = hook_on(client, ws, aid, secret="")["path"]
    route = hermes_route(core, ws, path)
    assert route is not None and route["secret"] == hooks.INSECURE  # loopback only
    r = deliver(client, path, b'{"row": 5, "link": "https://youtu.be/x"}', secret=None)
    assert r.status_code == 200
    # A one-agent automation runs on the Kanban as one card for that agent.
    ((step,),) = [list(run.values()) for run in runs_on_board(core, ws)]
    assert step["assignee"] == "a-ideas"
    assert "https://youtu.be/x" in step["body"]
    # Its scheduled runs still go through Hermes cron.
    assert len(core.engine.cron_bridge.jobs) == 1

    # Off: Hermes refuses the deliveries (its route is disabled), nothing starts.
    step["status"] = "done"
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    assert deliver(client, path, b'{"row": 6}', secret=None).status_code == 403
    assert len(kanban_of(core, ws)) == 1
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": True})
    assert (hermes_route(core, ws, path) or {})["enabled"] is True

    # Neither a schedule nor a webhook: refused.
    r = client.post(
        f"/workspaces/{ws}/automations",
        json={"name": "Never", "instructions": "x", "schedule": "", "model": MODEL},
    )
    assert r.status_code == 400 and "schedule" in r.text
    # A webhook-only automation can't lose its webhook.
    wid = create(client, ws, name="Only hook", schedule="", steps=MONDAY_STEPS, hook=True)
    off = client.post(f"/workspaces/{ws}/automations/{wid}/hook", json={"on": False})
    assert off.status_code == 400


def test_public_address_setting(team: Env) -> None:
    client = team[0]
    assert client.get("/settings/hooks").json() == {"publicUrl": ""}
    assert client.put("/settings/hooks", json={"publicUrl": "http://x.dev"}).status_code == 400
    r = client.put("/settings/hooks", json={"publicUrl": "https://hooks.example.dev/"})
    assert r.json() == {"publicUrl": "https://hooks.example.dev"}


@pytest.fixture
def relay(tmp_path: Any, monkeypatch: Any) -> Any:
    """The relay in front of a stand-in Hermes that records what reaches it."""
    seen: list[tuple[str, str, bytes, dict[str, str]]] = []

    from http.server import BaseHTTPRequestHandler

    class Hermes(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.append(("POST", self.path, body, dict(self.headers)))
            self.send_response(202)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def do_GET(self) -> None:
            seen.append(("GET", self.path, b"", {}))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    hermes = ThreadingHTTPServer(("127.0.0.1", 0), Hermes)
    (tmp_path / "system").mkdir()
    (tmp_path / "system" / "hook-routes.json").write_text(
        json.dumps({ROUTE: hermes.server_address[1]})
    )
    monkeypatch.setattr(hook_relay, "DATA", str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), hook_relay.Relay)
    hook_relay.Relay.log_message = lambda *_: None  # type: ignore[method-assign]
    for s in (hermes, server):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()
    hermes.shutdown()


ROUTE = "agos-2-" + "a" * 24


def _post(
    url: str, body: bytes = b"{}", method: str = "POST", headers: dict[str, str] | None = None
) -> int:
    request = urllib.request.Request(  # noqa: S310
        url, data=body if method == "POST" else None, method=method, headers=headers or {}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as reply:  # noqa: S310
            return int(reply.status)
    except urllib.error.HTTPError as error:
        return int(error.code)
    except urllib.error.URLError:
        return 0  # the relay hung up before reading it all (a body too big)


def test_the_relay_passes_only_webhook_posts_to_the_routes_hermes(relay: Any) -> None:
    base, seen = relay
    signed = {
        "X-AGOS-Signature": "ABC",
        "X-AGOS-Delivery": "d-1",
        "Cookie": "session=x",
        "X-AGOS-Internal": "stolen",
    }
    assert _post(f"{base}/webhooks/{ROUTE}", b'{"a":1}', headers=signed) == 202
    assert _post(f"{base}/webhooks/{ROUTE}", method="GET") == 404
    unknown = "/webhooks/agos-3-" + "b" * 24
    for path in ("/workspaces", "/settings/hooks", unknown, "/webhooks/../workspaces", "/"):
        assert _post(base + path) == 404, path
    assert _post(f"{base}/webhooks/{ROUTE}", b"x" * (600 * 1024)) in (413, 0)
    assert len(seen) == 1
    method, path, body, headers = seen[0]
    lowered = {k.lower(): v for k, v in headers.items()}
    assert (method, path, body) == ("POST", f"/webhooks/{ROUTE}", b'{"a":1}')
    # Signed as Hermes reads it (GitHub style); the delivery id kept for its retries.
    assert lowered["x-hub-signature-256"] == "sha256=abc" and lowered["x-request-id"] == "d-1"
    # Cookies and the internal token never pass.
    assert "cookie" not in lowered and "x-agos-internal" not in lowered
    # AGOS's own signature AND Standard Webhooks style: Hermes checks the body one.
    both = {"X-AGOS-Signature": "sha256=AB", "webhook-id": "m1", "webhook-signature": "v1,x"}
    assert _post(f"{base}/webhooks/{ROUTE}", b"{}", headers=both) == 202
    last = {k.lower(): v for k, v in seen[-1][3].items()}
    assert last["x-hub-signature-256"] == "sha256=ab" and "webhook-signature" not in last
    # Only AGOS's own names are renamed: other apps' names pass as they are or not at all.
    other = {"X-Signature": "sha256=EF", "X-Event-Type": "x", "X-Delivery": "d-2"}
    assert _post(f"{base}/webhooks/{ROUTE}", b"{}", headers=other) == 202
    last = {k.lower(): v for k, v in seen[-1][3].items()}
    assert not {"x-hub-signature-256", "x-github-event", "x-request-id"} & set(last)
    # The legacy x-xag-* header names (from before the rename).
    old = {"X-XAG-Signature": "sha256=CD", "X-XAG-Delivery": "d-9"}
    assert _post(f"{base}/webhooks/{ROUTE}", b"{}", headers=old) == 202
    last = {k.lower(): v for k, v in seen[-1][3].items()}
    assert last["x-hub-signature-256"] == "sha256=cd" and last["x-request-id"] == "d-9"
    # The event's name, where Hermes reads it (its route filters on it).
    named = {"X-AGOS-Event": "spaces.task.moved"}
    assert _post(f"{base}/webhooks/{ROUTE}", b"{}", headers=named) == 202
    last = {k.lower(): v for k, v in seen[-1][3].items()}
    assert last["x-github-event"] == "spaces.task.moved"


def test_the_cofounder_makes_a_webhook_automation(team: Env) -> None:
    client, _, core, ws = team
    from test_cofounder_actions import _run

    from agos_core.actions import cofounder_actions

    assert '"webhook": true' in cofounder_actions.instructions(core, ws)
    [card] = _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Inspiration Watcher",
            "schedule": "",
            "webhook": True,
            "instructions": "A new row in the Inspiration sheet: transcribe and note it.",
            "agent": "ideas",
        },
    )
    assert card["status"] == "done" and "webhook" in card["title"], card
    [auto] = client.get(f"/workspaces/{ws}/automations").json()
    assert auto["hook"] and auto["schedule"] == "" and auto["agent"] == "ideas"
    # Undo removes it.
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code in (200, 204), r.text
    assert client.get(f"/workspaces/{ws}/automations").json() == []


def test_one_place_for_all_and_check_first_waits_for_the_owner(team: Env) -> None:
    client, _, core, ws = team
    create(client, ws, name="Monday", steps=MONDAY_STEPS)
    event = create(client, ws, name="Board", schedule="0 9 * * 1", steps=MONDAY_STEPS, hook=True)
    # Schedule and webhook live together in one automation, in one list.
    ev = client.get(f"/workspaces/{ws}/automations/{event}").json()
    assert ev["schedule"] == "0 9 * * 1" and ev["hook"]
    assert len(client.get(f"/workspaces/{ws}/automations").json()) == 2

    # By default an event runs by itself: its first steps start at once (unsigned here).
    path = hook_on(client, ws, event, secret="")["path"]
    deliver(client, path, b'{"title": "a"}', secret=None)
    (first,) = runs_on_board(core, ws)
    assert first["research"]["parents"] == [] and "owner-ok" not in first
    for card in kanban_of(core, ws).values():
        card["status"] = "done"

    # "Check with me first": nothing starts before the owner's OK (his card, Done).
    body = client.get(f"/workspaces/{ws}/automations/{event}").json()
    body.update(checkFirst=True)
    body = {
        k: body[k]
        for k in ("name", "instructions", "schedule", "model", "on", "agent", "steps", "checkFirst")
    }
    assert client.put(f"/workspaces/{ws}/automations/{event}", json=body).status_code == 200
    deliver(client, path, b'{"title": "b"}', secret=None)
    run = runs_on_board(core, ws)[-1]
    ok = run["owner-ok"]
    assert ok["assignee"] is None and ok["status"] == "todo"
    assert run["research"]["parents"] == [ok["id"]]
    assert "check" not in [k for k, c in run.items() if ok["id"] in c["parents"]]


def test_the_run_script_reads_hermess_board(tmp_path: Any) -> None:
    """The script's own read of the board (Hermes's kanban.db, read only)."""
    import sqlite3

    from agos_core.engine import cron

    board = tmp_path / "kanban.db"
    with sqlite3.connect(board) as db:
        db.executescript(
            """CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, status TEXT,
                 idempotency_key TEXT, created_at INTEGER);
               CREATE TABLE task_links (parent_id TEXT, child_id TEXT);"""
        )
        key = "agos-automation:4:20261001T100000000000Z:webhook:"
        db.executemany(
            "INSERT INTO tasks VALUES (?, 't', ?, ?, 1)",
            [("t1", "running", key + "a"), ("t2", "todo", key + "b"), ("t9", "todo", "other")],
        )
        db.execute("INSERT INTO task_links VALUES ('t1', 't2')")
    plan = {"automation": 4, "board": str(board), "mode": "cron"}
    script = tmp_path / "s.py"
    script.write_text(cron.run_script_text(plan))
    namespace: dict[str, Any] = {"__name__": "x"}
    exec(compile(script.read_text(), str(script), "exec"), namespace)  # noqa: S102
    (run,) = namespace["runs"]()
    assert sorted(run["cards"]) == ["a", "b"]
    assert namespace["first_cards"](run) == ["t1"] and namespace["last_cards"](run) == ["t2"]
    assert namespace["going"](run) == ["t1", "t2"] and namespace["begun"](run)
    # Still going: the schedule doesn't start another run (and says so).
    assert namespace["main"]([]) == 0
    assert namespace["main"](["manual"]) == namespace["STILL_GOING"]


def test_the_background_loops_run_a_whole_round_with_webhook_automations(
    team: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Every step of AGOS's background loops runs (one failing step stopped all the
    later ones: a webhook automation broke the automation loop live)."""
    import asyncio
    import logging

    from agos_core.actions import automations, channels, idle

    client, _fake, core, ws = team
    aid = create(client, ws, name="Board Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    hook_on(client, ws, aid, secret=SECRET, events=["spaces.task.moved"])
    create(client, ws, name="Monday ideas")

    class Round(Exception):
        pass

    async def one_round(_seconds: float) -> None:
        raise Round

    async def one_bell(_self: object, _timeout: float) -> bool:
        raise Round

    from agos_core.engine import doorbell

    monkeypatch.setattr(asyncio, "sleep", one_round)
    # The send loop waits on its doorbell, not asyncio.sleep: else the test hangs.
    monkeypatch.setattr(doorbell.Wait, "wait", one_bell)
    caplog.set_level(logging.ERROR)
    for loop in (automations.run_forever, channels.run_forever):
        with pytest.raises(Round):
            asyncio.run(loop(core))
    idle.chores(core)  # the idle round is a job now (agos_core/background/schedule.py)
    failed = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert failed == [], failed


def test_the_webhook_is_hermess_route_and_agos_keeps_no_copy(team: Env) -> None:
    client, _, core, ws = team
    file = core.engine.profile_home(ws) / hooks.SUBSCRIPTIONS
    file.write_text(json.dumps({"github-pr": {"secret": SECRET, "prompt": "x"}}))
    aid = create(client, ws, name="Watcher", schedule="", steps=MONDAY_STEPS, hook=True)
    hook = hook_on(client, ws, aid, secret=SECRET, events=["spaces.task.moved"])
    columns = [str(r[1]) for r in core.db.execute("PRAGMA table_info(automations)")]
    assert not [c for c in columns if c.startswith("hook")]  # AGOS has no column for it
    routes = json.loads(file.read_text())
    assert routes["github-pr"] == {"secret": SECRET, "prompt": "x"}  # not AGOS's: left alone
    # Changed in Hermes (its dashboard, its CLI): AGOS shows Hermes's.
    name = hook["path"].removeprefix("/webhooks/")
    routes[name]["enabled"] = False
    routes[name]["filters"][0]["any"][0]["in"] = ["row.added"]
    routes[name]["secret"] = hooks.INSECURE
    file.write_text(json.dumps(routes))
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["on"] is False and got["hook"]["events"] == ["row.added"]
    assert got["hook"]["signed"] is False
    assert [a["id"] for a in client.get(f"/workspaces/{ws}/automations?kind=event").json()] == [aid]
    assert client.get(f"/workspaces/{ws}/automations?kind=schedule").json() == []
    # Its name lives once: in its Hermes route's description, not in AGOS's row.
    assert routes[name]["description"] == "AGOS automation: Watcher"
    assert core.db.execute("SELECT name FROM automations WHERE id = ?", (aid,)).fetchone()[0] == ""
    assert got["name"] == "Watcher"
    routes[name]["description"] = "AGOS automation: Watcher 2"  # renamed in Hermes
    file.write_text(json.dumps(routes))
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["name"] == "Watcher 2"
    # An old copy goes once its route holds it.
    core.db.execute("UPDATE automations SET name = 'Watcher 2' WHERE id = ?", (aid,))
    assert hooks.move_names(core) == 1 and hooks.move_names(core) == 0
    # The relay's map follows Hermes's routes.
    relay = json.loads((core.layout.system / hooks.ROUTES_FILE).read_text())
    assert list(relay) == [name]
    # Deleted: its route goes from Hermes, the others stay.
    assert client.delete(f"/workspaces/{ws}/automations/{aid}").status_code == 200
    assert list(json.loads(file.read_text())) == ["github-pr"]
    assert json.loads((core.layout.system / hooks.ROUTES_FILE).read_text()) == {}


def _signed_samples(secret: str, body: bytes) -> dict[str, dict[str, str]]:
    """One real signed delivery per scheme Hermes checks itself."""
    import base64
    import hashlib
    import hmac
    import time

    def hexmac(data: bytes) -> str:
        return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()

    now = str(int(time.time()))
    svix = base64.b64encode(
        hmac.new(secret.encode(), f"msg_1.{now}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return {
        "svix": {"svix-id": "msg_1", "svix-timestamp": now, "svix-signature": f"v1,{svix}"},
        "standard": {
            "webhook-id": "msg_1",
            "webhook-timestamp": now,
            "webhook-signature": f"v1,{svix}",
        },
        "linear": {"Linear-Signature": hexmac(body)},
        "gitlab": {"X-Gitlab-Token": secret, "X-GitLab-Event": "Push Hook"},
        "github": {"X-Hub-Signature-256": "sha256=" + hexmac(body), "X-GitHub-Delivery": "g-1"},
        "v2": {
            "X-Webhook-Signature-V2": hexmac(now.encode() + b"." + body),
            "X-Webhook-Timestamp": now,
        },
        "agos": {"X-AGOS-Signature": "sha256=" + hexmac(body), "X-AGOS-Delivery": "a-1"},
        "xag": {"X-XAG-Signature": hexmac(body).upper(), "X-XAG-Event": "e2e.ping"},
    }


_HERMES_CHECK = r"""
import json, sys, types
from multidict import CIMultiDict
from gateway.platforms.webhook import WebhookAdapter
given = json.loads(sys.stdin.read())
out = {}
for name, (headers, body) in given["cases"].items():
    request = types.SimpleNamespace(headers=CIMultiDict(headers), match_info={"route_name": "r"})
    me = types.SimpleNamespace(_v1_signature_warned=set())
    out[name] = WebhookAdapter._validate_signature(me, request, body.encode(), given["secret"])
print("AGOS-JSON " + json.dumps(out))
"""


def test_signed_deliveries_pass_the_relay_and_hermess_own_check(relay: Any) -> None:
    """Svix, Standard Webhooks, Linear, GitLab token, GitHub and generic V2 senders
    reach Hermes with their headers as sent, and Hermes's own validator
    (gateway/platforms/webhook.py _validate_signature) takes each; a wrong secret
    is refused there."""
    import subprocess

    from test_cron_schedule import _bridge

    base, seen = relay
    secret, body = "s3cret-for-the-relay-test", b'{"type":"e2e.ping","n":1}'
    samples = _signed_samples(secret, body)
    forwarded: dict[str, list[Any]] = {}
    for name, headers in samples.items():
        assert _post(f"{base}/webhooks/{ROUTE}", body, headers=headers) == 202, name
        forwarded[name] = [dict(seen[-1][3]), seen[-1][2].decode()]
    lowered = {n: {k.lower() for k in h} for n, (h, _) in forwarded.items()}
    assert {"svix-id", "svix-timestamp", "svix-signature"} <= lowered["svix"]
    assert "linear-signature" in lowered["linear"]
    assert {"x-gitlab-token", "x-gitlab-event"} <= lowered["gitlab"]
    assert {"x-webhook-signature-v2", "x-webhook-timestamp"} <= lowered["v2"]
    assert "x-github-delivery" in lowered["github"]
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        found = _bridge(Path(tmp))
        if found is None:
            pytest.skip("no Hermes install on this machine")
        bridge, _home = found

        def hermes_says(key: str) -> dict[str, bool]:
            done = subprocess.run(  # noqa: S603 - fixed argv
                [bridge.python, "-c", _HERMES_CHECK],
                input=json.dumps({"cases": forwarded, "secret": key}),
                capture_output=True,
                text=True,
                timeout=120,
                env={**bridge.engine.runtime_env(), "HERMES_HOME": tmp, "PATH": "/usr/bin:/bin"},
                cwd=str(Path(bridge.python).parent.parent.parent),
                check=False,
            )
            line = [x for x in done.stdout.splitlines() if x.startswith("AGOS-JSON ")]
            assert line, done.stderr[-2000:]
            return dict(json.loads(line[-1][len("AGOS-JSON ") :]))

        assert hermes_says(secret) == dict.fromkeys(samples, True)
        assert hermes_says("another-secret") == dict.fromkeys(samples, False)
