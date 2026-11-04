"""What a Hermes session's messages say about skills (pure; moved out of
actions/skill_growth.py, which reads the session)."""

from __future__ import annotations

import contextlib
import json
from typing import Any


def called_skills(tool_calls: Any) -> set[str]:
    """The skills an assistant message read or changed (its skill_view / skill_manage
    calls' `name`): SkillClaw's _skills_referenced (injected skills don't count)."""
    try:
        calls = json.loads(tool_calls) if isinstance(tool_calls, str) else tool_calls
    except ValueError:
        return set()
    found: set[str] = set()
    for call in calls if isinstance(calls, list) else []:
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict) or fn.get("name") not in ("skill_view", "skill_manage"):
            continue
        args = fn.get("arguments")
        try:
            parsed = json.loads(args) if isinstance(args, str) else args
        except ValueError:
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), str):
            found.add(parsed["name"].strip())
    return found


def tool_error(content: Any) -> str:
    """A tool result that says it failed (Hermes's tools answer JSON with `error`)."""
    text = str(content or "").strip()
    if text.lower().startswith(("error:", "error ")):
        return text
    if text.startswith("{"):
        with contextlib.suppress(ValueError):
            data = json.loads(text)
            if isinstance(data, dict) and data.get("error") and data.get("success") is not True:
                return str(data.get("error"))
    return ""
