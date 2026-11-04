"""The owner's decisions reach Hermes, and Hermes learns from them by itself.

Hermes learns from what it is told in a conversation: after an answer its
background review decides what is worth keeping (memory, the owner's profile, a
skill) and its curator tidies the skills later. A decision on the board (approve,
cancel, a No to a proposal, an Undo) happens outside any conversation, so AGOS
only says it, as the owner's own words, in the workspace's learning conversation
on its Hermes gateway (`agos:l1`), whose channel prompt (Hermes's per-conversation
prompt) says what the conversation is for. What to learn, where to keep it and how
to tidy it is Hermes's: AGOS never writes the agents' memory itself.

Why AGOS says them at all: Hermes's background review and curator learn only from
what happens in a conversation (website/docs/user-guide/features/memory.md,
curator.md); a click on a card in AGOS happens in none.

Each workspace has its own conversation and its own memory: nothing of one
project reaches another.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agos_core.context import Core
from agos_core.db import hermes_inbox
from agos_core.engine import doorbell
from agos_core.hermes_gateway import state_rows

log = logging.getLogger("agos.learning")

ADDRESS = "agos:l1"  # the workspace's learning conversation on its Hermes gateway
TURN_ID = -3_000_000_001  # its answers need nothing from AGOS

INSTRUCTIONS = """[AGOS — the owner's decisions on the team's work]

Each message here is a decision the owner just made on the board of this workspace
(approved, cancelled, said no, undid something), with his reason when he gave one.
Learn from it the way you learn from anything he tells you: if it teaches something
that lasts (what he wants, what he doesn't, how he likes the work), keep it now with
your memory tool, in his profile when it's about him, or improve the skill it belongs
to. Don't keep one-off events. Do no other work here and start nothing. Answer in one
short word."""


def say(core: Core, workspace_id: str, text: str) -> None:
    """One decision, said in the workspace's learning conversation (Hermes takes it
    like a message from him; if it is already answering, it joins that answer)."""
    from agos_core.actions import hermes_channel
    from agos_core.db.workspaces import get_workspace

    workspace = get_workspace(core.db, workspace_id)
    if workspace is None:
        return
    # A stopped gateway isn't started for this: Hermes's service (Restart=always)
    # keeps it up and the inbox waits; one stopped on purpose stays stopped. Only the
    # test-only "spawn" supervisor brings back a gateway AGOS spawned (idle.spawned_up).
    from agos_core.actions import idle

    idle.spawned_up(core, workspace_id)
    switch = hermes_channel.model_command(
        core, f"{workspace_id}/{ADDRESS}", workspace.default_model, workspace_id
    )
    for body, kind in ((switch, "command"), (text, "message")):
        if body:
            hermes_inbox.put(core.db, workspace_id, ADDRESS, body, kind)
            doorbell.ring(doorbell.INBOX, workspace_id)


def started(core: Core, workspace_id: str) -> dict[str, Any]:
    return {"turnId": TURN_ID, "fullAccess": False, "agent": ""}


def decision_text(kind: str, subject: str, detail: str = "", agent: str | None = None) -> str:
    """One decision as the owner's own words."""
    who = f" ({agent})" if agent else ""
    text = f"The owner {kind}{who}: {subject}"
    return text + (f"\nHe said: {detail}" if detail else "")


_DECISION = re.compile(r"\AThe owner (\w+)(?: \((.*?)\))?: (.*?)(?:\nHe said: (.*))?\Z", re.S)

# The learning conversation's sessions first (a few hundred rows), then their messages
# through Hermes's own index (idx_messages_session_id): a JOIN with the LIKE on the
# session made SQLite walk every message of the workspace (345 ms on a 209 MB
# state.db, cold). Same rows, same order.
_DECISIONS_SQL = state_rows.DECISIONS_SQL


def decisions(core: Core, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """His decisions as Hermes keeps them: the learning conversation's messages in
    the workspace's own Hermes (state.db, read only), newest first."""
    import sqlite3
    from datetime import UTC, datetime

    if core.engine is None:
        return []
    path = core.engine.profile_home(workspace_id) / "state.db"
    if not path.is_file():
        return []
    try:
        rows = state_rows.user_messages(
            path,
            "%:agos:dm:" + ADDRESS.split(":", 1)[1],
            limit,  # agent:main:agos:dm:l1
        )
    except sqlite3.Error:
        return []
    out = []
    for content, at in rows:
        found = _DECISION.match(str(content or "").strip())
        if not found:
            continue
        out.append(
            {
                "at": datetime.fromtimestamp(float(at or 0), UTC).isoformat(),
                "kind": found[1],
                "subject": found[3],
                "detail": found[4] or "",
                "agent": found[2],
                "learned": True,
            }
        )
    return out
