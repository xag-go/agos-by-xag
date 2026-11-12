"""A step's "Only if" lines stay AGOS's: what a worker runs before its first model
call comes only from the automation the owner (or the Co-Founder) saved, never from
a place an agent can write; a burst of deliveries never loses one; a card is decided
once, on its first attempt.

Review of lane auto-b (M1-M3, L2-L6): each test below failed on cd917be6.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest
from test_automation_hooks import deliver
from test_automation_team import create, fire
from test_cofounder_actions import _run
from test_step_only_if import EDITOR, VOICE, Hermes, _link, _run_cards, _watcher, watcher
from work_env import Env, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.engine import automation_run, step_conditions
from agos_core.hermes_plugin.agos_guard import step_gate

_ = watcher  # the fixture, used by name below

GATE = "/workspace/tools/inspiration_gate.py --dir /workspace/records"


def _gated(client: Any, core: Any, ws: str) -> tuple[int, dict[str, dict[str, Any]]]:
    """A run whose step b has a check line (step a has no line)."""
    steps = [
        {"key": "a", "title": "Pull", "agent": VOICE},
        {
            "key": "b",
            "title": "Edit",
            "agent": EDITOR,
            "waitsOn": ["a"],
            "onlyIf": [{"check": GATE}],
        },
    ]
    aid = create(client, ws, steps=steps)
    assert fire(core, ws, aid)
    return aid, _run_cards(core, ws)


def _keyed(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    """The card's idempotency key as an agent could have set it (kanban_create)."""
    monkeypatch.setattr(
        sys.modules["hermes_cli.kanban_db"],
        "get_task",
        lambda _conn, _card: types.SimpleNamespace(idempotency_key=key),
    )


def _root(core: Any, ws: str) -> Path:
    return Path(core.engine.profile_home(ws))


# ---- M1: nothing an agent wrote is ever run ------------------------------------------------


@pytest.mark.parametrize("run", ["{evil}", "{rel}"])
def test_a_card_key_whose_run_is_a_path_never_runs_anything(
    watcher: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run: str
) -> None:
    """An agent writes `/workspace/evil.only-if.json` and makes a card whose key's run
    segment points at it: the worker must not read it, let alone run its line."""
    _client, _, core, ws = watcher
    evil = tmp_path / "files" / "evil"
    evil.parent.mkdir()
    Path(f"{evil}.only-if.json").write_text(
        json.dumps({"only_if": {"s": [{"check": "sh -c id"}]}, "values": {}, "payloads": []})
    )
    (_root(core, ws) / "agos-automations" / "1.runs").mkdir(parents=True)
    rel = os.path.relpath(evil, _root(core, ws) / "agos-automations" / "1.runs")
    hermes = Hermes(core, ws, monkeypatch)
    _keyed(monkeypatch, f"agos-automation:1:{run.format(evil=evil, rel=rel)}:webhook:s")
    assert step_gate.verdict("t1", "task-1") is None
    assert step_gate.pre_llm_call(card="t1", run=7, task_id="task-1") is None
    assert hermes.commands == [] and hermes.completed == []


def test_card_parts_takes_only_the_keys_the_run_script_makes() -> None:
    good = "agos-automation:3:20261111T101010123456Z:webhook:s2"
    assert step_gate.card_parts(good) == ("3", "20261111T101010123456Z", "s2")
    for bad in (
        "agos-automation:3:/tmp/x/evil:webhook:s2",
        "agos-automation:3:../x:webhook:s2",
        "agos-automation:3:20261111T101010123456Z:other:s2",
        "agos-automation:3:20261111T101010123456Z:webhook:../s2",
        "agos-automation:3:20261111T101010123456Z\n:webhook:s2",
        "agos-automation:x:20261111T101010123456Z:webhook:s2",
    ):
        assert step_gate.card_parts(bad) is None, bad


def test_the_check_lines_come_from_the_saved_automation_not_the_run_file(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run file gives the run's values only: a line written into it never runs."""
    client, _, core, ws = watcher
    aid, cards = _gated(client, core, ws)
    [kept] = list((_root(core, ws) / "agos-automations" / f"{aid}.runs").glob("*.only-if.json"))
    data = json.loads(kept.read_text())
    data["only_if"] = {"b": [{"check": "sh -c id"}]}
    kept.write_text(json.dumps(data))
    hermes = Hermes(core, ws, monkeypatch)
    hermes.answer = {"output": "GATE: AH", "exit_code": 0}
    assert hermes.worker(monkeypatch, cards["b"]["id"]) is None
    assert hermes.commands == [(f"python3 {GATE}", "task-1")]


def test_a_saved_line_that_breaks_the_save_rules_is_never_run(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, core, ws = watcher
    aid, cards = _gated(client, core, ws)
    saved = step_conditions.saved_lines_file(_root(core, ws) / "kanban.db", aid)
    assert json.loads(saved.read_text()) == {"b": [{"check": GATE}]}  # written by AGOS on save
    saved.write_text(json.dumps({"b": [{"check": "sh -c id"}]}))
    hermes = Hermes(core, ws, monkeypatch)
    assert hermes.worker(monkeypatch, cards["b"]["id"]) is None  # when in doubt it runs
    assert hermes.commands == [] and hermes.completed == []


def test_a_symlinked_run_file_is_not_read(
    watcher: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run file that is a link (to a file an agent wrote) is not the run's: the
    step runs and nothing is checked."""
    client, _, core, ws = watcher
    aid, cards = _gated(client, core, ws)
    [kept] = list((_root(core, ws) / "agos-automations" / f"{aid}.runs").glob("*.only-if.json"))
    planted = tmp_path / "planted.json"
    planted.write_text(kept.read_text())
    kept.unlink()
    kept.symlink_to(planted)
    hermes = Hermes(core, ws, monkeypatch)
    assert hermes.worker(monkeypatch, cards["b"]["id"]) is None
    assert hermes.commands == []


def test_the_plugin_reads_lines_by_the_same_rules_as_save() -> None:
    """The plugin can't import agos_core: its copy of the save rules must agree."""
    samples: list[Any] = [
        {"check": GATE},
        {"check": "/workspace//tools/x.py"},
        {"check": "/etc/x.py"},
        {"check": "/workspace/../etc/x"},
        {"check": "sh -c id"},
        {"check": "/workspace/x.py; id"},
        {"check": "/workspace/x.py $(id)"},
        {"check": "/workspacex/y"},
        {"check": "/workspace/x.py", "op": "is"},
        {"field": "payload.sheet", "op": "is", "values": ["Ideas"]},
        {"field": "payload.sheet", "op": "matches", "values": ["Ideas"]},
        {"field": "sheet name", "op": "is", "values": ["x"]},
        {"field": "topic", "op": "contains", "values": ["a", "b"]},
        {"field": "payload.x", "op": "is", "values": []},
        {"field": "payload.x", "op": "is", "values": ["1"], "when": "e"},
        "payload.x is 1",
    ]
    for line in samples:
        try:
            saved: Any = list(step_conditions.parse_only_if([line], "s", "work"))
        except step_conditions.ConditionError:
            saved = None
        assert step_gate.valid_lines([line]) == saved, line
        if saved is not None:  # what save keeps reads back as is
            assert step_gate.valid_lines(saved) == saved


def test_the_runs_folder_sits_where_agents_cannot_write(watcher: Env) -> None:
    """Beside the board in the workspace's engine root, never under the files folder
    the sandboxes see as /workspace."""
    from agos_core.storage.layout import workspace_paths

    client, _, core, ws = watcher
    aid, _cards = _gated(client, core, ws)
    files = Path(workspace_paths(core.layout, ws).files).resolve()
    for path in (
        automation_run_dir(core, ws, aid),
        step_conditions.saved_lines_file(_root(core, ws) / "kanban.db", aid),
    ):
        real = path.resolve()
        assert real.exists() and files not in real.parents and real != files


def automation_run_dir(core: Any, ws: str, aid: int) -> Path:
    return _root(core, ws) / "agos-automations" / f"{aid}.runs"


# ---- M2: a burst of deliveries --------------------------------------------------------------


@pytest.fixture
def plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    board = tmp_path / "root" / "kanban.db"
    board.parent.mkdir()
    monkeypatch.setattr(
        automation_run,
        "PLAN",
        {
            "automation": 5,
            "board": str(board),
            "deliveries": str(tmp_path / "deliveries.jsonl"),
            "steps": [{"key": "s", "title": "S", "body": "", "only_if": [{"check": GATE}]}],
        },
    )
    monkeypatch.setattr(automation_run, "_board", lambda prefix="": [])
    return board


def test_two_deliveries_joining_one_run_at_once_both_count(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = "20261111T101010123456Z"
    automation_run.keep_run(run, {}, {"n": 0})
    real = automation_run._write

    def slow(path: Path, data: dict[str, Any]) -> None:
        time.sleep(0.2)  # between the read and the replace
        real(path, data)

    monkeypatch.setattr(automation_run, "_write", slow)
    threads = [threading.Thread(target=automation_run.joined, args=(run, {"n": n})) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    path = automation_run.runs_dir() / f"{run}.only-if.json"
    assert sorted(p["n"] for p in json.loads(path.read_text())["payloads"]) == [0, 1, 2]


def test_a_delivery_log_line_is_never_lost_in_a_burst(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = Path.read_text

    def slow(self: Path, *a: Any, **k: Any) -> str:
        text = real(self, *a, **k)
        time.sleep(0.1)
        return text

    monkeypatch.setattr(Path, "read_text", slow)
    threads = [
        threading.Thread(target=automation_run.note, args=("e", f"p{n}", "started", "d"))
        for n in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    monkeypatch.setattr(Path, "read_text", real)
    assert len(automation_run._noted()) == 4


def test_a_join_that_cannot_write_still_takes_the_delivery(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disk full on the join: the delivery is still commented on the waiting run's
    first cards and noted started; the run's steps then run (no values to judge)."""
    run = "20261111T101010123456Z"
    automation_run.keep_run(run, {}, {"n": 0})

    def full(_path: Path, _data: dict[str, Any]) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(automation_run, "_write", full)
    assert automation_run.joined(run, {"n": 1}) is True
    assert not (automation_run.runs_dir() / f"{run}.only-if.json").exists()


def test_a_run_that_began_meanwhile_does_not_take_the_delivery(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = "20261111T101010123456Z"
    automation_run.keep_run(run, {}, {"n": 0})
    key = f"agos-automation:5:{run}:webhook:s"
    monkeypatch.setattr(
        automation_run,
        "_board",
        lambda prefix="": [{"id": "t1", "status": "running", "key": key, "parents": []}],
    )
    assert automation_run.joined(run, {"n": 1}) is False
    data = json.loads((automation_run.runs_dir() / f"{run}.only-if.json").read_text())
    assert [p["n"] for p in data["payloads"]] == [0]


# ---- M3: a card is decided once ---------------------------------------------------------------


def test_a_later_attempt_of_the_same_card_never_checks_again(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First attempt: the check says AH, the agent works (and uses the new links up).
    It crashes / is unblocked / goes back from review: a new worker process, a new
    first turn. The check must not run again, and the card must not be skipped."""
    client, _, core, ws = watcher
    _aid, cards = _gated(client, core, ws)
    card = cards["b"]["id"]
    hermes = Hermes(core, ws, monkeypatch)
    kb = sys.modules["hermes_cli.kanban_db"]
    attempts = [types.SimpleNamespace(id=7, outcome=None)]
    monkeypatch.setattr(kb, "list_runs", lambda _c, _card, **_k: list(attempts), raising=False)
    assert hermes.worker(monkeypatch, card) is None
    assert len(hermes.commands) == 1
    # A new process (no memory of the first), the card's second run.
    monkeypatch.setattr(step_gate, "_checked", set())
    attempts[0].outcome = "crashed"
    attempts.append(types.SimpleNamespace(id=8, outcome=None))
    hermes.answer = {"output": "GATE: LA", "exit_code": 0}
    assert step_gate.pre_llm_call(card=card, run=8, task_id="task-1", is_first_turn=True) is None
    assert len(hermes.commands) == 1 and hermes.completed == []


def test_an_attempt_whose_worker_never_started_does_not_count(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, core, ws = watcher
    _aid, cards = _gated(client, core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    hermes.answer = {"output": "GATE: LA", "exit_code": 0}
    kb = sys.modules["hermes_cli.kanban_db"]
    runs = [
        types.SimpleNamespace(id=6, outcome="spawn_failed"),
        types.SimpleNamespace(id=7, outcome=None),
    ]
    monkeypatch.setattr(kb, "list_runs", lambda _c, _card, **_k: runs, raising=False)
    blocked = hermes.worker(monkeypatch, cards["b"]["id"])
    assert blocked is not None and len(hermes.commands) == 1


# ---- LOW ------------------------------------------------------------------------------------


def test_a_sender_cannot_mark_its_own_delivery_too_big(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L2: `agos_too_big` in a delivery is the sender's word, not AGOS's mark."""
    client, _, core, ws = watcher
    _aid, path = _watcher(client, ws)
    deliver(client, path, {**_link("Editing-Inspiration"), "agos_too_big": True})
    steps = _run_cards(core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    blocked = hermes.worker(monkeypatch, steps["s2"]["id"])  # Ideas/Scripts lines
    assert blocked is not None and "this run: Editing-Inspiration" in blocked["message"]


def test_a_delivery_too_big_to_keep_runs_the_step(plan: Path) -> None:
    run = "20261111T101010123456Z"
    automation_run.keep_run(run, {}, {"blob": "x" * (automation_run.PAYLOAD_KEPT + 1)})
    data = json.loads((automation_run.runs_dir() / f"{run}.only-if.json").read_text())
    line = {"field": "payload.sheet", "op": "is", "values": ["Ideas"]}
    assert step_gate.match_reason([line], {}, data["payloads"]) is None


def test_a_run_whose_values_cannot_be_kept_still_starts(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L3: disk full on the values file = the cards start anyway (their steps run)."""

    def full(_path: Path, _data: dict[str, Any]) -> None:
        raise OSError(28, "No space left on device")

    made: list[list[str]] = []

    def cli(args: list[str]) -> str:
        made.append(args)
        return json.dumps({"id": f"t{len(made)}"})

    monkeypatch.setattr(automation_run, "_write", full)
    monkeypatch.setattr(automation_run, "_cli", cli)
    monkeypatch.setitem(automation_run.PLAN, "name", "A")
    assert automation_run.start("webhook", "", [], {}, {"n": 1}) == ["t1"]


def test_pruning_never_drops_a_waiting_runs_file(
    plan: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L4: 50 newest kept, but a run still on the board keeps its file."""
    first = "20261101T000000000000Z"
    key = f"agos-automation:5:{first}:webhook:s"
    monkeypatch.setattr(
        automation_run,
        "_board",
        lambda prefix="": [{"id": "t1", "status": "todo", "key": key, "parents": []}],
    )
    automation_run.keep_run(first, {}, None)
    for n in range(automation_run.RUNS_KEPT + 2):
        automation_run.keep_run(f"20261102T0000{n:02d}000000Z", {}, None)
    kept = {p.name.split(".")[0] for p in automation_run.runs_dir().glob("*.only-if.json")}
    assert first in kept and len(kept) == automation_run.RUNS_KEPT + 1


def test_each_check_run_leaves_one_audit_line(
    watcher: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """L6: the check runs outside the agent's tool calls: one log line says what ran."""
    client, _, core, ws = watcher
    _aid, cards = _gated(client, core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    hermes.answer = {"output": "GATE: LA", "exit_code": 0}
    with caplog.at_level(logging.INFO, logger="agos_guard"):
        hermes.worker(monkeypatch, cards["b"]["id"])
    lines = [r.getMessage() for r in caplog.records if "Only if check" in r.getMessage()]
    assert len(lines) == 1, lines
    assert cards["b"]["id"] in lines[0] and "inspiration_gate.py" in lines[0]
    assert "exit 0" in lines[0] and "no" in lines[0]


def test_a_cofounder_change_keeps_a_steps_kind_and_waits_it_does_not_name(watcher: Env) -> None:
    """L5 (kept on purpose): update_automation changes only what it names."""
    client, _, core, ws = watcher
    steps = [
        {"key": "a", "title": "Draft", "agent": VOICE},
        {
            "key": "b",
            "title": "Check",
            "agent": EDITOR,
            "kind": "review",
            "reviews": "a",
            "waitsOn": ["a"],
        },
    ]
    aid = create(client, ws, steps=steps)
    name = client.get(f"/workspaces/{ws}/automations/{aid}").json()["name"]
    [card] = _run(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": name,
            "steps": [{"key": "b", "title": "Check it"}],
        },
    )
    assert card["status"] == "done", card
    by_key = {
        s["key"]: s for s in client.get(f"/workspaces/{ws}/automations/{aid}").json()["steps"]
    }
    assert by_key["b"]["title"] == "Check it"
    assert by_key["b"]["kind"] == "review" and by_key["b"]["waitsOn"] == ["a"]


def test_a_card_closed_after_hermes_stopped_waiting_never_ends_its_worker(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L1: on a Hermes without the veto, a close that lands after the hook's wait
    (the owner's "A stuck plugin step" set low) must not end a worker that may be
    working already."""
    client, _, core, ws = watcher
    _aid, cards = _gated(client, core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    hermes.answer = {"output": "GATE: LA", "exit_code": 0}
    monkeypatch.delitem(sys.modules, "agent.turn_context")
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    config = types.ModuleType("hermes_cli.config")
    config.load_config = lambda: {"plugins": {"hook_callback_timeout": 10}}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_cli.config", config)
    clock = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    real_close = step_gate._close

    def slow_close(*a: Any) -> bool:
        clock[0] += 6  # the board was locked: past 10 s - 5 s of margin
        return real_close(*a)

    monkeypatch.setattr(step_gate, "_close", slow_close)
    ended: list[int] = []
    monkeypatch.setattr(step_gate, "end_process", ended.append)
    assert hermes.worker(monkeypatch, cards["b"]["id"]) is not None
    assert ended == []
    assert step_gate._close_budget() == 5.0
