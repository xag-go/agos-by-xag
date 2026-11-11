"""A team automation step's "Only if" lines: a step with nothing to do never starts
its agent. The lines are saved like every step field (owner page and Co-Founder, the
same check), the run script hands them to the step's worker beside the board, and
the agos-guard plugin decides before the worker's first model call: a skipped card
is done with `agos-skipped: <why>` (Runs shows it), and the cards waiting on it go on.

The live case (workspace content-creation, Inspiration Watcher): a webhook of the
Inspiration Sheet, `{"sheet": "<tab>"}`; brand-voice-developer works the Ideas and
Scripts tabs, video-editor the Editing tab, the Co-Founder ends the run."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest
from test_automation_hooks import SECRET, deliver, hook_on
from test_automation_team import create, fire, steps_on_board
from test_cofounder_actions import _run
from work_env import Env, agent, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.engine import team_steps
from agos_core.hermes_plugin.agos_guard import bridge_kanban, step_gate

VOICE, EDITOR = "voice", "editor"

WATCHER_STEPS = [
    {
        "key": "s2",
        "title": "Grow the brand voice",
        "agent": VOICE,
        "description": "media_intake.py --kinds ideas,scripts",
        "onlyIf": [
            {
                "field": "payload.sheet",
                "op": "is",
                "values": ["Ideas-Inspiration", "Scripts-Inspiration"],
            }
        ],
    },
    {
        "key": "s3",
        "title": "Update the records and tell Sam",
        "description": "flow.md section 10 step 3.",
        "waitsOn": ["s2", "s4"],
    },
    {
        "key": "s4",
        "title": "Study the editing reels",
        "agent": EDITOR,
        "description": "media_intake.py --kinds editing",
        "onlyIf": [{"field": "{payload.sheet}", "op": "is", "values": ["Editing-Inspiration"]}],
    },
]


@pytest.fixture
def watcher(env: Env, fake_board: None) -> Env:  # noqa: F811
    from test_automations import FakeCron

    client, _, core, ws = env
    for name in (VOICE, EDITOR):
        agent(client, ws, name)
    cron = FakeCron()
    cron.runner = core.engine.runner
    core.engine.cron_bridge = cron
    return env


class Hermes:
    """Hermes's kanban functions the plugin calls, over the tests' fake board, and
    its terminal (a check line's script)."""

    def __init__(self, core: Any, ws: str, monkeypatch: pytest.MonkeyPatch) -> None:
        self.core, self.ws = core, ws
        self.completed: list[tuple[str, str, int | None]] = []
        self.commands: list[tuple[str, str]] = []
        self.answer = {"output": "GATE: AH", "exit_code": 0}
        kb = types.ModuleType("hermes_cli.kanban_db")
        kb.get_task = self.get_task  # type: ignore[attr-defined]
        kb.kanban_db_path = lambda: core.engine.profile_home(ws) / "kanban.db"  # type: ignore[attr-defined]
        kb.complete_task = self.complete_task  # type: ignore[attr-defined]
        kbc = types.ModuleType("hermes_cli.kanban_db_connect")
        kbc.connect = lambda board=None: types.SimpleNamespace(close=lambda: None)  # type: ignore[attr-defined]
        term = types.ModuleType("tools.terminal_tool")
        term.terminal_tool = self.terminal  # type: ignore[attr-defined]
        turn = types.ModuleType("agent.turn_context")  # this Hermes has the veto
        turn.PRE_LLM_BLOCK_EXIT_REASON = "blocked_by_plugin_pre_llm_call"  # type: ignore[attr-defined]
        pkg = types.ModuleType("hermes_cli")
        pkg.kanban_db, pkg.kanban_db_connect = kb, kbc  # type: ignore[attr-defined]
        for name, module in {
            "hermes_cli": pkg,
            "hermes_cli.kanban_db": kb,
            "hermes_cli.kanban_db_connect": kbc,
            "tools": types.ModuleType("tools"),
            "tools.terminal_tool": term,
            "agent": types.ModuleType("agent"),
            "agent.turn_context": turn,
        }.items():
            monkeypatch.setitem(sys.modules, name, module)
        monkeypatch.setattr(step_gate, "_checked", set())

    def get_task(self, _conn: Any, card: str) -> Any:
        return types.SimpleNamespace(idempotency_key=kanban_of(self.core, self.ws)[card]["key"])

    def complete_task(self, _conn: Any, card: str, **kw: Any) -> bool:
        self.completed.append((card, str(kw["result"]), kw.get("expected_run_id")))
        found = kanban_of(self.core, self.ws)[card]
        found["status"], found["result"] = "done", kw["result"]
        return True

    def terminal(self, command: str, task_id: str | None = None, **_: Any) -> str:
        self.commands.append((command, str(task_id)))
        return json.dumps(self.answer)

    def worker(self, monkeypatch: pytest.MonkeyPatch, card: str, **kw: Any) -> Any:
        """Hermes's dispatcher started the card's worker: its first turn's hook."""
        del monkeypatch
        return step_gate.pre_llm_call(card=card, run=7, task_id="task-1", is_first_turn=True, **kw)


def _watcher(client: Any, ws: str) -> tuple[int, str]:
    aid = create(client, ws, schedule="", steps=WATCHER_STEPS, hook=True)
    return aid, str(hook_on(client, ws, aid, secret=SECRET)["path"])


def _link(tab: str) -> dict[str, Any]:
    return {
        "event": "inspiration.link_added",
        "sheet": tab,
        "row": 22,
        "links": ["https://x.example.com/p/1"],
    }


def _plan(core: Any, ws: str, aid: int) -> dict[str, Any]:
    """The plan AGOS wrote at the end of the automation's run script."""
    script = core.engine.profile_home(ws) / "scripts" / f"agos-automation-{aid}.py"
    namespace: dict[str, Any] = {"__name__": "plan"}
    exec(compile(script.read_text(), str(script), "exec"), namespace)  # noqa: S102 - AGOS's own script
    return dict(namespace["PLAN"])


def _run_cards(core: Any, ws: str) -> dict[str, dict[str, Any]]:
    cards = list(kanban_of(core, ws))
    return steps_on_board(core, ws, cards)


# ---- saving ---------------------------------------------------------------------------


def test_lines_are_saved_shown_and_handed_to_the_run(watcher: Env) -> None:
    client, _, core, ws = watcher
    aid, _path = _watcher(client, ws)
    auto = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    by_key = {s["key"]: s for s in auto["steps"]}
    assert by_key["s2"]["onlyIf"] == [
        {
            "field": "payload.sheet",
            "op": "is",
            "values": ["Ideas-Inspiration", "Scripts-Inspiration"],
            "check": None,
        }
    ]
    assert by_key["s4"]["onlyIf"][0]["field"] == "payload.sheet"  # {payload.sheet} read as written
    assert by_key["s3"]["onlyIf"] == []  # no line: it always runs
    plan = {s["key"]: s for s in _plan(core, ws, aid)["steps"]}
    assert plan["s4"]["only_if"][0]["values"] == ["Editing-Inspiration"]
    assert "only_if" not in plan["s3"]


@pytest.mark.parametrize(
    ("line", "said"),
    [
        # The page's typed form refuses a field or test it doesn't know (422) ...
        ({"field": "payload.sheet", "op": "is", "values": ["x"], "color": "red"}, None),
        ({"field": "payload.sheet", "op": "matches", "values": ["x"]}, None),
        # ... and the plan's own check says the rest in plain words (as for the Co-Founder).
        ({"field": "payload.sheet", "op": "is", "values": []}, "give 1 to 100 values"),
        ({"field": "sheet name", "op": "is", "values": ["x"]}, "isn't a field"),
        ({"check": "/etc/gate.py"}, "inside /workspace"),
        ({"check": "/workspace/../etc/gate.py"}, "inside /workspace"),
        ({"check": "/workspace/tools/gate.py; rm -rf /"}, "no shell characters"),
        ({"check": "/workspace/tools/gate.py", "op": "is"}, "only “check”"),
    ],
)
def test_a_bad_line_is_refused_with_a_plain_word(
    watcher: Env, line: dict[str, Any], said: str | None
) -> None:
    from work_env import MODEL

    client, _, _core, ws = watcher
    steps = [{"key": "s1", "title": "One", "agent": VOICE, "onlyIf": [line]}]
    body = {"name": "Bad", "instructions": "x", "schedule": "0 9 * * 1", "on": True, "model": MODEL}
    r = client.post(f"/workspaces/{ws}/automations", json={**body, "steps": steps})
    assert r.status_code in (400, 422), r.text
    if said:
        assert said in r.json()["detail"], r.text
    assert client.get(f"/workspaces/{ws}/automations").json() == []


def test_the_plan_check_itself() -> None:
    def plan(only_if: Any, kind: str = "work") -> Any:
        return team_steps.parse_plan(
            {"steps": [{"key": "a", "title": "A", "kind": kind, "only_if": only_if}]}, []
        )

    assert plan(None).steps[0].only_if == ()
    kept = plan([{"check": "/workspace/tools/inspiration_gate.py --dir /workspace/records"}])
    assert kept.steps[0].only_if == (
        {"check": "/workspace/tools/inspiration_gate.py --dir /workspace/records"},
    )
    for bad, said in (
        (
            [{"field": "payload.x", "op": "is", "values": ["1"], "when": "e"}],
            "unknown field “when”",
        ),
        ([{"check": "relative/gate.py"}], "inside /workspace"),
        ("payload.x is 1", "must be a list"),
    ):
        with pytest.raises(team_steps.PlanError, match=said):
            plan(bad)
    with pytest.raises(team_steps.PlanError, match="approval waits for you"):
        plan([{"field": "payload.x", "values": ["1"]}], kind="approval")


# ---- the run ----------------------------------------------------------------------------


def test_an_editing_link_never_starts_brand_voice(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Editing link -> brand-voice-developer closes skipped before any model call,
    video-editor works, the Co-Founder ends the run (its parents are done)."""
    client, _, core, ws = watcher
    aid, path = _watcher(client, ws)
    assert deliver(client, path, _link("Editing-Inspiration")).status_code == 200
    steps = _run_cards(core, ws)
    assert set(steps) == {"s2", "s3", "s4"}
    # The run's lines and its delivery sit beside the board, before any card starts.
    [kept] = list(
        (core.engine.profile_home(ws) / "agos-automations" / f"{aid}.runs").glob("*.only-if.json")
    )
    data = json.loads(kept.read_text())
    assert (
        set(data["only_if"]) == {"s2", "s4"}
        and data["payloads"][0]["sheet"] == "Editing-Inspiration"
    )

    hermes = Hermes(core, ws, monkeypatch)
    blocked = hermes.worker(monkeypatch, steps["s2"]["id"])
    reason = (
        "agos-skipped: Only if sheet is one of Ideas-Inspiration, Scripts-Inspiration "
        "(this run: Editing-Inspiration)"
    )
    assert blocked == {"action": "block", "message": reason}
    assert hermes.completed == [(steps["s2"]["id"], reason, 7)]  # the worker's own run
    assert steps["s2"]["status"] == "done" and steps["s2"]["result"].startswith("agos-skipped: ")
    # video-editor and the Co-Founder start as before (no veto, nothing closed).
    assert hermes.worker(monkeypatch, steps["s4"]["id"]) is None
    assert hermes.worker(monkeypatch, steps["s3"]["id"]) is None
    assert len(hermes.completed) == 1
    # The Co-Founder's card waits on both; one skipped never holds it.
    assert set(steps["s3"]["parents"]) == {steps["s2"]["id"], steps["s4"]["id"]}
    # A skipped last card wakes nobody (like WALO).
    assert bridge_kanban._nothing_done(reason)


def test_an_ideas_link_skips_the_video_editor(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, core, ws = watcher
    _aid, path = _watcher(client, ws)
    deliver(client, path, _link("Ideas-Inspiration"))
    steps = _run_cards(core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    assert hermes.worker(monkeypatch, steps["s2"]["id"]) is None
    blocked = hermes.worker(monkeypatch, steps["s4"]["id"])
    assert blocked is not None and "this run: Ideas-Inspiration" in blocked["message"]
    assert [c for c, _r, _ in hermes.completed] == [steps["s4"]["id"]]


def test_a_link_that_joins_a_waiting_run_counts_too(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A burst: an Ideas link then an Editing link before the run began: one run,
    and both steps have work."""
    client, _, core, ws = watcher
    _aid, path = _watcher(client, ws)
    deliver(client, path, _link("Ideas-Inspiration"))
    deliver(client, path, {**_link("Editing-Inspiration"), "row": 23})
    steps = _run_cards(core, ws)
    assert len(steps) == 3  # the second delivery joined the run
    hermes = Hermes(core, ws, monkeypatch)
    assert hermes.worker(monkeypatch, steps["s2"]["id"]) is None
    assert hermes.worker(monkeypatch, steps["s4"]["id"]) is None
    assert hermes.completed == []


def test_run_now_with_no_delivery_runs_every_step(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run with no delivery can't judge payload lines: every step runs, as before."""
    client, _, core, ws = watcher
    aid, _path = _watcher(client, ws)
    assert fire(core, ws, aid)
    hermes = Hermes(core, ws, monkeypatch)
    for card in _run_cards(core, ws).values():
        assert hermes.worker(monkeypatch, card["id"]) is None
    assert hermes.completed == []


def test_a_check_script_answers_in_the_steps_own_sandbox(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, core, ws = watcher
    steps = [
        {"key": "a", "title": "Pull", "agent": VOICE},
        {
            "key": "b",
            "title": "Edit",
            "agent": EDITOR,
            "waitsOn": ["a"],
            "onlyIf": [{"check": "/workspace/tools/inspiration_gate.py --dir /workspace/records"}],
        },
    ]
    aid = create(client, ws, steps=steps)
    assert fire(core, ws, aid)
    cards = _run_cards(core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    hermes.answer = {"output": "- Editing-Inspiration: 3 rows, 0 new\nGATE: LA", "exit_code": 0}
    blocked = hermes.worker(monkeypatch, cards["b"]["id"])
    assert blocked == {
        "action": "block",
        "message": "agos-skipped: /workspace/tools/inspiration_gate.py said GATE: LA",
    }
    # Run by Hermes's terminal of this very worker (its sandbox), never on the host.
    assert hermes.commands == [
        ("python3 /workspace/tools/inspiration_gate.py --dir /workspace/records", "task-1")
    ]
    # Unsure (a failure, no answer word) = the step runs.
    for answer in ({"output": "GATE: LA", "exit_code": 2}, {"output": "done", "exit_code": 0}):
        monkeypatch.setattr(step_gate, "_checked", set())
        cards["b"]["status"] = "running"
        hermes.answer = answer
        assert hermes.worker(monkeypatch, cards["b"]["id"]) is None


def test_no_lines_runs_exactly_as_before(watcher: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Daily Ideas (no lines): no run file, no check, no card closed."""
    from test_automation_team import MONDAY_STEPS

    client, _, core, ws = watcher
    agent(client, ws, "researcher")
    agent(client, ws, "ideas")
    aid = create(client, ws, steps=MONDAY_STEPS)
    assert not any("only_if" in s for s in _plan(core, ws, aid)["steps"])
    assert fire(core, ws, aid)
    assert not (core.engine.profile_home(ws) / "agos-automations" / f"{aid}.runs").exists()
    hermes = Hermes(core, ws, monkeypatch)
    for card in _run_cards(core, ws).values():
        assert hermes.worker(monkeypatch, card["id"]) is None
    assert hermes.completed == [] and hermes.commands == []


def test_only_the_workers_first_turn_decides(watcher: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, core, ws = watcher
    _aid, path = _watcher(client, ws)
    deliver(client, path, _link("Editing-Inspiration"))
    s2 = _run_cards(core, ws)["s2"]["id"]
    hermes = Hermes(core, ws, monkeypatch)
    # A subagent of the card's worker, a later turn, a chat (no card): never.
    assert hermes.worker(monkeypatch, s2, parent_session_id="p1") is None
    assert step_gate.pre_llm_call(card=s2, run=7, task_id="t", is_first_turn=False) is None
    assert step_gate.pre_llm_call(card="", task_id="t", is_first_turn=True) is None
    assert hermes.completed == []
    # Hermes refusing to close the card (not this run's any more): the step runs.
    monkeypatch.setattr(hermes, "complete_task", lambda *_a, **_k: False)
    monkeypatch.setattr(sys.modules["hermes_cli.kanban_db"], "complete_task", hermes.complete_task)
    assert hermes.worker(monkeypatch, s2) is None


def test_an_older_hermes_without_the_veto_ends_the_worker_itself(
    watcher: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live's Hermes (0.22.2) ignores a pre_llm_call block: the card is done first,
    then its own worker process ends before the model is called."""
    client, _, core, ws = watcher
    _aid, path = _watcher(client, ws)
    deliver(client, path, _link("Editing-Inspiration"))
    steps = _run_cards(core, ws)
    hermes = Hermes(core, ws, monkeypatch)
    monkeypatch.delitem(sys.modules, "agent.turn_context")
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    ended: list[int] = []

    def end(code: int) -> None:
        ended.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(step_gate, "end_process", end)
    with pytest.raises(SystemExit):
        hermes.worker(monkeypatch, steps["s2"]["id"])
    assert ended == [0] and steps["s2"]["status"] == "done"  # closed before it ended
    # A step that runs never ends its worker.
    assert hermes.worker(monkeypatch, steps["s4"]["id"]) is None and ended == [0]


# ---- the Co-Founder ----------------------------------------------------------------------


def test_the_cofounder_adds_a_line_to_one_step_and_undo_takes_it_back(watcher: Env) -> None:
    client, _, core, ws = watcher
    aid, _path = _watcher(client, ws)
    name = client.get(f"/workspaces/{ws}/automations/{aid}").json()["name"]
    line = {"field": "payload.row", "op": "is_not", "values": ["1"]}
    [card] = _run(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": name,
            "steps": [{"key": "s3", "only_if": [line]}],
        },
    )
    assert card["status"] == "done", card
    by_key = {
        s["key"]: s for s in client.get(f"/workspaces/{ws}/automations/{aid}").json()["steps"]
    }
    assert by_key["s3"]["onlyIf"][0]["values"] == ["1"]
    # What it didn't name stays: the step's waits and title, the other steps' lines.
    assert by_key["s3"]["waitsOn"] == ["s2", "s4"] and by_key["s3"]["title"].startswith("Update")
    assert by_key["s2"]["onlyIf"] and by_key["s4"]["onlyIf"]
    r = client.post(f"/workspaces/{ws}/cofounder-actions/{card['id']}", json={"choice": "undo"})
    assert r.status_code == 200
    by_key = {
        s["key"]: s for s in client.get(f"/workspaces/{ws}/automations/{aid}").json()["steps"]
    }
    assert by_key["s3"]["onlyIf"] == []
    # A script outside /workspace is refused with a plain word, nothing changes.
    [bad] = _run(
        core,
        ws,
        {
            "do": "update_automation",
            "automation": name,
            "steps": [{"key": "s3", "only_if": [{"check": "/home/x.py"}]}],
        },
    )
    assert bad["status"] != "done" and "inside /workspace" in json.dumps(bad), bad


def test_the_cofounder_is_told_how(watcher: Env) -> None:
    from agos_core.actions import cofounder_actions

    _client, _, core, ws = watcher
    text = cofounder_actions.instructions(core, ws)
    assert '"only_if" lines' in text and "agos-skipped: <why>" in text
    assert '{"check": "/workspace/tools/<script>"}' in text  # one brace: the text is filled


def test_the_guard_hands_hermes_its_worker_card_and_run() -> None:
    """Registered on Hermes's pre_llm_call with the card and run id Hermes's
    dispatcher gave this worker (runtime._current_card, review._run_id)."""
    import inspect

    import agos_core.hermes_plugin.agos_guard as guard

    source = inspect.getsource(guard.register)
    assert '"pre_llm_call", lambda **kw: runtime._sibling("step_gate").pre_llm_call(' in source
    assert 'card=runtime._current_card(), run=runtime._sibling("review")._run_id()' in source


def test_pure_reading_of_a_check_answer() -> None:
    assert step_gate.answer_of("- a\n- b\nGATE: AH\n") is True
    assert step_gate.answer_of("GATE: LA") is False
    assert step_gate.answer_of("YES") is True and step_gate.answer_of("no") is False
    assert step_gate.answer_of("") is None and step_gate.answer_of("maybe") is None
    assert step_gate.answer_of("AH or LA") is None  # both: unsure, it runs
    assert step_gate.card_parts("agos-automation:3:20261111T1Z:webhook:s2") == (
        "3",
        "20261111T1Z",
        "s2",
    )
    assert step_gate.card_parts("agos-ticket:linear:1") is None
