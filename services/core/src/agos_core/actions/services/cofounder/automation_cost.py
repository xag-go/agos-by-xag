"""The Co-Founder's read of what an automation cost: this month and last month
(UTC), or one run step by step, in the words the owner reads.

Owns: that answer's text. Must not: count or price anything (the Automation
service's run_detail / run_usage read Hermes's own counts).
"""

from __future__ import annotations

from agos_core.actions.errors import ActionError
from agos_core.actions.services.automation import run_detail, run_history
from agos_core.actions.services.cofounder.action_args import Fields, Result, text_arg
from agos_core.actions.services.cofounder.automation_kinds import automation_id_of
from agos_core.context import Core
from agos_core.db.records import AutomationCost, RunDetail, Usage

__all__ = ["cost_text", "do_automation_cost", "money", "tokens"]


def tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(n)


def money(usage: Usage) -> str:
    """Its cost as Hermes priced it; "unknown" when it gave no price."""
    if usage.cost_usd is None:
        return "cost unknown (no price for this model)"
    text = f"${usage.cost_usd:.2f}"
    return text if usage.priced else f"{text} (part of it has no price)"


def _usage(usage: Usage) -> str:
    return (
        f"{money(usage)}, {tokens(usage.tokens)} tokens ({tokens(usage.input_tokens)} in, "
        f"{tokens(usage.output_tokens)} out, "
        f"{tokens(usage.cache_read_tokens + usage.cache_write_tokens)} cache)"
    )


def cost_text(cost: AutomationCost) -> str:
    def month(m: str, runs: int, usage: Usage) -> str:
        return f"{m}: {runs} run{'s' if runs != 1 else ''}, {_usage(usage)}"

    return (
        f"“{cost.name}” (#{cost.automation_id}) — "
        f"this month {month(cost.this_month.month, cost.this_month.runs, cost.this_month.usage)}; "
        f"last month {month(cost.last_month.month, cost.last_month.runs, cost.last_month.usage)}"
    )


def _run_text(detail: RunDetail) -> str:
    lines = [f"Run {detail.run_id} of “{detail.automation_name}”: {_usage(detail.totals)}"]
    for s in detail.steps:
        took = f", {s.duration_s}s" if s.duration_s is not None else ""
        why = f" ({s.reason})" if s.reason else ""
        lines.append(f"- {s.title} · {s.agent} · {s.status}{why}{took} · {_usage(s.usage)}")
    return "\n".join(lines)


def do_automation_cost(core: Core, ws: str, p: Fields) -> Result:
    wanted = text_arg(p, "automation", "")
    costs = run_detail.month_costs(core, ws)
    if wanted:
        automation_id = automation_id_of(core, ws, wanted)
        costs = [c for c in costs if c.automation_id == automation_id]
        run = text_arg(p, "run", "")
        if run:
            return {"report": _run_text(run_history.detail_of(core, ws, automation_id, run))}
    if not costs:
        raise ActionError("There is no such automation in this workspace.", 404)
    return {"report": "\n".join(cost_text(c) for c in costs)[:8000]}
