"""Telegram topics AGOS asks the workspace's Hermes gateway to make, and waiting for their ids.
Must not: decide which chat goes where (addresses does).

Split out of agos_core.actions.channels (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import itertools
import threading
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.engine import doorbell

__all__ = [
    "TOPIC_WAIT_S",
    "make_topic",
]

# Topics he asked for (a chat's own topic in his Telegram group): the workspace's
# Hermes gateway makes them with its own bot; AGOS waits for the answer.
TOPIC_WAIT_S = 45.0
_topics: dict[int, dict[str, Any]] = {}
_topics_lock = threading.Lock()
_topic_ids = itertools.count(1)


def _topics_to_make(workspace_id: str) -> list[dict[str, Any]]:
    with _topics_lock:
        out = []
        for tid, t in _topics.items():
            if t["workspace"] == workspace_id and not t["taken"]:
                t["taken"] = True
                out.append({"id": tid, "chat": t["chat"], "name": t["name"]})
        return out


def make_topic(workspace_id: str, chat: str, name: str) -> str:
    """Asks the workspace's Hermes gateway to create the topic; its address."""
    tid = next(_topic_ids)
    done = threading.Event()
    with _topics_lock:
        _topics[tid] = {
            "workspace": workspace_id,
            "chat": chat,
            "name": name[:128],
            "taken": False,
            "done": done,
            "thread": None,
            "error": None,
        }
    doorbell.ring(doorbell.OUTBOX, workspace_id)
    try:
        if not done.wait(TOPIC_WAIT_S):
            raise ActionError("Couldn't create it: the workspace didn't answer (is it running?)")
        t = _topics[tid]
        if t["error"] or not t["thread"]:
            raise ActionError(
                f"Couldn't create it: Telegram: {str(t['error'] or 'no topic')[:200]}"
            )
        return f"{chat}:{t['thread']}"
    finally:
        with _topics_lock:
            _topics.pop(tid, None)
