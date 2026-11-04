"""The agents' tools for the owner (agos_guard/asks.py): agos_propose and
agos_ask_owner post to AGOS, which writes the card the parsers read; a question
asked while working a card is linked by the owning run (Hermes's rule) and the
agent is told to block as a dependency. The block hook tells AGOS about a card
that waits for a teammate too."""

from __future__ import annotations

import json
import sys
import types
from typing import Any

import pytest

from agos_core.hermes_plugin import agos_guard
from agos_core.hermes_plugin.agos_guard import asks


class Posts:
    def __init__(self, answer: dict[str, Any] | None) -> None:
        self.answer = answer
        self.sent: list[tuple[str, dict[str, Any], float]] = []

    def __call__(
        self, path: str, body: dict[str, Any], timeout: float = 30
    ) -> dict[str, Any] | None:
        self.sent.append((path, body, timeout))
        return self.answer


def test_the_tools_are_registered_for_every_agent_with_their_schemas() -> None:
    registered: list[dict[str, Any]] = []

    class Ctx:
        def register_tool(self, **kw: Any) -> None:
            registered.append(kw)

    import contextlib

    asks.register(
        Ctx(),
        member_of=lambda: "editor",
        post=Posts(None),
        guard=lambda _n: contextlib.nullcontext(),
    )
    assert [r["name"] for r in registered] == ["agos_propose", "agos_ask_owner"]
    assert all(r["toolset"] == "agos" for r in registered)
    propose = registered[0]["schema"]["parameters"]
    assert propose["properties"]["kind"]["enum"] == ["hire", "instructions", "plan", "goal", "kit"]
    ask = registered[1]["schema"]["parameters"]
    assert ask["properties"]["kind"]["enum"] == [
        "ask",
        "confirm",
        "choice",
        "checkbox",
        "verdicts",
        "suggest_tasks",
    ]
    # The handlers carry the member AGOS told the guard (the policy file).
    answer = json.loads(registered[1]["handler"]({"kind": "ask", "question": "q"}))
    assert answer == {"error": "AGOS can't be reached; nothing was asked."}


def test_propose_posts_the_proposal_and_tells_the_agent_where_it_is(monkeypatch: Any) -> None:
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_work")
    posts = Posts({"card": "t_p", "ask_id": 4, "proposed": True})
    out = json.loads(
        asks.propose_tool(
            {
                "kind": "plan",
                "payload": {"title": "P", "markdown": "# p"},
                "words": "Here.",
                "revises": "t_old",
            },
            member="editor",
            post=posts,
        )
    )
    [(path, body, _timeout)] = posts.sent
    assert path == "propose"
    assert body == {
        "member": "editor",
        "kind": "plan",
        "payload": {"title": "P", "markdown": "# p"},
        "words": "Here.",
        "revises": "t_old",
        "card": "t_work",
    }
    assert out["card"] == "t_p" and "card t_p in the owner's Inbox" in out["next"]
    # AGOS's refusal is the tool's answer, as is.
    refused = json.loads(
        asks.propose_tool({"kind": "plan", "payload": {}}, member="", post=Posts({"error": "x"}))
    )
    assert refused == {"error": "x"}


def test_ask_owner_from_a_chat_needs_no_block(monkeypatch: Any) -> None:
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    posts = Posts({"card": "t_q", "ask_id": 7})
    out = json.loads(
        asks.ask_owner_tool(
            {"kind": "choice", "question": "Tone?", "options": ["A", "B"], "continuation": "none"},
            member="",
            post=posts,
        )
    )
    [(path, body, _timeout)] = posts.sent
    assert path == "ask-owner" and body["kind"] == "choice" and body["member"] == ""
    assert body["payload"] == {"question": "Tone?", "options": ["A", "B"]} and body["card"] == ""
    assert body["continuation"] == "none"
    assert "nothing to do now" in out["next"] and "linked" not in out


def test_ask_owner_from_a_card_links_the_question_as_its_parent_by_the_owning_run(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_work")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "42")
    linked: list[tuple[str, str, int | None]] = []

    class Conn:
        closed = False

        def close(self) -> None:
            self.closed = True

    conn = Conn()
    kb = types.ModuleType("hermes_cli.kanban_db")
    kb.link_tasks = lambda c, parent, child, expected_child_run_id=None: linked.append(  # type: ignore[attr-defined]
        (parent, child, expected_child_run_id)
    )
    kbc = types.ModuleType("hermes_cli.kanban_db_connect")
    kbc.connect = lambda: conn  # type: ignore[attr-defined]
    hermes_cli = types.ModuleType("hermes_cli")
    monkeypatch.setitem(sys.modules, "hermes_cli", hermes_cli)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db", kb)
    monkeypatch.setitem(sys.modules, "hermes_cli.kanban_db_connect", kbc)
    posts = Posts({"card": "t_q", "ask_id": 8})
    out = json.loads(
        asks.ask_owner_tool({"kind": "confirm", "question": "Go?"}, member="editor", post=posts)
    )
    assert posts.sent[0][1]["card"] == "t_work"
    assert linked == [("t_q", "t_work", 42)] and conn.closed
    assert out["linked"] is True
    assert (
        'kanban_block(kind="dependency", reason="waiting for the owner\'s answer on t_q")'
        in out["next"]
    )
    # Hermes refuses the link (the card isn't running any more): the agent is told
    # to finish and name the question card.
    kb.link_tasks = lambda *a, **k: (_ for _ in ()).throw(ValueError("child is already running"))  # type: ignore[attr-defined]
    out = json.loads(
        asks.ask_owner_tool({"kind": "confirm", "question": "Go?"}, member="editor", post=posts)
    )
    assert out["linked"] is False and "t_q holds the open question" in out["next"]
    # No run id: no link (Hermes would refuse it), the same words.
    monkeypatch.delenv("HERMES_KANBAN_RUN_ID")
    out = json.loads(
        asks.ask_owner_tool({"kind": "confirm", "question": "Go?"}, member="editor", post=posts)
    )
    assert out["linked"] is False


@pytest.mark.parametrize(
    ("reason", "told"),
    [
        ("waiting for the owner: Run commands", True),
        ("waiting for the owner: question", True),
        ("Waiting for @writer: send the draft", True),
        ("waiting for @Co-Founder: pick", True),
        ("Which colour?", False),
        ("", False),
    ],
)
def test_the_block_hook_tells_agos_about_blocks_for_a_person(
    monkeypatch: Any, reason: str, told: bool
) -> None:
    posts = Posts({"settled": False})

    class Bridge:
        post = staticmethod(posts)

    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: Bridge)
    agos_guard.blocked_for_owner("t_1", reason)
    assert bool(posts.sent) is told
    if told:
        assert posts.sent[0][:2] == ("kanban-blocked", {"card": "t_1"})
