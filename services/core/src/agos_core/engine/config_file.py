"""Reading a Hermes home's own files: its config.yaml and its .env.

AGOS changes a Hermes config only through Hermes (`hermes config set`); it reads
it back from the file Hermes wrote, the way Hermes's own `load_config` does
(YAML). A file that can't be read counts as empty: the caller decides what an
empty config means.
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

import yaml

_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
_lock = threading.Lock()


def read(home: Path) -> dict[str, Any]:
    """The home's config.yaml as Hermes has it (a fresh copy each call)."""
    import copy

    return copy.deepcopy(_parsed(home))


def value(home: Path, dotted: str, default: Any = None) -> Any:
    """One setting of the home's config.yaml as Hermes has it, without copying the
    whole file first: a bot's on/off is read on every outbox poll and per row of
    some statements, and a deep copy of a whole Hermes config each time was most of
    that read. The caller must not change what it gets (it is the parsed file's own
    value, shared until the file changes)."""
    return get(_parsed(home), dotted, default)


def stamp(home: Path) -> tuple[int, int] | None:
    """When and how big the home's config.yaml is (None: no file): a value read from
    it holds while this is unchanged."""
    try:
        found = (home / "config.yaml").stat()
    except OSError:
        return None
    return (found.st_mtime_ns, found.st_size)


def _parsed(home: Path) -> dict[str, Any]:
    """The parsed file, parsed again only when its stamp changed (shared: never
    changed by a caller)."""
    path = home / "config.yaml"
    key = stamp(home)
    if key is None:
        return {}
    with _lock:
        found = _cache.get(path)
        if found is not None and found[0] == key:
            return found[1]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    parsed = data if isinstance(data, dict) else {}
    with _lock:
        _cache[path] = (key, parsed)
    return parsed


def get(config: dict[str, Any], dotted: str, default: Any = None) -> Any:
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def string_list(value: Any) -> list[str] | None:
    """A list setting (None when it isn't set). Hermes also accepts a JSON-array
    string here (`agent.skill_utils.parse_config_string_list`)."""
    if value is None:
        return None
    if isinstance(value, str):
        import json

        with contextlib.suppress(ValueError):
            value = json.loads(value)
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return None


def read_env(home: Path) -> dict[str, str]:
    """The home's .env lines (name → value)."""
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for line in (home / ".env").read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.lstrip().startswith("#"):
                out[name.strip()] = value.strip()
    return out
