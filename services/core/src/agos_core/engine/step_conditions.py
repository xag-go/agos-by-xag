"""A team automation step's "Only if" lines: their shape, checked on save.

A step with lines starts its agent only when every line holds; else its card is
closed at once with `agos-skipped: <reason>` before any model call (the agos-guard
plugin decides at the moment the step would start: hermes_plugin/agos_guard/
step_gate.py; the run script hands it the lines and the run's values:
engine/automation_run.py). No line = the step always runs.

Two kinds of line:
- a match line on the run's values, the same tests as the webhook's "Only if"
  lines: {"field": "payload.<path>" | "<variable>", "op": "is" | "is_not" |
  "contains" | "not_contains", "values": [...]};
- a check line: {"check": "/workspace/<script> [args]"}, a workspace script run in
  the step agent's own sandbox; its last line says YES/AH (run) or NO/LA (skip).

Owns: the lines' shape and the save-time refusals (plain words).
Must not: evaluate a line (the plugin does, inside Hermes).
"""

from __future__ import annotations

import posixpath
import re
import shlex
from typing import Any

__all__ = ["MAX_LINES", "OPS", "ConditionError", "describe", "parse_only_if"]

MAX_LINES = 20
OPS = ("is", "is_not", "contains", "not_contains")
_MATCH_KEYS = frozenset({"field", "op", "values"})
_FIELD = re.compile(r"^(payload(\.[A-Za-z0-9_-]{1,60}){1,12}|[a-z][a-z0-9_]{0,39})$")
# A check is a script and its words, never a shell line.
_SHELL = re.compile(r"[;&|$`<>(){}\\\n\r*?!~'\"]")
WORKSPACE = "/workspace"


class ConditionError(ValueError):
    pass


def _field(raw: object) -> str:
    text = str(raw or "").strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()  # {payload.sheet}, as written in a step's text
    return text


def _match(line: dict[str, Any], where: str) -> dict[str, Any]:
    unknown = sorted(set(line) - _MATCH_KEYS)
    if unknown:
        raise ConditionError(
            f"{where}: unknown field “{unknown[0]}” (a line has field, op, values)"
        )
    field = _field(line.get("field"))
    if not _FIELD.match(field):
        raise ConditionError(
            f"{where}: “{field or 'nothing'}” isn't a field (payload.<path>, or a variable name)"
        )
    op = str(line.get("op") or "is").strip().lower()
    if op not in OPS:
        raise ConditionError(f"{where}: unknown test “{op}” (is, is_not, contains, not_contains)")
    raw = line.get("values")
    values = raw if isinstance(raw, list) else [raw] if raw not in (None, "") else []
    kept = list(dict.fromkeys(str(v).strip()[:200] for v in values if str(v).strip()))
    if not kept or len(kept) > 100:
        raise ConditionError(f"{where}: give 1 to 100 values to test {field} against")
    return {"field": field, "op": op, "values": kept}


def _check(line: dict[str, Any], where: str) -> dict[str, str]:
    if set(line) != {"check"}:
        other = sorted(set(line) - {"check"})[0]
        raise ConditionError(f"{where}: a check line has only “check” (not “{other}”)")
    text = str(line.get("check") or "").strip()
    if not text or len(text) > 300 or _SHELL.search(text):
        raise ConditionError(
            f"{where}: a check is a script in /workspace and its words, no shell characters"
        )
    words = shlex.split(text)
    path = posixpath.normpath(words[0]) if words else ""
    if not path.startswith(WORKSPACE + "/") or ".." in words[0].split("/"):
        raise ConditionError(f"{where}: the check script must be inside /workspace ({words[0]})")
    return {"check": shlex.join([path, *words[1:]])}


def parse_only_if(raw: object, step: str, kind: str) -> tuple[dict[str, Any], ...]:
    """A step's "Only if" lines, checked: a list of match / check lines. None or
    [] = no line (the step always runs)."""
    if raw in (None, "", []):
        return ()
    if not isinstance(raw, list):
        raise ConditionError(f"step {step}: only_if must be a list of lines")
    if kind == "approval":
        raise ConditionError(f"step {step}: an approval waits for you, it can't have Only if lines")
    if len(raw) > MAX_LINES:
        raise ConditionError(f"step {step}: at most {MAX_LINES} Only if lines")
    lines: list[dict[str, Any]] = []
    for i, line in enumerate(raw, start=1):
        where = f"step {step}, Only if line {i}"
        if not isinstance(line, dict):
            raise ConditionError(f"{where} is not an object")
        # A typed form (the owner's page) sends its empty fields too.
        line = {k: v for k, v in line.items() if v not in (None, "", [])}
        lines.append(_check(line, where) if "check" in line else _match(line, where))
    return tuple(lines)


_OP_WORDS = {
    "is": "is",
    "is_not": "is not",
    "contains": "contains",
    "not_contains": "doesn't contain",
}


def describe(raw: object) -> str:
    """A step's "Only if" lines in plain words for the preview ("sheet is Ideas or
    Hooks and the check tools/gate.py says yes"); "" when there is no line or the
    lines are not readable (the save check reports those)."""
    if not isinstance(raw, list):
        return ""
    parts: list[str] = []
    for line in raw:
        if not isinstance(line, dict):
            return ""
        # A typed form (the owner's page) sends its empty fields too.
        line = {k: v for k, v in line.items() if v not in (None, "", [])}
        if "check" in line:
            try:
                words = shlex.split(str(line.get("check") or ""))
            except ValueError:
                return ""
            script = words[0].removeprefix(WORKSPACE + "/") if words else "a script"
            parts.append(f"the check {script} says yes")
            continue
        field = _field(line.get("field")).removeprefix("payload.")
        values = line.get("values")
        shown = values if isinstance(values, list) else [values] if values else []
        wanted = " or ".join(str(v).strip() for v in shown if str(v).strip())
        if not field or not wanted:
            return ""
        op = _OP_WORDS.get(str(line.get("op") or "is").strip().lower(), "is")
        parts.append(f"{field} {op} {wanted}")
    return " and ".join(parts)
