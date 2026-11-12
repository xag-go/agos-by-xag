"""The workspace Log: everything that happened, and every problem with its cause."""

import logging

import channels_rig
import test_api
from fastapi.testclient import TestClient

from agos_core.actions.system_log import redact
from agos_core.db.activity import add_activity

client = test_api.client  # the API tests' fixture
env, fake_telegram = channels_rig.env, channels_rig.fake_telegram  # with an engine


def core_of(client: TestClient):  # type: ignore[no-untyped-def]
    return client.app.state.core  # type: ignore[attr-defined]


def test_log_shows_actions_problems_and_causes(client: TestClient) -> None:
    ws = test_api.create_workspace(client, "Argan Log")
    core = core_of(client)
    add_activity(core.db, ws, kind="folder.added", text="Folder added: Fix login")
    add_activity(
        core.db, ws, kind="automation.skipped", text="Brief: the tracker token was refused (401)."
    )
    # An error of AGOS itself, naming the workspace, with a secret in it.
    logging.getLogger("agos.channels").error(
        "channel of %s: sending failed with token=abcdef123456", ws
    )

    page = client.get(f"/workspaces/{ws}/log").json()
    texts = [(e["level"], e["area"], e["where"], e["text"]) for e in page["entries"]]
    assert ("info", "system", "folder.added", "Folder added: Fix login") in texts
    failed = next(e for e in page["entries"] if e["where"] == "automation.skipped")
    assert failed["level"] == "warn" and failed["area"] == "automation"
    system = next(e for e in page["entries"] if e["area"] == "system")
    assert system["level"] == "error" and system["where"] == "AGOS · channels"
    assert "abcdef123456" not in system["text"] and "[hidden]" in system["text"]

    # Only the problems.
    problems = client.get(f"/workspaces/{ws}/log", params={"level": "problems"}).json()
    assert all(e["level"] in ("warn", "error") for e in problems["entries"])
    assert {e["id"].split(":")[0] for e in problems["entries"]} >= {"activity", "system"}
    # Search.
    found = client.get(f"/workspaces/{ws}/log", params={"q": "401"}).json()["entries"]
    assert [e["where"] for e in found] == ["automation.skipped"]

    # Another workspace doesn't see this one's entries.
    other = test_api.create_workspace(client, "Other Log")
    assert all(
        "Fix login" not in e["text"]
        for e in client.get(f"/workspaces/{other}/log").json()["entries"]
    )


def test_redact_hides_secrets() -> None:
    text = redact(
        "bot123456789:AAabcdefghijklmnopqrstuvwxyz0123456 whsec_abc sk-abcdefghijklmnopqrst "
        "/hooks/abcdefghijklmnop password: hunter2hunter"
    )
    for secret in ("AAabcdef", "whsec_abc", "sk-abcdef", "abcdefghijklmnop", "hunter2"):
        assert secret not in text


def _hermes_side(core, ws: str) -> None:  # type: ignore[no-untyped-def]
    """What the workspace's Hermes keeps: its Kanban, its cron runs, its errors."""
    import json
    import sqlite3

    from agos_core.actions import agent_profiles

    board = agent_profiles.board_home(core, ws)
    board.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(board / "kanban.db")
    db.executescript(
        """CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT);
           CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, run_id INTEGER,
             kind TEXT, payload TEXT, created_at INTEGER);
           INSERT INTO tasks VALUES ('t_1', 'Write the brief');
           INSERT INTO task_events VALUES (1, 't_1', NULL, 'created', '{}', 1791500000);
           INSERT INTO task_events VALUES (2, 't_1', 1, 'heartbeat', '', 1791500010);
           INSERT INTO task_events VALUES (3, 't_1', 1, 'blocked',
             '{"reason": "needs the tracker key"}', 1791500020);
           INSERT INTO task_events VALUES (4, 't_1', 1, 'completed',
             '{"summary": "brief written"}', 1791500030);"""
    )
    db.commit()
    db.close()
    home = core.engine.profile_home(ws)
    (home / "cron").mkdir(parents=True, exist_ok=True)
    (home / "cron" / "jobs.json").write_text(
        json.dumps({"jobs": [{"id": "j1", "name": "Check the inbox"}]})
    )
    ex = sqlite3.connect(home / "cron" / "executions.db")
    ex.executescript(
        """CREATE TABLE executions (id TEXT PRIMARY KEY, job_id TEXT, status TEXT,
             started_at TEXT, finished_at TEXT, error TEXT);
           INSERT INTO executions VALUES ('e1', 'j1', 'failed', '2026-10-09T10:00:00+00:00',
             '2026-10-09T10:01:00+00:00', 'token=abcdef123456 refused');
           INSERT INTO executions VALUES ('e2', 'j1', 'completed', '2026-10-09T11:00:00+00:00',
             '2026-10-09T11:01:00+00:00', NULL);"""
    )
    ex.commit()
    ex.close()
    (home / "logs").mkdir(parents=True, exist_ok=True)
    (home / "logs" / "errors.log").write_text(
        "2026-10-09 12:00:00,100 WARNING agos.bridge: next failed: refused\n"
        "2026-10-09 12:00:01,200 ERROR tools.browser: could not start: No such file\n"
        "Traceback (most recent call last):\n"
    )


def test_log_reads_what_hermes_did(env) -> None:  # type: ignore[no-untyped-def]
    """The Kanban's events, the cron runs and Hermes's own errors come from the
    workspace's Hermes, not from a copy in AGOS; never another workspace's."""
    client, core, _fake, _tg, ws = env
    _hermes_side(core, ws)
    entries = client.get(f"/workspaces/{ws}/log").json()["entries"]
    got = {(e["area"], e["level"], e["where"], e["text"]) for e in entries}
    assert ("task", "info", "Card t_1 “Write the brief”", "Created") in got
    assert ("task", "warn", "Card t_1 “Write the brief”", "Blocked: needs the tracker key") in got
    assert ("task", "ok", "Card t_1 “Write the brief”", "Done: brief written") in got
    assert not any("heartbeat" in e["text"].lower() for e in entries)
    failed = next(e for e in entries if e["id"] == "cron:e1")
    assert failed["level"] == "error" and failed["where"] == "Scheduled job “Check the inbox”"
    assert "abcdef123456" not in failed["cause"]
    assert any(e["id"] == "cron:e2" and e["level"] == "ok" for e in entries)
    hermes = [e for e in entries if e["where"] == "Engine · tools.browser"]
    assert len(hermes) == 1 and hermes[0]["level"] == "error"
    assert hermes[0]["at"].startswith("2026-10-09T12:00:01")
    other = client.post(
        "/workspaces", json={"name": "Other Hermes", "defaultModel": channels_rig.MODEL}
    ).json()["id"]
    assert not any(
        e["id"].startswith(("kanban:", "cron:", "hermes:"))
        for e in client.get(f"/workspaces/{other}/log").json()["entries"]
    )


def test_log_reads_failed_answers_from_hermes_sessions(env) -> None:  # type: ignore[no-untyped-def]
    """A failed answer is Hermes's: its on_session_end hook's turn_exit_reason, kept
    on the chat's turn record (never read from agent.log). An answer and a stop
    are not problems."""
    from agos_core.actions import hermes_channel
    from agos_core.db import chats as repo

    client, core, _fake, _tg, ws = env
    chat = client.post(f"/workspaces/{ws}/chats", json={"title": "Invoices"}).json()["id"]

    def turn(reason: str) -> None:
        turn_id = repo.insert_turn(core.db, chat_id=chat, workspace_id=ws, asked_up_to=0)
        repo.set_turn(core.db, turn_id, status="running")
        hermes_channel.turn_ended(core, ws, turn_id, reason)

    for reason in (
        "budget_exhausted",
        "text_response(finish_reason=stop)",
        "interrupted_by_user",
        "pending_tool_result",
    ):
        turn(reason)
    (core.engine.profile_home(ws) / "logs").mkdir(parents=True, exist_ok=True)
    (core.engine.profile_home(ws) / "logs" / "agent.log").write_text(
        "2026-10-09 10:00:00,100 INFO agent.conversation_loop: Turn ended:"
        " reason=budget_exhausted model=m session=s1\n"
    )  # never read for this
    entries = client.get(f"/workspaces/{ws}/log").json()["entries"]
    failed = [e for e in entries if e["area"] == "chat"]
    assert [(e["where"], e["text"], e["cause"]) for e in failed] == [
        (
            "Chat “Invoices”",
            "The answer of the Co-Founder failed",
            "It stopped after a tool, without an answer",
        ),
        ("Chat “Invoices”", "The answer of the Co-Founder failed", "It used up its run budget"),
    ]
    assert failed[0]["href"] == f"/w/{ws}/sessions?chat={chat}"
    assert failed[0]["at"].startswith("20")
    assert not core.db.execute(
        "SELECT name FROM sqlite_master WHERE name IN ('automation_runs', 'automation_events')"
    ).fetchall()


def test_log_reads_the_channel_state_from_hermes(env) -> None:  # type: ignore[no-untyped-def]
    """A bot Hermes can't run shows in the Log as Hermes's gateway
    says now (its gateway_state.json), not from a status AGOS cached."""
    import json

    client, core, _fake, _tg, ws = env
    channels_rig.connect(client)
    home = core.engine.profile_home(ws)
    home.mkdir(parents=True, exist_ok=True)
    (home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": __import__("os").getpid(),
                "gateway_state": "running",
                "platforms": {"telegram": {"state": "fatal", "error_message": "Unauthorized"}},
            }
        )
    )
    entries = client.get(f"/workspaces/{ws}/log").json()["entries"]
    (down,) = [e for e in entries if e["id"].startswith("connection:")]
    assert down["cause"] == "Unauthorized"
    (lamp,) = client.get(f"/workspaces/{ws}/overview").json()["channels"]
    assert lamp["status"] == "error"
    (home / "gateway_state.json").write_text(
        json.dumps(
            {
                "pid": __import__("os").getpid(),
                "gateway_state": "running",
                "platforms": {"telegram": {"state": "connected"}},
            }
        )
    )
    entries = client.get(f"/workspaces/{ws}/log").json()["entries"]
    assert not [e for e in entries if e["id"].startswith("connection:")]
    (lamp,) = client.get(f"/workspaces/{ws}/overview").json()["channels"]
    assert lamp["status"] == "connected"


def test_dashboard_board_activity_is_hermess_kanban(env) -> None:  # type: ignore[no-untyped-def]
    """The Dashboard's "Board activity" is the board's own events (Hermes's Kanban
    task_events), newest first; the owner's audit trail (AGOS's activity) is not
    in it, and another workspace's board never is."""
    client, core, _fake, _tg, ws = env
    _hermes_side(core, ws)
    add_activity(core.db, ws, kind="folder.added", text="Folder added: Reports")
    items = client.get(f"/workspaces/{ws}/activity").json()
    assert [(i["text"], i["taskId"]) for i in items] == [
        ("Done: “Write the brief”", "t_1"),
        ("Blocked: “Write the brief”", "t_1"),
        ("Created: “Write the brief”", "t_1"),
    ]
    assert items[0]["at"] == "2026-10-08T22:53:50.000Z"
    assert not any("Reports" in i["text"] for i in items)
    other = client.post(
        "/workspaces", json={"name": "Other Board", "defaultModel": channels_rig.MODEL}
    ).json()["id"]
    assert client.get(f"/workspaces/{other}/activity").json() == []
