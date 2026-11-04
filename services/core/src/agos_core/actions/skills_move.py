"""The one-time move of the old shared skill library into each workspace's own skills.

Before, a library skill was ONE global row (workspace_id NULL) whose folder lived in
AGOS's library home (`global/skills/<name>`, or a hub category folder in it) and
every profile of every workspace read it there; a workspace turned it off with
`skills.disabled`, and the Co-Founder's update_skill made "its own version" in the
root's `skills/agos-library/<name>`. Now every skill is a workspace's own
(actions/workspace_skills.py). For each workspace and each old shared skill:
- an own version there is kept as it is, and every file only the library's copy
  had is added beside its files (none of its own is overwritten or removed);
- else, when the skill is on there (not in its skills.disabled), the library's
  folder is copied in;
- the workspace's own row is made (its source, hub identifier and hash kept);
  its notes on the skill move to it.
Then the shared rows go, the old library folder is moved aside (never deleted:
`global/skills.retired-<UTC stamp>`), the `.agos-sources.json` files go, and every
workspace's profiles are written again (its Co-Founder without the shared folder, its
members with the workspace's). Safe to repeat: a finished move finds nothing.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.db import connector_notes as notes_repo
from agos_core.db import library as repo
from agos_core.db.connection import transaction
from agos_core.engine import config_file
from agos_core.engine import library as lib

log = logging.getLogger("agos.skills_move")

RETIRED_PREFIX = "skills.retired-"


def _old_library(core: Core) -> Path:
    return core.layout.global_dir / "skills"


def _has_files(folder: Path) -> bool:
    """The old library is still there only when its folder holds something: Hermes
    creates an empty `skills/` in every home it starts in (global is one), and that
    one is not moved aside on every core start."""
    try:
        return any(folder.iterdir())
    except OSError:
        return False


def _old_skill_dir(base: Path, name: str) -> Path | None:
    """Where the old library had the skill: <library>/<name>, or where Hermes's hub
    put it (an official hub skill kept its category folders)."""
    flat = base / name
    if (flat / "SKILL.md").is_file():
        return flat
    if not lib.NAME.fullmatch(name) or not base.is_dir():
        return None
    for pattern in (f"*/{name}/SKILL.md", f"*/*/{name}/SKILL.md", f"*/*/*/{name}/SKILL.md"):
        for found in sorted(base.glob(pattern)):
            if not any(part.startswith(".") for part in found.relative_to(base).parts):
                return found.parent
    return None


def _old_rows(core: Core) -> list[Any]:
    return repo.old_shared_skills(core.db)


def _off_in(root: Path) -> set[str] | None:
    """The root's skills.disabled; None when AGOS never set the root up (then no
    library skill was on there: actions/hermes_config.py from_hermes)."""
    from agos_core.actions.hermes_config import PLATFORM

    cfg = config_file.read(root)
    if config_file.string_list(config_file.get(cfg, PLATFORM)) is None:
        return None
    return set(config_file.string_list(config_file.get(cfg, "skills.disabled")) or [])


def _carry_hub_lock(old_base: Path, root: Path, names: list[str]) -> None:
    """The old library's hub-lock entries (skills/.hub/lock.json, Hermes's
    HubLockFile format) of the web skills this workspace got go into its root's own
    lock, pointing at the workspace folder, so Hermes's `skills check` / `update`
    there know them (instead of each showing "not in the hub yet")."""
    try:
        old = json.loads((old_base / ".hub" / "lock.json").read_text())
    except (OSError, ValueError):
        return
    installed = old.get("installed") if isinstance(old, dict) else None
    if not isinstance(installed, dict):
        return
    entries = {n: installed[n] for n in names if isinstance(installed.get(n), dict)}
    if not entries:
        return
    path = root / "skills" / ".hub" / "lock.json"
    try:
        lock = json.loads(path.read_text())
    except (OSError, ValueError):
        lock = {"version": 1, "installed": {}}
    if not isinstance(lock.get("installed"), dict):
        lock["installed"] = {}
    for name, entry in entries.items():
        if name in lock["installed"]:
            continue  # the root's own hub already knows it
        lock["installed"][name] = {**entry, "install_path": f"{lib.SKILLS_DIR_NAME}/{name}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def move_old_shared_skills(core: Core) -> dict[str, list[str]]:
    """Returns {workspace: skills it got}. Nothing when the move is done."""
    from agos_core.actions import hermes_config as hc
    from agos_core.actions import workspace_skills
    from agos_core.db.workspaces import list_workspaces

    engine = core.engine
    old_base = _old_library(core)
    rows = _old_rows(core)
    if engine is None or (not rows and not _has_files(old_base)):
        return {}  # an empty global/skills is Hermes's own (it makes one in every home)
    moved: dict[str, list[str]] = {}
    touched: list[str] = []
    for w in list_workspaces(core.db, include_archived=True):
        if not hc.has_root(core, w.id):
            continue
        root = engine.profile_home(w.id)
        target = lib.copies_dir(root)
        off = _off_in(root)
        got: list[str] = []
        for row in rows:
            name = str(row["name"])
            own = target / name
            source = _old_skill_dir(old_base, name)
            if (own / "SKILL.md").is_file():
                if source is not None:
                    added = workspace_skills.add_missing_files(source, own)
                    if added:
                        log.info("skill %s of %s: library-only files added %s", name, w.id, added)
            elif source is not None and off is not None and name not in off:
                target.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, own, symlinks=False)
            else:
                continue  # off there and never changed there: nothing of it moves
            if repo.find_item(core.db, "skill", name, w.id) is None:
                with transaction(core.db):
                    new_id = repo.insert_item(
                        core.db,
                        kind="skill",
                        name=name,
                        title=str(row["title"] or ""),
                        summary="",
                        definition=workspace_skills.stored(repo.definition(row)),
                        source=str(row["source"] or "created"),
                        workspace_id=w.id,
                    )
                    notes_repo.move_item(core.db, w.id, int(row["id"]), new_id)
            got.append(name)
        _carry_hub_lock(old_base, root, got)
        (target / lib.SOURCES_FILE).unlink(missing_ok=True)
        touched.append(w.id)
        if got:
            moved[w.id] = got
    with transaction(core.db):
        for row in rows:
            repo.delete_item(core.db, int(row["id"]))
    if old_base.is_dir():
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        aside = old_base.with_name(f"{RETIRED_PREFIX}{stamp}")
        n = 2
        while aside.exists():
            aside = old_base.with_name(f"{RETIRED_PREFIX}{stamp}-{n}")
            n += 1
        old_base.rename(aside)
        log.info("old shared skill library moved aside to %s", aside)
    from agos_core.actions import library

    for workspace_id in touched:
        problem = library.apply_workspace(core, workspace_id)
        if problem:
            log.warning("skills of %s not applied after the move: %s", workspace_id, problem)
    if moved:
        log.info("shared skills moved into their workspaces: %s", moved)
    return moved
