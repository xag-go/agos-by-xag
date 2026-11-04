"""Settings → Helper models: Hermes's auxiliary models and its image mode, as
Hermes reads them, one value for every workspace.

AGOS keeps no copy and picks no value. The tasks and fields are Hermes's own
(engine/helper_models.py, from Hermes's settings list); each value is what each
profile's Hermes reads (its config.yaml with the managed scope on top, merged by
Hermes's own apply_managed_overlay: engine.as_hermes_reads). Save is Hermes's own
`hermes config set` into its managed scope (actions/hermes_managed.py write), and
"Use Hermes's default" its `hermes config unset` there.

A helper's model is chosen with AGOS's model picker (the logged-in providers'
models, GET /models/catalog, the same list as every other picker): a pick is
written as Hermes's provider name (engine/models.py hermes_slug, the catalog's own
`hermes_providers` mapping) and the model; "Same as the main model" is Hermes's
`auto`, i.e. the task's keys unset from the managed scope. These keys are not moved
in or given a start value (hermes_managed.by_card doesn't hold them): only the
owner's own Save writes them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine import helper_models as hm
from agos_core.engine import hermes_schema as hs
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hermes_helper_models")

_CHECKS: dict[str, tuple[re.Pattern[str], str]] = {
    "provider": (
        re.compile(r"^[a-z0-9][a-z0-9._:-]{0,63}$"),
        "a Hermes provider name (e.g. openrouter, or auto)",
    ),
    "model": (re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$"), "a model id"),
    "base_url": (re.compile(r"^https?://[^\s]{1,500}$"), "an http(s) address"),
    "api_mode": (re.compile(r"^[a-z][a-z0-9_]{0,39}$"), "one of Hermes's API modes"),
}
_MODE = re.compile(r"^[a-z][a-z_]{0,31}$")
_MISSING = object()


def _schema(core: Core) -> list[hs.Field]:
    if core.engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    try:
        return list(core.engine.config_schema())
    except (EngineError, OSError) as error:
        raise ActionError(
            f"Hermes's settings list couldn't be read: {error}", status=502
        ) from error


def _norm(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def _held(configs: list[dict[str, Any]], known: set[str]) -> list[hs.Field]:
    """Keys this page owns that Hermes holds but its list lacks (e.g. the video
    tool's auxiliary.video.model): shown, so nothing set in Hermes is invisible."""
    out: dict[str, hs.Field] = {}
    for config in configs:
        section = config.get(hm.SECTION)
        if not isinstance(section, dict):
            continue
        for task, block in section.items():
            if not isinstance(block, dict):
                continue
            for name, value in block.items():
                key = f"{hm.SECTION}.{task}.{name}"
                if hm.owns(key) and key not in known and key not in out:
                    out[key] = hs.unlisted(key, value)
    return list(out.values())


def _shown(
    field: hs.Field,
    labels: list[str],
    configs: list[dict[str, Any]],
    managed: dict[str, Any],
    secrets: list[set[hs.Path_]],
    options: list[str] | None = None,
) -> dict[str, Any]:
    from agos_core.engine import config_file

    found: list[tuple[str, Any]] = []
    for label, config, hidden in zip(labels, configs, secrets, strict=True):
        value = config_file.get(config, field.key, _MISSING)
        value = field.default if value is _MISSING else value
        if hs.holds_secret(hidden, field.key):
            value = hs.MASK
        found.append((label, value))
    if not found:  # no workspace yet: what the scope holds, else Hermes's default
        value = config_file.get(managed, field.key, _MISSING)
        found = [("", field.default if value is _MISSING else value)]
    groups: dict[str, tuple[Any, list[str]]] = {}
    for label, value in found:
        groups.setdefault(_norm(value), (value, []))[1].append(label)
    ordered = sorted(groups.values(), key=lambda g: -len(g[1]))
    value = ordered[0][0]
    return {
        "key": field.key,
        "name": field.key.rsplit(".", 1)[1],
        "value": value,
        "hermes_default": field.default,
        "is_default": len(ordered) == 1 and _norm(value) == _norm(field.default),
        "managed": config_file.get(managed, field.key, _MISSING) is not _MISSING,
        "spread": [(v, p) for v, p in ordered] if len(ordered) > 1 else [],
        "options": options if options is not None else list(field.options),
        "description": field.description,
        "secret": value == hs.MASK or field.secret,
        "in_hermes_list": field.in_defaults,
    }


def read(core: Core) -> dict[str, Any]:
    """Every helper task Hermes has, each field as each workspace's Hermes reads it."""
    from agos_core.actions import hermes_managed
    from agos_core.actions.hermes_time_limits import profiles

    fields = _schema(core)
    engine = core.engine
    assert engine is not None
    every = profiles(core)
    homes = [p.home for p in every]
    configs: list[dict[str, Any]] = []
    secrets: list[set[hs.Path_]] = []
    if homes:
        try:
            seen = engine.as_hermes_reads(homes)
            found = engine.hermes_secrets(homes)
        except (EngineError, OSError, ValueError) as error:
            raise ActionError(f"Hermes's settings couldn't be read: {error}", status=502) from error
        configs = [seen.get(str(h), {}) for h in homes]
        secrets = [hs.secret_paths(found.get(str(h))) for h in homes]
    managed = hermes_managed.current(core)
    labels = [p.label for p in every]
    known = {f.key for f in fields}
    tasks = []
    for task in hm.rows(fields, _held([*configs, managed], known)):
        tasks.append(
            {
                "task": task.task,
                "label": task.label,
                "summary": task.summary,
                "description": task.description,
                "in_hermes_list": task.in_hermes_list,
                "fields": [_shown(f, labels, configs, managed, secrets) for f in task.fields],
            }
        )
    image = hm.image_field(fields)
    modes = hs.image_modes() or ([] if image is None else list(image.options))
    return {
        "profiles": len(every),
        "tasks": tasks,
        "image_mode": None
        if image is None
        else _shown(image, labels, configs, managed, secrets, modes),
        "image_choices": hm.image_choices(modes),
    }


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): the page's Hermes reads
    (Hermes's settings list, each profile as Hermes reads it), one run at a time."""
    if core.engine is None:
        return
    try:
        read(core)
    except (ActionError, EngineError, OSError, ValueError) as error:
        log.info("helper models not read ahead: %s", error)


def check(fields: list[hs.Field], held: set[str], sets: dict[str, str], unsets: list[str]) -> None:
    """Only this page's keys (Hermes's tasks' routing fields, a key Hermes holds for
    a task its list lacks, the image mode), with values Hermes takes."""
    rows = hm.rows(fields)
    allowed = {f.key for t in rows for f in t.fields} | held
    if hm.image_field(fields) is not None:
        allowed.add(hm.IMAGE_MODE)
    for key in [*sets, *unsets]:
        if not hm.owns(key) or key not in allowed:
            raise ActionError(f"{key} isn't one of Hermes's helper-model settings.")
    for key, value in sets.items():
        if key == hm.IMAGE_MODE:
            modes = hs.image_modes()
            if (modes is not None and value not in modes) or not _MODE.fullmatch(value):
                raise ActionError(f"Hermes's image mode is one of: {', '.join(modes or [])}.")
            continue
        pattern, what = _CHECKS[key.rsplit(".", 1)[1]]
        if not pattern.fullmatch(value):
            raise ActionError(f"{key}: use {what}.")


def _picked(
    fields: list[hs.Field],
    managed: dict[str, Any],
    picks: dict[str, dict[str, str] | None],
) -> tuple[dict[str, str], list[str]]:
    """The owner's picker choices as Hermes keys. A pick (AGOS's provider id + way
    in + model) → the task's provider (Hermes's name for it) and model; a custom
    endpoint or API mode the managed scope holds for the task goes (Hermes would
    send the call there instead). None ("Same as the main model") → the task's
    keys unset, so Hermes uses its `auto`: the main model."""
    from agos_core.engine import config_file
    from agos_core.engine.models import hermes_slug

    by_task = {t.task: t for t in hm.rows(fields, _held([managed], {f.key for f in fields}))}
    sets: dict[str, str] = {}
    unsets: list[str] = []
    for task, pick in picks.items():
        row = by_task.get(task)
        if row is None:
            raise ActionError(f"{task} isn't one of Hermes's helper tasks.")
        keys = {f.key.rsplit(".", 1)[1]: f.key for f in row.fields}
        held = [k for k in keys.values() if config_file.get(managed, k, _MISSING) is not _MISSING]
        if pick is None:
            unsets.extend(held)
            continue
        if "provider" not in keys or "model" not in keys:
            raise ActionError(f"Hermes has no provider and model for {row.label}.")
        provider, mode = str(pick.get("provider") or ""), str(pick.get("mode") or "")
        if mode not in ("cli", "api"):
            raise ActionError("Pick a provider from the list.")
        sets[keys["provider"]] = hermes_slug(provider, mode)
        sets[keys["model"]] = str(pick.get("model") or "")
        unsets.extend(k for k in held if k.rsplit(".", 1)[1] in ("base_url", "api_mode"))
    return sets, unsets


def write(
    core: Core,
    sets: dict[str, str],
    unsets: list[str],
    picks: dict[str, dict[str, str] | None] | None = None,
) -> dict[str, Any]:
    """Into Hermes's managed scope with Hermes's own writer (every workspace)."""
    from agos_core.actions import hermes_managed

    fields = _schema(core)
    managed = hermes_managed.current(core)
    sets = {k: v.strip() for k, v in sets.items()}
    unsets = list(unsets)
    if picks:
        more_sets, more_unsets = _picked(fields, managed, picks)
        sets = {**sets, **more_sets}
        unsets += [k for k in more_unsets if k not in unsets]
    held = {f.key for f in _held([managed], {f.key for f in fields})}
    check(fields, held, sets, unsets)
    if set(sets) & set(unsets):
        raise ActionError("A setting can't be saved and reset at once.")
    if not sets and not unsets:
        return read(core)
    try:
        hermes_managed.write(core, sets, unsets)
    except (EngineError, OSError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    return read(core)
