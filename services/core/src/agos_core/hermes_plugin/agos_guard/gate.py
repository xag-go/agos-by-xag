"""AGOS's tools in Hermes: the owner gate on the plugin's side (moved out of bridge.py,
which keeps thin wrappers so `bridge.owner_decides` and friends stay where they were).

- `owner_decides`: before agos_action / agos_capability / agos_skill_request run,
  AGOS (bridge /tool-check) says whether Hermes asks the owner first. Fails closed:
  no answer = refused.
- A TAINTED ask (the session read untrusted content: taint.py) comes back with a
  one-time nonce. Its Hermes rule key is `agos:once:<nonce>`, never seen before, so
  Hermes's session / always allowlist can't answer it, and owner_asks (__init__.py)
  asks him itself under YOLO or approvals off. The nonce is kept for that very call
  and sent with it (`once`): the core runs the batch only with it, once.
- `tool_post`: the tool itself, with the session and that nonce.

`b` is the bridge module (its post, its chat lookup, its parents), passed in so a
test that patches bridge.post or bridge.bridge patches this too.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

# Said to the agent when AGOS can't tell whether the owner must say yes first.
GATE_UNREACHABLE = (
    "AGOS couldn't check whether the owner must approve this (AGOS is busy or can't be "
    "reached), so nothing was done. Try again in a minute; tell the owner if it keeps "
    "happening."
)
ONCE_KEY = "agos:once:"

_once: dict[tuple[str, str, str], str] = {}  # (top session, tool, args) -> nonce
_lock = threading.Lock()
_MAX = 500


def call_key(args: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()


def keep_once(session: str, tool: str, args: dict[str, Any], nonce: str) -> None:
    with _lock:
        if len(_once) >= _MAX:
            _once.clear()
        _once[(session, tool, call_key(args))] = nonce


def take_once(session: str, tool: str, args: dict[str, Any]) -> str:
    with _lock:
        return _once.pop((session, tool, call_key(args)), "")


def owner_decides(
    b: Any, tool: str, args: dict[str, Any], session_id: str = ""
) -> dict[str, str] | None:
    """Before one of AGOS's tools: Hermes's own Allow / Deny card when the owner must
    say yes first (AGOS decides: his settings, the conversation, what it touches).
    Fails closed: when AGOS can't answer (not connected, busy past the wait, down),
    the tool is refused rather than run without the owner's yes."""
    session = str(session_id or "")
    chat = b._address_of_session(session) or ""
    top = b._taint().root(session, b._parents)
    if b.bridge() is None or not b._taint().told(session, b._parents, chat, b.post):
        return {"action": "block", "message": GATE_UNREACHABLE}  # (read vs act: taint.py)
    body = {"tool": tool, "args": args, "chat": chat, "session": top}
    answer = b.post("tool-check", body, 15)
    if answer is None:
        return {"action": "block", "message": GATE_UNREACHABLE}
    if not answer.get("ask"):
        return None
    nonce = str(answer.get("once") or "")
    if nonce:
        keep_once(top, tool, args, nonce)
    return {
        "action": "approve",
        "message": str(answer.get("message") or tool)[:900],
        "rule_key": f"{ONCE_KEY}{nonce}" if nonce else f"agos:{tool}",
    }


def tool_post(
    b: Any, path: str, session_id: str, body: dict[str, Any], what: str, tool: str, args: Any
) -> str:
    """The tool's call to AGOS, from its chat, with its session and the nonce of the
    owner's yes (a tainted ask)."""
    session = str(session_id or "")
    address = b._address_of_session(session)
    if address is None or b.bridge() is None:
        return json.dumps({"error": f"AGOS can't tell which chat this is; {what}."})
    if not b._taint().told(session, b._parents, address, b.post):
        return json.dumps({"error": f"AGOS can't be reached; {what}."})
    top = b._taint().root(session, b._parents)
    once = take_once(top, tool, args if isinstance(args, dict) else {})
    sent = {"chat": address, **body, "session": top, "once": once}
    answer, late = b._post(path, sent, b.TOOL_WAIT_S)
    if answer is None and late:
        late_said = (
            f"AGOS is still working on it ({b.TOOL_WAIT_S // 60} minutes without an "
            "answer), so it may still get done: don't send it again. Its card in "
            "this chat shows how it ended."
        )
        return json.dumps({"error": late_said})
    if answer is None:
        return json.dumps({"error": f"AGOS can't be reached; {what}."})
    return json.dumps(answer)


def gate_fields(b: Any, session_id: str, tool: str, args: dict[str, Any]) -> dict[str, str]:
    """Where a tool of AGOS's that has its own body (agos_skill_request) was called
    from, and the owner's one-time yes for it, for the core's re-check."""
    session = str(session_id or "")
    top = b._taint().root(session, b._parents)
    chat = b._address_of_session(session) or ""
    if chat:
        b._taint().told(session, b._parents, chat, b.post)
    return {"chat": chat, "session": top, "once": take_once(top, tool, args)}
