"""An automation's revision history: one snapshot per save (Step 48).

Hermes's cron job is overwritten in place by `hermes cron edit` and keeps no
history (cron/jobs.json holds the current job, cron/executions its runs), so the
versions of an automation — name, instructions, schedule, who does it, steps,
variables, policy, webhook lines — are AGOS's rows (automation_revisions). A save
appends a snapshot when something changed; Restore is a new save from a snapshot,
recorded as a revision "restored from vN". The Revisions tab reads the list once
(snapshot and diff included).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agos_core.db.records import AutomationRevision, RevisionChange
from agos_core.db.rows import now

KEEP = 50  # revisions kept per automation (the oldest go)

# The snapshot's fields, in the order the diff lists them.
FIELDS = (
    "name",
    "instructions",
    "schedule",
    "on",
    "agent",
    "model",
    "steps",
    "check_first",
    "variables",
    "policy",
    "ticket",
    "hook",
)


def snapshot_of(automation: Any) -> dict[str, Any]:
    """The automation as saved, in one JSON-able dict (what Restore brings back)."""
    hook = automation.hook
    return {
        "name": automation.name,
        "instructions": automation.instructions,
        "schedule": automation.schedule,
        "on": automation.on,
        "agent": automation.agent,
        "model": automation.model.model_dump(),
        "steps": [s.model_dump() for s in automation.steps],
        "check_first": automation.check_first,
        "variables": [v.model_dump() for v in automation.variables],
        "policy": automation.policy,
        "ticket": automation.ticket.model_dump() if automation.ticket else None,
        "hook": (
            {
                "on": True,
                "events": list(hook.events),
                "conditions": [c.model_dump() for c in hook.conditions],
            }
            if hook is not None
            else None
        ),
    }


def _shown(value: Any) -> str:
    """A field's value as one line of text for the diff."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, str):
        return value if len(value) <= 300 else value[:297] + "…"
    if isinstance(value, list):
        if not value:
            return "none"
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(
                    str(item.get("title") or item.get("name") or item.get("field") or "")
                    + (f" = {item['default']}" if item.get("default") else "")
                )
            else:
                parts.append(str(item))
        return ", ".join(p for p in parts if p) or f"{len(value)} items"
    if isinstance(value, dict):
        if "provider" in value and "model" in value:
            return f"{value.get('model')} ({value.get('effort') or 'default effort'})"
        if "source" in value:
            return f"{value['source']} → @{value.get('member') or 'Co-Founder'}"
        if "events" in value:
            events = ", ".join(value.get("events") or []) or "every event"
            return f"on · {events} · {len(value.get('conditions') or [])} Only-if line(s)"
        return json.dumps(value, ensure_ascii=False)[:300]
    return str(value)


def diff(before: dict[str, Any] | None, after: dict[str, Any]) -> list[RevisionChange]:
    """What changed between two snapshots, field by field (an absent `before` is
    the first revision: every set field is new)."""
    changes = []
    for field in FIELDS:
        old = (before or {}).get(field)
        new = after.get(field)
        if before is None and (new is None or new == [] or new == "" or new is False):
            continue
        if old != new:
            changes.append(RevisionChange(field=field, before=_shown(old), after=_shown(new)))
    return changes


def summary_of(changes: list[RevisionChange], restored_from: int | None) -> str:
    if restored_from is not None:
        return f"restored from v{restored_from}"
    if not changes:
        return "saved"
    names = [c.field.replace("_", " ") for c in changes]
    return "changed " + ", ".join(names[:5]) + (f" (+{len(names) - 5})" if len(names) > 5 else "")


def latest(db: sqlite3.Connection, automation_id: int) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM automation_revisions WHERE automation_id = ? ORDER BY n DESC LIMIT 1",
        (automation_id,),
    ).fetchone()
    return found


def append(
    db: sqlite3.Connection,
    workspace_id: str,
    automation_id: int,
    snapshot: dict[str, Any],
    *,
    who: str,
    restored_from: int | None = None,
) -> int | None:
    """Appends a revision when the snapshot differs from the latest (or on a
    restore). Returns its number, None when nothing changed."""
    last = latest(db, automation_id)
    before = json.loads(str(last["snapshot"])) if last is not None else None
    changes = diff(before, snapshot)
    if last is not None and not changes and restored_from is None:
        return None
    n = int(last["n"]) + 1 if last is not None else 1
    db.execute(
        """INSERT INTO automation_revisions
             (workspace_id, automation_id, n, snapshot, who, summary, restored_from, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            automation_id,
            n,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            who,
            summary_of(changes, restored_from),
            restored_from,
            now(),
        ),
    )
    db.execute(
        """DELETE FROM automation_revisions WHERE automation_id = ? AND n <= ?""",
        (automation_id, n - KEEP),
    )
    return n


def list_revisions(db: sqlite3.Connection, automation_id: int) -> list[AutomationRevision]:
    """Newest first, each with its diff against the one before."""
    rows = db.execute(
        "SELECT * FROM automation_revisions WHERE automation_id = ? ORDER BY n",
        (automation_id,),
    ).fetchall()
    out: list[AutomationRevision] = []
    before: dict[str, Any] | None = None
    for row in rows:
        snapshot = json.loads(str(row["snapshot"]))
        out.append(
            AutomationRevision(
                n=int(row["n"]),
                at=str(row["created_at"]),
                who=str(row["who"]),
                summary=str(row["summary"]),
                restored_from=row["restored_from"],
                snapshot=snapshot,
                changes=diff(before, snapshot),
            )
        )
        before = snapshot
    return list(reversed(out))


def get_snapshot(db: sqlite3.Connection, automation_id: int, n: int) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT snapshot FROM automation_revisions WHERE automation_id = ? AND n = ?",
        (automation_id, n),
    ).fetchone()
    return json.loads(str(row["snapshot"])) if row is not None else None
