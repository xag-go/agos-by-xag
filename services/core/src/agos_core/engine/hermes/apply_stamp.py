"""A profile apply's outcome (ApplyResult) and the digest its stamp is made of.

Must not: apply anything (HermesEngine.apply in engine/hermes/__init__.py does).

Part of engine/hermes (moved out of the old common.py).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from agos_core.engine.rules import Mount

__all__ = [
    "ApplyResult",
    "_digest",
]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ApplyResult:
    profile: str
    mounts: list[Mount]
    restarted: bool
    sandboxes_removed: int
