"""A team member's revision history: one snapshot per change of who it is (Step 56).

Hermes keeps no history of a profile's SOUL.md, profile.yaml or the config fields
AGOS writes (H: hermes_cli/config_backups.py keeps config.yaml copies for its own
`config set` undo only, no SOUL.md and no who/why), so the versions of a member are
AGOS's rows (agent_revisions): its job title, what it's for, role text, the owner's
notes, model, skills, the rule files it reads, its lead, on/off and its heartbeat.
Every AGOS write that changed something appends a snapshot with who made it and
why; Restore is a new write from a snapshot through the team's normal path,
recorded as a revision "restored from vN". The Revisions tab reads the list once
(snapshot and diff included).
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from typing import Any

from agos_core.db.records import AgentRevision, AgentRevisionChange
from agos_core.db.rows import now

KEEP = 100  # revisions kept per member (the oldest go)

# The snapshot's fields, in the order the diff lists them.
FIELDS = (
    "title",
    "summary",
    "instructions",
    "local",
    "model",
    "skills",
    "reads",
    "reports_to",
    "on",
    "heartbeat",
)
TEXTS = ("instructions", "local")  # long texts: shown as a line diff


def snapshot_of(agent: Any, heartbeat: str | None) -> dict[str, Any]:
    """The member as it is (actions/team.Agent), in one JSON-able dict (what
    Restore brings back). `heartbeat`: its interval, "" when off."""
    return {
        "title": agent.title,
        "summary": agent.summary,
        "instructions": agent.instructions,
        "local": agent.local,
        "model": agent.model,
        "skills": list(agent.skills),
        "reads": [dict(r) for r in agent.reads],
        "reports_to": agent.reports_to,
        "on": agent.on,
        "heartbeat": heartbeat or "",
    }


def _shown(field: str, value: Any) -> str:
    """A field's value as one line of text."""
    if value is None or value == "":
        if field == "model":
            return "the workspace's model"
        if field == "reports_to":
            return "the Co-Founder"
        if field == "heartbeat":
            return "off"
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, list):
        if not value:
            return "none"
        return ", ".join(
            str(v.get("path") or v.get("name") or v) if isinstance(v, dict) else str(v)
            for v in value
        )
    if isinstance(value, dict):
        if "model" in value:
            return f"{value.get('model')} ({value.get('effort') or 'default effort'})"
        return json.dumps(value, ensure_ascii=False)[:300]
    if field == "reports_to":
        return f"@{value}"
    return str(value)


def _lines(before: str, after: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=2
        )
    )


def diff(before: dict[str, Any] | None, after: dict[str, Any]) -> list[AgentRevisionChange]:
    """What changed between two snapshots, field by field (an absent `before` is
    the first revision: every set field is new)."""
    changes = []
    for field in FIELDS:
        old = (before or {}).get(field)
        new = after.get(field)
        if before is None and new in (None, [], "", False):
            continue
        if old == new or (before is not None and field not in before):
            continue
        text = field in TEXTS
        changes.append(
            AgentRevisionChange(
                field=field,
                before=str(old or "") if text else _shown(field, old),
                after=str(new or "") if text else _shown(field, new),
                lines=_lines(str(old or ""), str(new or "")) if text else "",
            )
        )
    return changes


def summary_of(changes: list[AgentRevisionChange], restored_from: int | None, first: bool) -> str:
    if restored_from is not None:
        return f"restored from v{restored_from}"
    if first:
        return "first version"
    names = [c.field.replace("_", " ") for c in changes]
    return "changed " + ", ".join(names[:5]) + (f" (+{len(names) - 5})" if len(names) > 5 else "")


def latest(db: sqlite3.Connection, workspace_id: str, name: str) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        """SELECT * FROM agent_revisions WHERE workspace_id = ? AND name = ?
           ORDER BY n DESC LIMIT 1""",
        (workspace_id, name),
    ).fetchone()
    return found


def latest_snapshot(db: sqlite3.Connection, workspace_id: str, name: str) -> dict[str, Any] | None:
    last = latest(db, workspace_id, name)
    return json.loads(str(last["snapshot"])) if last is not None else None


def append(
    db: sqlite3.Connection,
    workspace_id: str,
    name: str,
    snapshot: dict[str, Any],
    *,
    who: str,
    why: str = "",
    restored_from: int | None = None,
) -> int | None:
    """Appends a revision when the snapshot differs from the latest (or on a
    restore). Returns its number, None when nothing changed."""
    last = latest(db, workspace_id, name)
    before = json.loads(str(last["snapshot"])) if last is not None else None
    changes = diff(before, snapshot)
    if last is not None and not changes and restored_from is None:
        return None
    n = int(last["n"]) + 1 if last is not None else 1
    db.execute(
        """INSERT INTO agent_revisions
             (workspace_id, name, n, snapshot, who, why, summary, restored_from, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            name,
            n,
            json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            who[:80],
            why[:500],
            summary_of(changes, restored_from, last is None),
            restored_from,
            now(),
        ),
    )
    db.execute(
        "DELETE FROM agent_revisions WHERE workspace_id = ? AND name = ? AND n <= ?",
        (workspace_id, name, n - KEEP),
    )
    return n


def list_revisions(db: sqlite3.Connection, workspace_id: str, name: str) -> list[AgentRevision]:
    """Newest first, each with its diff against the one before."""
    rows = db.execute(
        "SELECT * FROM agent_revisions WHERE workspace_id = ? AND name = ? ORDER BY n",
        (workspace_id, name),
    ).fetchall()
    out: list[AgentRevision] = []
    before: dict[str, Any] | None = None
    for row in rows:
        snapshot = json.loads(str(row["snapshot"]))
        out.append(
            AgentRevision(
                n=int(row["n"]),
                at=str(row["created_at"]),
                who=str(row["who"]),
                why=str(row["why"]),
                summary=str(row["summary"]),
                restored_from=row["restored_from"],
                snapshot=snapshot,
                changes=diff(before, snapshot),
            )
        )
        before = snapshot
    return list(reversed(out))


def get_snapshot(
    db: sqlite3.Connection, workspace_id: str, name: str, n: int
) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT snapshot FROM agent_revisions WHERE workspace_id = ? AND name = ? AND n = ?",
        (workspace_id, name, n),
    ).fetchone()
    return json.loads(str(row["snapshot"])) if row is not None else None
