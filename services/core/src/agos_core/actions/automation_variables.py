"""An automation's typed variables (Step 48, routines).

A variable is {name, type text|number|boolean|select|date, default, options}. The
owner writes `{name}` in a step's title or body, or in a one-agent automation's
instructions; each run fills it:
- a scheduled or webhook run uses the defaults;
- Run now may give values (the manual run dialog asks them);
- a webhook run also fills `{payload.<path>}` from the delivery (e.g.
  `{payload.data.title}`), and every run `{run.date}` / `{run.time}` (UTC);
- an unknown `{word}` stays as written.

The cards are filled by the script Hermes runs (engine/automation_run.py `fill`:
one code, imported here for the prompt). A one-agent job's prompt keeps the
`{name}` holes as the owner wrote them and ends with a "Variables" block of the
defaults, which engine/cron.py instructions_of strips when it reads the prompt back
(the prompt stays the one copy of the instructions, template included).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.db.records import AutomationVariable

PROMPT_VARS = "## Variables"

MAX_VARIABLES = 20
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0", "")


def check_variables(raw: list[Any]) -> list[dict[str, Any]]:
    """The owner's variables as saved: unique names, a select with options and a
    default among them, a default of the variable's type."""
    if len(raw) > MAX_VARIABLES:
        raise ActionError(f"Keep it to {MAX_VARIABLES} variables.")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in raw:
        v = (
            item
            if isinstance(item, AutomationVariable)
            else AutomationVariable.model_validate(item)
        )
        if v.name in seen:
            raise ActionError(f"Variable “{v.name}” is listed twice.")
        seen.add(v.name)
        options = [o.strip() for o in v.options if o.strip()]
        if v.type == "select" and not options:
            raise ActionError(f"Variable “{v.name}”: a select needs its options.")
        default = check_value(v.model_copy(update={"options": options}), v.default)
        out.append(
            {
                "name": v.name,
                "type": v.type,
                "default": default,
                "options": options if v.type == "select" else [],
                "label": v.label.strip(),
            }
        )
    return out


def check_value(variable: AutomationVariable, value: str) -> str:
    """A value of the variable's type, as text (what the cards show). Empty is
    allowed for every type but select (the owner may leave a default blank)."""
    text = (value or "").strip()
    kind = variable.type
    if kind == "number":
        if text and not _NUMBER.match(text):
            raise ActionError(f"Variable “{variable.name}”: “{text}” is not a number.")
        return text
    if kind == "boolean":
        if text.lower() in _TRUE:
            return "yes"
        if text.lower() in _FALSE:
            return "no"
        raise ActionError(f"Variable “{variable.name}”: “{text}” is not yes or no.")
    if kind == "date":
        if text:
            try:
                date.fromisoformat(text)
            except ValueError as error:
                raise ActionError(
                    f"Variable “{variable.name}”: “{text}” is not a date (YYYY-MM-DD)."
                ) from error
        return text
    if kind == "select":
        if text not in variable.options:
            if not text and variable.options:
                return variable.options[0]
            raise ActionError(
                f"Variable “{variable.name}”: pick one of {', '.join(variable.options)}."
            )
        return text
    return text


def check_values(
    variables: list[AutomationVariable], given: dict[str, Any] | None
) -> dict[str, str]:
    """Run now's values: the defaults, each replaced by what the owner gave (checked
    against the variable's type). An unknown name is refused."""
    by_name = {v.name: v for v in variables}
    values = {v.name: v.default for v in variables}
    for name, value in (given or {}).items():
        if name not in by_name:
            raise ActionError(f"“{name}” is not one of this automation's variables.")
        values[name] = check_value(by_name[name], str(value if value is not None else ""))
    return values


def defaults(variables: list[AutomationVariable]) -> dict[str, str]:
    return {v.name: v.default for v in variables}


def plan_entries(variables: list[AutomationVariable]) -> list[dict[str, Any]]:
    """What the script Hermes runs needs of the variables (names and defaults)."""
    return [{"name": v.name, "default": v.default} for v in variables]


def prompt_tail(variables: list[AutomationVariable]) -> str:
    """The block a one-agent job's prompt ends with: the defaults, so the agent
    fills the {name} holes itself (engine/cron.py instructions_of strips it)."""
    if not variables:
        return ""
    lines = "\n".join(f"- {v.name} = {v.default}" for v in variables)
    return f"\n\n{PROMPT_VARS}\nWhere the text above says {{name}}, use the value below.\n{lines}"
