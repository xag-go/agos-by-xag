"""AGOS's hidden skill `cofounder-actions`, written from the kinds catalogue.

Owns: the skill's text. Must not: change a kind or its gate.
"""

from __future__ import annotations

from agos_core.engine.cofounder_parity.catalog import DOMAINS, KINDS

__all__ = ["skill_text"]


def skill_text() -> str:
    """AGOS's hidden skill `cofounder-actions`: every kind's fields (skill_view on demand)."""
    lines = [
        "---",
        "name: cofounder-actions",
        'description: "Co-Founder only. Use when the owner asks for a change on one of his AGOS '
        'pages that your instructions do not list: every agos_action kind and its fields."',
        "---",
        "",
        "# More agos_action kinds (the rest of the owner's pages)",
        "",
        'Call them like the others: agos_action(actions=[{"do": "<kind>", ...fields}]).',
        "Each runs the same code as the owner's page. Undo = its card has Undo;",
        "his yes = it waits for his Allow on its card first; once = done, nothing to undo",
        "(the tool's answer says what came of it). Names (an agent, a skill, a rule, a",
        "label, a view) are their ID or their title; numbers come from the page or the",
        "tool's earlier answers. Read the thing first (its page, file or list) and send only",
        "what changes. Secrets (keys, tokens, passwords) never go through you: ask the",
        "owner with agos_ask_owner to type them on his page, and never write one in a chat.",
        "",
    ]
    for domain in DOMAINS:
        lines.append(f"## {domain}")
        lines.append("")
        for name, kind in KINDS.items():
            if kind.domain != domain:
                continue
            gate = {"undo": "Undo", "owner": "his yes", "once": "once"}[kind.gate]
            lines.append(f"- {name} ({gate}): {kind.fields}")
        lines.append("")
    return "\n".join(lines)
