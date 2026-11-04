"""Names of Hermes's managed scope (HERMES_MANAGED_DIR): the environment variable, its two
files, the one lock its config.yaml is written under, and its first command's timeout.

Owns: MANAGED_LOCK, the one lock for the managed config.yaml.
Must not: read or write the managed files (engine/hermes/managed.py does).

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

import threading
from pathlib import Path

__all__ = [
    "MANAGED_ENV",
    "MANAGED_FIRST_TIMEOUT_S",
    "MANAGED_LOCK",
    "managed_files",
]


MANAGED_ENV = "HERMES_MANAGED_DIR"  # Hermes's Managed Scope folder (config.py managed_dir)

MANAGED_FIRST_TIMEOUT_S = 1800  # the managed folder's first command: Hermes's home upkeep

MANAGED_LOCK = threading.Lock()  # one managed config.yaml: one write at a time


def managed_files(folder: Path) -> tuple[Path, Path]:
    """The two files Hermes's managed scope reads (hermes_cli/managed_scope.py
    load_managed_config / load_managed_env)."""
    return folder / "config.yaml", folder / ".env"
