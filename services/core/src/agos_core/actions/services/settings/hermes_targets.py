"""Where Hermes settings live: the roots and members a change reaches, Hermes's schema, the effective value.
Must not: decide what AGOS forces or write a setting.

Split out of agos_core.actions.hermes_all_settings (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine import hermes_schema as hs
from agos_core.engine.hermes import EngineError

__all__ = [
    "Target",
    "targets",
]

log = logging.getLogger("agos.hermes_all_settings")


@dataclass(frozen=True)
class Target:
    workspace_id: str
    workspace: str
    key: str  # the engine's profile key ("<ws>" or "<ws>--<member>")
    label: str
    member: bool


def targets(core: Core, workspace_id: str | None = None) -> list[Target]:
    from agos_core.actions.hermes_time_limits import profiles

    engine = core.engine
    if engine is None:
        return []
    from agos_core.db.workspaces import list_workspaces

    names = {w.id: w.name for w in list_workspaces(core.db, include_archived=True)}
    out: list[Target] = []
    for p in profiles(core):
        ws, member = engine.split(p.key)
        if workspace_id is not None and ws != workspace_id:
            continue
        out.append(Target(ws, names.get(ws, ws), p.key, p.label, bool(member)))
    return out


def _schema(core: Core) -> list[hs.Field]:
    if core.engine is None:
        raise ActionError("The engine isn't available.", status=503)
    try:
        return list(core.engine.config_schema())
    except (EngineError, OSError) as error:
        raise ActionError(
            f"The engine's settings list couldn't be read: {error}", status=502
        ) from error


def _as_hermes_reads(core: Core, every: list[Target]) -> dict[str, dict[str, Any]]:
    """Each profile as Hermes reads it: its config.yaml with the managed scope on top
    (one value for all), merged by Hermes's own apply_managed_overlay."""
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    homes = {t.key: engine.profile_home(t.key) for t in every}
    try:
        merged = engine.as_hermes_reads(list(homes.values()))
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine's settings couldn't be read: {error}", status=502) from error
    return {key: merged.get(str(home)) or {} for key, home in homes.items()}


def _secrets(core: Core, homes: dict[str, Path]) -> dict[str, set[hs.Path_]]:
    """Per profile, where Hermes's own masker hides a value (engine.hermes_secrets:
    the same runtime run as _as_hermes_reads)."""
    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    try:
        found = engine.hermes_secrets(list(homes.values()))
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine's settings couldn't be read: {error}", status=502) from error
    return {key: hs.secret_paths(found.get(str(home))) for key, home in homes.items()}


def _uncovered(
    config: dict[str, Any],
    known: set[str],
    prefix: str = "",
    parents: set[str] | None = None,
) -> dict[str, Any]:
    """What a home's config.yaml sets that no listed setting covers. `parents`: every
    dotted parent of a known key (made once per call; a path's own parents are then
    looked up, not every known key scanned for each path)."""
    if parents is None:
        parents = {k.rsplit(".", i)[0] for k in known for i in range(1, k.count(".") + 1)}
    out: dict[str, Any] = {}
    for name, value in config.items():
        path = f"{prefix}.{name}" if prefix else str(name)
        if path in known or path == "_config_version":
            continue
        parts = path.split(".")
        if any(".".join(parts[:i]) in known for i in range(1, len(parts))):
            continue  # inside a listed mapping (e.g. one provider of `providers`)
        below = path in parents
        if isinstance(value, dict) and value and (below or not prefix):
            out.update(_uncovered(value, known, path, parents))
        else:
            out[path] = value
    return out


def _effective(config: dict[str, Any], field: hs.Field) -> tuple[bool, Any]:
    from agos_core.engine import config_file

    missing = object()
    found = config_file.get(config, field.key, missing)
    if found is missing:
        return False, field.default
    return True, found


def _norm(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
