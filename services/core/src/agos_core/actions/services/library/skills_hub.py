"""Hermes's Skills Hub for a workspace: search, install (with its scan), update checks and updates, the read-ahead.
Must not: write a skill except through Hermes's hub.

Split out of agos_core.actions.workspace_skills (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.library.skill_copies import add_missing_files
from agos_core.actions.services.library.skill_folders import (
    FOLDER,
    _home,
    _row,
    existing_dir,
    skill_dir,
)
from agos_core.actions.services.library.skill_writes import applied, save
from agos_core.actions.skill_text_files import text_files
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.records import Record
from agos_core.engine import library as lib
from agos_core.engine import read_cache, sources
from agos_core.engine.library import LibraryError
from agos_core.hermes_gateway import process as hermes_process

__all__ = [
    "SCAN_BLOCKED",
    "SCAN_BLOCKED_STATUS",
    "Installed",
    "Update",
    "apply_update",
    "check_updates",
    "install_web",
    "read_ahead",
    "search_web",
]

log = logging.getLogger("agos.workspace_skills")  # the old module's logger (one name)

# ---- sources: this machine, the web (Hermes's hub, into the workspace's root) ---------


def _hub(core: Core, workspace_id: str) -> sources.Sources:
    """Hermes's hub commands for this workspace: run in its root, so its hub lock
    is the root's and a hub skill lands in its folder (`--category agos-library`).
    The hub's GitHub token stays in the library home's .env; Hermes's process gets
    it for the command only (never written into the root)."""
    from agos_core.actions.library import _sources, library_home
    from agos_core.engine import config_file
    from agos_core.engine.github_token import NAME

    token = config_file.read_env(library_home(core)).get(NAME)
    return _sources(
        core,
        _home(core, workspace_id),
        category=FOLDER,
        extra_env={NAME: token} if token else None,
    )


def search_web(core: Core, workspace_id: str, query: str) -> list[Any]:
    from agos_core.actions.library import _found, _sources

    require_workspace(core, workspace_id)
    try:
        return _found(core, _sources(core).search_skills(query), workspace_id)
    except (sources.SourceError, hermes_process.TimeoutExpired) as error:
        raise ActionError(f"The skills hub didn't answer: {error}", 503) from error


# Hermes's words when its skills-guard scan blocks an install (hermes_cli/skills_hub.py).
SCAN_BLOCKED = "security scan found"
SCAN_BLOCKED_STATUS = 423  # Locked: only the owner's Install anyway (Hermes's --force) opens it


class Installed(Record):
    id: int
    scan: str


def install_web(
    core: Core, workspace_id: str, identifier: str, *, force: bool = False
) -> Installed:
    """The owner confirmed after seeing the source, description and scan. Hermes's
    hub installs it straight into this workspace's folder (its scan runs again; a
    blocked verdict stops it) and keeps it in the root's hub lock, so Hermes itself
    checks and updates it later. On in this workspace at once."""
    from agos_core.actions.library import _with_github_limit

    require_workspace(core, workspace_id)
    src = _hub(core, workspace_id)
    try:
        name = src.skill_name(identifier)
    except (sources.SourceError, hermes_process.TimeoutExpired) as error:
        raise ActionError(f"Not installed: {_with_github_limit(core, str(error))}", 400) from error
    if (
        repo.find_item(core.db, "skill", name, workspace_id) is not None
        or (skill_dir(core, workspace_id, name) or Path("/nonexistent")).exists()
    ):
        raise ActionError(f"This workspace already has a skill named {name}.", 409)
    item_id = repo.insert_item(
        core.db,
        kind="skill",
        name=name,
        title=name,
        summary="",
        definition={"identifier": identifier},
        source="web",
        workspace_id=workspace_id,
    )
    try:
        text, _folder, scan = src.install_skill(identifier, name, force=force)
        _hub_changed(src)
        lib.check_skill(text)
    except (sources.SourceError, hermes_process.TimeoutExpired, LibraryError) as error:
        repo.delete_item(core.db, item_id)
        if not isinstance(error, sources.SourceError | hermes_process.TimeoutExpired):
            with contextlib.suppress(sources.SourceError, hermes_process.TimeoutExpired):
                src.uninstall_skill(name)  # Hermes's hub takes it back out
        said = str(error).strip()
        if isinstance(error, sources.SourceError) and "installed nothing" in said:
            said = _with_github_limit(core, said)
        said = said.removeprefix("Not installed:").strip()
        if isinstance(error, sources.SourceError) and SCAN_BLOCKED in said and not force:
            # Hermes's scan refused it: the owner may read the findings and install anyway.
            raise ActionError(f"Not installed: {said}", SCAN_BLOCKED_STATUS) from error
        raise ActionError(f"Not installed: {said}", 400) from error
    applied(core, workspace_id)
    return Installed(id=item_id, scan=scan)


# ---- updates -------------------------------------------------------------------------


class Update(Record):
    item_id: int
    name: str
    has_update: bool
    detail: str = ""


# Hermes's `hermes skills check` (a network check of every hub skill of a root,
# ~20 s): its last answer is kept in memory per root with when it was taken. The
# page gets it at once and Hermes checks again behind it every few hours, and
# right after AGOS changed that root's hub skills (`_hub_changed`).
_HUB_CHECK_S: float = 6 * 3600
_HUB: read_cache.ReadCache[tuple[float, dict[str, sources.HubState]]] = read_cache.ReadCache(
    "skills_hub_check", max_entries=32
)
_hub_writes: dict[str, int] = {}  # hub home → AGOS's changes of its hub so far
# (hub home, skill) AGOS just had Hermes update → when: not offered again while
# Hermes's next check (started by the change) runs.
_just_updated: dict[tuple[str, str], float] = {}


def _hub_changed(src: sources.Sources, updated: str | None = None) -> None:
    home = str(src.library_home)
    _hub_writes[home] = _hub_writes.get(home, 0) + 1
    if updated:
        _just_updated[(home, updated)] = time.time()


def _hub_states(
    src: sources.Sources, *, kept: bool
) -> tuple[float, dict[str, sources.HubState]] | None:
    """(when Hermes checked, what it said). `kept`: the page (the last answer at once,
    Hermes asked again behind it when it is old or the hub changed; None while
    Hermes's first check since the start runs behind the page)."""
    home = str(src.library_home)

    def ask() -> tuple[float, dict[str, sources.HubState]]:
        taken = time.time()
        return taken, src.hub_states()

    round_ = (int(time.time() // _HUB_CHECK_S), _hub_writes.get(home, 0))
    if kept and _HUB.peek(home) is None:
        _HUB.refresh(home, round_, ask)
        return None
    return _HUB.get(home, round_, ask, stale_ok=kept)


def check_updates(core: Core, workspace_id: str) -> list[Update]:
    """Is a newer copy there? Skills from the web: Hermes's own `hermes skills
    check` in the workspace's root (its hub lock), as last checked; left out while
    Hermes's first check runs. Skills imported from this machine: AGOS compares
    the text (no Hermes source knows them). Nothing changes until Update."""
    from agos_core.actions.library import _sources

    require_workspace(core, workspace_id)
    rows = repo.workspace_skills(core.db, workspace_id)
    result: list[Update] = []
    hub: dict[str, sources.HubState] | None = {}
    taken = 0.0
    home = ""
    if any(r["source"] == "web" for r in rows):
        src = _hub(core, workspace_id)
        home = str(src.library_home)
        try:
            checked = _hub_states(src, kept=True)
        except (sources.SourceError, hermes_process.TimeoutExpired) as error:
            raise ActionError(f"The skills hub didn't answer: {error}", 503) from error
        if checked is None:
            hub = None
        else:
            taken, hub = checked
    machine = _sources(core)
    on_machine = machine.machine_skills() if any(r["source"] == "machine" for r in rows) else []
    for row in rows:
        name = str(row["name"])
        if row["source"] == "web":
            if hub is None:
                continue  # Hermes's first check since the start runs behind the page
            if _just_updated.get((home, name), 0.0) > taken:
                result.append(Update(item_id=row["id"], name=name, has_update=False))
                continue
            state = hub.get(name)
            if state is None:
                # Not in this root's hub lock (made before, or copied from another
                # workspace): Update installs it again through the hub, which then
                # keeps it.
                result.append(
                    Update(
                        item_id=row["id"],
                        name=name,
                        has_update=True,
                        detail="Not in the skills hub yet: Update installs it again from the web",
                    )
                )
                continue
            newer = state.status == "update_available"
            result.append(
                Update(
                    item_id=row["id"],
                    name=name,
                    has_update=newer,
                    detail="Newer on the web" if newer else "",
                )
            )
        elif row["source"] == "machine":
            match = next((f for f in on_machine if f.name == name), None)
            if match is None:
                continue
            text, _ = machine.read_machine_skill(match.origin)
            newer = sources.text_hash(text) != repo.definition(row).get("hash")
            result.append(
                Update(
                    item_id=row["id"],
                    name=name,
                    has_update=newer,
                    detail="Changed on this machine" if newer else "",
                )
            )
    return result


def apply_update(core: Core, workspace_id: str, item_id: int) -> None:
    from agos_core.actions.library import _sources

    row = _row(core, workspace_id, item_id)
    name = str(row["name"])
    if row["source"] == "web":
        src = _hub(core, workspace_id)
        identifier = str(repo.definition(row).get("identifier") or "")
        try:
            if name in src.hub_states():
                src.update_skill(name)  # Hermes's own `hermes skills update`
            else:
                # Not in this root's hub lock yet: Hermes's hub installs it again
                # (over the copy) and keeps it from now on.
                src.install_skill(identifier, name)
        except (sources.SourceError, hermes_process.TimeoutExpired) as error:
            raise ActionError(f"Not updated: {error}", 400) from error
        _hub_changed(src, name)
        applied(core, workspace_id)
        return
    if row["source"] != "machine":
        raise ActionError("Only imported skills have updates.")
    machine = _sources(core)
    match = next((f for f in machine.machine_skills() if f.name == name), None)
    if match is None:
        raise ActionError("It's no longer on this machine.")
    text, found = machine.read_machine_skill(match.origin)
    save(
        core,
        workspace_id,
        item_id,
        name=name,
        title=str(row["title"]),
        given={"text": text, "files": text_files(found)},
    )
    written = existing_dir(core, workspace_id, name)
    if written is not None:
        add_missing_files(found, written)
    fresh = repo.get_item(core.db, item_id)
    if fresh is not None:
        repo.update_item(
            core.db,
            item_id,
            title=str(fresh["title"]),
            summary="",
            definition={**repo.definition(fresh), "hash": sources.text_hash(text)},
        )


def read_ahead(core: Core) -> None:
    """After the core starts: Hermes's update check of each workspace's hub skills
    (the slowest read of its skills list), one root at a time."""
    seen: set[str] = set()
    for row in repo.every_skill(core.db):
        ws = str(row["workspace_id"] or "")
        if row["source"] != "web" or not ws or ws in seen:
            continue
        seen.add(ws)
        try:
            _hub_states(_hub(core, ws), kept=False)
        except (ActionError, sources.SourceError, hermes_process.TimeoutExpired) as error:
            log.info("Hermes's skills check of %s not read ahead: %s", ws, error)
