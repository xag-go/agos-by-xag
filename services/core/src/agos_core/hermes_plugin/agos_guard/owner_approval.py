"""The owner's "Ask me" through Hermes's own approval gate.

Split out of agos_core.hermes_plugin.agos_guard (the guard's facade). Owns: refusing
it in a scheduled run (nobody can answer), the guard asking him itself under Full
access (Hermes's YOLO skips the gate), one question at a time per conversation, and
his yes for one call carried from the tool_execution middleware to the hook.

Must not: decide which rule applies (policy.py).
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
from typing import Any

from . import runtime

__all__ = [
    "_ANSWERED",
    "_ASKING",
    "_ASKING_GUARD",
    "_accepted",
    "_approval_module",
    "_asking",
    "_asks_him_itself",
    "_call_of",
    "_in_cron",
    "owner_asks",
]


def _approval_module() -> Any:
    """Hermes's approval module, or None outside Hermes."""
    try:
        import importlib

        return importlib.import_module("tools.approval")
    except Exception as error:  # noqa: BLE001 — not inside Hermes
        runtime._report("tools.approval", error)
        return None


def _in_cron() -> bool:
    """A scheduled run: Hermes's own ctx.current_cron_execution(). Its delegated
    children read None there (H: cron/execution_identity.py), so the cron session
    flag Hermes binds for the whole run (its public session env) counts too."""
    ctx = runtime._CTX.get("ctx")
    with runtime._guard("hermes_cli.plugins.PluginContext.current_cron_execution"):
        if ctx is not None and ctx.current_cron_execution() is not None:
            return True
    try:
        from gateway.session_context import get_session_env  # type: ignore[import-not-found]

        value = get_session_env("HERMES_CRON_SESSION", "")
    except Exception as error:  # noqa: BLE001 — outside Hermes's gateway
        runtime._report("gateway.session_context.get_session_env", error)
        value = os.environ.get("HERMES_CRON_SESSION", "")
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _accepted(function: Any, **kwargs: Any) -> dict[str, Any]:
    """Only the keyword arguments Hermes's function takes (its signature in this
    Hermes): a parameter Hermes dropped (v0.22.2 dropped `warnings` from
    tools/approval.py `_human_decision`) never turns the owner's card into a
    TypeError that blocks the action."""
    import inspect

    try:
        params = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def owner_asks(decision: dict[str, str] | None, tool: str) -> dict[str, str] | None:
    """An owner's rule that asks him first ("approve": Autonomy "Ask me", an AGOS
    tool he must OK) goes to Hermes's own approval gate, except where Hermes would
    answer it by itself:

    - a scheduled (cron) run: nobody is there and `approvals.cron_mode: approve`
      lets the gate say yes alone, so it is refused;
    - Full access (Hermes's YOLO for the conversation, or `approvals.mode: off`):
      the gate is skipped for every approval, so the guard asks him itself through
      Hermes's own Allow / Deny prompt. Full access never answers his own rules.
    Anything unexpected inside Hermes's gate fails closed (blocked)."""
    if not decision or decision.get("action") != "approve":
        return decision
    approval = _approval_module()
    if approval is None:
        return decision
    message = str(decision.get("message") or tool)
    once = str(decision.get("rule_key") or "").startswith("agos:once:")  # gate.py: tainted
    if _in_cron():
        return {
            "action": "block",
            "message": f"Blocked: the owner's rule says to ask him first ({message}), and "
            "nobody can answer in a scheduled run. Don't try another way; say in your "
            "result what you would have done.",
        }
    try:
        bypass = bool(approval.is_approval_bypass_active())
    except Exception as error:  # noqa: BLE001 — older Hermes: its own gate decides
        runtime._report("tools.approval.is_approval_bypass_active", error)
        bypass = once  # a tainted ask is never left to a gate YOLO may skip: asked here
    if not bypass:
        return decision
    pattern = f"plugin_rule:{decision.get('rule_key') or tool}"
    step = "tools.approval.get_current_session_key"
    try:
        session_key = approval.get_current_session_key()
        step = "tools.approval.is_approved"
        if not once and approval.is_approved(session_key, pattern):
            return None  # he already said yes for this conversation (never a tainted ask)
        step = "tools.approval._presence"
        callback, is_cli, is_gateway, is_ask = approval._presence(None)
        if not (is_cli or is_gateway or is_ask):
            return {
                "action": "block",
                "message": f"Blocked: the owner's rule says to ask him first ({message}), "
                "and nobody is here to answer.",
            }
        step = "tools.approval._ACTION_GATE"
        gate = approval._ACTION_GATE
        step = "tools.approval._human_decision"
        result = approval._human_decision(
            gate,
            **_accepted(
                approval._human_decision,
                command=f"<{tool}> (plugin approval rule)",
                description=message,
                pattern_key=pattern,
                pattern_keys=[pattern],
                session_key=session_key,
                approval_callback=callback,
                is_cli=is_cli,
                is_gateway=is_gateway,
                is_ask=is_ask,
            ),
        )
    except Exception as error:  # fail closed: his rule is never skipped
        logging.getLogger("agos_guard").warning("owner's approval not asked", exc_info=True)
        runtime._report(step, error)
        return {
            "action": "block",
            "message": f"Blocked: the owner's rule says to ask him first ({message}), and "
            "his approval could not be asked.",
        }
    if isinstance(result, dict) and result.get("approved"):
        return None
    reason = result.get("message") if isinstance(result, dict) else None
    return {"action": "block", "message": str(reason or f"The owner did not allow {tool}.")}


# His yes for one tool call, asked by the tool_execution middleware (no timeout)
# and read by the pre_tool_call hook Hermes then runs inside that call. Hermes
# copies the caller's context into the hook's worker (H: hermes_cli/
# plugins_dispatch.py:306 contextvars.copy_context), so the hook sees it.
_ANSWERED: contextvars.ContextVar[str] = contextvars.ContextVar("agos_owner_answered", default="")


# One question at a time per conversation, as Hermes's own gate serializes its
# prompts (H: agent/tool_executor.py:488 _ConcurrentToolAuthorizationGate).
_ASKING: dict[str, threading.Lock] = {}


_ASKING_GUARD = threading.Lock()


def _asking(session: str) -> threading.Lock:
    with _ASKING_GUARD:
        return _ASKING.setdefault(session, threading.Lock())


def _call_of(tool_name: str, kwargs: dict[str, Any]) -> str:
    """The one tool call an answer is for ("" when Hermes gave no call id)."""
    call = str(kwargs.get("tool_call_id") or "")
    return f"{call}\x00{tool_name}" if call else ""


def _asks_him_itself() -> bool:
    """Full access is on (Hermes's YOLO or approvals.mode off) outside a scheduled
    run: Hermes's gate would let it through, so the guard asks him itself."""
    approval = _approval_module()
    if approval is None or _in_cron():
        return False
    try:
        return bool(approval.is_approval_bypass_active())
    except Exception as error:  # noqa: BLE001 — the hook decides as before
        runtime._report("tools.approval.is_approval_bypass_active", error)
        return False
