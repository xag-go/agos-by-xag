"""The rows of the Hermes settings page: each setting and .env value with its rule, shared rows, notes.
Must not: cache, schedule or write; it only builds rows from what was read.

Split out of agos_core.actions.hermes_all_settings (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from agos_core.actions.services.settings.hermes_policy import (
    CARD_LABELS,
    _rule,
    forced_env,
    locked_env,
)
from agos_core.actions.services.settings.hermes_targets import Target, _effective, _norm, log
from agos_core.context import Core
from agos_core.engine import hermes_schema as hs
from agos_core.engine.hermes import EngineError
from agos_core.engine.hermes_env_keys import yaml_key_for

__all__ = [
    "SHARED_WHY",
    "shared_rows",
]

# Hermes processes the page starts at once (each holds 100-200 MB while it runs).
_PROBES = 4


def _with_partner(key: str) -> set[str]:
    """The key and the row _pair_models pairs it with (provider <-> model)."""
    out = {key}
    for mine, other in ((".provider", ".model"), (".model", ".provider")):
        if key.endswith(mine):
            out.add(key[: -len(mine)] + other)
    return out


# The shared home (~/.hermes: the owner's own Hermes, where General settings keeps
# the logins and keys) is no workspace's: the page doesn't write it. These of its
# keys still matter for AGOS, so they are shown read-only with why.
_NEW_MODEL = (
    "A new workspace starts on this home's model (actions/engine.py shared_model). "
    "Afterwards each workspace has its own (Workspace → Default model); change this one "
    "with `hermes model` in your own Hermes."
)
SHARED_WHY: dict[str, str] = {
    "model.provider": _NEW_MODEL,
    "model.default": _NEW_MODEL,
    "agent.reasoning_effort": _NEW_MODEL,
    "credential_pool_strategies": (
        "Settings → Models (several keys per provider) writes the strategy once, into "
        "Hermes's managed config.yaml, for every workspace; this home's own line counts "
        "only for a `hermes` you run yourself."
    ),
}
_MANAGED_HERE = (
    "AGOS's own runs use the managed scope's value (one for every workspace; "
    "HERMES_MANAGED_DIR, hermes_cli/managed_scope.py get_managed_dir). That variable "
    "reaches only the processes AGOS starts, so a `hermes` you run yourself in this home "
    "uses this home's own value."
)


def shared_rows(core: Core, managed: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The shared home's keys that matter for AGOS: its value (secrets masked), the
    managed scope's where one applies to AGOS's runs, and why it matters."""
    from agos_core.actions import hermes_managed
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return []
    config = config_file.read(engine.settings.hermes_home)
    shared, scope = engine.settings.hermes_home, engine.settings.managed_home
    try:
        found_secrets = engine.hermes_secrets([shared, scope])
    except (EngineError, OSError, ValueError) as error:
        log.info("Hermes's list of hidden settings not read: %s", error)
        found_secrets = None
    if found_secrets is None:
        # Nothing is shown that Hermes didn't say is safe to show.
        everything: set[hs.Path_] = {()}
        mine = pinned_secrets = everything
    else:
        mine = hs.secret_paths(found_secrets.get(str(shared)))
        pinned_secrets = hs.secret_paths(found_secrets.get(str(scope)))
    missing = object()
    out: list[dict[str, Any]] = []
    for key, why in SHARED_WHY.items():
        found = config_file.get(config, key, missing)
        out.append(
            {
                "key": key,
                "value": None
                if found is missing
                else hs.masked(found, mine, () if mine == {()} else key),
                "set": found is not missing,
                "managed": None,
                "reason": why,
            }
        )
    for key in hermes_managed.by_card():
        if key.isupper():
            continue  # a .env line: this home's .env holds General settings' keys
        found = config_file.get(config, key, missing)
        pinned = config_file.get(managed or {}, key, missing)
        out.append(
            {
                "key": key,
                "value": None
                if found is missing
                else hs.masked(found, mine, () if mine == {()} else key),
                "set": found is not missing,
                "managed": None
                if pinned is missing
                else hs.masked(pinned, pinned_secrets, () if pinned_secrets == {()} else key),
                "reason": _MANAGED_HERE,
            }
        )
    return out


def _env_uses(
    core: Core,
    every: list[Target],
    probes: dict[str, Future[dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per profile, what Hermes's gateway really uses ({} where Hermes didn't say).
    `probes`: the asks _ask_ahead already started (the page waits for those)."""
    engine = core.engine
    if engine is None:
        return {}
    out: dict[str, dict[str, Any]] = {}

    def one(t: Target) -> None:
        try:
            ahead = (probes or {}).get(t.key)
            out[t.key] = (
                ahead.result()
                if ahead is not None
                else engine.env_in_use(engine.profile_home(t.key))
            )
        except (EngineError, OSError, ValueError) as error:
            log.info("what Hermes uses in %s not read: %s", t.key, error)

    if probes is not None:
        for t in every:
            one(t)
        return out
    with ThreadPoolExecutor(max_workers=_PROBES) as pool:
        list(pool.map(one, every))
    return out


def _env_rows(
    core: Core,
    every: list[Target],
    configs: dict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    cards: dict[str, str],
    probes: dict[str, Future[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Hermes's .env settings (its own registry), each profile's value, which one wins
    where config.yaml sets the same thing, and AGOS's rule."""
    from agos_core.engine import config_file

    registry = hs.env_registry()
    if registry is None:
        return []
    from agos_core.engine import tool_keys

    # A name a profile passes into its tools is a key of Workspace → Keys.
    cards = {
        **cards,
        **{n: "keys" for config in configs.values() for n in tool_keys.passthrough(config)},
    }
    engine = core.engine
    assert engine is not None
    envs = {t.key: config_file.read_env(engine.profile_home(t.key)) for t in every}
    uses = _env_uses(core, every, probes)
    bridged = {name for found in uses.values() for name in (found.get("yaml") or {})}
    known = {v.name for v in registry}
    extra = sorted({n for env in envs.values() for n in env if n.isupper()} - known)
    fields = list(registry) + [
        hs.EnvVar(n, hs.unlisted_env(n).description, "custom", False, listed=False)
        if n in bridged
        else hs.unlisted_env(n)
        for n in extra
    ]
    yaml_rows = {r["key"]: r for r in rows}
    out: list[dict[str, Any]] = []
    for var in fields:
        values = [(t, var.name in envs[t.key], envs[t.key].get(var.name)) for t in every]

        def shown(value: Any, secret: bool = var.secret) -> Any:
            if secret:
                return hs.MASK if value not in (None, "") else None
            return value

        counts = Counter(_norm(shown(v)) for _t, _s, v in values)
        common = json.loads(counts.most_common(1)[0][0]) if counts else None
        workspaces: list[dict[str, Any]] = []
        if len(counts) > 1:
            by_ws: dict[str, list[tuple[Target, bool, Any]]] = {}
            for item in values:
                by_ws.setdefault(item[0].workspace_id, []).append(item)
            for items in by_ws.values():
                root = next((i for i in items if not i[0].member), items[0])
                workspaces.append(
                    {
                        "id": root[0].workspace_id,
                        "name": root[0].workspace,
                        "value": shown(root[2]),
                        "members": [
                            {"label": i[0].label, "value": shown(i[2])}
                            for i in items
                            if i is not root and _norm(shown(i[2])) != _norm(shown(root[2]))
                        ],
                    }
                )
        notes: list[dict[str, str]] = []
        for t, was_set, value in values:
            found = uses.get(t.key) or {}
            used = (found.get("used") or {}).get(var.name)
            if was_set and var.name in (found.get("managed") or ()):
                # Hermes applies its managed .env last, over every profile's own line
                # (hermes_cli/env_loader.py _apply_managed_env).
                if used is not None and str(used) != str(value):
                    notes.append(
                        {
                            "label": t.label,
                            "value": str(shown(used)),
                            "reason": "Hermes's managed scope (one value for every "
                            f"workspace) beats this .env line: Hermes uses {shown(used)}.",
                        }
                    )
                continue
            yaml_value = (found.get("yaml") or {}).get(var.name)
            if not was_set or yaml_value is None or str(yaml_value) == str(value):
                continue
            yaml_key = yaml_key_for(var.name, str(yaml_value), configs.get(t.key, {}))
            where = (
                f"config.yaml {yaml_key}"
                if yaml_key
                else "config.yaml (its value or Hermes's default)"
            )
            if used is not None and str(used) == str(value):
                reason = (
                    f".env beats {where} ({shown(yaml_value, False)}): Hermes uses the .env value."
                )
                if yaml_key and yaml_key in yaml_rows:
                    yaml_rows[yaml_key]["notes"].append(
                        {
                            "label": t.label,
                            "value": str(shown(used)),
                            "reason": f"Hermes uses this instead: the .env line {var.name} beats "
                            "this setting.",
                        }
                    )
            elif used is not None and str(used) == str(yaml_value):
                reason = f"{where} beats this .env line: Hermes uses {yaml_value}."
            else:
                continue
            notes.append(
                {
                    "label": t.label,
                    "value": str(shown(used if used is not None else "")),
                    "reason": reason,
                }
            )
        rule = _env_rule(var, cards)
        out.append(
            {
                "key": var.name,
                "group": var.group,
                "type": "string",
                "description": var.description
                or f"Hermes reads it from .env ({var.category or 'setting'}).",
                "default": None,
                "options": [],
                "in_defaults": var.listed,
                "value": common,
                "set_in": sum(1 for _t, was_set, _v in values if was_set),
                "same": len(counts) <= 1,
                "workspaces": workspaces,
                "rule": rule,
                "editable": rule is None,
                "pair": None,
                "notes": notes,
                "source": "env",
            }
        )
    return out


def _env_rule(var: hs.EnvVar, cards: dict[str, str]) -> dict[str, Any] | None:
    card = cards.get(var.name)
    if card is not None:
        return {"kind": "card", "card": card, "reason": f"Changed on {CARD_LABELS[card]}."}
    forced = forced_env(var.name)
    if forced is not None:
        return {"kind": "forced", "card": None, "reason": forced}
    locked = locked_env(var.name)
    if locked is not None:
        return {"kind": "locked", "card": None, "reason": locked}
    if var.secret:
        where = (
            " Provider keys are added and removed on Settings → General (API keys)."
            if var.category == "provider"
            else ""
        )
        return {
            "kind": "secret",
            "card": None,
            "reason": f"Holds a secret: AGOS never shows it.{where}",
        }
    return None


# Verified in Hermes v0.22.2: no checkpoint is ever taken while terminal.backend is a
# container (AGOS forces docker): agent/tool_executor.py :103 (_ensure_file_checkpoint
# returns for container paths) and :1041 (terminal), and /rollback refuses to restore
# (gateway/slash_commands.py :726, tools/checkpoint_manager.py unsupported_backend_reason).
_NO_CHECKPOINTS = (
    "No effect in AGOS: Hermes takes no checkpoints while terminal.backend is a container "
    "(AGOS runs every command in the workspace's Docker sandbox), and its /rollback refuses "
    "to restore there (agent/tool_executor.py _ensure_file_checkpoint, "
    "tools/checkpoint_manager.py unsupported_backend_reason). AGOS keeps its own document "
    "versions instead."
)


def _note_no_checkpoints(rows: list[dict[str, Any]]) -> None:
    from agos_core.engine import rules

    backend = rules.profile_config(
        image="agos-sandbox:1", mounts=[], network={}, container_key="agos-x"
    ).get("terminal.backend")
    if backend != "docker":
        return
    for row in rows:
        if row["key"].startswith("checkpoints."):
            row["notes"].append(
                {"label": "Every workspace", "value": "docker", "reason": _NO_CHECKPOINTS}
            )


def _pair_models(rows: list[dict[str, Any]]) -> None:
    """A `<x>.provider` key with a `<x>.model` beside it in Hermes's own list is one
    choice: the page edits both with AGOS's model picker (no free text to guess)."""
    by_key = {r["key"]: r for r in rows}
    for row in rows:
        key = row["key"]
        if not key.endswith(".provider"):
            continue
        model = by_key.get(key[: -len(".provider")] + ".model")
        if model is None or not (row["editable"] and model["editable"]):
            continue
        pair = {"provider": key, "model": model["key"]}
        row["pair"] = pair
        model["pair"] = pair


# The key whose member values AGOS extends (actions/agent_profiles.py _make).
_MEMBER_TOOLSETS = "agent.disabled_toolsets"


def _explain_member_toolsets(
    core: Core,
    rows: list[dict[str, Any]],
    every: list[Target],
    configs: dict[str, dict[str, Any]],
) -> None:
    """Why a member has toolsets off that its Co-Founder hasn't (the page lists them)."""
    from agos_core.actions import agent_profiles
    from agos_core.engine import config_file

    row = next((r for r in rows if r["key"] == _MEMBER_TOOLSETS), None)
    if row is None:
        return
    notes: list[dict[str, str]] = []
    for t in every:
        if not t.member:
            continue
        found = agent_profiles._KEY.match(t.key)
        if found is None:
            continue
        mine = config_file.get(configs.get(t.key, {}), _MEMBER_TOOLSETS) or []
        cofounder = config_file.get(configs.get(t.workspace_id, {}), _MEMBER_TOOLSETS) or []
        extra = [x for x in mine if x not in cofounder] if isinstance(mine, list) else []
        if not extra:
            continue
        try:
            why = agent_profiles.off_reasons(core, t.workspace_id, found["agent"])
        except Exception as error:  # noqa: BLE001 — the list still shows, without why
            log.info("why %s has toolsets off not read: %s", t.key, error)
            why = {}
        for toolset in extra:
            notes.append(
                {
                    "label": t.label,
                    "value": str(toolset),
                    "reason": "Off: " + why.get(str(toolset), "Not in its Co-Founder's list."),
                }
            )
    row["notes"] = notes


def _seeded() -> dict[str, str]:
    from agos_core.engine import rules

    return rules.seeded_config()


def _row(
    field: hs.Field,
    every: list[Target],
    configs: dict[str, dict[str, Any]],
    forced: set[str],
    cards: dict[str, str],
    seeded: dict[str, str],
    choices: dict[str, str] | None = None,
    secrets: dict[str, set[hs.Path_]] | None = None,
) -> dict[str, Any]:
    secret = field.secret
    values: list[tuple[Target, bool, Any]] = []
    for t in every:
        was_set, value = _effective(configs.get(t.key, {}), field)
        values.append((t, was_set, value))
    # Each profile's value as Hermes's own masker shows it (its paths, per profile:
    # a `${VAR}` reference stays visible where a literal is hidden).
    hidden = {t.key: (secrets or {}).get(t.key) or set() for t in every}

    def shown(value: Any, t: Target | None = None) -> Any:
        # t None: Hermes's default (DEFAULT_CONFIG holds no credential values).
        if secret:
            return hs.MASK if value not in (None, "") else ""
        return hs.masked(value, hidden[t.key] if t is not None else None, field.key)

    counts = Counter(_norm(shown(v, t)) for t, _s, v in values)
    common = json.loads(counts.most_common(1)[0][0]) if counts else shown(field.default)
    workspaces: list[dict[str, Any]] = []
    if len(counts) > 1:
        by_ws: dict[str, list[tuple[Target, bool, Any]]] = {}
        for item in values:
            by_ws.setdefault(item[0].workspace_id, []).append(item)
        for items in by_ws.values():
            root = next((i for i in items if not i[0].member), items[0])
            root_value = shown(root[2], root[0])
            workspaces.append(
                {
                    "id": root[0].workspace_id,
                    "name": root[0].workspace,
                    "value": root_value,
                    "members": [
                        {"label": i[0].label, "value": shown(i[2], i[0])}
                        for i in items
                        if i is not root and _norm(shown(i[2], i[0])) != _norm(root_value)
                    ],
                }
            )
    rule = _rule(field.key, forced, cards, seeded, choices)
    if rule is None and (
        secret
        or hs.MASK in _norm(shown(field.default))
        or any(hs.MASK in _norm(shown(v, t)) for t, _s, v in values)
    ):
        rule = {
            "kind": "secret",
            "card": None,
            "reason": "Holds a secret (an API key): AGOS never shows it.",
        }
    return {
        "key": field.key,
        "group": field.group,
        "type": field.type,
        "description": field.description,
        "default": shown(field.default),
        "options": field.options,
        "in_defaults": field.in_defaults,
        "value": common,
        "set_in": sum(1 for _t, was_set, _v in values if was_set),
        "same": len(counts) <= 1,
        "workspaces": workspaces,
        "rule": rule,
        "editable": rule is None or rule["kind"] in ("seeded", "choice"),
        "pair": None,
        "notes": [],
        "source": "config",
    }
