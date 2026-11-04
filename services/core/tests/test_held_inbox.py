"""Held-back writes in the Inbox: Hermes's write_approval queue (memory and skills)
read as one card per request, with a plain title, the notes before / after, an
"In short" from Hermes's helper model, and Approve (the newest copy) / Reject (all).
Hermes's runtime is stubbed here; the _PENDING script itself runs against the real
Hermes in test_held_pending_live."""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import held_writes

OLD = "Skills (2026-10-26): workers read an old shared folder."
OLD2 = "Skills: workers read the stale copy."


def _batch(pid: str, at: float, new: str, *, gone: bool = False) -> dict[str, Any]:
    return {
        "id": pid,
        "subsystem": "memory",
        "action": "batch",
        "summary": "background review consolidation (batch on memory): ...",
        "origin": "background_review",
        "created_at": at,
        "detail": "",
        "target": "memory",
        "ops": [
            {"action": "remove", "target": "memory", "before": OLD, "after": "", "gone": gone},
            {"action": "patch", "target": "memory", "before": OLD2, "after": new, "gone": False},
        ],
    }


def _rig(core: Any, a: str, queue: dict[str, list[dict[str, Any]]], decided: list[Any]) -> None:
    homes = {str(core.engine.profile_home(k)): k for k in queue}
    # The files Hermes keeps them in (the badge looks for one before asking Hermes).
    for key, items in queue.items():
        for item in items:
            folder = core.engine.profile_home(key) / "pending" / item["subsystem"]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / f"{item['id']}.json").write_text("{}")

    def pending_writes(home: Any) -> dict[str, Any]:
        return {"gates": {"memory": False, "skills": False}, "items": list(queue[homes[str(home)]])}

    def decide_pending(
        home: Any, subsystem: str, pending_id: str, approve: bool, *, keep: bool = False
    ) -> dict[str, Any]:
        key = homes[str(home)]
        decided.append((key, subsystem, pending_id, approve))
        found = [i for i in queue[key] if i["id"] == pending_id]
        queue[key] = [i for i in queue[key] if i["id"] != pending_id]
        (Path(home) / "pending" / subsystem / f"{pending_id}.json").unlink(missing_ok=True)
        return {"found": bool(found), "gone": True, "text": "Approved 1 memory write(s)."}

    core.engine.pending_writes = pending_writes
    core.engine.decide_pending = decide_pending


def test_the_same_request_asked_again_is_one_inbox_card(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    member = f"{a}--a-writer"
    queue = {
        a: [
            _batch("a3b93f77", 10.0, "Skills: fixed at 19:27."),
            _batch("727e81b8", 30.0, "Skills: fixed, checked at 19:38."),
            _batch("d4a61f19", 20.0, "Skills: fixed at 20:05."),
            {
                "id": "dc0a5cc2",
                "subsystem": "memory",
                "action": "add",
                "summary": "add",
                "origin": "foreground",
                "created_at": 40.0,
                "detail": "+ Kanban: assignee is a-<member>",
                "target": "user",
                "ops": [
                    {
                        "action": "add",
                        "target": "user",
                        "before": "",
                        "after": "Kanban: assignee is a-<member>",
                        "gone": False,
                    }
                ],
            },
        ],
        member: [
            {
                "id": "57cacd57",
                "subsystem": "skills",
                "action": "patch",
                "summary": "patch probe",
                "origin": "background_review",
                "created_at": 5.0,
                "detail": "--- a/SKILL.md\n+++ b/SKILL.md",
                "target": "probe",
            }
        ],
    }
    decided: list[Any] = []
    _rig(core, a, queue, decided)

    body = client.get(f"/workspaces/{a}/inbox").json()
    held = [i for i in body["items"] if i["type"] == "held"]
    assert len(held) == 3  # the three copies of one request are one card
    skills = next(i for i in held if i["held"]["subsystem"] == "skills")
    assert skills["title"].endswith("wants to change the skill “probe”")
    assert skills["held"]["detail"].startswith("--- a/SKILL.md")
    same = next(i for i in held if len(i["held"]["ids"]) == 3)["held"]
    assert same["ids"] == ["a3b93f77", "d4a61f19", "727e81b8"]  # oldest first
    assert same["id"] == "727e81b8"  # the newest is the one shown and applied
    assert same["ops"][1]["after"] == "Skills: fixed, checked at 19:38."
    assert "wants to remove a note and update a note in its memory" in same["title"]
    assert not same["stale"]
    about = next(i for i in held if i["held"]["ids"] == ["dc0a5cc2"])
    assert about["title"].endswith("wants to add a note in its notes about you")
    # The badge counts the requests waiting, from Hermes's queue.
    assert client.get(f"/workspaces/{a}/inbox/count").json()["count"] >= 3

    # Approve: the newest is applied, the older copies dropped (Hermes's reject).
    r = client.post(
        f"/workspaces/{a}/held-writes/decide",
        json={"profile": a, "subsystem": "memory", "ids": same["ids"], "approve": True},
    )
    assert r.status_code == 200, r.text
    assert decided == [
        (a, "memory", "727e81b8", True),
        (a, "memory", "a3b93f77", False),
        (a, "memory", "d4a61f19", False),
    ]
    assert r.json()["waiting"] == 2
    # Reject: every copy dropped; another workspace's agent or a made-up id refused.
    decided.clear()
    r = client.post(
        f"/workspaces/{a}/held-writes/decide",
        json={"profile": member, "subsystem": "skills", "ids": ["57cacd57"], "approve": False},
    )
    assert r.status_code == 200, r.text
    assert decided == [(member, "skills", "57cacd57", False)]
    b = ws(client, "Beta")
    for wsid, ids in ((b, ["dc0a5cc2"]), (a, ["../x"])):
        r = client.post(
            f"/workspaces/{wsid}/held-writes/decide",
            json={"profile": a, "subsystem": "memory", "ids": ids, "approve": True},
        )
        assert r.status_code == 404, r.text


def test_a_request_whose_note_is_gone_is_out_of_date(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    queue = {a: [_batch("42f0fef0", 1.0, "new", gone=True)]}
    _rig(core, a, queue, [])
    held = next(i for i in client.get(f"/workspaces/{a}/inbox").json()["items"] if i["held"])
    assert held["held"]["stale"] is True and held["held"]["left"] == 1
    # Approve of a part-done request: what still applies is saved through Hermes.
    rest: list[str] = []

    def apply_pending_rest(home: Any, pending_id: str) -> dict[str, Any]:
        rest.append(pending_id)
        queue[a] = []
        return {"found": True, "gone": True, "text": "Saved 1 change(s); 1 already done before."}

    core.engine.apply_pending_rest = apply_pending_rest
    r = client.post(
        f"/workspaces/{a}/held-writes/decide",
        json={"profile": a, "subsystem": "memory", "ids": ["42f0fef0"], "approve": True},
    )
    assert r.status_code == 200, r.text
    assert rest == ["42f0fef0"] and r.json()["said"].startswith("Saved 1")


def test_in_short_is_asked_of_hermes_once_per_request(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    queue = {a: [_batch("a3b93f77", 1.0, "Skills: fixed.")]}
    _rig(core, a, queue, [])
    asked: list[tuple[str, str, dict[str, Any]]] = []

    def walled_cli(key: str, *args: str, timeout: float = 60) -> str:
        asked.append((key, args[0], json.loads(args[1])))
        return 'noise\n{"ok": true, "text": "The Manager wants to drop an outdated note."}\n'

    core.engine.walled_cli = walled_cli
    held_writes._EXPLAINED.clear()
    url = f"/workspaces/{a}/held-writes/{a}/memory/a3b93f77/explain"
    for _ in range(2):
        r = client.post(url)
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "The Manager wants to drop an outdated note."
    assert len(asked) == 1
    key, command, job = asked[0]
    assert (key, command) == (a, "agos-explain")
    assert [c["action"] for c in job["changes"]] == ["remove", "patch"]
    assert (
        client.post(f"/workspaces/{a}/held-writes/{a}/memory/ffffffff/explain").status_code == 404
    )


def test_the_settings_page_is_gone_and_the_explainer_is_a_plugin_command() -> None:
    root = Path(__file__).resolve().parents[3]
    page = root / "apps/web/src/app/(app)/w/[id]/settings/held-writes/page.tsx"
    assert "redirect(" in page.read_text()
    from agos_core.hermes_plugin.agos_guard import explain

    assert explain.TASK == "review"
    msg = explain._message(
        {
            "agent": "Manager",
            "kind": "memory",
            "changes": [{"action": "remove", "where": "own notes", "before": OLD, "after": ""}],
        }
    )
    assert "Manager" in msg and OLD in msg


def test_held_pending_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The _PENDING script against the real Hermes: a background batch staged with
    Hermes's own stage_write reads back note by note, and a note already gone is
    flagged."""
    monkeypatch.undo()
    hermes = shutil.which("hermes")
    if not hermes:
        pytest.skip("no Hermes install on this machine")
    from agos_core.config import EngineConfig
    from agos_core.engine.hermes import _PENDING, HermesEngine

    tools = Path.home() / ".hermes" / "tools"
    engine = HermesEngine(
        EngineConfig(
            hermes_bin=hermes,
            docker_bin="docker",
            hermes_home=tmp_path / "shared",
            profile_prefix="agos-",
            sandbox_image="x",
            host_home=Path.home(),
            roots_dir=tmp_path / "roots",
            runtime_dir=tools if tools.is_dir() else None,
        ),
        egress=False,
    )
    home = tmp_path / "root"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    stage = (
        "import json\n"
        "from tools.memory_tool import load_on_disk_store\n"
        "from tools import write_approval as wa\n"
        "store = load_on_disk_store()\n"
        f"store.add('memory', {OLD!r})\n"
        f"store.add('memory', {OLD2!r})\n"
        "ops = [\n"
        f"  {{'action': 'remove', 'old_text': 'old shared', 'matched_entry': {OLD!r}}},\n"
        f"  {{'action': 'patch', 'old_text': 'stale copy', 'content': 'new copy',"
        f" 'matched_entry': {OLD2!r}}},\n"
        "  {'action': 'remove', 'old_text': 'x', 'matched_entry': 'A note no longer there'},\n"
        "  {'action': 'add', 'content': 'Kanban: assignee is a-<member>'},\n"
        "]\n"
        "r = wa.stage_write(wa.MEMORY, {'action': 'batch', 'target': 'memory', 'operations': ops},"
        " summary='bg', origin='background_review')\n"
        "print('AGOS-STAGED ' + json.dumps(r['id']))\n"
    )
    try:
        engine._in_runtime(home, stage, "AGOS-STAGED")
        found = json.loads(engine._in_runtime(home, _PENDING, "AGOS-PENDING"))
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"Hermes's runtime isn't usable here: {error}")
    (item,) = found["items"]
    ops = item["ops"]
    assert [o["action"] for o in ops] == ["remove", "patch", "remove", "add"]
    assert ops[0] == {
        "action": "remove",
        "target": "memory",
        "before": OLD,
        "after": "",
        "gone": False,
    }
    assert ops[1]["before"] == OLD2 and ops[1]["after"] == "Skills: workers read the new copy."
    assert ops[2]["gone"] is True
    assert ops[3]["after"] == "Kanban: assignee is a-<member>" and ops[3]["before"] == ""
    # Part of it is already done (a note gone): Hermes's approve refuses the whole
    # batch, apply_pending_rest saves what still applies and drops the held write.
    done = engine.apply_pending_rest(home, item["id"])
    assert done["found"] and done["gone"] and done["kept"] == 3 and done["skipped"] == 1
    mem = json.loads(
        engine._in_runtime(
            home,
            "import json\nfrom tools.memory_tool import load_on_disk_store\n"
            "print('AGOS-MEM ' + json.dumps(load_on_disk_store().memory_entries))\n",
            "AGOS-MEM",
        )
    )
    assert mem == ["Skills: workers read the new copy.", "Kanban: assignee is a-<member>"]
