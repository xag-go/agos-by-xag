"""Which Hermes approval request the owner's own Autonomy rule asked for.

Owns: telling a guard "Ask me" approval (the agos-guard plugin marks it) from a
risky-command approval Hermes asks for. Full access never answers the first kind:
the owner set that rule on purpose, so it always waits for his Approve.

Must not: answer or store an approval (actions/access.py does).
"""

from __future__ import annotations

from typing import Any

from agos_core.shared.guard_contract import ASK_MARK

__all__ = ["ASK_RULE_MARK", "owner_rule"]

ASK_RULE_MARK = ASK_MARK


def owner_rule(asked: Any) -> bool:
    """This approval comes from an Autonomy rule (\"Ask me\"), not a risky command."""
    if not isinstance(asked, dict):
        return False
    text = f"{asked.get('description') or ''} {asked.get('pattern_key') or ''}"
    return (
        ASK_RULE_MARK in text
        or "plugin_rule:agos:" in text
        # marks from before the app was named AGOS
        or "[XAG rule: Ask me]" in text
        or "plugin_rule:xag:" in text
    )
