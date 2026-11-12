"""Automation runs in detail and their monthly cost: each step's card, who worked
it (or why it was skipped), its time and the tokens and cost Hermes counted for the
sessions that worked it; the run's totals; each automation's month. Hermes's
stores are real SQLite files here (the board's runs and events, each profile's
state.db), read only, and never another workspace's."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from test_automation_team import MONDAY_STEPS, create, fire, steps_on_board, team
from work_env import Env, agent, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.actions import agent_profiles
from agos_core.actions.services.automation import run_detail, run_usage

team = team  # the team fixture (researcher + ideas), with a FakeCron

BOARD = """
CREATE TABLE IF NOT EXISTS task_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
  profile TEXT, step_key TEXT, status TEXT NOT NULL, started_at INTEGER NOT NULL,
  ended_at INTEGER, outcome TEXT, summary TEXT, metadata TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
  run_id INTEGER, kind TEXT NOT NULL, payload TEXT, created_at INTEGER NOT NULL);
"""
STATE = """
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL,
  parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL,
  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
  cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,
  estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
  role TEXT, content TEXT, timestamp REAL);
"""
T0 = 1_794_000_000  # 2026-11-06 (UTC)


def _profile(core: Any, ws: str, member: str | None) -> str:
    key = agent_profiles.key(ws, member) if member else ws
    return str(core.engine.hermes_name(key))


def _store(core: Any, ws: str, member: str | None) -> Path:
    key = agent_profiles.key(ws, member) if member else ws
    home = Path(core.engine.profile_home(key))
    home.mkdir(parents=True, exist_ok=True)
    path = home / "state.db"
    with sqlite3.connect(path) as db:
        db.executescript(STATE)
    return path


def _session(
    store: Path,
    sid: str,
    *,
    card: str | None = None,
    at: float = T0,
    tokens: tuple[int, int, int, int] = (100, 50, 1000, 10),
    cost: float | None = 0.25,
    status: str | None = "estimated",
    parent: str | None = None,
    source: str = "kanban",
) -> None:
    with sqlite3.connect(store) as db:
        db.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (sid, source, parent, at, at + 60, *tokens, cost, status),
        )
        if card:
            db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, 'user', ?, ?)",
                (sid, f"work kanban task {card}", at),
            )


def _board(core: Any, ws: str) -> Path:
    path = agent_profiles.board_db(core, ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.executescript(BOARD)
    return path


def _attempt(
    board: Path,
    card: str,
    profile: str,
    *,
    start: int = T0,
    end: int | None = T0 + 90,
    outcome: str = "completed",
    metadata: str | None = None,
    error: str | None = None,
) -> int:
    with sqlite3.connect(board) as db:
        cursor = db.execute(
            "INSERT INTO task_runs (task_id, profile, status, started_at, ended_at, outcome,"
            " metadata, error) VALUES (?, ?, 'done', ?, ?, ?, ?, ?)",
            (card, profile, start, end, outcome, metadata, error),
        )
        return int(cursor.lastrowid or 0)


def _run_with_cards(rig: Env) -> tuple[Any, str, int, dict[str, dict[str, Any]]]:
    client, _fake, core, ws = rig
    aid = create(client, ws, steps=MONDAY_STEPS)
    cards = fire(core, ws, aid)
    assert cards is not None
    by_step = steps_on_board(core, ws, cards)
    return core, ws, aid, by_step


# ---- the run in detail ------------------------------------------------------------------


def test_a_skipped_step_shows_its_reason_and_no_tokens_and_totals_add_up(team: Env) -> None:
    core, ws, aid, by_step = _run_with_cards(team)
    board = _board(core, ws)
    research, ideas, check = by_step["research"], by_step["ideas"], by_step["check"]
    researcher, ideas_p = _profile(core, ws, "researcher"), _profile(core, ws, "ideas")
    # research: worked once, Hermes stamped its session on the attempt.
    store_r = _store(core, ws, "researcher")
    _session(store_r, "s-research", card=None, tokens=(10, 20, 300, 0), cost=0.1)
    _attempt(board, research["id"], researcher, metadata='{"worker_session_id": "s-research"}')
    # ideas: found by its prompt, with a subagent of its own.
    store_i = _store(core, ws, "ideas")
    _session(store_i, "s-ideas", card=ideas["id"], tokens=(5, 5, 50, 5), cost=0.05)
    _session(
        store_i, "s-ideas-sub", parent="s-ideas", source="subagent", tokens=(1, 1, 0, 0), cost=0.01
    )
    _attempt(board, ideas["id"], ideas_p, start=T0 + 100, end=T0 + 160)
    # check: nothing to do (lane b's mark), no agent started.
    research.update(status="done", completed_at=T0 + 90)
    ideas.update(status="done", completed_at=T0 + 160)
    check.update(
        status="done",
        completed_at=T0 + 161,
        result="agos-skipped: nothing new to check this week",
    )
    for c in by_step.values():
        c["assignee"] = {"research": researcher, "ideas": ideas_p, "check": researcher}[
            str(c["key"]).rsplit(":", 1)[1]
        ]
    run_id = str(research["key"]).split(":")[2]

    client = team[0]
    got = client.get(f"/workspaces/{ws}/automations/{aid}/runs/{run_id}/detail")
    assert got.status_code == 200, got.text
    detail = got.json()
    steps = {s["key"]: s for s in detail["steps"]}
    assert [s["key"] for s in detail["steps"]][:2] == ["research", "ideas"]
    skipped = steps["check"]
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "nothing new to check this week"
    assert skipped["usage"]["tokens"] == 0 and skipped["usage"]["costUsd"] == 0
    assert skipped["attempts"] == 0
    assert steps["research"]["usage"]["tokens"] == 330
    assert steps["research"]["durationS"] == 90
    assert steps["ideas"]["usage"]["tokens"] == 67  # its subagent included
    assert steps["ideas"]["usage"]["sessions"] == 2
    totals = detail["totals"]
    for k in ("inputTokens", "outputTokens", "cacheReadTokens", "cacheWriteTokens", "tokens"):
        assert totals[k] == sum(s["usage"][k] for s in detail["steps"])
    assert totals["costUsd"] == round(0.1 + 0.05 + 0.01, 6)
    assert totals["priced"] is True
    # The run history carries the same detail.
    history = client.get(f"/workspaces/{ws}/automation-runs").json()
    assert history[0]["detail"]["totals"] == totals
    assert {s["key"]: s["status"] for s in history[0]["detail"]["steps"]}["check"] == "skipped"


def test_a_cost_hermes_did_not_price_stays_unknown(team: Env) -> None:
    core, ws, aid, by_step = _run_with_cards(team)
    board = _board(core, ws)
    research = by_step["research"]
    researcher = _profile(core, ws, "researcher")
    store = _store(core, ws, "researcher")
    _session(store, "s-unpriced", card=research["id"], cost=None, status="unknown")
    _attempt(board, research["id"], researcher)
    research.update(status="done", completed_at=T0 + 90, assignee=researcher)
    run_id = str(research["key"]).split(":")[2]
    detail = team[0].get(f"/workspaces/{ws}/automations/{aid}/runs/{run_id}/detail").json()
    step = next(s for s in detail["steps"] if s["key"] == "research")
    assert step["usage"]["costUsd"] is None and step["usage"]["priced"] is False
    assert step["usage"]["tokens"] == 1160
    assert detail["totals"]["costUsd"] is None  # nothing priced: unknown, never 0


def test_a_failed_step_says_why(team: Env) -> None:
    core, ws, aid, by_step = _run_with_cards(team)
    board = _board(core, ws)
    research = by_step["research"]
    _attempt(
        board,
        research["id"],
        _profile(core, ws, "researcher"),
        outcome="crashed",
        error="worker died",
    )
    research.update(status="blocked")
    state, reason = run_detail.step_state(
        research, [{"outcome": "crashed", "error": "worker died"}]
    )
    assert (state, reason) == ("failed", "worker died")
    run_id = str(research["key"]).split(":")[2]
    detail = team[0].get(f"/workspaces/{ws}/automations/{aid}/runs/{run_id}/detail").json()
    step = next(s for s in detail["steps"] if s["key"] == "research")
    assert step["status"] == "failed" and step["reason"] == "worker died"
    assert {s["status"] for s in detail["steps"] if s["key"] != "research"} == {"waiting"}


def test_another_workspaces_sessions_never_count(team: Env) -> None:
    client, _fake, core, ws = team
    other = client.post("/workspaces", json={"name": "Other", "defaultModel": team_model(core, ws)})
    assert other.status_code in (200, 201), other.text
    ws_b = other.json()["id"]
    store_b = _store(core, ws_b, None)
    _session(store_b, "s-b", tokens=(9_000, 9_000, 0, 0), cost=50.0)
    _core, ws_a, aid, by_step = _run_with_cards(team)
    board = _board(core, ws_a)
    research = by_step["research"]
    researcher = _profile(core, ws_a, "researcher")
    # A's board names B's session and B's store: both ignored.
    run = _attempt(board, research["id"], researcher, metadata='{"worker_session_id": "s-b"}')
    with sqlite3.connect(board) as db:
        db.execute(
            "INSERT INTO task_events (task_id, run_id, kind, payload, created_at)"
            " VALUES (?, ?, 'owner_admitted', ?, ?)",
            (research["id"], run, f'{{"db": "{store_b}", "session_id": "s-b"}}', T0),
        )
    # A profile name that walks out of A's root is no profile.
    _attempt(board, research["id"], "../../agos-x", metadata='{"worker_session_id": "s-b"}')
    research.update(status="done", completed_at=T0 + 90, assignee="../" + ws_b)
    run_id = str(research["key"]).split(":")[2]
    detail = client.get(f"/workspaces/{ws_a}/automations/{aid}/runs/{run_id}/detail").json()
    assert detail["totals"]["tokens"] == 0 and detail["totals"]["costUsd"] == 0
    # B's own run detail of A's automation is not found (scoped by workspace).
    assert (
        client.get(f"/workspaces/{ws_b}/automations/{aid}/runs/{run_id}/detail").status_code == 404
    )
    costs = client.get(f"/workspaces/{ws_b}/automation-costs").json()
    assert costs == []


def team_model(core: Any, ws: str) -> dict[str, Any]:
    from work_env import MODEL

    return dict(MODEL)


# ---- the month ---------------------------------------------------------------------------


def test_monthly_cost_sums_this_month_and_last_month_in_utc(team: Env) -> None:
    core, ws, aid, by_step = _run_with_cards(team)
    board = _board(core, ws)
    research = by_step["research"]
    researcher = _profile(core, ws, "researcher")
    store = _store(core, ws, "researcher")
    _session(store, "s-1", card=research["id"], tokens=(1, 1, 1, 1), cost=0.5)
    _attempt(board, research["id"], researcher)
    for c in by_step.values():
        c.update(status="done", completed_at=T0)
    research["assignee"] = researcher
    started = datetime.fromisoformat(run_detail_started(str(research["key"]).split(":")[2]))
    costs = run_detail.month_costs(core, ws, now=started)
    mine = next(c for c in costs if c.automation_id == aid)
    assert mine.this_month.month == started.strftime("%Y-%m")
    assert mine.this_month.runs == 1 and mine.this_month.usage.cost_usd == 0.5
    assert mine.last_month.runs == 0 and mine.last_month.usage.tokens == 0
    # A month later, the run is last month's.
    first = started.replace(day=1)
    later = (
        first.replace(month=first.month + 1)
        if first.month < 12
        else first.replace(year=first.year + 1, month=1)
    )
    moved = next(c for c in run_detail.month_costs(core, ws, now=later) if c.automation_id == aid)
    assert moved.this_month.runs == 0 and moved.last_month.usage.cost_usd == 0.5
    # The page's read.
    shown = team[0].get(f"/workspaces/{ws}/automation-costs").json()
    assert {c["automationId"] for c in shown} == {aid}


def run_detail_started(run_id: str) -> str:
    return datetime.strptime(run_id, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC).isoformat()


def test_a_one_agent_automations_cost_is_its_cron_sessions(team: Env) -> None:
    store = Path(team[2].engine.profile_home(team[3])) / "state.db"
    store.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store) as db:
        db.executescript(STATE)
    _session(store, "cron_job1_20261106_000000", source="cron", at=T0, cost=0.3)
    _session(store, "sub-1", parent="cron_job1_20261106_000000", source="subagent", cost=0.2)
    _session(store, "cron_job2_20261106_000000", source="cron", at=T0, cost=9.0)
    found = run_usage.cron_sessions(team[2], store.parent, "job1", T0 - 10, T0 + 10)
    assert len(found) == 1
    at, usage = found[0]
    assert at == T0 and usage.sessions == 2 and usage.cost_usd == 0.5


def test_usage_math() -> None:
    priced = run_usage.of_session({"input_tokens": 10, "estimated_cost_usd": 0.2})
    actual = run_usage.of_session(
        {"input_tokens": 10, "estimated_cost_usd": 0.2, "actual_cost_usd": 0.15}
    )
    unknown = run_usage.of_session({"input_tokens": 10, "cost_status": "unknown"})
    included = run_usage.of_session(
        {"input_tokens": 10, "estimated_cost_usd": 0, "cost_status": "included"}
    )
    assert priced.cost_usd == 0.2 and actual.cost_usd == 0.15 and included.cost_usd == 0
    assert unknown.cost_usd is None and not unknown.priced
    mixed = run_usage.total([priced, unknown])
    assert mixed.cost_usd == 0.2 and mixed.priced is False and mixed.tokens == 20
    assert run_usage.total([]).cost_usd == 0 and run_usage.total([unknown]).cost_usd is None


# ---- the Co-Founder ----------------------------------------------------------------------


def test_the_cofounder_reads_what_an_automation_cost_without_undo(team: Env) -> None:
    from test_cofounder_actions import _run

    from agos_core.engine import power

    core, ws, aid, by_step = _run_with_cards(team)
    board = _board(core, ws)
    research = by_step["research"]
    researcher = _profile(core, ws, "researcher")
    _session(_store(core, ws, "researcher"), "s-1", card=research["id"], cost=1.25)
    _attempt(board, research["id"], researcher)
    research.update(status="done", completed_at=T0, assignee=researcher)
    assert power.EFFECT["automation_cost"] == "read"
    [card] = _run(core, ws, {"do": "automation_cost", "automation": "Monday ideas"})
    assert card["status"] == "done", card
    assert card["canUndo"] is False
    started = run_detail_started(str(research["key"]).split(":")[2])
    if started[:7] == datetime.now(UTC).strftime("%Y-%m"):
        assert "$1.25" in card["detail"] and "1 run," in card["detail"]
    assert "this month" in card["detail"] and "last month" in card["detail"]
    run_id = str(research["key"]).split(":")[2]
    [step_card] = _run(core, ws, {"do": "automation_cost", "automation": str(aid), "run": run_id})
    assert "This week's topics" in step_card["detail"] and "$1.25" in step_card["detail"]
