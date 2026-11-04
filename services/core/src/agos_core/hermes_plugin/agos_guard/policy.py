"""The owner's Autonomy rules, as this profile's policy file says them.

Split out of agos_core.hermes_plugin.agos_guard (the guard's facade). Owns: reading
agos-guard.json (cached by its mtime), the action type of a tool call, and the
owner's rule for it (do / ask / never) for one agent.

Must not: ask the owner or act on the rule (the facade's _verdict and
owner_approval.py do).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import runtime
from .guard_contract import ACTIONS, ASK_MARK, POLICY_FILE

__all__ = [
    "READ_TOOLS",
    "_DELETE_VERBS",
    "_READ_VERBS",
    "_cache",
    "_policy",
    "action_of",
    "decide",
]

# Tools that only read (the watcher may use these and nothing else).
READ_TOOLS = {
    "read_file",
    "search_files",
    "session_search",
    "skills_list",
    "skill_view",
    "web_search",
    "web_extract",
    "vision_analyze",
    "todo_list",
    "clarify",
}


_READ_VERBS = re.compile(
    r"(^|_)(list|get|read|search|find|query|fetch|view|show|describe|count|lookup|status"
    r"|info|details|metadata|meta|download|export|preview|inspect|tabs|peek|history)(_|$)"
)


_DELETE_VERBS = re.compile(r"(^|_)(delete|remove|trash|destroy|purge|archive)(_|$)")


_cache: dict[str, Any] = {"path": None, "mtime": None, "policy": {}}


# Tools that always do one kind of thing (the rest are found by their name's shape).
_ACTION_OF_TOOL = {
    "write_file": "files",
    "patch": "files",
    "terminal": "commands",
    "execute_code": "commands",
    "process": "commands",
    "send_message": "messages",
    "computer_use": "desktop",
    "image_generate": "images",
    "text_to_speech": "images",
    "kanban_create": "cards",
    "memory": "memory",
    "skill_manage": "memory",
}
_BROWSER_LOOKS = {"browser_snapshot", "browser_get_images", "browser_vision"}


def action_of(tool: str, args: dict[str, Any] | None = None) -> str | None:
    """The action type of a tool call, or None when it only reads."""
    name = tool.lower()
    if name in READ_TOOLS:
        return None
    if name in _ACTION_OF_TOOL:
        return _ACTION_OF_TOOL[name]
    if name.startswith("browser_"):
        return None if name in _BROWSER_LOOKS else "browser"
    if name.startswith("computer_use"):
        return "desktop"
    if name.startswith("mcp_"):
        return _app_action(name, args)
    return None


def _app_action(name: str, args: dict[str, Any] | None) -> str | None:
    """A connected app's tool (mcp_*): a delete, a read, or a change."""
    # Putting a file in the trash through an "update" is a delete.
    if _DELETE_VERBS.search(name) or (args or {}).get("trashed") in (True, "true"):
        return "apps_delete"
    if _READ_VERBS.search(name):
        return None
    return "apps_change"


def _policy() -> dict[str, Any]:
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        path = Path(get_hermes_home()) / POLICY_FILE
        mtime = path.stat().st_mtime
    except ImportError as error:
        runtime._report("hermes_constants.get_hermes_home", error)
        return {}
    except OSError:
        return {}
    if _cache["path"] != path or _cache["mtime"] != mtime:
        try:
            _cache.update(path=path, mtime=mtime, policy=json.loads(path.read_text()))
        except (OSError, ValueError):
            _cache.update(path=path, mtime=mtime, policy={})
    policy: dict[str, Any] = _cache["policy"]
    return policy


def decide(
    policy: dict[str, Any], agent: str, tool: str, args: dict[str, Any] | None
) -> dict[str, str] | None:
    """The owner's rule for this agent's tool call ("" = the Co-Founder)."""
    action = action_of(tool, args)
    if action is None:
        return None
    rules = policy.get("rules") or {}
    choice = (rules.get(agent) or {}).get(action) or (rules.get("*") or {}).get(action) or "do"
    label = ACTIONS.get(action, action)
    if choice == "never":
        return {
            "action": "block",
            "message": f"Blocked by the owner's rule: “{label}” is set to Never for you. "
            "Don't try another way; say what you would have done instead.",
        }
    if action == "memory":
        # Ask me / Do it is Hermes's own write_approval gate in this profile (it holds
        # the write for his review, Full access or not): no second question here.
        return None
    if choice == "ask":
        return {
            "action": "approve",
            "message": f"{ASK_MARK} {label}: {tool}",
            "rule_key": f"agos:{action}",
        }
    return None
