"""The Co-Founder's agos_action kinds: one catalogue (KINDS) merged from the
operation registry (ops/specs), the one-line domain names of its always-on prompt (DOMAINS),
which fields are structured, and the per-call rules (owner_first, title).

Owns: the gate/title rules of a kind. Must not: define a kind (that lives in the
operation registry's ops/specs) or run one (actions/cofounder_more.py).
"""

from __future__ import annotations

import string
from typing import Any

from agos_core.engine.cofounder_kind import AUTOMATIONS, BOARD, SKILLS, TEAM, WORKSPACE, Kind
from agos_core.ops import catalog as ops_catalog
from agos_core.ops.specs import SPECS

__all__ = ["DOMAINS", "KINDS", "STRUCTURED", "owner_first", "title"]

# One line per domain in the Co-Founder's always-on prompt (cofounder_actions.instructions).
DOMAINS: dict[str, str] = {
    AUTOMATIONS: "card-move rules, heartbeats, automation revisions, a missed run's "
    "catch-up (once / skip), scheduled jobs, webhook address, watched trees",
    TEAM: "groups, hire kits and Readiness, kits for members hired without one, the office "
    "look of members",
    SKILLS: "skill delete / duplicate / update from source / auto-update, Skill Studio "
    "tests and versions, skill growth settings, MCP sign-in, installs",
    BOARD: "labels, saved views, card goal / assignee / archive / hold, bulk changes, "
    "watchers, review stages, card documents, status cards",
    WORKSPACE: "Vision rhythm (daily plan / recap / weekly times) and notes, work hours "
    "(check-in / check-out days, who stays on today, wake an agent now), docs and agent "
    "versions, owner rules and Brain "
    "methods, tool keys (remove / test only), apps, Telegram and channels, templates, "
    "artifacts, workspace export / import, workspace and General settings, backups, Hermes "
    "update, folders of the automations / skills / projects lists, AGOS's Errors list (mark "
    "an error fixed / open it again)",
}

# Every kind is declared in the operation registry (ops/specs): no hand-written row.
KINDS: dict[str, Kind] = ops_catalog.kinds(SPECS)

# Fields read as a list or an object, per kind (engine/cofounder_actions.py _clean).
STRUCTURED: dict[str, frozenset[str]] = {k: frozenset(v.structured) for k, v in KINDS.items()}


def owner_first(do: str, fields: dict[str, Any]) -> bool:
    """Waits for the owner's yes on its card (Hermes's Allow / Deny), in any mode."""
    kind = KINDS.get(do)
    if kind is None:
        return False
    if kind.gate == "owner":
        return True
    # An archive or a cancel can't be taken back by a card's Undo: his call.
    return (do == "card_action" and fields.get("action") == "archive") or (
        do == "hold_cards" and fields.get("action") == "cancel"
    )


class _Blank(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def title(do: str, fields: dict[str, Any]) -> str:
    shown = _Blank(
        {
            k: ("on" if v is True else "off" if v is False else str(v))
            for k, v in fields.items()
            if not isinstance(v, (list, dict))
        }
    )
    text = string.Formatter().vformat(KINDS[do].title, (), shown)
    return " ".join(text.split())[:200]
