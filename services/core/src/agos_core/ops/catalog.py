"""The tables every caller needs, derived from the declarations (ops/specs), so a
new operation is written once and the Co-Founder, the web parity check and the
agent tools follow:

- `kinds`: the Co-Founder's agos_action kinds (engine/cofounder_parity merges them);
- `effects`: their read-vs-act rows (engine/power.py merges them);
- `web_do` / `owner_only`: the web parity rows (engine/cofounder_parity/web_actions.py,
  engine/cofounder_owner_only.py merge them);
- `agent_tools`: the tool schemas for the agents.

Owns: those derivations. Must not: run an operation or hold a hand-written kind.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agos_core.engine.cofounder_kind import Effect, Kind
from agos_core.ops.spec import WORKSPACE_FIELD, OperationSpec

__all__ = ["agent_tools", "effects", "kinds", "owner_only", "web_do"]

Specs = Iterable[OperationSpec[Any]]


def kinds(specs: Specs) -> dict[str, Kind]:
    out: dict[str, Kind] = {}
    for spec in specs:
        if spec.cofounder_domain is None:
            continue
        fields = spec.caller_fields()
        out[spec.name] = Kind(
            domain=spec.cofounder_domain,
            required=tuple(k for k, f in fields.items() if f.is_required()),
            title=spec.audit_title,
            fields=spec.cofounder_fields,
            gate=spec.gate,
            structured=spec.cofounder_structured,
        )
    return out


def effects(specs: Specs) -> dict[str, Effect]:
    return {s.name: s.effect for s in specs if s.cofounder_domain is not None}


def web_do(specs: Specs) -> dict[str, str]:
    return {
        s.web_action: f"do:{s.name}"
        for s in specs
        if s.web_action is not None and s.cofounder_domain is not None
    }


def owner_only(specs: Specs) -> dict[str, str]:
    return {
        s.web_action: s.owner_only
        for s in specs
        if s.web_action is not None and s.owner_only is not None
    }


def agent_tools(specs: Specs) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for spec in specs:
        if spec.agent_tool is None:
            continue
        schema = spec.input_model.model_json_schema()
        schema["properties"] = {
            k: v for k, v in schema.get("properties", {}).items() if k != WORKSPACE_FIELD
        }
        schema["required"] = [k for k in schema.get("required", []) if k != WORKSPACE_FIELD]
        tools.append({"name": spec.name, "description": spec.agent_tool, "parameters": schema})
    return tools
