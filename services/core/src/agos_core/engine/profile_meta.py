"""A Hermes profile's own facts that Hermes keeps outside config.yaml:

- `profile.yaml` (hermes_cli/profiles.py `read_profile_meta` / `write_profile_meta`):
  `display_name` is the profile's presentation name (Hermes: max 64 characters),
  written by Hermes's own write_profile_meta (engine Hermes.set_display_name);
  `description` what it does (`hermes profile describe --text`; the Kanban
  decomposer routes cards by it). `ui_meta.<app>` is the place an app keeps its own
  facts about a profile (tui_gateway/methods_profiles.py `_configure_ui_meta`: merged
  key-wise, each key's revision counted in `_ui_meta_revisions`). AGOS's is
  `ui_meta.agos`; write_profile_meta has no ui_meta field and Hermes no public
  setter, so AGOS writes that one key here, the way Hermes does. Other keys are
  kept as they are.
- `gateway.parked` (hermes_cli/profiles.py `profile_is_parked`): while it exists, the
  root's gateway does not serve the profile (its bots and cron stop). Hermes's docs
  (user-guide/multi-profile-gateways.md, "Stopping one profile"): provisioning may
  create it by hand, and the gateway's 30-second rescan applies an added or removed
  marker; its contents are ignored.
"""

from __future__ import annotations

import contextlib
import copy
import fcntl
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from agos_core.engine import read_cache

PROFILE_YAML = "profile.yaml"
PARKED = "gateway.parked"
UI_KEY = "agos"
TITLE_MAX = 64  # hermes_cli/profiles.set_profile_display_name

# Each profile.yaml as last parsed, kept while the file's stamp holds (a change by
# Hermes or by `write` gives it a new one): the Team, the Office and the Dashboard
# read every member's about 20 times per page, each a YAML parse (0.02-0.04 s).
_PARSED: read_cache.ReadCache[dict[str, Any]] = read_cache.ReadCache(PROFILE_YAML, max_entries=512)


def read(home: Path) -> dict[str, Any]:
    """profile.yaml as a mapping ({} when missing or unreadable, like Hermes). Each
    caller gets its own copy: the parsed file is shared, and callers change theirs
    (`write` does)."""
    path = home / PROFILE_YAML
    stamp = read_cache.file_stamp(path)  # before the read: a write meanwhile shows next time
    return copy.deepcopy(_PARSED.get(path, stamp, lambda: _parse(path)))


def read_fresh(home: Path) -> dict[str, Any]:
    """profile.yaml as it is on disk now, never the kept parse: what a writer bases
    its change on (a write over a stale parse puts back what another writer, Hermes
    or another AGOS process, just changed)."""
    return _parse(home / PROFILE_YAML)


def _parse(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def display_name(meta: dict[str, Any]) -> str:
    return str(meta.get("display_name") or "").strip()


def description(meta: dict[str, Any]) -> str:
    return str(meta.get("description") or "").strip()


def agos(meta: dict[str, Any]) -> dict[str, Any]:
    """AGOS's own facts about the profile (`ui_meta.agos`)."""
    ui = meta.get("ui_meta")
    found = ui.get(UI_KEY) if isinstance(ui, dict) else None
    return dict(found) if isinstance(found, dict) else {}


@contextlib.contextmanager
def locked(home: Path) -> Iterator[None]:
    """One writer of profile.yaml at a time on AGOS's side (read, change, write;
    Hermes's write_profile_meta called by AGOS runs under it too)."""
    fd = os.open(home / f".{PROFILE_YAML}.agos-lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def write(home: Path, *, agos_facts: dict[str, Any]) -> bool:
    """AGOS's own facts (`ui_meta.agos`), keeping every other key (like Hermes's
    `write_profile_meta`). Call it under `locked`. False when profile.yaml
    already said exactly that."""
    if not home.is_dir():
        raise FileNotFoundError(f"profile directory does not exist: {home}")
    data = read_fresh(home)
    if agos(data) == agos_facts and (home / PROFILE_YAML).is_file():
        return False
    ui = data.get("ui_meta")
    ui = dict(ui) if isinstance(ui, dict) else {}
    if agos_facts:
        ui[UI_KEY] = agos_facts
    else:
        ui.pop(UI_KEY, None)
    if ui:
        data["ui_meta"] = ui
    else:
        data.pop("ui_meta", None)
    raw = data.get("_ui_meta_revisions")
    revisions = dict(raw) if isinstance(raw, dict) else {}
    count = revisions.get(UI_KEY, 0)
    revisions[UI_KEY] = (count if isinstance(count, int) else 0) + 1
    data["_ui_meta_revisions"] = revisions
    fd, tmp = tempfile.mkstemp(dir=home, prefix=f".{PROFILE_YAML}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        Path(tmp).replace(home / PROFILE_YAML)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def parked(home: Path) -> bool:
    return (home / PARKED).exists()


def set_parked(home: Path, value: bool) -> bool:
    """Parks (True) or unparks the profile; False when it already was so."""
    marker = home / PARKED
    if marker.exists() == value:
        return False
    if value:
        marker.touch()
    else:
        marker.unlink(missing_ok=True)
    return True
