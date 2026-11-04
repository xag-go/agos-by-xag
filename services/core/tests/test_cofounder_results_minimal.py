"""STEP 32 A (925047d area2 C1): a Co-Founder card's result keeps no copy of Hermes's
data. Skills: Hermes's ledger ids (test_skills_through_hermes.py). A member's role:
the id of its AGOS identity history row (agent_versions, which keeps every SOUL.md
before a change: Hermes keeps none). An automation: only what Undo needs where
Hermes's cron has no history (the changed fields; the whole job only for a delete,
H: cron/jobs.py remove_job deletes it). Old rows are moved once."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _cofounder_turn, _member, _run

from agos_core.actions import cofounder_actions
from agos_core.actions.errors import ActionError


def _result(core: Any, action_id: int) -> dict[str, Any]:
    row = core.db.execute(
        "SELECT result FROM cofounder_actions WHERE id = ?", (action_id,)
    ).fetchone()
    found: dict[str, Any] = json.loads(row["result"])
    return found


def test_an_agent_change_keeps_a_history_id_not_its_role(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _member(client, ws, "ideas", instructions="old role " * 50)
    [upd] = _run(core, ws, {"do": "update_agent", "name": "ideas", "instructions": "new role"})
    assert upd["status"] == "done", upd
    kept = _result(core, upd["id"])
    assert "old role" not in json.dumps(kept)
    version = core.db.execute(
        "SELECT * FROM agent_versions WHERE id = ?", (kept["before"]["version"],)
    ).fetchone()
    assert version is not None and "old role" in version["definition"]
    client.post(f"/workspaces/{ws}/cofounder-actions/{upd['id']}", json={"choice": "undo"})
    [agent] = client.get(f"/workspaces/{ws}/agents").json()
    assert agent["definition"]["instructions"] == ("old role " * 50).strip()


def test_an_automation_change_keeps_only_what_changed(env: Any) -> None:  # noqa: F811
    client, core, _cron, ws = env
    _run(
        core,
        ws,
        {
            "do": "create_automation",
            "name": "Daily",
            "schedule": "0 8 * * *",
            "instructions": "the job's whole prompt",
        },
    )
    [changed] = _run(
        core, ws, {"do": "update_automation", "automation": "daily", "schedule": "30 7 * * *"}
    )
    assert _result(core, changed["id"])["before"] == {"schedule": "0 8 * * *"}
    [paused] = _run(core, ws, {"do": "pause_automation", "automation": "Daily"})
    assert _result(core, paused["id"])["before"] == {"on": True}
    [ran] = _run(core, ws, {"do": "run_automation", "automation": "Daily"})
    assert "prompt" not in json.dumps(_result(core, ran["id"]))
    client.post(f"/workspaces/{ws}/cofounder-actions/{paused['id']}", json={"choice": "undo"})
    client.post(f"/workspaces/{ws}/cofounder-actions/{changed['id']}", json={"choice": "undo"})
    [back] = client.get(f"/workspaces/{ws}/automations").json()
    assert back["schedule"] == "0 8 * * *" and back["on"] is True
    assert back["instructions"] == "the job's whole prompt"


def _old(core: Any, ws: str, action: str, result: dict[str, Any], payload: Any = None) -> int:
    chat, turn = _cofounder_turn(core, ws)
    cur = core.db.execute(
        """INSERT INTO cofounder_actions
             (workspace_id, chat_id, turn_id, action, title, payload, status, result, created_at)
           VALUES (?, ?, ?, ?, 'old', ?, 'done', ?, '2026-10-01T00:00:00Z')""",
        (ws, chat, turn, action, json.dumps(payload or {}), json.dumps(result)),
    )
    return int(cur.lastrowid or 0)


def test_old_snapshots_are_moved_once(env: Any, tmp_path: Path, monkeypatch: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    backups = tmp_path / "backups"
    monkeypatch.setenv("AGOS_BACKUP_DIR", str(backups))
    _member(_client, ws, "ideas", instructions="now")
    skill = _old(
        core,
        ws,
        "update_skill",
        {"copy": "notes", "before": {"text": "OLD SKILL", "files": {"references/a.md": "A"}}},
    )
    library = _old(
        core,
        ws,
        "update_skill",
        {
            "item_id": 3,
            "kind": "skill",
            "name": "notes",
            "was_on": True,
            "before": {"title": "", "summary": "", "definition": {"text": "OLD LIB"}},
        },
    )
    agent_before = {"title": "Ideas", "summary": "", "definition": {"instructions": "OLD ROLE"}}
    agent = _old(
        core,
        ws,
        "update_agent",
        {"item_id": 1, "kind": "agent", "name": "ideas", "was_on": True, "before": agent_before},
    )
    full = {"name": "Daily", "instructions": "OLD PROMPT", "schedule": "0 8 * * *", "on": True}
    auto = _old(
        core,
        ws,
        "update_automation",
        {"automation_id": 1, "before": full},
        {"automation": "Daily", "schedule": "1 8 * * *"},
    )
    ran = _old(core, ws, "run_automation", {"automation_id": 1, "before": full})
    bundle = _old(
        core,
        ws,
        "bundle",
        {
            "items": [
                {
                    "do": "update_agent",
                    "result": {
                        "item_id": 1,
                        "kind": "agent",
                        "name": "ideas",
                        "before": agent_before,
                    },
                }
            ]
        },
    )
    for _ in range(2):  # safe to repeat
        cofounder_actions.move_snapshots(core)
    rows = {
        r["id"]: r["result"]
        for r in core.db.execute("SELECT id, result FROM cofounder_actions").fetchall()
    }
    for text in ("OLD SKILL", "OLD LIB", "OLD ROLE", "OLD PROMPT", '"A"'):
        assert all(text not in str(v) for v in rows.values()), text
    # The skills' old copies: in the backups folder (never deleted), not the database.
    [kept] = list(backups.glob("cofounder-actions-*.json"))
    moved = json.loads(kept.read_text())
    assert {m["id"] for m in moved} == {skill, library}
    assert "OLD SKILL" in kept.read_text() and "OLD LIB" in kept.read_text()
    # The role: in the identity history, and the card points at it.
    version = json.loads(rows[agent])["before"]["version"]
    v = core.db.execute("SELECT * FROM agent_versions WHERE id = ?", (version,)).fetchone()
    assert v is not None and "OLD ROLE" in v["definition"] and v["name"] == "ideas"
    inner = json.loads(rows[bundle])["items"][0]["result"]["before"]
    assert inner == {"version": version}
    assert json.loads(rows[auto])["before"] == {"schedule": "0 8 * * *"}
    assert "before" not in json.loads(rows[ran])
    # An old skill change can't be undone from a copy any more: it says so.
    for action_id in (skill, library):
        with pytest.raises(ActionError, match="backups"):
            cofounder_actions.decide(core, ws, action_id, "undo")
