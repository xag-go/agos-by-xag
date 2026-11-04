"""The owner's account-wide preferences kept in AGOS (app_settings): the usage
thresholds that pause new work, the order of the workspace tabs and the order of
the workspaces on the rail. The same in every workspace; no Hermes setting.

Must not: write a Hermes setting, or know about HTTP (api/settings_account.py maps it).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agos_core.db import workspaces as workspaces_repo
from agos_core.db.app_settings import get_setting, set_setting

__all__ = [
    "TABS",
    "UsageRule",
    "save_tabs",
    "save_usage",
    "save_workspace_order",
    "tabs_order",
    "usage_prefs",
]


class UsageRule(BaseModel):
    """When AGOS warns about an account's limits and when it pauses new work (%).
    Read as the page's body (api/settings_account.py UsagePrefs) was saved."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    enabled: bool = True
    warn_at: int = Field(default=80, ge=1, le=100)
    pause_at: int = Field(default=100, ge=1, le=100)


def usage_prefs(core: Any) -> UsageRule:
    return UsageRule.model_validate(get_setting(core.db, "usage", {}))


def save_usage(core: Any, enabled: bool, warn_at: int, pause_at: int) -> None:
    """A pause below the warning is raised to it (he is warned before work waits)."""
    rule = UsageRule(enabled=enabled, warn_at=warn_at, pause_at=max(pause_at, warn_at))
    set_setting(core.db, "usage", rule.model_dump())


# ---- workspace tabs: the owner's order, the same in every workspace --------------

TABS = (
    "dashboard",
    "office",
    "kanban",
    "inbox",
    "sessions",
    "hierarchy",
    "vision",
    "status",
    "messages",
    "automations",
    "docs",
    "artifacts",
    "screen",
    "log",
    "search",
)

# Tabs AGOS added later go next to the one they belong with, not at the end.
_PLACED_AFTER = {
    "office": "dashboard",
    "inbox": "kanban",
    "artifacts": "docs",
    "vision": "hierarchy",
    "status": "vision",
}
# A tab's name before AGOS renamed it: a saved order keeps its place (step 53: the
# Goals tab became the Vision page; the Board became the Kanban, and its old
# /board address is left free for a new page).
_RENAMED = {"goals": "vision", "board": "kanban"}


def _filled(order: list[str]) -> list[str]:
    order = order + [t for t in TABS if t not in order and t not in _PLACED_AFTER]
    for tab, after in _PLACED_AFTER.items():
        if tab not in order:
            order.insert(order.index(after) + 1 if after in order else len(order), tab)
    return order


def tabs_order(core: Any) -> list[str]:
    """Saved order, cleaned: unknown tabs dropped, missing (new) tabs put back in."""
    saved = get_setting(core.db, "tabs", [])
    names = [_RENAMED.get(str(t), str(t)) for t in saved] if isinstance(saved, list) else []
    order = list(dict.fromkeys(t for t in names if t in TABS))
    return _filled(order)


def save_tabs(core: Any, order: list[str]) -> None:
    clean = list(dict.fromkeys(_RENAMED.get(t, t) for t in order if _RENAMED.get(t, t) in TABS))
    set_setting(core.db, "tabs", _filled(clean))


# ---- the workspaces' order on the rail (dragged there) -----------------------------


def save_workspace_order(core: Any, order: list[str]) -> None:
    workspaces_repo.save_order(core.db, order)
