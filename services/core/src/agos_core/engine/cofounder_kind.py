"""One Co-Founder action kind (engine/cofounder_parity/'s KINDS) and the domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Gate = Literal["undo", "owner", "once"]
# What a kind changes (engine/power.py, read vs act).
Effect = Literal["power", "work", "read"]


@dataclass(frozen=True)
class Kind:
    """One Co-Founder action of a domain.

    gate: "undo" = done at once, its card has Undo; "owner" = waits for the owner's
    yes on its card first (imports, Hermes update, people, deletes...); "once" = done,
    nothing to take back (a run, a test, a check: its card says what came of it)."""

    domain: str
    required: tuple[str, ...]
    title: str
    fields: str
    gate: Gate = "undo"
    structured: tuple[str, ...] = ()  # fields given as a list or an object


AUTOMATIONS = "automations"
TEAM = "team"
SKILLS = "skills_admin"
BOARD = "board_admin"
WORKSPACE = "workspace"
