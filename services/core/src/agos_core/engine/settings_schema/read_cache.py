"""Reading the list from Hermes's runtime (one small process) and keeping it in memory while Hermes's file is unchanged.
Must not: decide what AGOS does with a setting (actions/services/settings does).

Split out of agos_core.engine.hermes_schema (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from agos_core.engine.settings_schema.env import EnvVar, env_vars
from agos_core.engine.settings_schema.fields import Field, build

__all__ = [
    "SCRIPT",
    "cached",
    "env_registry",
    "forget",
    "image_modes",
    "kanban_auto_cap",
    "kanban_workflow",
    "keep",
    "keep_env",
    "parse",
    "source_path",
]


def env_registry() -> list[EnvVar] | None:
    """Hermes's .env settings, read with the settings list (None: not read)."""
    with _lock:
        found = _cache.get("env")
    return list(found) if isinstance(found, list) else None


def keep_env(found: list[EnvVar] | None) -> None:
    with _lock:
        _cache["env"] = list(found) if found is not None else None


def source_path() -> Path | None:
    with _lock:
        found = _cache.get("source")
    return found if isinstance(found, Path) else None


# --- reading it from Hermes's runtime -------------------------------------------

# Run in Hermes's runtime: the dashboard's own schema and defaults
# (hermes_cli/web_routers/config_env.py get_schema / get_defaults), where Hermes's
# defaults file is (its comments are the descriptions), and Hermes's Kanban
# workflow (its columns: the dashboard's GET /workflow, kanban_workflow.py), and
# the Kanban cap Hermes uses while `kanban.max_in_progress` is unset (its memory-
# derived default, hermes_cli/kanban_db_dispatch.py derive_default_max_in_progress),
# and the modes of agent.image_input_mode (agent/image_routing.py _VALID_MODES).
SCRIPT = r"""
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli import config_defaults
from hermes_cli.config import DEFAULT_CONFIG, _is_secret_config_key
from hermes_cli.web_server_config import _schema_with_dynamic_provider_options
fields = _schema_with_dynamic_provider_options()
# `stt.provider` has no DEFAULT_CONFIG seed (unset = autodetect), so the dashboard's
# walk skips the select Hermes defines for it: its own override, with its own merge
# of command and plugin providers (web_server_config.py _custom_provider_options).
try:
    from hermes_cli.config import load_config
    from hermes_cli.web_server_config import _SCHEMA_OVERRIDES, _custom_provider_options
    for kind in ("stt", "tts"):
        key = kind + ".provider"
        base = _SCHEMA_OVERRIDES.get(key)
        if key not in fields and isinstance(base, dict) and base.get("options"):
            fields = {**fields, key: {**base, "options": _custom_provider_options(
                kind, list(base["options"]), load_config())}}
except Exception:
    pass
# The keys Hermes names credentials (the rule its config printer masks by).
def _leaves(d, prefix=""):
    for k, v in d.items():
        path = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict) and v:
            yield from _leaves(v, path)
        else:
            yield path
secret_keys = sorted(k for k in set(fields) | set(_leaves(DEFAULT_CONFIG))
                     if _is_secret_config_key(k))
try:
    from hermes_cli.kanban_workflow import DEFAULT_WORKFLOW
    workflow = DEFAULT_WORKFLOW.to_dict()
except Exception:
    workflow = None
# Hermes's .env settings: its registry (OPTIONAL_ENV_VARS, the names its setup flows
# write: _EXTRA_ENV_KEYS) and the provider catalog's key names (the dashboard's
# GET /api/env builds its Keys page from the same three).
env = None
try:
    from hermes_cli.config import OPTIONAL_ENV_VARS, _EXTRA_ENV_KEYS
    env = {}
    for k, v in OPTIONAL_ENV_VARS.items():
        env[k] = {"description": v.get("description") or "", "category": v.get("category") or "",
                  "password": bool(v.get("password"))}
    for k in sorted(_EXTRA_ENV_KEYS):
        env.setdefault(k, {"description": "", "category": "", "password": None})
    try:
        from hermes_cli.web_routers.config_env import _catalog_provider_env_metadata
        for k, v in _catalog_provider_env_metadata().items():
            e = env.setdefault(k, {"description": "", "category": "provider", "password": None})
            e["description"] = e["description"] or v.get("description") or ""
            e["category"] = e["category"] or "provider"
            if e["password"] is None:
                e["password"] = bool(v.get("is_password"))
    except Exception:
        pass
except Exception:
    env = None
try:
    from hermes_cli.kanban_db_dispatch import derive_default_max_in_progress
    kanban_auto = derive_default_max_in_progress()
except Exception:
    kanban_auto = None
for k, e in (env or {}).items():
    e["secret"] = _is_secret_config_key(k)
# The modes agent.image_input_mode takes (its reader keeps only these).
try:
    from agent.image_routing import _VALID_MODES
    image_modes = sorted(_VALID_MODES)
except Exception:
    image_modes = None
print("AGOS-SCHEMA " + json.dumps({
    "fields": fields, "defaults": DEFAULT_CONFIG, "source": config_defaults.__file__,
    "kanban_workflow": workflow, "kanban_auto_cap": kanban_auto, "env": env,
    "secret_keys": secret_keys, "image_modes": image_modes,
}, default=str))
"""

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def parse(stdout: str) -> tuple[list[Field], Path]:
    lines = [ln for ln in stdout.splitlines() if ln.startswith("AGOS-SCHEMA ")]
    if not lines:
        raise ValueError("Hermes didn't answer with its settings list")
    found = json.loads(lines[-1][len("AGOS-SCHEMA ") :])
    workflow = found.get("kanban_workflow")
    env = found.get("env")
    with _lock:
        _cache["workflow"] = workflow if isinstance(workflow, dict) else None
        auto = found.get("kanban_auto_cap")
        _cache["kanban_auto"] = auto if isinstance(auto, int) and auto > 0 else None
        modes = found.get("image_modes")
        _cache["image_modes"] = [str(m) for m in modes] if isinstance(modes, list) else None
        secret = found.get("secret_keys")
        _cache["secret_keys"] = frozenset(str(k) for k in secret or ())
    keep_env(env_vars(env) if isinstance(env, dict) else None)
    source = Path(str(found.get("source") or ""))
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        text = ""
    return (
        build(
            found.get("fields") or {},
            found.get("defaults") or {},
            text,
            set(_cache["secret_keys"]),
        ),
        source,
    )


def _mark(source: Path) -> tuple[int, int] | None:
    try:
        stat = source.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def cached() -> list[Field] | None:
    """The list read before, while Hermes's defaults file is unchanged (an upgrade
    of Hermes shows at once)."""
    with _lock:
        source, mark, fields = _cache.get("source"), _cache.get("mark"), _cache.get("fields")
    if source is None or mark is None or _mark(source) != mark:
        return None
    return list(fields or [])


def keep(source: Path, fields: list[Field]) -> None:
    mark = _mark(source)
    if mark is None:
        return
    with _lock:
        _cache.update(source=source, mark=mark, fields=list(fields))


def kanban_workflow() -> dict[str, Any] | None:
    """Hermes's Kanban workflow read with the settings list (None: not read)."""
    with _lock:
        found = _cache.get("workflow")
    return dict(found) if isinstance(found, dict) else None


def kanban_auto_cap() -> int | None:
    """How many Kanban cards Hermes runs at once on this machine while
    `kanban.max_in_progress` is unset (MemTotal / 512 MiB in [2, 8]; None: no cap
    or not read), read with the settings list."""
    with _lock:
        found = _cache.get("kanban_auto")
    return found if isinstance(found, int) else None


def image_modes() -> list[str] | None:
    """The modes Hermes reads for `agent.image_input_mode` (agent/image_routing.py
    _VALID_MODES; another value falls back to "auto"), read with the settings list
    (None: not read)."""
    with _lock:
        found = _cache.get("image_modes")
    return list(found) if isinstance(found, list) else None


def forget() -> None:
    with _lock:
        _cache.clear()
