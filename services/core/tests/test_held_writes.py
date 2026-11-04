"""Workspace → Held-back writes: Hermes's write_approval queue (memory and skills),
read and decided with Hermes's own functions in its runtime (stubbed here: the fake
runner has no runtime; the scripts are probed against real Hermes by hand)."""

from typing import Any

from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.engine import hermes as engine_module


def test_held_writes_are_listed_and_decided_by_hermes(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    member = f"{a}--a-writer"
    queue: dict[str, list[dict[str, Any]]] = {
        a: [
            {
                "id": "0cd1ed62",
                "subsystem": "memory",
                "action": "add",
                "summary": "add to MEMORY: likes tea",
                "origin": "foreground",
                "created_at": 2.0,
                "detail": "+ likes tea",
                "target": "memory",
            }
        ],
        member: [
            {
                "id": "57cacd57",
                "subsystem": "skills",
                "action": "create",
                "summary": "create probe",
                "origin": "background_review",
                "created_at": 1.0,
                "detail": "---\nname: probe",
                "target": "probe",
            }
        ],
    }
    homes = {str(core.engine.profile_home(k)): k for k in (a, member)}
    decided: list[tuple[str, str, str, bool]] = []

    def pending_writes(home: Any) -> dict[str, Any]:
        key = homes[str(home)]
        return {"gates": {"memory": key == a, "skills": False}, "items": list(queue[key])}

    def decide_pending(
        home: Any, subsystem: str, pending_id: str, approve: bool, *, keep: bool = False
    ) -> dict[str, Any]:
        key = homes[str(home)]
        decided.append((key, subsystem, pending_id, approve))
        found = [i for i in queue[key] if i["id"] == pending_id]
        queue[key] = [i for i in queue[key] if i["id"] != pending_id]
        return {"found": bool(found), "gone": True, "text": "Approved 1 memory write(s)."}

    core.engine.pending_writes = pending_writes
    core.engine.decide_pending = decide_pending
    body = client.get(f"/workspaces/{a}/held-writes").json()
    assert body["gates"] == {"memory": True, "skills": False}
    assert [i["id"] for i in body["items"]] == ["57cacd57", "0cd1ed62"]  # oldest first
    assert body["items"][0]["agent"].endswith("writer")
    assert body["items"][0]["detail"].startswith("---")
    r = client.post(f"/workspaces/{a}/held-writes/{a}/memory/0cd1ed62", json={"approve": True})
    assert r.status_code == 200, r.text
    assert decided == [(a, "memory", "0cd1ed62", True)]
    assert [i["id"] for i in r.json()["items"]] == ["57cacd57"]
    assert r.json()["said"].startswith("Approved")
    # Gone already, another workspace's agent, a made-up id: refused.
    assert (
        client.post(
            f"/workspaces/{a}/held-writes/{a}/memory/0cd1ed62", json={"approve": False}
        ).status_code
        == 404
    )
    b = ws(client, "Beta")
    assert (
        client.post(
            f"/workspaces/{b}/held-writes/{a}/memory/0cd1ed62", json={"approve": True}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/workspaces/{a}/held-writes/{a}/memory/..%2Fx", json={"approve": True}
        ).status_code
        == 404
    )


def test_the_scripts_use_hermes_own_functions() -> None:
    assert "handle_pending_subcommand" in engine_module._DECIDE_PENDING
    assert "load_on_disk_store" in engine_module._DECIDE_PENDING
    assert "wa.list_pending" in engine_module._PENDING
    assert "skill_pending_diff" in engine_module._PENDING
    # A skill approval's Undo is Hermes's skill-ledger rollback, not AGOS's own
    # snapshot and restore of the skill's files.
    assert "skill_ledger.rollback_entry" in engine_module._UNDO_PENDING
    for own in ("rmtree", "write_text", "unlink", "rglob"):
        assert own not in engine_module._UNDO_PENDING + engine_module._SKILL_LEDGER
