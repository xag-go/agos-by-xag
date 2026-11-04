"""The model a hire proposes for its member, sized to the role's work.

A big model often does small work: the Co-Founder proposes, with each hire, the
model family and version and the reasoning effort the role's work needs (small,
repetitive work: a small model, low; deep work: a big one, high), and says why in
one line (`model_why`, shown on the card). The owner may change it before Approve.

Hermes is the engine and AGOS keeps no copy:
- the models are Hermes's model catalog (the one Settings → Models and every model
  picker read, actions/services/settings/model_catalog.py), only the workspace's own provider (the one its
  Co-Founder runs on, Hermes's model.* there) and only what that catalog lists for
  it; an id it doesn't list is refused with the ones it does;
- on approve the choice goes into the member's Hermes profile through the team's own
  code, like any member's model (actions/team.py write: model.* and
  agent.reasoning_effort by `hermes config set`);
- a NEW member always names its model (check hire=True): an exact version from that
  catalog (a family alone is refused with its versions), a reasoning effort, nothing
  else in the model field, and its why in `model_why`. Refused when proposed (told the
  agent) and when approved (the owner's edit took it out). A member's later model
  change (update_agent) may still be a family or "workspace".
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions.services.settings import model_catalog
from agos_core.context import Core
from agos_core.engine import hire_kit as rules

log = logging.getLogger("agos.hire_model")

OWNERS_CHOICE = "the owner's choice"


def catalog(core: Core, *, wait: bool = True) -> list[dict[str, Any]] | None:
    """Hermes's model catalog (None: unreadable now). `wait` False: only an answer
    already read (a page view never starts Hermes)."""
    if core.engine is None:
        return None
    try:
        kept = model_catalog.catalog_of(core)
        found = kept.load() if wait else kept.kept()
    except Exception:  # unreadable = none known (the check says so)
        log.info("model catalog not read", exc_info=True)
        return None
    return list(found["catalog"]) if found else None


def _workspace(core: Core, workspace_id: str) -> tuple[str, str, str] | None:
    """The workspace's provider (AGOS's id), its mode and its name."""
    from agos_core.actions.engine import workspace_model
    from agos_core.engine.models import provider_name

    selection = workspace_model(core, workspace_id)
    if selection is None:
        return None
    return selection.provider, selection.mode, provider_name(selection.provider)


def _models(found: list[dict[str, Any]] | None, provider: str) -> list[dict[str, Any]] | None:
    if found is None:
        return None
    entry = next((p for p in found if p.get("id") == provider), None)
    return list(entry.get("models") or []) if entry else []


def check(
    core: Core,
    workspace_id: str,
    payload: dict[str, Any],
    *,
    kept_ok: bool = False,
    hire: bool = False,
) -> list[str]:
    """The hire's `model` resolved in place against the catalog (a family becomes
    its newest version, a missing effort the model's own), or what is wrong with it.
    `kept_ok`: a model checked when it was proposed stands when the catalog lists
    none now (the approve of a proposal as made). `hire`: a new member's model, whole
    (rules.resolve_model hire: an exact version, an effort, nothing else in it) and
    its why in `model_why`; none is refused."""
    raw = payload.get("model")
    if not raw and not hire:
        payload["model"] = None
        return []
    ws = _workspace(core, workspace_id)
    if ws is None:
        if hire:
            return ["model: this workspace has no model yet: set it in Settings → Models first"]
        return ["model: this workspace has no model yet; leave model out"]
    provider, mode, label = ws
    models = _models(catalog(core), provider)
    if (
        not models
        and kept_ok
        and isinstance(raw, dict)
        and _complete(raw, provider)
        and not (hire and set(raw) - set(rules.MODEL_KEYS))
    ):
        return (
            [] if not hire or str(payload.get("model_why") or "").strip() else [rules.NO_MODEL_WHY]
        )
    model, problems = rules.resolve_model(
        raw, provider=provider, label=label, mode=mode, models=models, hire=hire
    )
    if not problems:
        payload["model"] = model
        if hire and not str(payload.get("model_why") or "").strip():
            problems = [rules.NO_MODEL_WHY]
    return problems


def member_model(core: Core, workspace_id: str, raw: Any) -> dict[str, str] | None:
    """A member's model the Co-Founder sets (update_agent model): checked like a
    hire's; "workspace" (or none) = back to the workspace's model."""
    from agos_core.actions.errors import ActionError

    if not raw or (isinstance(raw, str) and raw.strip().lower() in ("workspace", "default")):
        return None
    payload: dict[str, Any] = {"model": raw}
    problems = check(core, workspace_id, payload)
    if problems:
        raise ActionError("; ".join(problems) + ".")
    found: dict[str, str] | None = payload["model"]
    return found


def _complete(raw: dict[str, Any], provider: str) -> bool:
    return raw.get("provider") == provider and all(raw.get(k) for k in ("mode", "model", "effort"))


def choices(core: Core, workspace_id: str) -> dict[str, Any] | None:
    """What the owner may pick for a hire (the proposal card's model picker): the
    workspace's provider, its models as the catalog has them now (family, version,
    efforts) and the workspace's own model. None when not known (no catalog read
    yet, no workspace model): the card then shows the proposal's model only."""
    ws = _workspace(core, workspace_id)
    if ws is None:
        return None
    provider, _mode, label = ws
    models = _models(catalog(core, wait=False), provider)
    if not models:
        return None
    from agos_core.actions.engine import workspace_model

    current = workspace_model(core, workspace_id)
    return {
        "provider": provider,
        "label": label,
        "models": [
            {
                "id": str(m["id"]),
                "label": str(m.get("label") or m["id"]),
                "family": rules.model_family(str(m["id"])),
                "efforts": [str(e) for e in m.get("efforts") or []],
                "defaultEffort": str(m.get("defaultEffort") or ""),
            }
            for m in models
        ],
        "workspace": {"model": current.model, "effort": current.effort} if current else None,
    }


def edited(proposed: dict[str, Any], model: Any) -> dict[str, Any]:
    """The owner's model edit merged into the hire (None: the workspace's model); its
    why line follows (the agent's when he kept its model)."""
    out = {**proposed, "model": model if isinstance(model, dict) and model.get("model") else None}
    before = proposed.get("model") if isinstance(proposed.get("model"), dict) else {}
    same = out["model"] is not None and all(
        str((out["model"] or {}).get(k) or "") == str((before or {}).get(k) or "")
        for k in ("model", "effort")
    )
    if not same:
        out["model_why"] = OWNERS_CHOICE
    return out
