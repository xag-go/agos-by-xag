"""Rogue-agent alert: the owner hears when an agent grows its own powers.

Two signs, from the Co-Founder's agos_action / agos_capability (the only tools that
change what the agents can do, actions/hermes_channel.py run_actions):

- an agent working alone (a card's worker, an automation's run) created an
  automation, an MCP server, a skill, a key or a rule that starts work by itself
  (engine/power.py CREATES): in a chat the owner already sees the card it made;
- a burst: more than BURST power actions in WINDOW_S in one workspace, from anywhere.

Told like AGOS's other cards (event `agos.agent_power`, Settings → Notifications:
instant, in the daily digest, or silent), and always written to the activity log.
A failure here never changes what the action did.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from agos_core.context import Core

log = logging.getLogger("agos.agent_power")

EVENT = "agos.agent_power"
BURST = 10
WINDOW_S = 300
_recent: dict[str, deque[float]] = {}
_told_burst: dict[str, float] = {}
_lock = threading.Lock()

_NAMES = {
    "create_automation": "an automation",
    "create_mcp": "an MCP server",
    "create_skill": "a skill",
    "duplicate_skill": "a skill",
    "install_skill": "a skill",
    "add_pool_key": "a key",
    "save_pipeline_rule": "a card-move rule",
    "set_heartbeat": "a heartbeat",
    "watch_tree": "a watched folder",
}


def _burst(workspace_id: str, count: int) -> int:
    """How many power actions in the window when this call crosses BURST (told once
    per window), else 0."""
    at = time.monotonic()
    with _lock:
        seen = _recent.setdefault(workspace_id, deque())
        seen.extend([at] * count)
        while seen and at - seen[0] > WINDOW_S:
            seen.popleft()
        if len(seen) <= BURST or at - _told_burst.get(workspace_id, -WINDOW_S) < WINDOW_S:
            return 0
        _told_burst[workspace_id] = at
        return len(seen)


def noted(core: Core, workspace_id: str, address: str, kinds: list[str]) -> None:
    """These actions were just done (not the ones waiting for the owner)."""
    from agos_core.actions.hermes_channel import _run_title, is_run
    from agos_core.engine import power

    try:
        powers = [k for k in kinds if power.is_power(k)]
        if not powers:
            return
        many = _burst(workspace_id, len(powers))
        where = _run_title(core, workspace_id, address) if is_run(address) else ""
        made = sorted({_NAMES[k] for k in kinds if k in _NAMES}) if where else []
        if made:
            tell(core, workspace_id, f"An agent made {', '.join(made)} by itself. {where}.")
        if many:
            tell(
                core,
                workspace_id,
                f"An agent made {many} changes to what the team can do in the last "
                f"{WINDOW_S // 60} minutes. Check them in the Co-Founder chat.",
            )
    except Exception:  # an alert never changes what was done
        log.warning("agent power alert of %s not told", workspace_id, exc_info=True)


def tell(core: Core, workspace_id: str, text: str) -> None:
    """In the activity log, then to the owner as his Notifications setting says."""
    from agos_core.actions.notification_rules import delivery_for
    from agos_core.actions.services.channel import owner_needs
    from agos_core.db.activity import add_activity

    add_activity(core.db, workspace_id, kind="agent.power", text=text[:500])
    delivery = delivery_for(core, EVENT)
    if delivery == "silent":
        return
    message_id = owner_needs.tell_owner(core, workspace_id, text)
    if delivery == "batched":
        from agos_core.actions import digest

        digest.hold(core, workspace_id, EVENT, text)
        return
    owner_needs.push(
        core,
        workspace_id,
        text,
        f"msg:{message_id}" if message_id else f"power:{int(time.time())}",
        chat_id=owner_needs.cofounder_chat(core, workspace_id),
    )
