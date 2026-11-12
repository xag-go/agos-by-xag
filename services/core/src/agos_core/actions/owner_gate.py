"""AGOS's tools in Hermes (agos-guard plugin): what needs the owner's yes.

Moved out of actions/hermes_channel.py (which re-exports these names). Two checks:

- `tool_check`: asked by the plugin before agos_action / agos_capability run. When it
  says ask, Hermes shows its own Allow / Deny card where the agent works, and the
  tool runs only after his Allow.
- `gate_refusal`: the core's own re-check at the bridge's /actions and /capability
  (the plugin is not the only gate): a gated call from an owner's chat that was never
  asked about is refused.

Read vs act (engine/power.py, actions/read_vs_act.py): in a session that read
untrusted content, every power action is gated too, whatever the mode, with the
reason named ("this came after reading …"). A card's worker or an automation's run
has nobody at an Allow / Deny card: its gated actions wait on their card
(hermes_channel.run_actions).

Such a tainted ask is a ONE-TIME question: tool_check gives it a nonce (`once`) that
the plugin uses as Hermes's rule key, so Hermes's session / always allowlist can
never answer it (each ask's key is new), and the core runs the batch only with that
very nonce back (one use). His own clean "Ask me" keeps the fixed key (his "always"
still works there).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from typing import Any

from agos_core.context import Core
from agos_core.domain.secrets import same_secret

log = logging.getLogger("agos.hermes_channel")

# The core's own check of the owner gate (the plugin is not the only one). Hermes shows
# its Allow / Deny card only when tool_check answered ask=True, and the tool runs only
# after his Allow. So a gated batch that reaches the bridge's /actions (or /capability)
# from an owner's chat must have been asked about, for that chat, just before: a check
# that failed, timed out or was skipped never lets it through. In memory: a core
# restart in between only makes the agent call the tool again.
_ASKED_FOR_S = 24 * 3600
_ASKED_MAX = 2000
# (workspace, address, batch key) -> (when, the tainted ask's nonce or "").
_asked_at: dict[tuple[str, str, str], tuple[float, str]] = {}
_asked_lock = threading.Lock()

GATE_NOT_ASKED = (
    "This needs the owner's yes first, and AGOS has no record that he was asked "
    "(its check before the tool didn't get through): nothing was done. Call the tool "
    "again so he gets the Allow / Deny card."
)


HELD_AFTER = "held_after"  # the card's payload: what was read before it (its card says)


def _is_run(address: str) -> bool:
    from agos_core.actions.hermes_channel import is_run

    return is_run(address)


def tainted(core: Core, workspace_id: str | None, address: str, session: str = "") -> str:
    """What untrusted content this session or run read ("" = none)."""
    from agos_core.actions import read_vs_act

    return read_vs_act.source_of(core, workspace_id, address, session) if workspace_id else ""


def fields_of(fields: dict[str, Any]) -> dict[str, Any]:
    """An action's own fields, without what its card says it was held after."""
    return {k: v for k, v in (fields or {}).items() if k != HELD_AFTER}


def held_kinds(core: Core, actions: list[Any], *, source: str) -> list[bool]:
    """For each action: does it need the owner's yes first (his mode, its own rule,
    or a power after an untrusted read)."""
    from agos_core.actions import cofounder_actions
    from agos_core.engine import cofounder_actions as action_rules
    from agos_core.engine import power

    ask_mode = cofounder_actions.mode(core) == "ask"
    return [
        a.do != "hire_agent"
        and (ask_mode or action_rules.needs_owner(a) or bool(source and power.is_power(a.do)))
        for a in actions
    ]


def marked(actions: list[Any], waits: list[bool], source: str) -> list[Any]:
    """A run's power actions held after an untrusted read say why on their card."""
    from agos_core.engine import cofounder_actions as action_rules
    from agos_core.engine import power

    return [
        action_rules.Action(a.do, {**a.fields, HELD_AFTER: source})
        if wait and source and power.is_power(a.do)
        else a
        for a, wait in zip(actions, waits, strict=True)
    ]


def tool_check(
    core: Core,
    tool: str,
    args: dict[str, Any],
    workspace_id: str | None = None,
    address: str = "",
    session: str = "",
) -> dict[str, Any]:
    """Asked by the plugin before one of AGOS's tools runs: does Hermes ask the owner
    first (its own Allow / Deny card, where the agent works), and with what words. A
    tainted ask carries its one-time nonce (`once`)."""
    from agos_core.actions import cofounder_actions
    from agos_core.engine import cofounder_actions as action_rules
    from agos_core.engine import power

    if _is_run(address):
        # A card's worker or an automation's run: nobody is there to answer Hermes's
        # Allow / Deny, so what needs his yes waits as a card in the Co-Founder chat
        # (run_actions / ask_capability) instead.
        return {"ask": False, "message": ""}
    source = tainted(core, workspace_id, address, session)
    once = secrets.token_urlsafe(16) if source else ""
    if tool == "agos_action":
        items = [action_rules._clean(a) for a in args.get("actions") or [] if isinstance(a, dict)]
        actions = [a for a in items if a is not None]
        if not actions:
            return {"ask": False, "message": ""}
        # A hire (in every mode) makes a PROPOSAL card (the owner decides in his
        # Inbox): no Allow / Deny card for it here, or he would answer twice.
        decided_later = [a for a in actions if a.do == "hire_agent"]
        others = [a for a in actions if a.do != "hire_agent"]
        ask = any(held_kinds(core, others, source=source))
        titles = "; ".join(action_rules.title_of(a) for a in (others or decided_later)[:10])
        if ask and workspace_id:
            _asked(workspace_id, address, _batch_key(args.get("actions")), once)
        message = f"🛠 {titles}"
        if ask and source and any(power.is_power(a.do) for a in others):
            message = power.held_message(source, message)
        return _answer(ask, message, once)
    if tool == "agos_capability":
        verb = "Turn on" if args.get("on", True) is not False else "Turn off"
        name = str(args.get("name") or "")
        ask = cofounder_actions.mode(core) == "ask" or bool(source)
        if ask and workspace_id:
            _asked(workspace_id, address, _capability_key(args), once)
        message = f"🔌 {verb} {args.get('kind') or 'app'} {name}"
        return _answer(ask, power.held_message(source, message) if source else message, once)
    if tool == SKILL_REQUEST and args.get("action") == "request" and source:
        # A hub skill installed on a tainted session's word: a power (engine/power.py).
        if workspace_id:
            _asked(workspace_id, address, _skill_key(args), once)
        said = f"🧩 Install the skill {str(args.get('source') or '')[:200]} from the skills hub"
        return _answer(True, power.held_message(source, said), once)
    return {"ask": False, "message": ""}


SKILL_REQUEST = "agos_skill_request"
SKILL_HELD = (
    "A new skill isn't installed from a run that read untrusted content (nobody is here "
    "to say yes): nothing was installed. Say in your result which skill you need and why."
)


def _answer(ask: bool, message: str, once: str) -> dict[str, Any]:
    out: dict[str, Any] = {"ask": ask, "message": message[:900]}
    if ask and once:
        out["once"] = once
    return out


def _batch_key(raw: Any) -> str:
    items = [a for a in raw or [] if isinstance(a, dict)] if isinstance(raw, list) else []
    text = json.dumps(items, sort_keys=True, default=str)
    return "a:" + hashlib.sha256(text.encode()).hexdigest()


def _skill_key(args: dict[str, Any]) -> str:
    return "s:" + hashlib.sha256(str(args.get("source") or "").encode()).hexdigest()


def _capability_key(args: dict[str, Any]) -> str:
    on = args.get("on", True) is not False
    said = [str(args.get("kind") or "app"), str(args.get("name") or ""), on]
    return "c:" + hashlib.sha256(json.dumps(said).encode()).hexdigest()


def _asked(workspace_id: str, address: str, key: str, once: str = "") -> None:
    if _is_run(address):
        return
    at = time.monotonic()
    with _asked_lock:
        for old in [k for k, (t, _o) in _asked_at.items() if at - t > _ASKED_FOR_S]:
            del _asked_at[old]
        while len(_asked_at) >= _ASKED_MAX:
            del _asked_at[next(iter(_asked_at))]
        _asked_at[(workspace_id, address, key)] = (at, once)


def _was_asked(workspace_id: str, address: str, key: str, once: str, tainted: bool) -> bool:
    """Asked just before, once (popped); a tainted batch only with that ask's nonce."""
    with _asked_lock:
        found = _asked_at.pop((workspace_id, address, key), None)
    if found is None or time.monotonic() - found[0] > _ASKED_FOR_S:
        return False
    if tainted or found[1]:
        return same_secret(once, found[1])
    return True


def gate_refusal(
    core: Core,
    workspace_id: str,
    address: str,
    tool: str,
    args: dict[str, Any],
    session: str = "",
    once: str = "",
) -> str | None:
    """The bridge's /actions and /capability, before they act: None when the call may
    go on, else why nothing is done (the owner must say yes and was never asked)."""
    from agos_core.actions import cofounder_actions
    from agos_core.engine import cofounder_actions as action_rules
    from agos_core.engine import power

    if _is_run(address):
        # A run's gated actions wait on their card (run_actions); a skill install has
        # no card: after an untrusted read it is refused (nobody to answer).
        asks_skill = tool == SKILL_REQUEST and args.get("action") == "request"
        held = asks_skill and tainted(core, workspace_id, address, session)
        return power.held_message(held, SKILL_HELD) if held else None
    source = tainted(core, workspace_id, address, session)
    if tool == "agos_action":
        items = [action_rules._clean(a) for a in args.get("actions") or [] if isinstance(a, dict)]
        others = [a for a in items if a is not None and a.do != "hire_agent"]
        gated = any(held_kinds(core, others, source=source))
        asked_as = _batch_key(args.get("actions"))
    elif tool == SKILL_REQUEST:
        gated = bool(source) and args.get("action") == "request"
        asked_as = _skill_key(args)
    else:
        gated = cofounder_actions.mode(core) == "ask" or bool(source)
        asked_as = _capability_key(args)
    if not gated or _was_asked(workspace_id, address, asked_as, once, bool(source)):
        return None
    log.warning("refused %s from %s: the owner was never asked", tool, address)
    return GATE_NOT_ASKED
