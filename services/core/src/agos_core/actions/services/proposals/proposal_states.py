"""A proposal's states and the owner's choices, its kinds, and the goals a proposal can serve.
Must not: read or write a card.

Split out of agos_core.actions.proposals (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.engine import proposals as rules

__all__ = [
    "CHOICE_OF",
    "CONSENT_FILE",
    "FAILED",
    "KEEP_TOKENS",
    "REFUSED",
    "STATUS_OF",
    "TERMINAL",
    "Choice",
    "member_of",
]

log = logging.getLogger("agos_core.actions.proposals")  # the old module's name


def _json(value: Any) -> dict[str, Any]:
    """A row's JSON column as a dict ('' / NULL / not an object = {})."""
    try:
        found = json.loads(value) if value else None
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


Choice = Literal["approve", "revise", "reject"]
# The ask row's status after each decision.
STATUS_OF: dict[str, str] = {"approve": "approved", "revise": "revised", "reject": "rejected"}
CHOICE_OF: dict[str, str] = {v: k for k, v in STATUS_OF.items()}
# The marker AGOS writes when a decision's work failed after its marker was on the card.
FAILED = "failed"
TERMINAL = ("approved", "revised", "rejected", "undone")
# The asks' rows that are proposals (an SQL list; the kinds are AGOS's own words).
_KINDS = ", ".join(f"'{k}'" for k in rules.KINDS)
CONSENT_FILE = "agos-consent.json"
KEEP_TOKENS = 50


REFUSED = "[agos-refused]"


# ---- reading --------------------------------------------------------------------------


def _goals_of(core: Core, workspace_id: str) -> dict[int, dict[str, Any]]:
    """The workspace's goals and projects by id (one read): what a hire serves."""
    return {
        int(g["id"]): {
            "title": str(g["title"]),
            "level": "vision" if g["parent_id"] is None else str(g["level"] or "") or "goal",
            "status": str(g["status"]),
        }
        for g in goals_repo.rows(core.db, workspace_id)
    }


def member_of(assignee: str) -> str:
    """The team member a card's assignee is ("" = the Co-Founder): Hermes names a
    member's profile a-<name> in the workspace's root (actions/team.py PREFIX)."""
    from agos_core.actions.team import PREFIX

    return assignee[len(PREFIX) :] if assignee.startswith(PREFIX) else ""
