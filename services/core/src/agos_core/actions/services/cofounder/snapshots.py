"""Moving the Co-Founder's old Undo snapshots out of its cards into a file (a one-time move).
Must not: run or undo an action.

Split out of agos_core.actions.cofounder_actions (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.context import Core
from agos_core.db import agent_versions as versions_repo
from agos_core.db import cofounder_actions as cards_repo
from agos_core.db.rows import load_json
from agos_core.engine import cofounder_actions as rules

__all__ = [
    "SNAPSHOTS_FILE",
    "move_snapshots",
]

log = logging.getLogger("agos.cofounder_actions")  # the old module's logger (one name)

# ---- one-time move of old cards' copies (STEP 32) --------------------------------------

SNAPSHOTS_FILE = "cofounder-actions-before-step32.json"
# The snapshot fields a payload key changed (update_automation).
_AUTOMATION_FIELDS = {
    "name": ("name",),
    "schedule": ("schedule",),
    "instructions": ("instructions",),
    "steps": ("steps", "agent"),
    "agent": ("agent", "steps"),
    "on": ("on",),
    "webhook": ("webhook",),
    "webhook_events": ("webhook_events",),
    "webhook_conditions": ("webhook_conditions",),
    "check_first": ("check_first",),
}


def _version_for(core: Core, row: Any, name: str, before: dict[str, Any]) -> int:
    """The identity-history row holding this old role (the same title and text),
    else a new one (event "changed", at the card's time)."""
    definition = before.get("definition") or {}
    found = versions_repo.find_role(
        core.db,
        row["workspace_id"],
        name,
        str(before.get("title") or ""),
        definition.get("instructions"),
    )
    if found is not None:
        return found
    return versions_repo.insert_changed(
        core.db,
        row["workspace_id"],
        name,
        title=str(before.get("title") or ""),
        summary=str(before.get("summary") or ""),
        definition=json.dumps(definition),
        created_at=row["created_at"],
    )


def _slim(
    core: Core,
    row: Any,
    action: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    moved: list[dict[str, Any]],
) -> dict[str, Any]:
    """One card's result without its copy of Hermes's data (see move_snapshots)."""
    before = result.get("before")
    if action == rules.BUNDLE:
        fields = [dict(i.get("fields") or {}) for i in payload.get("items") or []]
        items = []
        for i, d in enumerate(result.get("items") or []):
            inner = d.get("result")
            if isinstance(inner, dict):
                p = fields[i] if i < len(fields) else {}
                inner = _slim(core, row, str(d.get("do")), p, inner, moved)
            items.append({**d, "result": inner})
        return {**result, "items": items}
    if not isinstance(before, dict):
        return result
    if action in ("update_skill", "create_skill") and ("text" in before or "definition" in before):
        moved.append({"id": int(row["id"]), "action": action, "result": result})
        out = {**result, "before": {"kept_in": SNAPSHOTS_FILE}}
        if "copy" in result:
            out["own"] = True
        return out
    if action in ("update_agent", "create_agent") and "definition" in before:
        name = str(result.get("name") or "")
        if not name:
            moved.append({"id": int(row["id"]), "action": action, "result": result})
            return {**result, "before": {"kept_in": SNAPSHOTS_FILE}}
        return {**result, "before": {"version": _version_for(core, row, name, before)}}
    if action == "run_automation":
        return {k: v for k, v in result.items() if k != "before"}
    if action in ("pause_automation", "resume_automation"):
        return {**result, "before": {"on": before.get("on")}}
    if action == "update_automation":
        keys = {f for k in payload for f in _AUTOMATION_FIELDS.get(k, ())}
        return {**result, "before": {k: v for k, v in before.items() if k in keys}}
    return result


def move_snapshots(core: Core) -> int:
    """Once (STEP 32): old Co-Founder cards kept a copy of Hermes's data for their Undo.
    A skill's (SKILL.md and its files) goes to the backups folder (kept, never
    deleted; Hermes's skill ledger is the Undo of every card since); a member's role
    goes to AGOS's identity history (agent_versions) and the card keeps its id; an
    automation keeps only the fields its change touched (a run: nothing). Safe to
    repeat. Returns the cards changed."""
    from agos_core.actions import backups

    rows = cards_repo.with_results(core.db)
    moved: list[dict[str, Any]] = []
    updates: list[tuple[str, int]] = []
    for row in rows:
        result = load_json(row["result"])
        payload = load_json(row["payload"]) or {}
        if not isinstance(result, dict):
            continue
        slim = _slim(
            core,
            row,
            str(row["action"]),
            payload if isinstance(payload, dict) else {},
            result,
            moved,
        )
        if slim != result:
            updates.append((json.dumps(slim), int(row["id"])))
    if moved:
        folder = backups.backup_dir(core)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / SNAPSHOTS_FILE
        try:
            have = json.loads(path.read_text())
        except (OSError, ValueError):
            have = []
        known = {int(m["id"]) for m in have if isinstance(m, dict) and "id" in m}
        have += [m for m in moved if m["id"] not in known]
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(have, ensure_ascii=False, indent=1))
        tmp.chmod(0o600)
        tmp.replace(path)
    for text, action_id in updates:
        cards_repo.set_result(core.db, action_id, text)
    if updates:
        log.info("Co-Founder cards' copies of Hermes data moved: %d", len(updates))
    return len(updates)
