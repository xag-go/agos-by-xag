"""The Board's saved views and bulk actions (Step 58, F17).

A view is the owner's way of looking at the board (filters, group-by, sort, layout,
the list's columns): UI state Hermes has no notion of, kept per workspace in AGOS's
preferences (app_settings `board.views.<workspace>`). Filtering and grouping happen
in the browser over the board's one read, so a view costs no extra Hermes call; the
page's URL carries the view (`?view=<id>` or the filters themselves).

Bulk actions on the selected cards go to Hermes batched: its own multi-card CLI for
the board's buttons (archive / complete / unblock / block --ids), one Hermes process
for assign and labels (kanban_board._bulk).
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.connection import transaction

SETTING = "board.views.{}"
MAX_VIEWS = 30
GROUPS = ("status", "member", "label", "goal", "project")
SORTS = ("created-desc", "created-asc", "title", "priority", "status")
LAYOUTS = ("board", "list")
COLUMNS = ("id", "title", "status", "member", "labels", "goal", "review", "created", "priority")
BULK = ("assign", "label", "unblock", "done", "block", "archive")
MAX_BULK = 200


def listing(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    found = get_setting(core.db, SETTING.format(workspace_id), [])
    return [v for v in found if isinstance(v, dict)] if isinstance(found, list) else []


def save(core: Core, workspace_id: str, view: dict[str, Any]) -> dict[str, Any]:
    """A new view (no id) or the same view changed (its id). Names are unique."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    name = " ".join(str(view.get("name") or "").split())[:60]
    if not name:
        raise ActionError("Give the view a name.")
    views = listing(core, workspace_id)
    view_id = int(view.get("id") or 0)
    if view_id and not any(v.get("id") == view_id for v in views):
        raise NotFoundError("This view")
    if any(v.get("name", "").lower() == name.lower() and v.get("id") != view_id for v in views):
        raise ActionError("A view with this name exists already.")
    if not view_id and len(views) >= MAX_VIEWS:
        raise ActionError(f"{MAX_VIEWS} saved views at most.")
    clean = {
        "id": view_id or max((int(v.get("id") or 0) for v in views), default=0) + 1,
        "name": name,
        "filters": dict(view.get("filters") or {}),
        "groupBy": view.get("groupBy") if view.get("groupBy") in GROUPS else "status",
        "sort": view.get("sort") if view.get("sort") in SORTS else "created-desc",
        "layout": view.get("layout") if view.get("layout") in LAYOUTS else "board",
        "columns": [c for c in view.get("columns") or [] if c in COLUMNS] or list(COLUMNS[:5]),
    }
    kept = [clean if v.get("id") == clean["id"] else v for v in views]
    if not view_id:
        kept.append(clean)
    with transaction(core.db):
        set_setting(core.db, SETTING.format(workspace_id), kept)
    return clean


def remove(core: Core, workspace_id: str, view_id: int) -> None:
    views = listing(core, workspace_id)
    if not any(v.get("id") == view_id for v in views):
        raise NotFoundError("This view")
    with transaction(core.db):
        set_setting(
            core.db, SETTING.format(workspace_id), [v for v in views if v.get("id") != view_id]
        )


def bulk(
    core: Core,
    workspace_id: str,
    cards: list[str],
    action: str,
    *,
    member: str = "",
    add: list[int] | None = None,
    remove: list[int] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    """One action on the selected cards, batched into Hermes. {done, failed}."""
    from agos_core.actions import kanban_board, labels

    picked = list(dict.fromkeys(c for c in cards if c))
    if not picked:
        raise ActionError("Select some cards first.")
    if len(picked) > MAX_BULK:
        raise ActionError(f"{MAX_BULK} cards at most at once.")
    if action == "assign":
        # The owner's own bulk move: he may give cards to himself (the Founder).
        return kanban_board.assign_many(core, workspace_id, picked, member, founder=True)
    if action == "label":
        return labels.apply(core, workspace_id, picked, add=add or [], remove=remove or [])
    if action in ("unblock", "done", "block", "archive"):
        if action == "done" and not summary.strip():
            # Hermes refuses most cards without words on what was done; AGOS never
            # makes some up (kanban_board.complete_args).
            raise ActionError("Write what was done first.")
        return kanban_board.act_many(core, workspace_id, picked, action, summary)
    raise ActionError("Unknown action.")
