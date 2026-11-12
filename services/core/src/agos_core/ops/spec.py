"""The declaration of one operation (pure data: no service code, no database).

Owns: what an operation is called, what it takes, how it is gated and who may run
it. Must not: run anything (operation.py binds the service's code; registry.py
runs it) or import a service.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from agos_core.engine.cofounder_kind import Effect, Gate

__all__ = ["WORKSPACE_FIELD", "CofounderFields", "In", "OperationSpec"]

In = TypeVar("In", bound=BaseModel)

# An input field of this name is the workspace the run is for: the Co-Founder and
# the agents get theirs from where they run, never from their own words.
WORKSPACE_FIELD = "workspace_id"


class CofounderFields(BaseModel):
    """The input of a kind the Co-Founder already ran with loose fields (its page
    action reads them: text_arg, flag_arg...): the declared fields say which it takes
    and which are required; every field it sent reaches the page action as sent."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())


class _Blank(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass(frozen=True)
class OperationSpec(Generic[In]):
    """name: snake_case, the Co-Founder's kind when it is exposed.
    gate: "undo" = done at once with Undo; "owner" = waits for his yes; "once" =
    nothing to take back. owner_only: why only the owner runs it (exclusive with
    cofounder_domain, the Co-Founder domain it is a kind of). agent_tool: its
    description when agents get it as a tool. idempotent: create / run operations,
    which take an idempotency key. extra_web_actions: more web actions that are this same operation.
    cofounder_structured: the fields the Co-Founder
    gives as a list or an object. undo_after_yes: an "owner" gate whose run, once he
    said yes, still has Undo on its card."""

    name: str
    input_model: type[In]
    audit_title: str
    gate: Gate
    effect: Effect = "power"
    web_action: str | None = None
    extra_web_actions: tuple[str, ...] = ()
    owner_only: str | None = None
    cofounder_domain: str | None = None
    cofounder_fields: str = ""
    agent_tool: str | None = None
    idempotent: bool = False
    cofounder_structured: tuple[str, ...] = ()
    undo_after_yes: bool = False

    def __post_init__(self) -> None:
        if (self.owner_only is None) == (self.cofounder_domain is None):
            raise ValueError(
                f"{self.name}: say who runs it: owner_only (with why) or a cofounder_domain"
            )
        if self.owner_only is not None and self.agent_tool is not None:
            raise ValueError(f"{self.name}: an owner-only operation is no agent tool")
        if self.undo_after_yes and self.gate != "owner":
            raise ValueError(f"{self.name}: an Undo after his yes is for an owner gate")

    @property
    def has_undo(self) -> bool:
        """Its card has Undo: done at once with Undo, or after his yes with Undo."""
        return self.gate == "undo" or self.undo_after_yes

    def title(self, data: BaseModel) -> str:
        shown = _Blank(
            {
                k: ("on" if v is True else "off" if v is False else str(v))
                for k, v in data.model_dump().items()
                if not isinstance(v, (list, dict))
            }
        )
        text = string.Formatter().vformat(self.audit_title, (), shown)
        return " ".join(text.split())[:200]

    def caller_fields(self) -> dict[str, Any]:
        """The input's fields a caller gives (the workspace comes from where it runs)."""
        return {k: f for k, f in self.input_model.model_fields.items() if k != WORKSPACE_FIELD}
