"""The ownership registry's building blocks (db/ownership/):
the two classes an AGOS-held thing can be in, and the helpers each entry is written with.

Must not: hold a registry entry (each lives in its area module).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "AGOS_ONLY",
    "CHANGED",
    "CHAT",
    "ID",
    "MADE",
    "MOVE_ONCE",
    "WS",
    "Kind",
    "Owned",
    "Table",
    "agos",
    "cols",
    "move",
]

Kind = Literal["AGOS_ONLY", "MOVE_ONCE"]
AGOS_ONLY: Kind = "AGOS_ONLY"
MOVE_ONCE: Kind = "MOVE_ONCE"


@dataclass(frozen=True)
class Owned:
    kind: Kind
    why: str
    hermes: str = ""  # Hermes evidence (v0.22.2), where Hermes has something close
    moving: tuple[str, int] | None = None  # (branch, migrations count when marked)


@dataclass(frozen=True)
class Table:
    owned: Owned
    columns: dict[str, Owned] = field(default_factory=dict)
    view: bool = False
    # The one module that writes the table (its repository, db/<table>.py) once its
    # service owns it; "" while it still has more (tests/test_board_chat_repositories.py
    # checks that nothing else writes a table that names one).
    writer: str = ""


def agos(why: str, hermes: str = "", moving: tuple[str, int] | None = None) -> Owned:
    return Owned(AGOS_ONLY, why, hermes, moving)


def move(why: str, hermes: str) -> Owned:
    return Owned(MOVE_ONCE, why, hermes)


def cols(**reasons: str | Owned) -> dict[str, Owned]:
    """Columns: a plain reason is AGOS_ONLY."""
    return {k: v if isinstance(v, Owned) else agos(v) for k, v in reasons.items()}


ID = "row id"
WS = "the workspace it belongs to (AGOS's own workspace list)"
CHAT = "the AGOS chat it belongs to"
MADE = "when AGOS made the row"
CHANGED = "when AGOS last changed the row"
