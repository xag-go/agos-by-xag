"""Copy agos_core/shared/ modules into the agos-guard plugin, byte for byte.

The plugin runs inside Hermes and cannot import agos_core, so it keeps its own copy of
each shared module (the core imports agos_core.shared, never the plugin).

    python scripts/sync_shared.py          # write the copies
    python scripts/sync_shared.py --check  # fail when a copy differs (tests do this too)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
SHARED = CORE / "src" / "agos_core" / "shared"
PLUGIN = CORE / "src" / "agos_core" / "hermes_plugin" / "agos_guard"


def sources() -> list[Path]:
    """The shared modules the plugin keeps a copy of (the package doc is not one)."""
    return sorted(p for p in SHARED.glob("*.py") if p.name != "__init__.py")


def stale() -> list[str]:
    """Plugin copies that are missing or differ from their shared source."""
    out = []
    for source in sources():
        copy = PLUGIN / source.name
        if not copy.is_file() or copy.read_bytes() != source.read_bytes():
            out.append(copy.name)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        names = stale()
        if names:
            print("plugin copies differ: run `python scripts/sync_shared.py`: " + ", ".join(names))
            return 1
        return 0
    for source in sources():
        (PLUGIN / source.name).write_bytes(source.read_bytes())
        print(f"copied {source.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
