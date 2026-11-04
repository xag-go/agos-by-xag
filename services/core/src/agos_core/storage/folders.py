"""Folders the owner adds to a workspace."""

import re
import unicodedata
from pathlib import Path

from agos_core.storage.layout import DataLayout
from agos_core.storage.paths import is_inside


class FolderNotAllowedError(ValueError):
    """The message is safe to show to the owner."""


def check_added_folder(layout: DataLayout, requested: str) -> Path:
    """Real path of a folder the owner wants to add. Refuses AGOS's own data, anything
    containing it, and its private folders. Another workspace's folder is allowed."""
    path = Path(requested)
    if not path.is_absolute():
        raise FolderNotAllowedError("use a full path, starting with /")
    try:
        real = path.resolve(strict=True)
    except (FileNotFoundError, RuntimeError) as error:
        raise FolderNotAllowedError("this folder doesn't exist") from error
    if not real.is_dir():
        raise FolderNotAllowedError("this is a file, not a folder")
    if real == Path(real.anchor):
        raise FolderNotAllowedError("the whole disk can't be added")
    data_root = layout.root.resolve()
    if is_inside(real, data_root):
        raise FolderNotAllowedError("this folder contains AGOS's own data (settings and secrets)")
    for private in (layout.system, layout.trash, layout.global_dir):
        if is_inside(private.resolve(), real):
            raise FolderNotAllowedError("this is one of AGOS's private folders")
    return real


def share_name(real_path: Path, taken: list[str]) -> str:
    """The name inside the container (`/shared/<name>`), safe and unique."""
    ascii_only = unicodedata.normalize("NFKD", real_path.name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")[:40] or "folder"
    name, n = base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name
