"""Where everything lives under AGOS_DATA_DIR."""

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from agos_core.domain.workspace import require_workspace_id

TRASH_SEPARATOR = "--"


@dataclass(frozen=True)
class DataLayout:
    root: Path
    workspaces: Path
    global_dir: Path
    system: Path
    trash: Path
    database: Path
    master_key: Path


def data_layout(data_dir: str | Path) -> DataLayout:
    root = Path(data_dir)
    if not root.is_absolute():
        raise ValueError("the data directory must be an absolute path")
    return DataLayout(
        root=root,
        workspaces=root / "workspaces",
        global_dir=root / "global",
        system=root / "system",
        trash=root / ".trash",
        database=root / "system" / "agos.db",
        master_key=root / "system" / "master.key",
    )


def ensure_data_layout(layout: DataLayout) -> None:
    for directory in (
        layout.root,
        layout.workspaces,
        layout.global_dir,
        layout.system,
        layout.trash,
    ):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    files: Path  # the only folder an agent may write to (/workspace)
    automations: Path


# Folders AGOS once made in every workspace and never used: a workspace's memory is
# its Hermes profile's (memories/), its connectors live under system/connectors.
UNUSED = ("memory", "connectors")


def workspace_paths(layout: DataLayout, workspace_id: str) -> WorkspacePaths:
    """Re-validates the id, so a bad value never becomes a path."""
    root = layout.workspaces / require_workspace_id(workspace_id)
    return WorkspacePaths(root, root / "files", root / "automations")


class WorkspaceFolderExistsError(FileExistsError):
    def __init__(self) -> None:
        super().__init__("a folder with this identifier already exists")


def create_workspace_folders(layout: DataLayout, workspace_id: str) -> WorkspacePaths:
    paths = workspace_paths(layout, workspace_id)
    try:
        paths.root.mkdir(mode=0o700)  # not parents=True: refuses an existing folder
    except FileExistsError as error:
        raise WorkspaceFolderExistsError from error
    for directory in (paths.files, paths.automations):
        directory.mkdir(mode=0o700)
    return paths


def remove_unused_folders(layout: DataLayout) -> list[Path]:
    """Once: the empty unused folders go (`rmdir`: a folder with anything in it is
    never touched). Safe to repeat."""
    removed: list[Path] = []
    if not layout.workspaces.is_dir():
        return removed
    for workspace in sorted(layout.workspaces.iterdir()):
        for name in UNUSED:
            folder = workspace / name
            if folder.is_dir() and not folder.is_symlink():
                try:
                    folder.rmdir()
                except OSError:
                    continue  # not empty (or not ours to remove): it stays
                removed.append(folder)
    return removed


def move_workspace_to_trash(
    layout: DataLayout, workspace_id: str, now_ms: int | None = None
) -> str:
    """Moves the folder to `.trash/<id>--<ms>` and returns that name."""
    paths = workspace_paths(layout, workspace_id)
    stamp = now_ms if now_ms is not None else int(time.time() * 1000)
    name = f"{paths.root.name}{TRASH_SEPARATOR}{stamp}"
    paths.root.rename(layout.trash / name)
    return name


def restore_workspace_from_trash(layout: DataLayout, trash_name: str) -> str:
    parts = trash_name.split(TRASH_SEPARATOR)
    if len(parts) != 2:
        raise ValueError("not a trash entry")
    paths = workspace_paths(layout, parts[0])
    if paths.root.exists():
        raise WorkspaceFolderExistsError
    (layout.trash / trash_name).rename(paths.root)
    return parts[0]


def purge_trash(layout: DataLayout, days: int, now_ms: int) -> list[str]:
    """Removes trash entries older than `days`."""
    limit = now_ms - days * 24 * 60 * 60 * 1000
    removed: list[str] = []
    for entry in layout.trash.iterdir():
        parts = entry.name.split(TRASH_SEPARATOR)
        if len(parts) == 2 and parts[1].isdigit() and int(parts[1]) < limit:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
    return removed
