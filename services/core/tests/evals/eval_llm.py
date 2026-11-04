"""The agent evals' scripted model: tests/e2e/fake_llm.py plus the eval turns.

Run: python eval_llm.py <port> <log file>

A Co-Founder DM whose owner message holds `eval:<scenario> <name>` plays that
scenario's tool calls in order, one per model step, then answers
"Eval <scenario> done: <the last tool's answer>":

- `eval:label <name>`: agos_action create_label (a WORK action);
- `eval:skill <name>`: agos_action create_skill (a POWER action, untainted turn);
- `eval:taint <name>`: terminal `curl` first (an outside read marks the session), then
  agos_action create_skill (a POWER action in a tainted turn: AGOS must ask first).

A card's worker whose kanban_complete AGOS refuses (the card has review stages)
hands it in with agos_review `submit`. Everything else is fake_llm.py's own script
(rooms, Kanban workers, DMs), so the evals' rig keeps the e2e behaviour.
"""

from __future__ import annotations

import io
import json
import re
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
import fake_llm

__all__ = ["SCRIPTS", "decide", "steps_for"]

_BASE = fake_llm.decide
# The owner's message starts with it (after Hermes's time stamp): Hermes's own side
# calls (memory review, titles) quote the conversation and must not replay it.
_MARK = re.compile(r"^\s*(?:\[[^\]\n]*\]\s*)*eval:([a-z]+)\s+([A-Za-z0-9_-]+)")
_REQUEST = threading.local()  # the tools this thread's request offers (Handler)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0


def _skill(name: str) -> dict[str, Any]:
    return {
        "actions": [
            {
                "do": "create_skill",
                "name": name,
                "title": name.replace("-", " ").title(),
                "description": "Use when an eval asks for it.",
                "instructions": "Say that the eval skill ran.",
            }
        ]
    }


SCRIPTS: dict[str, Any] = {
    "label": lambda name: [
        ("agos_action", {"actions": [{"do": "create_label", "name": name, "color": "red"}]})
    ],
    "skill": lambda name: [("agos_action", _skill(name))],
    "taint": lambda name: [
        ("terminal", {"command": f"curl -s http://127.0.0.1:{PORT}/v1/models"}),
        ("agos_action", _skill(name)),
    ],
}


def steps_for(prompt: str) -> tuple[str, list[tuple[str, dict[str, Any]]]] | None:
    found = _MARK.search(prompt)
    if found is None or found.group(1) not in SCRIPTS:
        return None
    return found.group(1), list(SCRIPTS[found.group(1)](found.group(2)))


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    offered = getattr(_REQUEST, "tools", None)
    if offered is not None and name not in offered and "tool_call" in offered:
        # Hermes's tool search keeps the plugin's tools behind its bridge tools
        # (tools/tool_search.py): the call goes through `tool_call`.
        return fake_llm._tool_call("tool_call", {"calls": [{"name": name, "arguments": args}]})
    return fake_llm._tool_call(name, args)


def _reviewed_worker(card: str, since: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A card worker whose kanban_complete AGOS refused (the card has review stages)
    hands the card in with agos_review `submit`, then stops."""
    calls = json.dumps([m.get("tool_calls") for m in since if m.get("role") == "assistant"])
    if "agos_review" in calls:
        return {"text": f"Card {card} handed in for review."}
    said = [fake_llm._text(m.get("content")) for m in since if m.get("role") == "tool"]
    if "kanban_complete" in calls and said and "review" in said[-1].lower():
        return _call(
            "agos_review",
            {"card": card, "verdict": "submit", "summary": "Wrote the line; read it back."},
        )
    return None


def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not users:
        return _BASE(messages)
    prompt = fake_llm._text(messages[users[-1]].get("content"))
    card = re.match(r"work kanban task (t_[0-9a-f]+)", prompt.strip())
    if card is not None:
        handed = _reviewed_worker(card.group(1), messages[users[-1] + 1 :])
        if handed is not None:
            return handed
    planned = steps_for(prompt)
    if planned is None or fake_llm._handle_of(prompt) is not None:
        return _BASE(messages)
    scenario, steps = planned
    since = messages[users[-1] + 1 :]
    made = sum(len(m.get("tool_calls") or []) for m in since if m.get("role") == "assistant")
    if made < len(steps):
        name, args = steps[made]
        return _call(name, args)
    said = [fake_llm._text(m.get("content")) for m in since if m.get("role") == "tool"]
    last = said[-1] if said else ""
    return {"text": f"Eval {scenario} done: {json.dumps(last)[:400]}"}


class Handler(fake_llm.Handler):
    """fake_llm's handler; also writes which tools each request offered (tools.jsonl
    beside the log): a scenario's check that the agent had its tool at all."""

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
            names = sorted(
                str((t.get("function") or {}).get("name") or "") for t in body.get("tools") or []
            )
            _REQUEST.tools = set(names)
            with Path(fake_llm.LOG).with_name("tools.jsonl").open("a") as out:
                out.write(json.dumps({"tools": names}) + "\n")
        except (ValueError, OSError, AttributeError):
            _REQUEST.tools = None
        self.rfile = io.BytesIO(raw)
        super().do_POST()


if __name__ == "__main__":
    fake_llm.decide = decide  # its Handler looks `decide` up per request
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
