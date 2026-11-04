"""What a Co-Founder action's card says under its title (moved out of
actions/cofounder_actions.py, which imports it as `_detail`)."""

from __future__ import annotations

from typing import Any

from agos_core.engine import cofounder_actions as rules


def detail(payload: dict[str, Any]) -> str:
    if payload.get("items"):
        lines = []
        for i, item in enumerate(payload["items"], 1):
            fields = item.get("fields") or {}
            lines.append(
                f"{i}. {rules.title_of(rules.Action(str(item['do']), fields))}"
                + (f" — {fields['why']}" if fields.get("why") else "")
            )
        return "\n".join(lines)
    text = str(payload.get("instructions") or payload.get("url") or "")
    steps = payload.get("steps") or []
    if steps:
        lines = []
        for i, s in enumerate(steps, 1):
            who = (
                f"@{s['agent']}"
                if s.get("agent")
                else ("you" if s.get("kind") == "approval" else "Co-Founder")
            )
            after = f" (after {', '.join(s['waits_on'])})" if s.get("waits_on") else ""
            lines.append(f"{i}. {s.get('title') or s.get('key')} — {who}{after}")
        text = "Who does what:\n" + "\n".join(lines) + (f"\n\n{text}" if text else "")
    elif payload.get("agent"):
        text = f"{text}\n\nDone by @{str(payload['agent']).lstrip('@')}".strip()
    return text
