"""Running an import: the plan's steps in order, the bundle's model, the report.
Must not: hold any piece's import (import_steps does).

Split out of agos_core.actions.portability (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.portability.import_report import (
    Plan,
    Report,
    _review,
    _strategies,
    check_inputs,
)
from agos_core.actions.services.portability.import_steps import (
    import_agents,
    import_automations,
    import_folders,
    import_keys,
    import_skills,
    import_vision,
)
from agos_core.actions.services.portability.preview import parsed
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db.activity import add_activity
from agos_core.domain.models import ModelSelection
from agos_core.engine import bundle as fmt
from agos_core.engine.hermes import EngineError

__all__ = [
    "apply",
]


def apply(
    core: Core,
    files: dict[str, str],
    *,
    workspace_id: str | None,
    name: str = "",
    default_model: ModelSelection | None = None,
    strategies: dict[str, str] | None = None,
    inputs: dict[str, str] | None = None,
    later: list[str] | None = None,
    under: str = "",
    who: str = "import",
    why: str = "imported from a bundle",
) -> tuple[Report, fmt.Parsed]:
    """Imports the bundle into `workspace_id`, or into a new workspace (`name`,
    `default_model`) when None. Everything goes through AGOS's own writers."""
    from agos_core.actions import team
    from agos_core.actions.engine import write_identity
    from agos_core.actions.workspaces import create_workspace

    found = parsed(files)
    plan = Plan(
        strategies=_strategies(strategies),
        inputs={k: str(v) for k, v in (inputs or {}).items()},
        later=set(later or []),
        under=under.strip().lstrip("@"),
        who=who,
        why=why,
    )
    check_inputs(found, plan.inputs, plan.later)
    if workspace_id is None:
        settings_ws = found.settings.get("workspace") or {}
        model = default_model or _bundle_model(found)
        if model is None:
            raise ActionError("Pick the new workspace's model.", 400)
        workspace_id = create_workspace(
            core,
            name=name.strip() or str(settings_ws.get("name") or found.name or "Imported"),
            description=str(settings_ws.get("description") or found.meta.get("description") or ""),
            default_model=model,
        )
        new = True
    else:
        require_workspace(core, workspace_id)
        new = False
        if plan.under and team.get(core, workspace_id, plan.under) is None:
            raise NotFoundError("That lead")
    report = Report(workspace_id)
    skills = import_skills(core, workspace_id, found, plan, report)
    agents = import_agents(core, workspace_id, found, plan, report, skills)
    import_automations(core, workspace_id, found, plan, report, agents)
    import_vision(core, workspace_id, found, plan, report, agents)
    import_folders(core, workspace_id, found, report)
    if found.cofounder and (new or plan.strategies["agents"] == "replace"):
        with contextlib.suppress(EngineError, OSError):
            write_identity(core, workspace_id, own=found.cofounder)
            report.add("cofounder", "Co-Founder identity", "created" if new else "replaced")
    review = found.settings.get("review")
    if isinstance(review, dict) and (new or plan.strategies["agents"] == "replace"):
        _review(core, workspace_id, review, agents, report)
    import_keys(core, workspace_id, found, plan, report)
    report.needs_owner.append(
        {
            "kind": "telegram",
            "name": "Telegram",
            "text": "Connect a Telegram bot and the members' topics in Settings → Channels, if you want them.",
        }
    )
    add_activity(
        core.db,
        workspace_id,
        kind="workspace.imported",
        text=f"Imported {found.name or 'a bundle'}: "
        f"{sum(1 for i in report.items if i['result'] in ('created', 'renamed', 'replaced'))} items",
    )
    return report, found


def _bundle_model(found: fmt.Parsed) -> ModelSelection | None:
    raw = found.settings.get("default_model")
    if not isinstance(raw, dict):
        return None
    try:
        return ModelSelection.model_validate(raw)
    except ValueError:
        return None
