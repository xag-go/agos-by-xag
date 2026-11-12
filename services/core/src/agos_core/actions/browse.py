"""Browse this machine's folders to pick one to add (names only, never file contents).

A web page can't read a real path from the system's folder picker, so AGOS shows
its own: the owner walks the folders of the machine AGOS runs on (his Mac today,
the server later). Only folder names are listed. Hidden folders and those that
can never be shared (keys, Docker, Hermes's and AGOS's own data) are left out.
"""

from __future__ import annotations

import os
from pathlib import Path

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.records import Record

MAX_ENTRIES = 500


class FolderEntry(Record):
    name: str
    path: str
    can_add: bool


class FolderListing(Record):
    path: str
    parent: str | None
    home: str
    places: list[FolderEntry]
    folders: list[FolderEntry]
    truncated: bool = False


def _home(core: Core) -> Path:
    if core.engine is not None:
        return core.engine.settings.host_home.resolve()
    return Path.home().resolve()


def _blocked(core: Core) -> list[Path]:
    """Folders never offered (nor anything inside them)."""
    blocked = [core.layout.root]
    if core.engine is not None:
        blocked += list(core.engine.forbidden(core.layout.root))
    out = []
    for p in blocked:
        try:
            out.append(p.resolve())
        except OSError:
            continue
    return out


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or parent in child.parents


def _can_add(real: Path, blocked: list[Path]) -> bool:
    if real == Path(real.anchor):
        return False
    return not any(_inside(real, b) or _inside(b, real) for b in blocked)


def _places(home: Path, blocked: list[Path]) -> list[FolderEntry]:
    names = ["Desktop", "Documents", "Downloads", "Projects", "Pictures", "Movies", "Music"]
    out = [FolderEntry(name="Home", path=str(home), can_add=_can_add(home, blocked))]
    for n in names:
        p = home / n
        if p.is_dir():
            out.append(FolderEntry(name=n, path=str(p), can_add=_can_add(p, blocked)))
    volumes = Path("/Volumes")
    if volumes.is_dir():
        with os.scandir(volumes) as it:
            for e in sorted(it, key=lambda e: e.name.lower()):
                if e.is_dir() and not e.name.startswith("."):
                    p = Path(e.path)
                    out.append(FolderEntry(name=e.name, path=str(p), can_add=_can_add(p, blocked)))
    return out


def list_folders(core: Core, path: str | None) -> FolderListing:
    home = _home(core)
    blocked = _blocked(core)
    target = Path(path) if path else home
    if not target.is_absolute():
        raise ActionError("Use a full path, starting with /.")
    try:
        real = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ActionError("This folder doesn't exist.", 404) from None
    if not real.is_dir():
        raise ActionError("This is a file, not a folder.")
    if any(_inside(real, b) for b in blocked):
        raise ActionError("This folder is private (keys, Docker, engine or AGOS data).", 403)
    folders: list[FolderEntry] = []
    truncated = False
    try:
        with os.scandir(real) as it:
            entries = sorted(
                (e for e in it if not e.name.startswith(".")), key=lambda e: e.name.lower()
            )
    except PermissionError:
        raise ActionError("macOS doesn't let AGOS open this folder.", 403) from None
    for e in entries:
        try:
            if not e.is_dir():
                continue
            child = Path(e.path).resolve()
        except OSError:
            continue
        if any(_inside(child, b) for b in blocked):
            continue
        if len(folders) >= MAX_ENTRIES:
            truncated = True
            break
        folders.append(
            FolderEntry(name=e.name, path=str(Path(e.path)), can_add=_can_add(child, blocked))
        )
    parent = None if real == Path(real.anchor) else str(real.parent)
    return FolderListing(
        path=str(real),
        parent=parent,
        home=str(home),
        places=_places(home, blocked),
        folders=folders,
        truncated=truncated,
    )
