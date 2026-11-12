"""Changing Hermes settings with Hermes's own `hermes config set`: write, Undo, a new profile's start.
Must not: change a forced or locked key (hermes_policy says which).

Split out of agos_core.actions.hermes_all_settings (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.settings.hermes_policy import (
    _rule,
    card_keys,
    choice_keys,
    forced_keys,
)
from agos_core.actions.services.settings.hermes_reads import _one_row, warm_after_write
from agos_core.actions.services.settings.hermes_rows import _seeded
from agos_core.actions.services.settings.hermes_targets import (
    Target,
    _effective,
    _norm,
    log,
    targets,
)
from agos_core.context import Core
from agos_core.engine import hermes_schema as hs
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "as_argument",
    "give_new_profile",
    "restore",
    "write",
]


def as_argument(field_type: str, value: Any) -> str:
    """The text `hermes config set` turns back into this value (Hermes keeps a
    string-typed key verbatim and parses true/false, numbers and JSON lists/maps:
    hermes_cli/config.py _coerce_config_set_value)."""
    if field_type == "boolean":
        if not isinstance(value, bool):
            raise ActionError("Choose on or off.")
        return "true" if value else "false"
    if field_type == "number":
        if value is None:
            return "null"
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ActionError("Use a number.")
        return str(value)
    if field_type in ("list", "object"):
        want = list if field_type == "list" else dict
        if not isinstance(value, want):
            raise ActionError(f"Use a JSON {'list' if want is list else 'object'}.")
        return json.dumps(value)
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ActionError("Use text.")
    return str(value)


def write(
    core: Core,
    key: str,
    value: Any,
    *,
    workspace_id: str | None = None,
    reset: bool = False,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One setting into every root and member (or one workspace's), with Hermes's
    own `hermes config set` (`config unset` for Hermes's default), only where it
    differs. Returns the setting as Hermes now has it. `before`: filled with what
    each profile had (restore() puts it back: a Co-Founder's card's Undo)."""
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    # Only this setting's row (C8: the whole page's read ran before each save).
    row = _one_row(core, key)
    if row is None:
        raise ActionError(f"{key} isn't one of the engine settings.", status=404)
    if not row["editable"]:
        rule = row["rule"] or {}
        raise ActionError(f"{key} can't be changed here: {rule.get('reason', '')}", status=409)
    if workspace_id is not None:
        from agos_core.actions.workspaces import require_workspace

        require_workspace(core, workspace_id)
    if (
        reset
        and (row["rule"] or {}).get("kind") in ("choice", "seeded")
        and row.get("source") != "env"
        and row.get("default") is not None
    ):
        # Hermes's default written as a value: an unset key looks like a new profile,
        # and AGOS's next sync would put its own start value back (keep_owner and the
        # seeded start values only fill a key a profile lacks).
        reset, value = False, row["default"]
    text = "" if reset else as_argument(row["type"], value)
    if not reset and row["type"] == "select" and row["options"] and text not in row["options"]:
        raise ActionError(f"Choose one of: {', '.join(row['options'])}.")
    field = hs.Field(key=key, type=row["type"], description="", default=None)
    want = None if reset else _parsed(row["type"], text)
    env = row.get("source") == "env"
    jobs: list[tuple[Target, list[str]]] = []
    for t in targets(core, workspace_id):
        home = engine.profile_home(t.key)
        if env:
            lines = config_file.read_env(home)
            was_set, have = key in lines, lines.get(key)
        else:
            was_set, have = _effective(config_file.read(home), field)
        if before is not None:
            before.setdefault("key", key)
            before.setdefault("source", "env" if env else "config")
            before.setdefault("values", {})[t.key] = [was_set, have if was_set else None]
        if reset:
            if was_set:
                jobs.append((t, ["config", "unset", key]))
        elif not was_set or _norm(have) != _norm(want):
            jobs.append((t, ["config", "set", "--force", key, text]))
    failed: list[str] = []

    def run(job: tuple[Target, list[str]]) -> None:
        target, args = job
        try:
            hermes_cli.cli(engine, target.key, *args)
        except (EngineError, OSError) as error:
            log.warning("%s not written into %s: %s", key, target.key, error)
            failed.append(f"{target.label}: {error}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, jobs))
    if jobs:
        warm_after_write(core)
    if failed:
        raise ActionError(f"The engine didn't take it in {'; '.join(failed)}", status=502)
    found = _one_row(core, key)
    assert found is not None
    return found


def restore(core: Core, before: dict[str, Any]) -> None:
    """Each profile's value back as write(before=…) found it: set again, or unset
    where it wasn't set (Hermes's own `hermes config set/unset`), only where it
    differs now. A profile gone since is skipped."""
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    key = str(before["key"])
    env = before.get("source") == "env"
    field = hs.Field(key=key, type="string", description="", default=None)
    jobs: list[tuple[str, list[str]]] = []
    for profile, (was_set, value) in (before.get("values") or {}).items():
        home = engine.profile_home(profile)
        if not (home / "config.yaml").is_file():
            continue
        if env:
            lines = config_file.read_env(home)
            now_set, now = key in lines, lines.get(key)
        else:
            now_set, now = _effective(config_file.read(home), field)
        if was_set and (not now_set or _norm(now) != _norm(value)):
            jobs.append((profile, ["config", "set", "--force", key, _text(value)]))
        elif not was_set and now_set:
            jobs.append((profile, ["config", "unset", key]))
    failed: list[str] = []

    def run(job: tuple[str, list[str]]) -> None:
        profile, args = job
        try:
            hermes_cli.cli(engine, profile, *args)
        except (EngineError, OSError) as error:
            failed.append(f"{profile}: {error}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, jobs))
    if jobs:
        warm_after_write(core)
    if failed:
        raise ActionError(f"The engine didn't take it back in {'; '.join(failed)}", status=502)


def _parsed(field_type: str, text: str) -> Any:
    if field_type == "boolean":
        return text == "true"
    if field_type == "number":
        if text == "null":
            return None
        number = float(text)
        return int(number) if number.is_integer() and "." not in text else number
    if field_type in ("list", "object"):
        return json.loads(text)
    return text


def give_new_profile(core: Core, key: str) -> None:
    """A new profile takes what the owner changed here: a member its Co-Founder's
    values, a new workspace's Co-Founder the values every other workspace agrees on.
    Only keys this page changes (not forced, not a card's, not a secret)."""
    from agos_core.engine import config_file

    engine = core.engine
    if engine is None:
        return
    try:
        fields = list(engine.config_schema())
    except (EngineError, OSError) as error:
        log.info("Hermes settings not copied into %s: %s", key, error)
        return
    every = targets(core)
    target = next((t for t in every if t.key == key), None)
    if target is None:
        return
    forced, cards, seeded, choices = forced_keys(core), card_keys(), _seeded(), choice_keys()
    # Only what the owner can change here (his choices among AGOS's recommendations
    # too); not Hermes's other front ends, and not `gateway.*` (one gateway per root
    # serves its members: a member's copy does nothing).
    editable = [
        f
        for f in fields
        if (_rule(f.key, forced, cards, seeded, choices) or {}).get("kind") in (None, "choice")
        and not f.secret
        and f.group != hs.NOT_USED
        and not f.key.startswith("gateway.")
    ]
    if target.member:
        sources = [engine.profile_home(target.workspace_id)]
    else:
        sources = [engine.profile_home(t.key) for t in every if not t.member and t.key != key]
    if not sources:
        return
    configs = [config_file.read(home) for home in sources]
    try:
        found_secrets = engine.hermes_secrets(sources)
    except (EngineError, OSError, ValueError) as error:
        log.info("Hermes settings not copied into %s: %s", key, error)
        return
    hidden = set().union(*(hs.secret_paths(found_secrets.get(str(h))) for h in sources))
    have = config_file.read(engine.profile_home(key))
    for field in editable:
        found = [_effective(c, field) for c in configs]
        if not all(was_set for was_set, _v in found):
            continue
        values = {_norm(v) for _s, v in found}
        if len(values) != 1:
            continue
        value = found[0][1]
        if hs.holds_secret(hidden, field.key) or (
            field.key not in choices and _norm(value) == _norm(field.default)
        ):
            continue  # a value holding a secret, or Hermes's own default (AGOS writes
            # its recommendation into a new profile: the owner's choice must win)
        was_set, mine = _effective(have, field)
        if was_set and _norm(mine) == _norm(value):
            continue
        try:
            hermes_cli.cli(engine, key, "config", "set", "--force", field.key, _text(value))
        except (EngineError, OSError) as error:
            log.info("%s not copied into %s: %s", field.key, key, error)


def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)
