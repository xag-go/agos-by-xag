"""AGOS's checks on single tools, beside the owner's Autonomy rules.

Split out of agos_core.hermes_plugin.agos_guard (the guard's facade). Owns: the
consent gate on an agent's own instructions (consent.py), reads that see the real
file, workspace and AGOS skills an agent can't change, other workspaces'
conversations, and a member giving the Founder (the owner) a card.

Must not: read the owner's rules or ask him.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import runtime

__all__ = [
    "CONSENT_TOOLS",
    "FOUNDER",
    "FOUNDER_REFUSED",
    "_FOUNDER_WORD",
    "_READS",
    "founder_refused",
    "fresh_read",
    "other_workspace",
    "own_instructions",
    "shared_skill",
]

_READS = {"read_file", "search_files"}


def own_instructions(tool: str, args: dict[str, Any]) -> dict[str, str] | None:
    """The consent gate (consent.py): the agent's own SOUL.md / config.yaml /
    AGENTS.md / profile.yaml change only through an approved instructions
    proposal; the approved content passes once. Fails open only when the profile
    home itself can't be known (an AGOS internal error, reported once)."""
    if tool not in CONSENT_TOOLS:
        return None
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        home = Path(get_hermes_home())
    except ImportError as error:
        runtime._report("hermes_constants.get_hermes_home", error)
        return None
    try:
        verdict: dict[str, str] | None = runtime._sibling("consent").gate(tool, args, home)
    except Exception as error:  # noqa: BLE001 — AGOS's own code failed: Hermes's checks apply
        runtime._report("agos_guard.consent.gate", error)
        return None
    return verdict


CONSENT_TOOLS = {"write_file", "patch", "terminal", "execute_code", "process", "skill_manage"}


def fresh_read(tool: str, task_id: str) -> None:
    """Every read sees the real file. Hermes keeps a 'not found' for 60 s (its
    exists() check runs on the host, so it can't see a file created in the
    sandbox) and blocks a 4th identical read as 'not changed' even when it
    changed: an agent checking the same file again and again (a watch) would
    then tell the owner something false."""
    if tool not in _READS:
        return
    try:
        from tools.file_tools_read_tracking import (  # type: ignore[import-not-found]
            notify_other_tool_call,
        )
    except ImportError as error:
        runtime._report("tools.file_tools_read_tracking.notify_other_tool_call", error)
        return
    try:
        notify_other_tool_call(task_id or "default")
    except Exception as error:  # noqa: BLE001 — never break a read for this
        runtime._report("tools.file_tools_read_tracking.notify_other_tool_call", error)
        return


def shared_skill(name: str, args: dict[str, Any]) -> bool:
    """skill_manage would change a skill Hermes reads from skills.external_dirs: a
    member's workspace skills (its Co-Founder's folder), AGOS's own and the Brain's
    (shared by every workspace). Refused, so only the Co-Founder (whose workspace
    skills are its own local ones) and the owner change them, and nothing one
    workspace's agents write reaches another's. A profile's local skills are its own."""
    if not name or str(args.get("action") or "") == "create":
        return False
    step = "agent.skill_utils.is_external_skill_path"
    try:
        from agent.skill_utils import (  # type: ignore[import-not-found]
            is_external_skill_path,
        )

        step = "tools.skill_manager_tool._find_skill"
        from tools.skill_manager_tool import _find_skill  # type: ignore[import-not-found]
    except ImportError as error:
        runtime._report(step, error)
        return False
    try:
        # (No public name-to-path resolver in Hermes v0.22.2: _find_skill stays.)
        step = "tools.skill_manager_tool._find_skill"
        found = _find_skill(name)
        if not found:
            return False
        # Hermes's own ownership test: under skills.external_dirs or a trusted
        # project skills folder (agent/skill_utils.py is_external_skill_path).
        step = "agent.skill_utils.is_external_skill_path"
        return bool(is_external_skill_path(found["path"]))
    except Exception as error:  # noqa: BLE001 - unknown = Hermes's own checks apply
        runtime._report(step, error)
        return False


# The Founder: the owner himself as a card's assignee (AGOS actions/founder.py). Only
# the Co-Founder (and the owner) give him tasks; a member asks its lead instead.
FOUNDER = "founder"


FOUNDER_REFUSED = (
    "Only the Co-Founder gives the Founder (the owner, a person) a task. Don't assign "
    "or create cards for founder: ask your lead or the Co-Founder for what you need "
    "from him (or agos_ask_owner), and say what it unblocks."
)


_FOUNDER_WORD = re.compile(r"(?<![A-Za-z0-9_-])founder(?![A-Za-z0-9_-])")


def founder_refused(tool: str, args: dict[str, Any]) -> bool:
    """A member's call that would give the Founder a card: Hermes's kanban_create with
    assignee founder, or a `hermes kanban` command (create / assign) naming him."""
    if tool == "kanban_create":
        return str(args.get("assignee") or "").strip().lower() == FOUNDER
    if tool in ("terminal", "execute_code"):
        text = str(args.get("command") or args.get("code") or "")
        return (
            "kanban" in text
            and bool(_FOUNDER_WORD.search(text))
            and ("assign" in text or "create" in text)
        )
    return False


def other_workspace(args: dict[str, Any], own: str | None = None) -> str:
    """session_search may read another profile's conversations (profile=, or an
    @session:<profile>/<id> link). Only this workspace's: the Co-Founder reads its own
    team members'; a member reads only its own."""
    own = runtime._own_profile() if own is None else own
    asked = str(args.get("profile") or "").strip()
    sid = str(args.get("session_id") or "")
    if not asked and "/" in sid:
        asked = sid.removeprefix("@session:").partition("/")[0].strip()
    if not asked or asked == own:
        return ""
    if own and "--a-" not in own and asked.startswith(own + "--a-"):
        return ""  # the Co-Founder reading one of its own team members
    return (
        "Not allowed: that is not this workspace's Hermes. Each workspace is closed off "
        "from the others; read only your own conversations"
        + ("" if "--a-" in own else " and your team members'")
        + "."
    )
