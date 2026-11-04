"""The Office's fingerprint (what its live refresh compares): every store the
Office page is read from, as it is now, and the last fingerprint kept while none of
them moved. api/office.py reads the page and asks here whether to read it again.

Must not: read the page itself (the team, the board, the looks), or know about HTTP.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from agos_core.actions import agent_profiles
from agos_core.engine import read_cache

__all__ = ["inputs", "kept", "remember"]

# The Office's fingerprint, kept while none of the stores it is read from moved:
# its live refresh asks every 2 s, and the reads behind it (the team, the board and
# the looks, which reads the team again) took ~0.55 s of the core each time.
_STAMPS: read_cache.ReadCache[str] = read_cache.ReadCache("office-stamp", max_entries=64)


def inputs(core: Any, workspace_id: str) -> tuple[Any, ...]:
    """Every store the Office's answers come from, as it is now (stats, no rows read):
    AGOS's rows (each write on the shared connection counts), Hermes's board, and each
    Hermes home of the root (its folder: a member added, parked or deleted; its
    profile, SOUL.md and config: titles and roles; its state.db and sessions index:
    the chats)."""
    stores: list[Any] = [core.db.total_changes]
    if core.engine is None:
        return tuple(stores)
    stores.append(read_cache.sqlite_stamp(agent_profiles.board_db(core, workspace_id)))
    root = core.engine.profile_home(workspace_id)
    profiles = root / "profiles"
    homes = [root]
    with contextlib.suppress(OSError):
        homes += sorted(p for p in profiles.iterdir() if p.is_dir())
    stores.append(read_cache.file_stamp(profiles, profiles / ".deleted"))
    for home in homes:
        stores.append(
            (
                home.name,
                read_cache.file_stamp(
                    home,
                    home / "profile.yaml",
                    home / "SOUL.md",
                    home / "config.yaml",
                    home / "sessions" / "sessions.json",
                ),
                read_cache.sqlite_stamp(home / "state.db"),
            )
        )
    return tuple(stores)


def remember(workspace_id: str, stamp: tuple[Any, ...], value: str) -> None:
    """The fingerprint of a page just read (taken before the reads)."""
    _STAMPS.drop(workspace_id)
    _STAMPS.get(workspace_id, stamp, lambda: value)


def kept(workspace_id: str, stamp: tuple[Any, ...], read: Callable[[], str]) -> str:
    """The kept fingerprint while `stamp` is unchanged, else `read()` again."""
    return _STAMPS.get(workspace_id, stamp, read)
