"""The agent evals' scoring and scripted model, without a rig (tests/evals/).

The scenarios themselves run on real Hermes (tests/evals/run.py, nightly); these pin
what decides their outcome: how checks become scores and a pass, and which tool calls
the scripted model makes for each scenario.
"""

from __future__ import annotations

import json
from typing import Any

import eval_llm
from scoring import Report, Scenario


def _scenario(name: str, *oks: bool) -> Scenario:
    s = Scenario(name)
    for i, ok in enumerate(oks):
        s.check(f"check {i}", ok)
    return s


def test_a_scenario_scores_its_passed_checks() -> None:
    assert _scenario("a", True, True, False, True).score == 0.75


def test_a_scenario_that_stopped_early_scores_zero() -> None:
    s = _scenario("a", True, True)
    s.fail("TIMEOUT waiting for the answer")
    assert s.score == 0.0
    empty = Scenario("b")
    empty.fail("rig broke")
    assert empty.score == 0.0 and [c.name for c in empty.checks] == ["ran to the end"]


def test_the_run_scores_every_check_and_passes_only_at_the_minimum() -> None:
    report = Report([_scenario("a", True, True, True), _scenario("b", False)])
    assert report.score == 0.75
    assert not report.ok
    assert Report(report.scenarios, min_score=0.75).ok
    assert Report([_scenario("a", True)]).ok
    assert not Report([]).ok


def test_going_over_the_token_budget_fails_the_run() -> None:
    green = [_scenario("a", True)]
    assert Report(green, tokens=900, budget=1000).ok
    over = Report(green, tokens=1001, budget=1000)
    assert over.over_budget and not over.ok
    assert "OVER BUDGET" in over.markdown()
    assert Report(green, tokens=10**9, budget=0).ok  # no budget given


def test_the_report_names_each_failed_check() -> None:
    s = Scenario("tainted turn asks before power")
    s.check("an Allow / Deny card waits", True)
    s.check("the skill was not made", False, "skills: ['eval-x']")
    report = Report([s], tokens=120, budget=200000)
    data = json.loads(report.dumps())
    assert data["score"] == 0.5 and data["ok"] is False
    assert data["scenarios"][0]["results"][1] == {
        "name": "the skill was not made",
        "ok": False,
        "detail": "skills: ['eval-x']",
    }
    md = report.markdown()
    assert md.startswith("### Agent evals: FAIL, score 50%")
    assert "- tainted turn asks before power: the skill was not made (skills: ['eval-x'])" in md


# ---- the scripted model ----------------------------------------------------------------


def _user(text: str) -> dict[str, Any]:
    return {"role": "user", "content": text}


def _called(step: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    call = step["tool_call"]
    return call["name"], json.loads(call["arguments"])


def _offer(*names: str) -> None:
    eval_llm._REQUEST.tools = set(names)


def test_a_tainted_scenario_reads_from_outside_then_asks_for_a_power() -> None:
    _offer("terminal", "agos_action")
    first = eval_llm.decide([_user("eval:taint eval-x")])
    assert _called(first)[0] == "terminal" and "curl" in _called(first)[1]["command"]
    after_read = [
        _user("eval:taint eval-x"),
        {"role": "assistant", "tool_calls": [{"function": {"name": "terminal"}}]},
        {"role": "tool", "content": "{...}"},
    ]
    name, args = _called(eval_llm.decide(after_read))
    assert name == "agos_action" and args["actions"][0]["do"] == "create_skill"
    assert args["actions"][0]["name"] == "eval-x"


def test_it_ends_with_the_last_tools_answer() -> None:
    _offer("agos_action")
    done = eval_llm.decide(
        [
            _user("[Tue 2026-11-03 13:00 GMT] eval:label eval-red"),
            {"role": "assistant", "tool_calls": [{"function": {"name": "agos_action"}}]},
            {"role": "tool", "content": '{"results": [{"status": "done"}]}'},
        ]
    )
    assert done["text"].startswith("Eval label done: ") and "done" in done["text"]


def test_a_deferred_plugin_tool_goes_through_hermess_tool_call() -> None:
    _offer("terminal", "tool_search", "tool_describe", "tool_call")
    name, args = _called(eval_llm.decide([_user("eval:label eval-red")]))
    assert name == "tool_call"
    assert args["calls"][0]["name"] == "agos_action"
    assert args["calls"][0]["arguments"]["actions"][0] == {
        "do": "create_label",
        "name": "eval-red",
        "color": "red",
    }


def test_hermess_side_calls_quoting_the_chat_do_not_replay_it() -> None:
    _offer("agos_action")
    side = eval_llm.decide([_user("Review the conversation below.\n\nUser: eval:label eval-red")])
    assert "tool_call" not in side


def test_a_worker_on_a_card_under_review_hands_it_in() -> None:
    _offer("kanban_complete", "tool_call")
    refused = [
        _user("work kanban task t_0123abcd"),
        {"role": "assistant", "tool_calls": [{"function": {"name": "kanban_complete"}}]},
        {"role": "tool", "content": "This card has review stages: finish with agos_review."},
    ]
    name, args = _called(eval_llm.decide(refused))
    assert name == "tool_call"
    assert args["calls"][0] == {
        "name": "agos_review",
        "arguments": {
            "card": "t_0123abcd",
            "verdict": "submit",
            "summary": "Wrote the line; read it back.",
        },
    }
    handed = [
        *refused,
        {
            "role": "assistant",
            "tool_calls": [{"function": {"name": "tool_call", "arguments": "agos_review"}}],
        },
        {"role": "tool", "content": "ok"},
    ]
    assert eval_llm.decide(handed) == {"text": "Card t_0123abcd handed in for review."}


def test_a_plain_card_worker_still_completes_its_card() -> None:
    _offer("kanban_complete")
    name, args = _called(eval_llm.decide([_user("work kanban task t_0123abcd")]))
    assert name == "kanban_complete" and args["task_id"] == "t_0123abcd"
