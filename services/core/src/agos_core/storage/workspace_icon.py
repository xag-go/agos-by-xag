"""A workspace's icon: the picture on its tile in the web app's rail.

AGOS-only presentation data (a Hermes profile carries a display name and a
description, no picture: hermes_cli/profiles.py:916 read_profile_meta, :958
write_profile_meta). The file sits with the workspace's own AGOS data, beside its
chat attachments (`files/.agos/uploads`, engine/attachments.py UPLOADS), as
`icon.<ext>`; its type is read from its bytes, never from the upload's name.
"""

import os
import re
from pathlib import Path

from agos_core.storage.layout import DataLayout, workspace_paths

MAX_BYTES = 1024 * 1024
# AGOS's own folder in the workspace's files, the one chat attachments use
# (engine/attachments.py UPLOADS is `.agos/uploads`): the icon sits beside them.
AGOS_DIR = Path(".agos")
# The one file per type (its name is fixed, so the registry can name it).
ICON_FILES: dict[str, str] = {
    "image/png": "icon.png",
    "image/jpeg": "icon.jpg",
    "image/webp": "icon.webp",
    "image/svg+xml": "icon.svg",
}
_ICON_MIMES = {name: mime for mime, name in ICON_FILES.items()}
_SVG_START = re.compile(rb"^\s*(?:<\?xml\b|<svg\b)", re.I)
_SVG_SCRIPT = re.compile(rb"<\s*script\b", re.I)


class IconError(ValueError):
    """Safe to show to the owner."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def folder(layout: DataLayout, workspace_id: str) -> Path:
    return workspace_paths(layout, workspace_id).files / AGOS_DIR


def sniff(data: bytes) -> str:
    """The image type the bytes are: PNG, JPEG, WebP or a safe SVG, else refused."""
    if len(data) > MAX_BYTES:
        raise IconError("The icon can be up to 1 MB.", 413)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if _SVG_START.match(data.lstrip(b"\xef\xbb\xbf")):
        if _SVG_SCRIPT.search(data):
            raise IconError("An SVG icon can't contain a script.", 415)
        return "image/svg+xml"
    raise IconError("The icon can be a PNG, JPEG, WebP or SVG picture.", 415)


_Found = tuple[Path, str, str] | None
# One directory read per workspace folder, then the answer is kept: icons change
# only through save/remove below (same process), so a list of 30 workspaces costs
# no file system call after the first view (the Docs page's listing guard counts).
_known: dict[Path, _Found] = {}


def find(layout: DataLayout, workspace_id: str) -> _Found:
    """The icon's path, type and stamp, with one directory read the first time."""
    icon_dir = folder(layout, workspace_id)
    if icon_dir in _known:
        return _known[icon_dir]
    found: _Found = None
    try:
        with os.scandir(icon_dir) as entries:
            for entry in entries:
                mime = _ICON_MIMES.get(entry.name)
                if mime is not None and entry.is_file(follow_symlinks=False):
                    found = (icon_dir / entry.name, mime, str(entry.stat().st_mtime_ns))
                    break
    except OSError:
        found = None
    _known[icon_dir] = found
    return found


def forget(icon_dir: Path | None = None) -> None:
    """Drop the kept answers (one folder, or all: a new data root in tests)."""
    if icon_dir is None:
        _known.clear()
    else:
        _known.pop(icon_dir, None)


def stamp(layout: DataLayout, workspace_id: str) -> str | None:
    """The record's `icon`: changes with the file, None without one."""
    found = find(layout, workspace_id)
    return found[2] if found else None


def save(layout: DataLayout, workspace_id: str, data: bytes) -> None:
    """Writes the icon aside then renames it over; an icon of another type goes."""
    mime = sniff(data)
    icon_dir = folder(layout, workspace_id)
    icon_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    icon_name = ICON_FILES[mime]
    icon_tmp = icon_dir / f".{icon_name}.tmp"
    icon_tmp.write_bytes(data)
    icon_tmp.chmod(0o600)
    icon_tmp.replace(icon_dir / icon_name)
    for other in ICON_FILES.values():
        if other != icon_name:
            (icon_dir / other).unlink(missing_ok=True)
    forget(icon_dir)


def remove(layout: DataLayout, workspace_id: str) -> None:
    icon_dir = folder(layout, workspace_id)
    for icon_name in ICON_FILES.values():
        (icon_dir / icon_name).unlink(missing_ok=True)
    forget(icon_dir)
