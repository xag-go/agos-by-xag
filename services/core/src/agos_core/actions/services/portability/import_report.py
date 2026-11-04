"""An import's plan and report: the owner's strategies, the inputs it needs, what each step said.
Must not: import anything itself.

Split out of agos_core.actions.portability (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.portability.preview import DEFAULTS, KINDS
from agos_core.context import Core
from agos_core.engine import bundle as fmt

__all__ = [
    "Plan",
    "Report",
    "check_inputs",
]

# ---- import ----------------------------------------------------------------------------


@dataclass
class Report:
    workspace_id: str
    items: list[dict[str, str]] = field(default_factory=list)
    needs_owner: list[dict[str, str]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def add(self, kind: str, name: str, result: str, as_name: str = "", detail: str = "") -> None:
        self.items.append(
            {
                "kind": kind,
                "name": name,
                "result": result,
                "asName": as_name or name,
                "detail": detail,
            }
        )

    def view(self) -> dict[str, Any]:
        return {
            "workspaceId": self.workspace_id,
            "items": self.items,
            "needsOwner": self.needs_owner,
            "problems": self.problems,
            "notCarried": list(fmt.NOT_CARRIED),
        }


@dataclass
class Plan:
    """How one import goes: where, the strategy per kind, the inputs given."""

    strategies: dict[str, str]
    inputs: dict[str, str]
    later: set[str]
    under: str = ""  # the lead the bundle's top members report to ("" = the Co-Founder)
    who: str = "import"
    why: str = "imported from a bundle"


def check_inputs(found: fmt.Parsed, values: dict[str, str], later: set[str]) -> None:
    """A required input with no value that the owner didn't put off stops the
    import before anything is written."""
    missing = [
        i["name"]
        for i in found.inputs
        if i["required"]
        and i["kind"] == "tool_key"
        and not str(values.get(i["name"]) or "").strip()
        and i["name"] not in later
    ]
    if missing:
        raise ActionError("Fill these in or mark them for later: " + ", ".join(missing) + ".", 400)


def _strategies(given: dict[str, str] | None) -> dict[str, str]:
    out = dict(DEFAULTS)
    for kind, value in (given or {}).items():
        if kind not in KINDS or value not in fmt.STRATEGIES:
            raise ActionError(f"Strategy for {kind}: skip, rename or replace.")
        out[kind] = value
    return out


def _said(error: Exception) -> str:
    return str(getattr(error, "message", None) or error)[:300]


def _review(
    core: Core, ws: str, review: dict[str, Any], agents: dict[str, str], report: Report
) -> None:
    from agos_core.actions import reviews

    data = dict(review)
    for key in ("stages",):
        data[key] = [agents.get(str(s), str(s)) for s in data.get(key) or []]
    if data.get("planReviewer"):
        data["planReviewer"] = agents.get(str(data["planReviewer"]), str(data["planReviewer"]))
    try:
        reviews.save_defaults(core, ws, data)
        report.add("review", "Review settings", "created")
    except ActionError as error:
        report.problems.append(f"Review settings: {_said(error)}")
