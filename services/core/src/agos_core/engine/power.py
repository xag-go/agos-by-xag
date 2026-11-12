"""Read vs act: which Co-Founder actions change its powers (pure rules).

A turn or a run that read untrusted content (a web page, an email, a webhook's body,
a Telegram message from someone who isn't the owner...) may not change what the
agents can do on the model's word alone: in that turn every POWER action waits for
the owner's yes (Hermes's own Allow / Deny card in a chat; its card in the
Co-Founder chat for a card's worker or an automation's run). WORK actions (the board,
notes, folders) and READ actions stay as they are. An owner's chat that read nothing
from outside is unchanged.

Every agos_action kind has its row here; tests/test_read_vs_act.py fails on a kind
with none, so a new action can't skip the decision.
"""

from __future__ import annotations

from agos_core.engine.cofounder_kind import Effect as Effect
from agos_core.ops import catalog
from agos_core.ops.specs import SPECS

# Every kind's row is its declaration's `effect` (ops/specs): no hand-written row.
EFFECT: dict[str, Effect] = dict(catalog.effects(SPECS))
# Several changes in one card (actions/cofounder_actions BUNDLE): always the owner's.
EFFECT["bundle"] = "power"

# The agos_capability tool turns an app or a toolset on or off: always a power.
CAPABILITY = "agos_capability"


def is_power(kind: str) -> bool:
    """Unknown kinds count as powers (fail closed)."""
    return EFFECT.get(kind, "power") == "power"


def held_message(source: str, titles: str) -> str:
    """What the owner reads on Hermes's Allow / Deny card (and on the run's card)."""
    return f"⚠️ This came after reading {source}. {titles}"[:900]


# What the agents create that the owner hears about (the rogue-agent alert).
CREATES = frozenset(
    {
        "create_automation",
        "create_mcp",
        "create_skill",
        "duplicate_skill",
        "install_skill",
        "add_pool_key",
        "save_pipeline_rule",
        "set_heartbeat",
        "watch_tree",
    }
)
