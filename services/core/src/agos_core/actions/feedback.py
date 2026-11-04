"""👍 / 👎 on an agent's reply or on a document revision, and what the agent learns
from it.

A vote is an AGOS row (Hermes keeps no vote on a message or a file revision);
each one is said, as the owner's own words, in the workspace's learning
conversation on its Hermes (actions/learning.py), so the agent learns what he
liked and what needs work the way it learns from a decision on the board. Nothing
leaves the server: there is no sharing of votes anywhere.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions import learning
from agos_core.actions.errors import ActionError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import feedback_votes

KINDS = ("reply", "revision")
WORDS = {1: "liked", -1: "disliked"}


def vote(
    core: Core,
    workspace_id: str,
    *,
    kind: str,
    ref: str,
    value: int,
    note: str = "",
    subject: str = "",
) -> dict[str, Any]:
    """Sets (1 / -1) or takes back (0) the owner's vote on one item; a set vote is
    said to the workspace's Hermes once, with his note when he wrote one.
    `ref`: reply = "<chat id>:<message id>", revision = "<card>:<key>:<n>".
    `subject`: what the item is, in words (shown to the agent)."""
    require_workspace(core, workspace_id)
    if kind not in KINDS:
        raise ActionError("A vote goes on a reply or on a document revision.")
    if value not in (-1, 0, 1):
        raise ActionError("A vote is 👍, 👎 or none.")
    if not ref.strip():
        raise ActionError("Nothing to vote on.")
    if value == 0:
        feedback_votes.delete(core.db, workspace_id, kind, ref)
        return {"vote": 0}
    feedback_votes.put(core.db, workspace_id, kind, ref, value, note.strip()[:2000])
    learning.say(
        core,
        workspace_id,
        learning.decision_text(WORDS[value], _subject(kind, ref, subject), note.strip()[:2000]),
    )
    return {"vote": value}


def _subject(kind: str, ref: str, subject: str) -> str:
    what = " ".join(subject.split())[:600]
    if kind == "reply":
        return f"your reply{(' — ' + what) if what else ''} (chat message {ref})"
    card, _sep, rest = ref.partition(":")
    key, _sep, n = rest.partition(":")
    return f"revision v{n} of document {key} on card {card}" + (f" — {what}" if what else "")


def votes_of(core: Core, workspace_id: str, kind: str, prefix: str) -> dict[str, int]:
    """The owner's votes on the items whose ref starts with `prefix` (one chat's
    replies, one document's revisions): ref -> vote."""
    return feedback_votes.with_prefix(core.db, workspace_id, kind, prefix)
