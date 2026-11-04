"""A throwaway Hermes home holding only a COPY of one profile's config.yaml, and a
throwaway managed scope holding only a COPY of the managed config.yaml: the
YAML-only side of the ".env vs config.yaml" probe (engine/hermes.py env_in_use runs
Hermes's own gateway start there to see what config.yaml alone sets, with Hermes's
managed overlay on top but without any .env). The profile and the managed scope are
never touched; the copies are deleted with their temporary folder."""

from __future__ import annotations

import shutil
from pathlib import Path


def yaml_only_home(home: Path, managed: Path, scratch: Path) -> tuple[Path, Path]:
    """(the throwaway home, the throwaway managed scope folder)."""
    root = scratch / "home"
    scope = scratch / "managed"
    root.mkdir()
    scope.mkdir()
    for source, target in ((home, root), (managed, scope)):
        if (source / "config.yaml").is_file():
            shutil.copyfile(source / "config.yaml", target / "config.yaml")
    return root, scope
