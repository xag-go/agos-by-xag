"""A member's refusal of a Co-Founder tool says what to do, and a repeat in the
same card run is told to stop (agos_guard/cofounder_tools.py)."""

from __future__ import annotations

from typing import Any

import pytest

from agos_core.hermes_plugin import agos_guard
from agos_core.hermes_plugin.agos_guard import cofounder_tools


@pytest.fixture(autouse=True)
def member(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bridge:
        agent_of_session = staticmethod(lambda session: "editor")

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: Bridge)
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "editor", "rules": {}})
    monkeypatch.setattr(agos_guard.tool_checks, "own_instructions", lambda tool, args: None)
    monkeypatch.setattr(agos_guard.board_waits, "answered_block", lambda card, args: None)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_RUN_ID", raising=False)
    cofounder_tools.forget()


def _block(tool: str, args: dict[str, Any] | None = None, session: str = "s1") -> str:
    verdict, asks = agos_guard._verdict(tool, args or {}, session)
    assert verdict is not None and verdict["action"] == "block" and not asks
    return str(verdict["message"])


def test_the_first_refusal_says_to_stop_and_hand_the_card_to_review() -> None:
    message = _block("agos_action", {"actions": [{"do": "update_automation"}]})
    assert message.startswith("Blocked: that is the Co-Founder's tool.")
    assert "Do not retry." in message
    assert "kanban_request_review" in message and "what change is needed" in message
    assert "Already refused" not in message


def test_a_repeat_in_the_same_card_run_is_told_to_stop_whatever_the_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_1")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "7")
    first = _block("agos_action")
    again = _block("agos_action")
    other = _block("kanban_create", {"title": "x"})
    assert not first.startswith("Already refused once")
    for repeat in (again, other):
        assert repeat == "Already refused once — stop and hand to review now. " + first


def test_another_card_run_starts_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_1")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "7")
    _block("agos_action")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "8")
    assert not _block("agos_action").startswith("Already refused once")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_2")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "7")
    assert not _block("agos_action").startswith("Already refused once")


def test_the_look_ahead_does_not_count_as_a_refusal() -> None:
    verdict, _ = agos_guard._verdict("agos_action", {}, "s1", acting=False)
    assert verdict is not None and "Already refused" not in verdict["message"]
    assert not _block("agos_action").startswith("Already refused once")


def test_the_co_founder_is_never_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {"member": "", "rules": {}})
    monkeypatch.setattr(
        agos_guard.runtime,
        "_bridge_module",
        lambda: type(
            "B",
            (),
            {
                "owner_decides": staticmethod(lambda *a: None),
                "agent_of_session": staticmethod(lambda s: ""),
            },
        ),
    )
    for _ in range(2):
        verdict, _asks = agos_guard._verdict("kanban_link", {}, "s1")
        assert not verdict or "Co-Founder's tool" not in str(verdict.get("message"))
