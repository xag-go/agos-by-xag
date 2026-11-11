"""A team member's refusal of the Co-Founder's tools, and the stop after the first one.

Owns: the one message a member gets when it calls a Co-Founder tool (what to do
instead), and the per-process memory of which card runs were already refused, so a
repeat gets "stop" instead of another retry that re-reads the whole context.

Must not: decide which tools are the Co-Founder's (the facade's COFOUNDER_TOOLS).
"""

from __future__ import annotations

import os

__all__ = ["forget", "refusal"]

REFUSED = (
    "Blocked: that is the Co-Founder's tool. Do not retry. Hand this card to review now "
    "(kanban_request_review or your completion path) with one note saying exactly what "
    "change is needed; the Co-Founder will do it."
)
AGAIN = "Already refused once — stop and hand to review now. "

# Card runs (card + run id, or the session of a chat) that were refused once. A worker
# is one process per card run, so this stays small; the cap only guards a long-lived one.
_REFUSED_RUNS: set[str] = set()
_CAP = 512


def _run_key(session: str) -> str:
    card = os.environ.get("HERMES_KANBAN_TASK", "")
    if card:
        return f"{card}#{os.environ.get('HERMES_KANBAN_RUN_ID', '')}"
    return f"session:{session}"


def refusal(session: str, *, acting: bool = True) -> str:
    """The message for a member's call of a Co-Founder tool. The first one in a run
    says what to do; every later one in the same run says to stop. `acting=False`
    (a look ahead, not the call itself) is not counted."""
    key = _run_key(session)
    seen = key in _REFUSED_RUNS
    if acting and not seen:
        if len(_REFUSED_RUNS) >= _CAP:
            _REFUSED_RUNS.clear()
        _REFUSED_RUNS.add(key)
    return (AGAIN if seen else "") + REFUSED


def forget() -> None:
    """Drop the memory (tests)."""
    _REFUSED_RUNS.clear()
