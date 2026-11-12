"""The Co-Founder's actions for the General and workspace settings, limits, voice, backups and Hermes's update.
Must not: hold the logic itself; each calls the page's own action.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.cofounder.action_args import (
    Fields,
    Result,
    flag_arg,
    int_arg,
    text_arg,
)
from agos_core.actions.services.settings import model_routes
from agos_core.context import Core

__all__ = [
    "do_backup_schedule",
    "do_check_update",
    "do_fallback",
    "do_helpers",
    "do_limits",
    "do_rehearse",
    "do_run_backup",
    "do_run_update",
    "do_time_limits",
    "do_voice",
    "do_ws_settings",
    "undo_backup_schedule",
    "undo_fallback",
    "undo_learned",
    "undo_limits",
    "undo_time_limits",
    "undo_voice",
    "undo_ws_settings",
]

# ---- workspace: settings and Hermes -----------------------------------------------------


def _ws_model(value: Any, current: Any) -> Any:
    """The new default model as the page's select gives it: a model id keeps the
    provider (and its mode / effort) the workspace has; a {provider, model, effort,
    mode} object names another provider."""
    from agos_core.domain.models import ModelSelection

    have = current.default_model
    if isinstance(value, dict):
        provider = str(value.get("provider") or have.provider).strip()
        model = str(value.get("model") or "").strip()
        effort = str(value.get("effort") or have.effort).strip()
    else:
        provider, model, effort = have.provider, str(value or "").strip(), have.effort
    if not model:
        raise ActionError("Give the model's id (e.g. claude-sonnet-5).")
    mode = str(value.get("mode") or "") if isinstance(value, dict) else ""
    if mode not in ("cli", "api"):
        # Claude runs on its login; another provider on its key unless it says "cli".
        mode = (
            have.mode if provider == have.provider else ("cli" if provider == "claude" else "api")
        )
    try:
        return ModelSelection.model_validate(
            {"provider": provider, "mode": mode, "model": model, "effort": effort}
        )
    except ValueError as error:
        raise ActionError(f"Not a model AGOS can pick: {provider} / {model}.") from error


def do_ws_settings(core: Core, ws: str, p: Fields) -> Result:
    """Workspace settings, as its page saves them: name, description and default
    model (actions/workspaces.save_settings, its Full access left as it is: that one
    is the owner's) and the page's Hermes settings."""
    from agos_core.actions import hermes_settings
    from agos_core.actions import workspaces as ws_actions
    from agos_core.db.workspaces import get_workspace

    values = {str(k): str(v) for k, v in dict(p.get("values") or {}).items()}
    page = {k: p[k] for k in ("model", "name", "description") if p.get(k) not in (None, "")}
    if not values and not page:
        raise ActionError("Say what to change: model, name, description or values.")
    out: Result = {}
    if page:
        current = get_workspace(core.db, ws)
        if current is None:
            raise NotFoundError("This workspace")
        model = _ws_model(p["model"], current) if "model" in page else current.default_model
        ws_actions.save_settings(
            core,
            ws,
            name=text_arg(p, "name") or current.name,
            description=text_arg(p, "description", current.description),
            default_model=model,
            chat_access=current.chat_access,
        )
        out["page"] = {
            "name": current.name,
            "description": current.description,
            "model": current.default_model.model_dump(),
        }
    if values:
        have = hermes_settings.read(core, ws)
        unknown = sorted(set(values) - set(have))
        if unknown:
            raise ActionError(f"Not on the Workspace settings page: {', '.join(unknown)}.")
        hermes_settings.write(core, ws, values)
        out["before"] = {k: have[k] for k in values}
    return out


def undo_ws_settings(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_settings
    from agos_core.actions import workspaces as ws_actions
    from agos_core.db.workspaces import get_workspace
    from agos_core.domain.models import ModelSelection

    if r.get("before"):
        hermes_settings.write(core, ws, dict(r["before"]))
    page = r.get("page")
    current = get_workspace(core.db, ws)
    if page and current is not None:
        ws_actions.save_settings(
            core,
            ws,
            name=str(page["name"]),
            description=str(page["description"]),
            default_model=ModelSelection.model_validate(page["model"]),
            chat_access=current.chat_access,
        )


_LIMITS = (
    "loop_on",
    "same_error",
    "same_tool_failing",
    "no_progress",
    "time_limit_minutes",
    "members_at_once",
)


def do_limits(core: Core, ws: str, p: Fields) -> Result:
    import dataclasses

    from agos_core.actions import hermes_limits

    before = hermes_limits.shown(core).limits
    changes: dict[str, Any] = {}
    for key in _LIMITS:
        if key in p:
            if key == "loop_on":
                changes[key] = flag_arg(p[key])
            else:
                changes[key] = int_arg(p[key], key) if text_arg(p, key) else None
    hermes_limits.write(core, dataclasses.replace(before, **changes))
    return {"before": dataclasses.asdict(before)}


def undo_limits(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_limits

    hermes_limits.write(core, hermes_limits.Limits(**dict(r["before"])))


def do_time_limits(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hermes_time_limits

    values = {str(k): int_arg(v, str(k)) for k, v in dict(p["values"]).items()}
    shown = hermes_time_limits.read(core)["limits"]
    before = {
        k: int(shown[k].value)
        for k in values
        if k in shown and isinstance(getattr(shown[k], "value", None), int)
    }
    hermes_time_limits.write(core, values)
    return {"before": before}


def undo_time_limits(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_time_limits

    if not r.get("before"):
        raise ActionError("The engine's earlier values weren't readable: set them again by hand.")
    hermes_time_limits.write(core, {str(k): int(v) for k, v in dict(r["before"]).items()})


def do_helpers(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hermes_helper_models

    hermes_helper_models.write(
        core,
        {str(k): str(v) for k, v in dict(p.get("sets") or {}).items()},
        [str(k) for k in p.get("unsets") or []],
        dict(p.get("picks") or {}) or None,
    )
    return {}


def do_voice(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hermes_voice

    shown = hermes_voice.read(core)
    before = {"provider": str(shown.get("provider") or ""), "model": str(shown.get("model") or "")}
    hermes_voice.write(core, text_arg(p, "provider"), text_arg(p, "model"))
    return {"before": before}


def undo_voice(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_voice

    hermes_voice.write(core, str(r["before"]["provider"]), str(r["before"]["model"]))


def do_fallback(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import hermes_fallback

    before = [dict(e) for e in hermes_fallback.read(core)["seen"].chain]
    chain = [e for e in p.get("chain") or [] if isinstance(e, dict)]
    hermes_fallback.write(core, model_routes.fallback_chain(chain))
    return {"before": before}


def undo_fallback(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import hermes_fallback

    if any(e.get("keyed") for e in r["before"]):
        raise ActionError("A route had its own API key: set the chain back on his page.")
    hermes_fallback.write(core, model_routes.fallback_chain(list(r["before"])))


def do_backup_schedule(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import backups

    schedule, kept = backups._schedule(core)
    if text_arg(p, "schedule") not in ("off", "daily", "weekly"):
        raise ActionError("schedule is off, daily or weekly.")
    keep = int_arg(p["keep"], "keep") if text_arg(p, "keep") else kept
    backups.set_schedule(core, text_arg(p, "schedule"), keep)  # type: ignore[arg-type]
    return {"before": {"schedule": schedule, "keep": kept}}


def undo_backup_schedule(core: Core, ws: str, r: Result) -> None:
    from agos_core.actions import backups

    b = r["before"]
    backups.set_schedule(core, b["schedule"], int(b["keep"]))


def do_run_backup(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import backups

    made = backups.run_backup(core)
    return {"report": json.dumps(made.model_dump(by_alias=True), default=str)[:1000]}


def do_rehearse(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import backups

    found = backups.rehearse(core, text_arg(p, "name") or None)
    return {"report": json.dumps(found.model_dump(by_alias=True), default=str)[:3000]}


def do_check_updates(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import updates

    return {"report": json.dumps(updates.run_check(core), default=str)[:3000]}


def do_run_updates(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import updates

    return {"report": json.dumps(updates.start_update(core), default=str)[:2000]}


def undo_learned(core: Core, ws: str, p: Fields) -> Result:
    from agos_core.actions import proactive

    proactive.undo_change(core, ws, text_arg(p, "entry"))
    return {}
