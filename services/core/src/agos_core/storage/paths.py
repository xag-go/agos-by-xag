"""The single check every agent-facing path goes through (ARCHITECTURE §12).

Paths are resolved the way the filesystem will (symlinks followed, `..`
collapsed) and must land inside one of the run's allowed roots. The container
mounts are the other layer: a symlink created after this check (a race) is
stopped there.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AccessMode = Literal["read", "write"]


class PathOutsideRootsError(ValueError):
    def __init__(self, mode: AccessMode) -> None:
        # The requested path is not echoed: it may come from a model.
        super().__init__(f"path is outside the allowed {mode} folders")


@dataclass(frozen=True)
class Roots:
    """Real paths. Write roots are also readable."""

    read: tuple[Path, ...]
    write: tuple[Path, ...]


def make_roots(*, read: list[Path] | None = None, write: list[Path] | None = None) -> Roots:
    def real(p: Path) -> Path:
        if not p.is_absolute():
            raise ValueError("roots must be absolute paths")
        return p.resolve(strict=True)

    return Roots(tuple(real(p) for p in read or []), tuple(real(p) for p in write or []))


def is_inside(root: Path, child: Path) -> bool:
    """True when `child` is `root` itself or inside it (not a same-prefix sibling)."""
    return child == root or root in child.parents


def resolve_safe_path(
    roots: Roots, requested: str, mode: AccessMode, base: Path | None = None
) -> Path:
    """The real absolute path, or PathOutsideRootsError. Relative paths start at `base`
    (default: the first write root, i.e. the workspace)."""
    if "\0" in requested:
        raise PathOutsideRootsError(mode)
    start = base or (roots.write[0] if roots.write else roots.read[0] if roots.read else None)
    if start is None:
        raise PathOutsideRootsError(mode)
    # resolve(strict=False) follows every symlink that exists and appends the
    # rest; parts that don't exist yet can't be symlinks.
    real = (start / requested).resolve(strict=False)
    allowed = roots.write if mode == "write" else roots.write + roots.read
    if not any(is_inside(root, real) for root in allowed):
        raise PathOutsideRootsError(mode)
    return real
