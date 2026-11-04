"""Where the agos-guard plugin's files are on disk.

Owns: the plugin's source folder (AGOS copies it into each Hermes profile) and the
plugin file the core runs as a script in Hermes's own runtime (keys.py: masking and
the Secrets check).

Must not: import the plugin. It runs inside Hermes; the core only copies its files
and runs them there. Names both sides share are in agos_core/shared/.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["KEYS_SCRIPT", "PLUGIN_SOURCE"]

PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "hermes_plugin" / "agos_guard"
KEYS_SCRIPT = PLUGIN_SOURCE / "keys.py"
