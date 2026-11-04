"""Merging what the Co-Founder proposes into what is there (lines, steps, reads).
Must not: read or write storage; pure functions only.

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "merged_lines",
    "merged_reads",
    "merged_steps",
]

# ---- a change never wipes what it doesn't name ---------------------------------------
# The Co-Founder's lists are ADDED to what is there (the same key = that one item
# changes); an item goes only when its removal is named (remove_*). So a change sent
# from a partial picture (a screenshot, an old copy) can never lose the rest.


def _line_key(line: dict[str, Any]) -> tuple[str, str, str]:
    field = str(line.get("field") or "").strip().removeprefix("payload.")
    return (str(line.get("when") or ""), field, str(line.get("op") or "is"))


def merged_lines(
    current: list[dict[str, Any]], sent: list[dict[str, Any]], removed: list[Any]
) -> list[dict[str, Any]]:
    """A webhook's "Only if" lines after a change. A line is known by its event,
    field and test: "values" sets that line's values, "add_values" / "remove_values"
    change only those; a new line is added. remove_webhook_conditions names whole
    lines to drop (same event, field and test)."""
    out = [dict(c) for c in current]
    for raw in sent:
        line = dict(raw)
        key = _line_key(line)
        found = next((c for c in out if _line_key(c) == key), None)
        adds = [str(v) for v in line.pop("add_values", None) or []]
        drops = {str(v) for v in line.pop("remove_values", None) or []}
        if found is None:
            values = [*(line.get("values") or []), *adds]
            out.append({**line, "values": [v for v in dict.fromkeys(values) if v not in drops]})
            continue
        values = list(line["values"]) if line.get("values") else list(found.get("values") or [])
        values += [v for v in adds if v not in values]
        found["values"] = [v for v in values if v not in drops]
    gone = {_line_key(r) for r in removed if isinstance(r, dict)}
    return [c for c in out if _line_key(c) not in gone]


def merged_steps(
    current: list[dict[str, Any]], sent: list[dict[str, Any]], removed: list[str]
) -> list[dict[str, Any]]:
    """A team automation's steps after a change: a sent step with an existing key
    replaces that step (where it is), a new key is added at the end; only the keys
    in remove_steps go."""
    out = [dict(s) for s in current]
    for step in sent:
        key = str(step.get("key") or "")
        at = next((i for i, s in enumerate(out) if key and s.get("key") == key), None)
        if at is None:
            out.append(dict(step))
        else:
            out[at] = {**out[at], **{k: v for k, v in step.items() if v not in (None, "")}}
    gone = set(removed)
    return [s for s in out if s.get("key") not in gone]


def merged_reads(
    current: list[dict[str, Any]], sent: list[dict[str, Any]], removed: list[str]
) -> list[dict[str, Any]]:
    """An agent's rule files after a change: added (the same path = that one
    changes); only the paths in remove_reads go."""
    out = [dict(r) for r in current]
    for read in sent:
        at = next((i for i, r in enumerate(out) if r.get("path") == read.get("path")), None)
        if at is None:
            out.append(dict(read))
        else:
            out[at] = dict(read)
    gone = set(removed)
    return [r for r in out if r.get("path") not in gone]


def _changed(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Only the fields a change touched, as they were: Hermes's cron keeps no
    history of a job (H: cron/jobs.py update_job), so this is all its Undo needs."""
    return {k: before[k] for k in before if after.get(k) != before[k]}
