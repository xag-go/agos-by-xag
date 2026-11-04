"""The library's tool rows: one id row per toolset Hermes offers, added by themselves.
The row holds only the toolset's id in AGOS (what each workspace turns on); its name
and words are Hermes's, read from the catalog each time.

Owns: adding the missing tool rows (through db/library.py, the table's one writer).
Must not: change any other library row, or a workspace's Hermes config.

Split out of agos_core.actions.library (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from agos_core.actions.services.library.records import hermes_tools_module
from agos_core.context import Core
from agos_core.db import library as repo

__all__ = ["ensure_tools"]


def ensure_tools(core: Core) -> None:
    """Hermes's toolsets appear in the library by themselves: every one Hermes
    offers (its own list). The row is only the toolset's id in AGOS (what each
    workspace turns on); its name and words are Hermes's, read from the catalog
    each time (title_of, summary_of)."""
    tools = hermes_tools_module()
    for name in tools.names():
        if repo.find_item(core.db, "tool", name) is not None:
            continue
        repo.insert_item(
            core.db,
            kind="tool",
            name=name,
            title="",
            summary="",
            definition={},
            source="hermes",
        )
