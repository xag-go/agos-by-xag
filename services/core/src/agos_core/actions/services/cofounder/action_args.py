"""Reading a Co-Founder action's fields (flags, numbers, text, member names).
Must not: run any action or touch storage.

Split out of agos_core.actions.cofounder_more (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

from agos_core.actions.errors import ActionError

__all__ = [
    "Fields",
    "Result",
]

Fields = dict[str, Any]
Result = dict[str, Any]


def flag_arg(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("false", "no", "off", "0")


def int_arg(value: Any, what: str) -> int:
    try:
        return int(str(value).strip().lstrip("#v"))
    except (TypeError, ValueError) as error:
        raise ActionError(f"Give {what} as a number.") from error


def text_arg(p: Fields, key: str, default: str = "") -> str:
    value = p.get(key)
    return default if value is None else str(value).strip()


def member_arg(value: Any) -> str:
    return str(value or "").strip().lstrip("@")
