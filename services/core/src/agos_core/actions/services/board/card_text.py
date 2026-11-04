"""The rules of a card's text (no Hermes call, no database): its success criteria
and skill-pins block, its result as words, why it waits for the owner, an event's
detail, and the argv / summary rule of Hermes's `kanban complete`.

Owns: those text rules. Must not: read or write a card (actions/kanban_board.py).
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "PINS_BLOCK",
    "complete_args",
    "done_needs_summary",
    "readable_result",
    "skill_pins",
    "with_criteria",
    "without_pins",
]


def _question(raw: dict[str, Any]) -> str:
    """Why it waits for him: the reason of its latest block."""
    for event in reversed(raw.get("events") or []):
        if isinstance(event, dict) and event.get("kind") == "blocked":
            payload = event.get("payload") or {}
            return str(payload.get("reason") or "") if isinstance(payload, dict) else ""
    return ""


def _event_detail(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("reason", "summary", "assignee", "error"):
        if payload.get(key):
            return str(payload[key])[:300]
    return ""


def with_criteria(body: str, criteria: list[str]) -> str:
    """Success criteria live in the card's text (the goal judge reads them there)."""
    items = [c.strip() for c in criteria if c.strip()]
    if not items:
        return body.strip()
    listed = "\n".join(f"- {c}" for c in items)
    return f"{body.strip()}\n\n## Success criteria\n{listed}".strip()


PINS_BLOCK = "agos-skill-pins"  # {skill name: version number} in the card's body


def skill_pins(body: str) -> list[dict[str, Any]]:
    """The skill versions a card was made with (its pins block), as shown."""
    from agos_core.engine import card_blocks

    found = card_blocks.read_block(body, PINS_BLOCK) or {}
    return [
        {"skill": str(k), "version": int(v)}
        for k, v in sorted(found.items())
        if isinstance(v, int) and not isinstance(v, bool)
    ]


def without_pins(body: str) -> str:
    from agos_core.engine import card_blocks

    return card_blocks.strip_block(body, PINS_BLOCK)


def readable_result(text: str) -> str:
    """A card's result as words: some results are a run's raw JSON record
    ({"status": ..., "output": "..."}); show its output."""
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            return text
        if isinstance(data, dict):
            for key in ("output", "summary", "result", "text"):
                if isinstance(data.get(key), str) and data[key].strip():
                    return str(data[key])
    return text


def done_needs_summary(status: str, result: Any) -> bool:
    """Hermes refuses to finish this card without words on what was done: its
    empty-completion gate (hermes_cli/kanban_db.py _gate_empty_completion) lets
    a card out of `review` go (the human approving it is the record) and one that
    already holds a result (a stripped `tasks.result`); any other needs
    --result/--summary. Hermes's own dashboard asks for that summary there."""
    if status == "review":
        return False
    return not (result is not None and str(result).strip())


def complete_args(card_id: str, summary: str = "") -> list[str]:
    """`hermes kanban complete`'s argv; his words on what was done go the way
    Hermes's own dashboard sends them on a move to done (its completion prompt:
    plugins/kanban/dashboard performMoveTask / withCompletionSummary set both
    `result` and `summary` to his text): the card's result and the closing run's
    summary. `--flag=text`, so a text that starts with "-" stays text. No words, no
    flag: AGOS never makes some up (Hermes then decides, and says why)."""
    text = summary.strip()
    if not text:
        return ["complete", card_id]
    return ["complete", card_id, f"--result={text}", f"--summary={text}"]
