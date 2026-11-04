"""Step 63: skills that grow on Hermes.

- Find-skills: the shipped skill; an agent's agos_skill_request through a fake Hermes
  hub (scan pass / caution / blocked-unless-forced / hard block, scripts -> the owner's
  Inbox approval, tests pass / fail), the daily limit, workspace isolation.
- The weekly skill review: the Co-Founder's Hermes cron job (monitor script, prompt,
  on / off), the evidence read (Hermes's session store, 👎, review Changes, failed
  tests; pinned), candidate promotion (all pass and score >= current -> a version
  'evolved from evidence'; else discarded) with a fake grader, the week's Inbox note.
- The scorecard derived from a fake board, events, comments and votes.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from skill_growth_rig import HUB, _hub
from test_automations import env  # noqa: F401 - fixture
from test_library import skill
from test_team_hierarchy import _agent

from agos_core.actions import (
    hermes_channel,
    hermes_config,
    scorecard,
    skill_growth,
    skill_requests,
    skill_tests,
    workspace_skills,
)
from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.channel import owner_needs
from agos_core.actions.services.library import growth_candidates
from agos_core.hermes_plugin.agos_guard import grade as plugin_grade
from agos_core.hermes_plugin.agos_guard import skills as plugin_skills

SKILL = "---\nname: invoice-check\ndescription: Check invoices for mistakes.\n---\n\n1. Read it.\n"
BETTER = SKILL + "2. Check the total against the lines.\n"


@pytest.fixture
def space(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any, str]:  # noqa: F811
    client, core, cron, ws = env
    _agent(client, ws, "writer")
    # Background steps run inline; the owner's phone is not reached.
    monkeypatch.setattr(skill_requests, "_soon", lambda fn, *a: fn(*a))
    monkeypatch.setattr(owner_needs, "push", lambda *a, **k: 1)
    monkeypatch.setattr(growth_candidates, "_curator_soon", lambda core, ws: curated.append(ws))
    curated.clear()
    return client, core, cron, ws


curated: list[str] = []


def _bridge(client: Any, core: Any, ws: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{ws}/{path}", json=body, headers={"authorization": f"Bearer {key}"}
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _ask(client: Any, core: Any, ws: str, **extra: Any) -> dict[str, Any]:
    body = {
        "member": "writer",
        "action": "request",
        "source": HUB,
        "reason": "Check the March invoices",
        "tests": [{"input": "Invoice #12: 3 x 40 = 100", "expected": "The total is wrong: 120."}],
        **extra,
    }
    return _bridge(client, core, ws, "skill-request", body)


def _grader(core: Any, scores: dict[str, float] | None = None) -> list[dict[str, Any]]:
    graded: list[dict[str, Any]] = []

    def fake(key: str, *args: str, timeout: float = 60) -> str:
        assert args[0] == "agos-grade"
        job = json.loads(args[1])
        graded.append(job)
        ok = "120" in job["output"]
        score = next(
            (v for k, v in (scores or {}).items() if k in job["output"]), 0.9 if ok else 0.1
        )
        return json.dumps({"ok": True, "pass": ok, "score": score, "notes": "checked"})

    core.engine.walled_cli = fake
    return graded


def _finish(client: Any, ws: str, card: str, text: str) -> None:
    r = client.post(f"/workspaces/{ws}/kanban/{card}/act", json={"action": "done", "summary": text})
    assert r.status_code == 204, r.text


def _request(core: Any, ws: str, rid: int) -> dict[str, Any]:
    return skill_requests.view(skill_requests._get(core, ws, rid))


def _cards_of(core: Any, ws: str, run_ids: list[int]) -> list[str]:
    from agos_core.db import skill_tests as repo

    rows = [repo.get_run(core.db, r) for r in run_ids]
    return [str(r["card"]) for r in rows if r is not None]


def _on(core: Any, ws: str) -> set[str]:
    return hermes_config.here(core, ws).skills


# ---- find-skills ---------------------------------------------------------------------------


def test_every_workspace_gets_find_skills_hidden_like_team_design(space: Any) -> None:
    client, core, _cron, ws = space
    skill_requests._done.clear()
    assert skill_requests.ensure(core, ws) is True
    assert skill_requests.ensure(core, ws) is False  # once per start
    folder = workspace_skills.existing_dir(core, ws, skill_requests.NAME)
    assert folder is not None
    text = (folder / "SKILL.md").read_text()
    assert "agos_skill_request" in text and "action `search`" in text and "skills.sh" in text
    assert "1-2 test inputs" in text and "Nothing fits" in text
    assert skill_requests.NAME in workspace_skills.agos_owned()
    shown = [s["name"] for s in client.get(f"/workspaces/{ws}/skills").json()]
    assert skill_requests.NAME not in shown  # the owner never sees it
    assert skill_requests.NAME in _on(core, ws)  # every agent has it


def test_a_safe_skill_without_scripts_lands_once_its_tests_pass(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    hub = _hub(monkeypatch)
    found = _bridge(client, core, ws, "skill-request", {"action": "search", "query": "invoice"})
    assert found["hub"][0]["source"] == HUB and found["workspace"] == []
    asked = _ask(client, core, ws)
    rid = int(asked["request"])
    shown = _request(core, ws, rid)
    # Hermes's hub installed it (its scan, no --force) into the workspace, OFF there.
    install = next(c for c in hub.calls if c[:2] == ["skills", "install"])
    assert "--force" not in install and install[install.index("--category") + 1] == "agos-library"
    assert shown["status"] == "testing" and shown["verdict"] == "safe" and not shown["scripts"]
    assert "scanner 3.1" in shown["scan"] and shown["source"] == HUB and shown["member"] == "writer"
    assert "invoice-pro" not in _on(core, ws)
    # Its test: a Skill Studio card for the requester, the skill's text as the revision.
    item = shown["itemId"]
    [card] = _cards_of(core, ws, [r["id"] for r in skill_tests.overview(core, ws, item)["runs"]])
    board = core.engine.runner.kanban[core.engine.profile(ws)]
    assert "The revision under test is a candidate" in board[card]["body"]
    assert "1. Add it up." in board[card]["body"]
    assert board[card]["assignee"] == core.engine.hermes_name(f"{ws}--a-writer") or board[card][
        "assignee"
    ].endswith("writer")
    _grader(core)
    _finish(client, ws, card, "The total is wrong: it should be 120.")
    # The card's move (the guard's hook) advances it: tested, safe, no scripts -> on.
    _bridge(client, core, ws, "pipeline-event", {"card": card})
    assert _request(core, ws, rid)["status"] == "landed"
    assert "invoice-pro" in _on(core, ws)
    notes = [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "note"
    ]
    assert any("invoice-pro" in n["title"] and "landed" in n["title"] for n in notes)
    log = client.get(f"/workspaces/{ws}/skill-growth").json()
    assert log["requests"][0]["status"] == "landed" and log["usedToday"] == 1
    # The same source asked again while one is open is the same request.
    assert skill_requests.status(core, ws, "writer")["requests"][0]["id"] == rid


def test_scripts_wait_for_the_owners_approval_in_the_inbox(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    _hub(monkeypatch, scripts=True)
    rid = int(_ask(client, core, ws)["request"])
    item = _request(core, ws, rid)["itemId"]
    [card] = _cards_of(core, ws, [r["id"] for r in skill_tests.overview(core, ws, item)["runs"]])
    _grader(core)
    _finish(client, ws, card, "120")
    skill_requests.advance(core, ws)
    shown = _request(core, ws, rid)
    assert shown["status"] == "approval" and shown["scripts"] and shown["askId"]
    assert "invoice-pro" not in _on(core, ws)
    [proposal] = [
        p for p in client.get(f"/workspaces/{ws}/proposals").json() if p["kind"] == "skill"
    ]
    assert proposal["payload"]["request"] == rid and "scripts" in proposal["payload"]["asked"]
    assert proposal["label"] == "Add the skill invoice-pro"
    assert (
        client.post(
            f"/workspaces/{ws}/proposals/{proposal['id']}", json={"choice": "revise", "note": "x"}
        ).status_code
        == 400
    )
    r = client.post(f"/workspaces/{ws}/proposals/{proposal['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    assert _request(core, ws, rid)["status"] == "landed" and "invoice-pro" in _on(core, ws)


def test_a_caution_scan_asks_the_owner_and_a_reject_uninstalls(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    hub = _hub(monkeypatch, verdict="CAUTION")
    rid = int(_ask(client, core, ws)["request"])
    item = _request(core, ws, rid)["itemId"]
    [card] = _cards_of(core, ws, [r["id"] for r in skill_tests.overview(core, ws, item)["runs"]])
    _grader(core)
    _finish(client, ws, card, "120")
    skill_requests.advance(core, ws)
    assert _request(core, ws, rid)["status"] == "approval"
    [p] = [p for p in client.get(f"/workspaces/{ws}/proposals").json() if p["kind"] == "skill"]
    assert "warned" in p["payload"]["asked"]
    r = client.post(f"/workspaces/{ws}/proposals/{p['id']}", json={"choice": "reject"})
    assert r.status_code == 200, r.text
    shown = _request(core, ws, rid)
    assert shown["status"] == "rejected" and shown["itemId"] is None
    assert ["skills", "uninstall", "invoice-pro", "--yes"] in hub.calls
    assert workspace_skills.existing_dir(core, ws, "invoice-pro") is None


def test_a_scan_hermes_blocks_unless_forced_asks_first_then_installs_forced(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    hub = _hub(
        monkeypatch,
        block="Not installed: the security scan found 1 high-risk pattern(s) in 'x'. Re-run "
        'with --force to install anyway. Finding: HIGH exfil scripts/a.py:3 "curl"',
    )
    rid = int(_ask(client, core, ws)["request"])
    shown = _request(core, ws, rid)
    assert (
        shown["status"] == "approval" and shown["itemId"] is None and "HIGH exfil" in shown["scan"]
    )
    [p] = [p for p in client.get(f"/workspaces/{ws}/proposals").json() if p["kind"] == "skill"]
    assert "Install anyway" in p["payload"]["asked"]
    r = client.post(f"/workspaces/{ws}/proposals/{p['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    installs = [c for c in hub.calls if c[:2] == ["skills", "install"]]
    assert installs[-1][-1] == "--force"  # his yes is Hermes's own --force
    shown = _request(core, ws, rid)
    assert shown["status"] == "testing" and shown["forced"]
    [card] = _cards_of(
        core, ws, [r["id"] for r in skill_tests.overview(core, ws, shown["itemId"])["runs"]]
    )
    _grader(core)
    _finish(client, ws, card, "120")
    skill_requests.advance(core, ws)
    assert _request(core, ws, rid)["status"] == "landed"  # he already said yes


def test_a_hard_block_is_refused_and_a_failed_test_uninstalls(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    _hub(
        monkeypatch,
        block="Not installed: the security scan found 2 high-risk pattern(s). Hermes never "
        "installs unverified skills with high-risk findings, even with --force.",
    )
    rid = int(_ask(client, core, ws)["request"])
    shown = _request(core, ws, rid)
    assert shown["status"] == "refused" and shown["askId"] is None
    assert not [p for p in client.get(f"/workspaces/{ws}/proposals").json() if p["kind"] == "skill"]
    # A test that fails: Hermes's hub takes it back out.
    skill_requests.set_limit(core, ws, 5)
    hub = _hub(monkeypatch)
    rid = int(_ask(client, core, ws, source=HUB + "-2")["request"])
    item = _request(core, ws, rid)["itemId"]
    [card] = _cards_of(core, ws, [r["id"] for r in skill_tests.overview(core, ws, item)["runs"]])
    _grader(core)
    _finish(client, ws, card, "Looks fine.")
    skill_requests.advance(core, ws)
    shown = _request(core, ws, rid)
    assert shown["status"] == "failed" and "tests failed" in shown["note"]
    assert any(c[:2] == ["skills", "uninstall"] for c in hub.calls)
    assert workspace_skills.existing_dir(core, ws, "invoice-pro") is None


def test_the_daily_limit_and_the_requests_checks(
    space: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, core, _cron, ws = space
    _hub(monkeypatch, block="Not installed: the security scan found 1 x, even with --force.")
    r = client.put(f"/workspaces/{ws}/skill-growth/limit", json={"limit": 1})
    assert r.status_code == 200 and r.json()["limit"] == 1
    assert client.put(f"/workspaces/{ws}/skill-growth/limit", json={"limit": 99}).status_code == 422
    assert "request" in _ask(client, core, ws)
    second = _ask(client, core, ws, source=HUB + "-2")
    assert "limit of 1" in second["error"]
    assert skill_requests.status(core, ws, "writer")["leftToday"] == 0
    # No tests, no expected answer, an unknown member: refused before anything runs.
    skill_requests.set_limit(core, ws, 5)
    assert "1-2 tests" in _ask(client, core, ws, source=HUB + "-3", tests=[])["error"]
    no_expected = _ask(client, core, ws, source=HUB + "-3", tests=[{"input": "x"}])
    assert "expected" in no_expected["error"]
    assert "Not a member" in _ask(client, core, ws, member="ghost", source=HUB + "-4")["error"]


def test_requests_stay_in_their_workspace(space: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, core, _cron, ws = space
    _hub(monkeypatch, block="Not installed: the security scan found 1 x, even with --force.")
    rid = int(_ask(client, core, ws)["request"])
    other = client.post(
        "/workspaces", json={"name": "Other", "defaultModel": _model(client, ws)}
    ).json()["id"]
    assert client.get(f"/workspaces/{other}/skill-growth").json()["requests"] == []
    assert skill_requests.status(core, other, "")["requests"] == []
    with pytest.raises(NotFoundError):
        skill_requests._get(core, other, rid)
    with pytest.raises(NotFoundError):
        skill_requests.decided(core, other, rid, 1, "approve")
    # A's key on B's bridge URL: refused.
    key = hermes_channel.bridge_key(core, ws)
    r = client.post(
        f"/hermes-bridge/{other}/skill-request",
        json={"action": "status"},
        headers={"authorization": f"Bearer {key}"},
    )
    assert r.status_code == 401


def _model(client: Any, ws: str) -> dict[str, Any]:
    from test_automations import MODEL

    return dict(MODEL)


# ---- the weekly skill review ------------------------------------------------------------------


def _root_jobs(core: Any, cron: Any, ws: str) -> dict[str, dict[str, Any]]:
    home = str(core.engine.profile_home(ws))
    return {j["spec"].name: j for j in cron.jobs.values() if j["home"] == home}


def test_the_skill_review_job_is_the_cofounders_monitor_job(space: Any) -> None:
    client, core, cron, ws = space
    assert client.get(f"/workspaces/{ws}/skill-growth").json()["job"]["on"] is False
    skill_growth._jobs_done.clear()
    assert skill_growth.ensure_job(core, ws) is True
    job = _root_jobs(core, cron, ws)[skill_growth.JOB_NAME]
    assert (
        job["spec"].schedule == "0 18 * * 5" and job["spec"].monitor_script == skill_growth.SCRIPT
    )
    assert job["spec"].prompt == skill_growth.PROMPT and job["spec"].deliver == "local"
    script = core.engine.profile_home(ws) / "scripts" / skill_growth.SCRIPT
    assert "/skill-review" in script.read_text() and '"evidence"' in script.read_text()
    r = client.put(
        f"/workspaces/{ws}/skill-growth/review", json={"on": False, "time": "19:30", "day": 6}
    )
    assert r.status_code == 200, r.text
    job = _root_jobs(core, cron, ws)[skill_growth.JOB_NAME]
    assert job["enabled"] is False and job["paused_reason"] == skill_growth.OFF_REASON
    assert job["spec"].schedule == "30 19 * * 6"
    assert r.json()["job"] == {**r.json()["job"], "on": False, "time": "19:30", "day": 6}
    client.put(
        f"/workspaces/{ws}/skill-growth/review", json={"on": True, "time": "19:30", "day": 6}
    )
    assert _root_jobs(core, cron, ws)[skill_growth.JOB_NAME]["enabled"] is True
    assert len([n for n in _root_jobs(core, cron, ws) if n == skill_growth.JOB_NAME]) == 1
    # The Ongoing list marks it as AGOS's own (Stop refuses it).
    from agos_core.actions import ongoing

    assert ongoing._system({"name": skill_growth.JOB_NAME}) == "skills"


def test_the_review_prompt_follows_skillclaws_rules() -> None:
    p = skill_growth.PROMPT
    assert "agos_skill_candidate" in p and "Never write the skill with skill_manage" in p
    assert "When in doubt, skip it" in p and "agent problem" in p and "environment" in p
    assert "passes them all and scores at least as well" in p and "stay cheap" in p


def _state_db(core: Any, ws: str, rows: list[tuple[Any, ...]]) -> None:
    """A member's Hermes session store with the columns AGOS reads (pinned)."""
    home = core.engine.profile_home(ws)
    db = sqlite3.connect(home / "state.db")
    db.execute(
        """CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
           role TEXT, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,
           timestamp REAL NOT NULL)"""
    )
    db.executemany(
        "INSERT INTO messages (session_id, role, content, tool_calls, tool_name, timestamp)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    db.commit()
    db.close()
    from agos_core.db import hermes_chats

    store = hermes_chats.store()
    if store is not None:
        store.forget()


def _view_call(name: str) -> str:
    return json.dumps(
        [{"function": {"name": "skill_view", "arguments": json.dumps({"name": name})}}]
    )


def test_the_weeks_evidence_is_read_where_it_lives_and_grouped_by_skill(space: Any) -> None:
    client, core, _cron, ws = space
    skill(client, ws, text=SKILL)
    t = datetime.now(UTC).timestamp()
    old = t - 30 * 86400
    _state_db(
        core,
        ws,
        [
            ("s1", "user", "Check the invoice", None, None, t - 50),
            ("s1", "assistant", "", _view_call("invoice-check"), None, t - 40),
            ("s1", "tool", '{"error": "file not found"}', None, "read_file", t - 30),
            ("s1", "assistant", "It is fine.", None, None, t - 20),
            ("s1", "user", "No, the total is wrong", None, None, t - 10),
            ("s2", "assistant", "Done.", None, None, t - 9),
            ("s2", "user", "Actually use euros", None, None, t - 8),
            ("s3", "assistant", "Done.", None, None, old),
            ("s3", "user", "No, never", None, None, old),
        ],
    )
    core.db.execute(
        """INSERT INTO feedback_votes (workspace_id, kind, ref, vote, note, created_at)
           VALUES (?, 'reply', '1:2', -1, 'too long', ?)""",
        (ws, datetime.now(UTC).isoformat(timespec="seconds")),
    )
    text = skill_growth.evidence(core, ws)
    assert text.startswith("Skill review evidence, ")
    head, *_ = text.split("## (no skill named)")
    assert "## invoice-check (2)" in head
    assert "- correction [session:agos-" in head and '"No, the total is wrong"' in head
    assert "- tool error [" in head and "read_file: file not found" in head
    unnamed = text.split("## (no skill named)")[1]
    assert (
        '"Actually use euros"' in unnamed
        and "- 👎 note [vote:" in unnamed
        and "too long" in unnamed
    )
    assert "No, never" not in text  # older than the week
    assert skill_growth.evidence(core, ws) == text  # stable: Hermes's monitor hashes it
    via = _bridge(client, core, ws, "skill-review", {"action": "evidence"})
    assert via["evidence"] == text


def test_no_evidence_is_one_constant_line() -> None:
    assert skill_growth.render([]) == skill_growth.NOTHING
    found = skill_growth.session_evidence(
        [
            {
                "session_id": "a",
                "role": "assistant",
                "content": "x",
                "tool_calls": None,
                "tool_name": None,
            },
            {
                "session_id": "a",
                "role": "user",
                "content": "thanks!",
                "tool_calls": None,
                "tool_name": None,
            },
        ],
        "agos-w",
        {"invoice-check"},
    )
    assert found == []


def test_judge_promotes_only_when_all_pass_and_it_scores_at_least_as_well() -> None:
    def runs(*pairs: tuple[str, float | None]) -> list[dict[str, Any]]:
        return [{"grade": g, "score": s, "input_name": f"i{n}"} for n, (g, s) in enumerate(pairs)]

    ok, score, base, _ = skill_growth.judge(
        runs(("pass", 0.9), ("pass", 0.8)), runs(("pass", 0.85))
    )
    assert ok and (score, base) == (0.85, 0.85)  # equal is enough
    ok, *_rest, note = skill_growth.judge(runs(("pass", 1.0), ("fail", 0.2)), runs(("fail", 0.0)))
    assert not ok and "Failed 1 of 2 tests (i1)" in note
    ok, *_rest, note = skill_growth.judge(runs(("pass", 0.6)), runs(("pass", 0.9)))
    assert not ok and "Scored 0.6 against 0.9" in note
    ok, score, base, _ = skill_growth.judge(runs(("pass", None)), runs(("fail", None)))
    assert ok and (score, base) == (1.0, 0.0)  # no score from an older grader: pass 1 / fail 0
    assert skill_growth.judge([], [])[0] is False
    assert not skill_growth.judge(runs(("error", None)), [])[0]


def _candidate(client: Any, core: Any, ws: str, text: str = BETTER, **extra: Any) -> dict[str, Any]:
    body = {
        "action": "candidate",
        "skill": "invoice-check",
        "text": text,
        "why": "The owner corrected totals twice",
        "evidence": ["session:agos-x/s1", "run:7"],
        **extra,
    }
    return _bridge(client, core, ws, "skill-review", body)


def _sides(core: Any, ws: str, cid: int) -> dict[str, list[str]]:
    from agos_core.db import skill_tests as repo

    row = core.db.execute("SELECT runs FROM skill_candidates WHERE id = ?", (cid,)).fetchone()
    out: dict[str, list[str]] = {}
    for plan in json.loads(row["runs"]):
        run = repo.get_run(core.db, plan["run"])
        assert run is not None
        out.setdefault(plan["side"], []).append(str(run["card"]))
    return out


def test_a_candidate_that_passes_and_scores_at_least_as_well_becomes_the_next_version(
    space: Any,
) -> None:
    client, core, _cron, ws = space
    sid = skill(client, ws, text=SKILL)
    made = _candidate(
        client,
        core,
        ws,
        tests=[{"input": "Invoice #12: 3 x 40 = 100", "expected": "The total is wrong: 120."}],
    )
    assert made["status"] == "testing" and made["runs"] == 1
    inputs = skill_tests.overview(core, ws, sid)["inputs"]
    assert [i["name"] for i in inputs] == ["From evidence 1"]  # its tests grow from evidence
    sides = _sides(core, ws, int(made["candidate"]))
    board = core.engine.runner.kanban[core.engine.profile(ws)]
    assert "2. Check the total against the lines." in board[sides["candidate"][0]]["body"]
    assert "revision under test" not in board[sides["current"][0]]["body"]
    _grader(core, {"lines: 120": 0.95, "120 too": 0.7})
    _finish(client, ws, sides["candidate"][0], "From the lines: 120")
    _finish(client, ws, sides["current"][0], "Maybe 120 too")
    assert skill_growth.advance(core, ws) == 1
    [shown] = client.get(f"/workspaces/{ws}/skill-growth").json()["candidates"]
    assert shown["status"] == "promoted" and (shown["from"], shown["to"]) == (1, 2)
    assert (shown["score"], shown["baseScore"]) == (0.95, 0.7)
    folder = workspace_skills.existing_dir(core, ws, "invoice-check")
    assert folder is not None and (folder / "SKILL.md").read_text() == BETTER
    v2 = client.get(f"/workspaces/{ws}/skills/{sid}/versions").json()[0]
    assert v2["number"] == 2 and v2["author"] == "cofounder"
    assert v2["summary"].startswith("evolved from evidence: The owner corrected totals twice")
    assert "session:agos-x/s1" in v2["summary"]
    # The week's note: one for the batch, with what Skill Studio's diff / Restore needs.
    notes = [
        i
        for i in client.get(f"/workspaces/{ws}/inbox").json()["items"]
        if i["type"] == "note" and i["note"]["kind"] == skill_growth.NOTE_KIND
    ]
    assert len(notes) == 1 and notes[0]["title"] == "Skills improved this week: 1 of 1"
    detail = json.loads(notes[0]["note"]["detail"])
    assert detail["items"][0] == {**detail["items"][0], "itemId": sid, "from": 1, "to": 2}
    assert curated == [ws]  # Hermes's curator gets one pass
    skill_growth._close_batch(core, ws, detail["batch"])  # closing again: no second note
    again = [
        i for i in client.get(f"/workspaces/{ws}/inbox").json()["items"] if i["type"] == "note"
    ]
    assert len([n for n in again if n["note"]["kind"] == skill_growth.NOTE_KIND]) == 1


def test_a_candidate_that_fails_or_scores_lower_is_discarded_with_a_note(space: Any) -> None:
    client, core, _cron, ws = space
    sid = skill(client, ws, text=SKILL)
    skill_tests.add_input(core, ws, sid, name="March", text="Invoice #12", expected="120")
    made = _candidate(client, core, ws)
    sides = _sides(core, ws, int(made["candidate"]))
    _grader(core, {"low 120": 0.55, "high 120": 0.9})
    _finish(client, ws, sides["candidate"][0], "low 120")
    _finish(client, ws, sides["current"][0], "high 120")
    _bridge(client, core, ws, "pipeline-event", {"card": sides["current"][0]})
    [shown] = skill_growth.candidates(core, ws)
    assert shown["status"] == "discarded" and "Scored 0.55 against 0.9" in shown["note"]
    folder = workspace_skills.existing_dir(core, ws, "invoice-check")
    assert folder is not None and (folder / "SKILL.md").read_text() == SKILL
    assert curated == []
    # A failing candidate is discarded too; the current version's graded run is reused.
    made = _candidate(client, core, ws)
    sides = _sides(core, ws, int(made["candidate"]))
    assert sides["current"] == [_sides(core, ws, int(shown["id"]))["current"][0]]
    _finish(client, ws, sides["candidate"][0], "no idea")
    skill_growth.advance(core, ws)
    latest = skill_growth.candidates(core, ws)[0]
    assert latest["status"] == "discarded" and "Failed 1 of 1 tests (March)" in latest["note"]


def test_candidate_checks(space: Any) -> None:
    client, core, _cron, ws = space
    skill(client, ws, text=SKILL)
    assert "same as the current" in _candidate(client, core, ws, text=SKILL)["error"]
    renamed = BETTER.replace("name: invoice-check", "name: other")
    assert "keep the skill's name" in _candidate(client, core, ws, text=renamed)["error"]
    assert "This skill" in _candidate(client, core, ws, skill="team-design")["error"]
    # No tests anywhere: discarded at once, nothing written.
    made = _candidate(client, core, ws)
    assert made["status"] == "discarded"
    assert "No tests" in skill_growth.candidates(core, ws)[0]["note"]


def test_the_plugin_tools() -> None:
    posted: list[tuple[str, dict[str, Any]]] = []

    def post(path: str, body: dict[str, Any], wait: float) -> dict[str, Any]:
        posted.append((path, body))
        return {"ok": True}

    said = plugin_skills.request_tool(
        {"action": "request", "source": HUB, "tests": [{"input": "x", "expected": "y"}, {}, {}]},
        member="writer",
        post=post,
    )
    assert json.loads(said) == {"ok": True}
    assert posted[0][0] == "skill-request" and posted[0][1]["member"] == "writer"
    assert len(posted[0][1]["tests"]) == 2
    refused = plugin_skills.candidate_tool(
        {"skill": "a", "text": "b", "why": "c"}, member="writer", post=post
    )
    assert "Only the Co-Founder" in json.loads(refused)["error"] and len(posted) == 1
    plugin_skills.candidate_tool({"skill": "a", "text": "b", "why": "c"}, member="", post=post)
    assert posted[1][0] == "skill-review" and posted[1][1]["action"] == "candidate"
    registered: list[str] = []

    class Ctx:
        def register_tool(self, name: str, **_: Any) -> None:
            registered.append(name)

    import contextlib

    plugin_skills.register(
        Ctx(), member_of=lambda: "", post=post, guard=lambda n: contextlib.nullcontext()
    )
    assert registered == ["agos_skill_request", "agos_skill_candidate"]
    # The grader's verdict carries a 0-1 score (clamped) when the model gives one.
    assert plugin_grade.verdict('{"pass": true, "score": 1.4, "notes": "ok"}') == {
        "pass": True,
        "notes": "ok",
        "score": 1.0,
    }
    assert "score" not in (plugin_grade.verdict('{"pass": false}') or {})


# ---- the scorecard ----------------------------------------------------------------------------


def _board(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript(
        """CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,
             assignee TEXT, status TEXT, created_at INTEGER, started_at INTEGER,
             completed_at INTEGER, skills TEXT);
           CREATE TABLE IF NOT EXISTS task_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
             task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER);
           CREATE TABLE IF NOT EXISTS task_comments (id INTEGER PRIMARY KEY AUTOINCREMENT,
             task_id TEXT, author TEXT, body TEXT, created_at INTEGER);"""
    )
    return db


def test_scorecards_are_derived_from_the_board_votes_and_heartbeats(
    space: Any, tmp_path: Path
) -> None:
    client, core, _cron, ws = space
    _label, start, end = scorecard.week_bounds()
    writer = core.engine.hermes_name(f"{ws}--a-writer")
    from agos_core.actions import kanban_board

    profiles = {p: m["name"] for p, m in kanban_board._members(core, ws).items()}
    assert profiles.get(writer) == "writer"
    path = tmp_path / "kanban.db"
    db = _board(path)
    s = int(start) + 3600
    db.executemany(
        "INSERT INTO tasks (id, assignee, status, created_at, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("t1", writer, "done", s, s, s + 600),
            ("t2", writer, "done", s, s + 100, s + 100 + 1800),
            ("t3", writer, "blocked", s, s, None),
            ("t4", writer, "done", s - 9 * 86400, s - 9 * 86400, s - 8 * 86400),  # last week
        ],
    )
    db.executemany(
        "INSERT INTO task_events (task_id, kind, created_at) VALUES (?, ?, ?)",
        [
            ("t3", "blocked", s + 60),
            ("t3", "unblocked", s + 60 + 1200),
            ("t3", "blocked", s + 2000),
        ],
    )
    db.executemany(
        "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
        [
            ("t1", writer, "[agos-review t1 r1 s1: submit] done", s + 10),
            ("t1", "owner", "[agos-review t1 r1 s1: changes] fix the title", s + 20),
            ("t1", writer, "[agos-review t1 r2 s1: submit] fixed", s + 30),
            ("t2", writer, "[agos-review t2 r1 s1: submit] done", s + 40),
        ],
    )
    db.commit()
    found, owner_of = scorecard.from_board(db, profiles, start, end, end)
    db.close()
    row = found["writer"]
    assert row["cardsDone"] == 2 and row["medianMinutes"] == 20.0  # 10 and 30 minutes
    assert row["blocked"] == 2 and row["submitted"] == 3 and row["returned"] == 1
    assert owner_of["t1"] == "writer"
    # Through the page's read: the board file where Hermes keeps it, votes on top.
    from agos_core.actions import agent_profiles

    board_path = agent_profiles.board_db(core, ws)
    board_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, board_path)
    at = datetime.fromtimestamp(s + 100, UTC).isoformat(timespec="seconds")
    core.db.execute(
        """INSERT INTO feedback_votes (workspace_id, kind, ref, vote, note, created_at)
           VALUES (?, 'revision', 't1:report:2', 1, '', ?), (?, 'revision', 't2:report:1', -1, 'no', ?)""",
        (ws, at, ws, at),
    )
    r = client.get(f"/workspaces/{ws}/scorecards")
    assert r.status_code == 200, r.text
    cards = {m["member"]: m for m in r.json()["members"]}
    w = cards["writer"]
    assert (w["cardsDone"], w["thumbsUp"], w["thumbsDown"], w["returnRate"]) == (2, 1, 1, 0.33)
    assert w["blockedMinutes"] >= 20 and w["ready"] is None
    assert cards["cofounder"]["cardsDone"] == 0
    assert client.get(f"/workspaces/{ws}/scorecards?week=bad").status_code == 400
    lines = scorecard.status_lines(core, ws)
    assert lines[0].startswith("Team scorecards (") and any("@writer: 2 done" in x for x in lines)
    # The Co-Founder's agos_goals status ends with them; a member's doesn't.
    said = _bridge(client, core, ws, "goals", {"action": "status"})["status"]
    assert "Team scorecards" in said
    assert (
        "Team scorecards"
        not in _bridge(client, core, ws, "goals", {"action": "status", "member": "writer"})[
            "status"
        ]
    )
