"""Full access / Ask me is Hermes's own approvals (config per profile, YOLO per
conversation); the owner's Autonomy "Never" is Hermes's disabled toolsets where a
whole toolset is off; "Ask me" stays the agos-guard plugin's, and Full access
never answers it."""

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from test_agent_profiles import add_agent
from test_library import MODEL, env, ws  # noqa: F401 - fixture

from agos_core.actions import access, autonomy, hermes_channel
from agos_core.hermes_plugin import agos_guard


def settings(client: Any, w: str, chat_access: str) -> None:
    body = {"name": "Alpha", "description": "", "defaultModel": MODEL, "chatAccess": chat_access}
    assert client.put(f"/workspaces/{w}", json=body).status_code in (200, 204)


def test_full_access_is_hermes_approvals_on_every_profile(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    cofounder, member = runner.config[f"agos-{a}"], runner.config[f"agos-{a}--a-writer"]
    # A new workspace starts on Full access (the owner's General config).
    for config in (cofounder, member):
        assert config["approvals.mode"] == "off"
        assert config["approvals.cron_mode"] == "approve"  # automations run
    # Ask me first: Hermes asks before a risky command, on every profile.
    settings(client, a, "ask")
    assert cofounder["approvals.mode"] == member["approvals.mode"] == "manual"
    assert member["approvals.cron_mode"] == "approve"
    # A re-sync keeps the owner's switch (the base config never resets it).
    from agos_core.actions.engine import sync_workspace

    settings(client, a, "full")
    (core.engine.profile_home(a) / ".agos-applied").unlink()
    sync_workspace(core, a)
    assert runner.config[f"agos-{a}"]["approvals.mode"] == "off"


def test_a_member_made_in_the_background_follows_the_latest_switch(env: Any) -> None:  # noqa: F811
    """A member's profile is planned from AGOS's data, then written in the
    background: if the owner switches access meanwhile, it still ends on his last
    choice (its approvals are its Co-Founder's, read when written)."""
    from agos_core.actions import agent_profiles
    from agos_core.actions.engine import _grants

    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    settings(client, a, "ask")
    item = next(i for i in agent_profiles.team(core, a) if i.name == "writer")
    plan = agent_profiles._plan(core, a, item, {}, _grants(core, a), {})
    settings(client, a, "full")  # while the old plan waits
    agent_profiles._make(core, plan)
    assert runner.config[f"agos-{a}--a-writer"]["approvals.mode"] == "off"


def test_members_follow_the_cofounders_switch_read_from_its_config_file(env: Any) -> None:  # noqa: F811
    """C10: a member's approvals follow its Co-Founder's `approvals.mode` as the root's
    config.yaml holds it (no Hermes start per member, every re-sync); Hermes's own
    `config get` answers only when the file holds none of the modes."""
    import os

    import yaml

    client, core, runner, _home = env
    engine = core.engine
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    members = [f"{a}--a-writer", f"{a}--a-editor"]
    path = engine.profile_home(a) / "config.yaml"

    def root_holds(value: Any) -> None:
        """The root's approvals.mode in its file (None: no line), and what Hermes's
        CLI prints for it."""
        config = yaml.safe_load(path.read_text()) or {}
        approvals = config.setdefault("approvals", {})
        approvals.pop("mode", None)
        said = runner.config[f"agos-{a}"]
        said.pop("approvals.mode", None)
        if value is not None:
            approvals["mode"] = value
            said["approvals.mode"] = "false" if value is False else str(value)
        before = path.stat().st_mtime_ns
        text = yaml.safe_dump(config, sort_keys=False)
        path.write_text(text.replace("mode: false", "mode: off"))  # a bare `off`, by hand
        later = max(path.stat().st_mtime_ns, before + 1)  # a new stamp, like any write
        os.utime(path, ns=(later, later))

    def follow() -> tuple[int, list[str]]:
        """Each member follows its Co-Founder: the Hermes starts asking the Co-Founder's
        mode, and the mode each member ends on."""
        runner.calls.clear()
        for key in members:
            access.follow_cofounder(engine, a, key)
        asked = sum(c[1:4] == ["config", "get", "approvals.mode"] for c in runner.calls)
        return asked, [runner.config[f"agos-{key}"]["approvals.mode"] for key in members]

    root_holds("smart")
    assert follow() == (0, ["smart", "smart"])
    root_holds(False)  # YAML reads a bare `off` as false: Full access
    assert follow() == (0, ["off", "off"])
    root_holds("auto")  # none of the modes: Hermes's CLI says (an unknown one is manual)
    assert follow() == (2, ["manual", "manual"])
    root_holds(None)  # no line: Hermes's CLI says (Hermes fills in its default)
    assert follow()[0] == 2


def _routing(home: Any, key: str, yolo: bool) -> None:
    """Hermes's gateway routing index (state.db gateway_routing), as Hermes keeps it."""
    import sqlite3

    con = sqlite3.connect(home / "state.db")
    con.execute(
        "CREATE TABLE IF NOT EXISTS gateway_routing (scope TEXT NOT NULL DEFAULT '',"
        " session_key TEXT NOT NULL, entry_json TEXT NOT NULL, updated_at REAL NOT NULL,"
        " PRIMARY KEY (scope, session_key))"
    )
    entry = {
        "session_key": key,
        "session_id": "s1",
        "updated_at": "2026-10-15T10:00:00",
        "yolo": yolo,
        # The chat it came from (SessionEntry.origin), under the store's scope (its
        # resolved sessions dir, gateway/session_persistence.py _routing_scope).
        "origin": {"platform": "agos", "chat_id": key.rsplit(":", 1)[1], "chat_type": "dm"},
    }
    scope = str((home / "sessions").resolve())
    con.execute(
        "INSERT OR REPLACE INTO gateway_routing VALUES (?, ?, ?, 1.0)",
        (scope, key, json.dumps(entry)),
    )
    con.commit()
    con.close()


def test_a_chats_full_access_is_its_own_hermes_yolo(env: Any) -> None:  # noqa: F811
    import threading

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    settings(client, a, "ask")
    chat = client.post(f"/workspaces/{a}/workers/dm", json={"agent": ""}).json()["id"]
    home = core.engine.profile_home(a)

    def view() -> dict[str, Any]:
        found: dict[str, Any] = client.get(f"/workspaces/{a}/chats/{chat}").json()
        return found

    # What the chat shows is Hermes's own /yolo of its conversation.
    assert view()["access"] == "ask" and view()["workspaceFull"] is False
    _routing(home, f"agent:main:agos:dm:{chat}", True)
    assert view()["access"] == "full"
    _routing(home, f"agent:main:agos:dm:{chat}", False)
    assert view()["access"] == "ask"
    # AGOS starts no answer with a switch of its own.
    assert "fullAccess" not in hermes_channel.turn_start(core, a, f"agos:{chat}", "s-1")

    # His switch: Hermes's own /yolo command in the conversation (a command item,
    # the toggle Hermes has), and the switch answers once Hermes's entry says so.
    taken: list[dict[str, Any]] = []

    def gateway() -> None:
        for _ in range(100):
            for item in hermes_channel.take_inbox(core, a, agos=True):
                taken.append(item)
                if item["kind"] == "command" and item["text"] == "/yolo":
                    _routing(home, f"agent:main:agos:dm:{chat}", True)
                hermes_channel.inbox_done(core, a, item["id"], True)
                return
            threading.Event().wait(0.05)

    worker = threading.Thread(target=gateway)
    worker.start()
    r = client.put(f"/workspaces/{a}/chats/{chat}", json={"access": "full"})
    worker.join()
    assert r.status_code == 204, r.text
    assert [(i["chat"], i["kind"], i["text"]) for i in taken] == [
        (f"agos:{chat}", "command", "/yolo")
    ]
    assert view()["access"] == "full"
    # Already what he asks: no /yolo (it would toggle it off again).
    before = core.db.execute("SELECT count(*) FROM hermes_inbox").fetchone()[0]
    assert client.put(f"/workspaces/{a}/chats/{chat}", json={"access": "full"}).status_code == 204
    assert core.db.execute("SELECT count(*) FROM hermes_inbox").fetchone()[0] == before
    # No gateway takes it: he is told, and nothing stays queued.
    access.YOLO_WAIT_S = 0.3
    try:
        r = client.put(f"/workspaces/{a}/chats/{chat}", json={"access": "ask"})
    finally:
        access.YOLO_WAIT_S = 20.0
    assert r.status_code == 503
    assert (
        core.db.execute(
            "SELECT count(*) FROM hermes_inbox WHERE text = '/yolo' AND done_at IS NULL"
        ).fetchone()[0]
        == 0
    )
    # The workspace's Full access is its profiles' config; every chat shows it.
    settings(client, a, "full")
    assert view()["workspaceFull"] is True


def test_the_chat_switch_uses_no_private_gateway_state() -> None:
    """Guard: a chat's Full access is Hermes's own /yolo command. Neither the plugin
    nor AGOS reaches into Hermes's YOLO toggle to set it, and the running gateway's
    reference is taken in one place only (the plugin's member-topic bind)."""
    root = Path(access.__file__).resolve().parents[1]
    runner_refs = []
    for path in root.rglob("*.py"):
        if path.name == "hermes_contract.py" or "/engine/contract/" in path.as_posix():
            continue  # the list of what AGOS uses (engine/hermes_contract.py)
        text = path.read_text()
        for private in ("set_session_yolo", "toggle_session_yolo"):
            assert private not in text, f"{path}: {private}"
        runner_refs += [path.name] * text.count("_gateway_runner_ref")
    # the call, and the contract name it is reported under when it breaks
    assert runner_refs == ["bridge_sessions.py", "bridge_sessions.py"], runner_refs
    bridge_text = "".join(
        p.read_text() for p in (root / "hermes_plugin" / "agos_guard").glob("bridge*.py")
    )
    assert "set_yolo" not in bridge_text
    assert "'yolo'" not in Path(access.__file__).read_text()


def test_a_members_own_never_is_its_profiles_toolsets(env: Any) -> None:  # noqa: F811
    client, core, runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    add_agent(client, a, "editor")
    autonomy.set_rule(core, a, "writer", "browser", "never")
    assert autonomy.never_toolsets(core, a, "writer") == ["browser"]
    assert autonomy.never_toolsets(core, a, "editor") == []
    assert autonomy.never_toolsets(core, a) == []  # the Co-Founder's profile keeps it
    writer = json.loads(runner.config[f"agos-{a}--a-writer"]["agent.disabled_toolsets"])
    editor = json.loads(runner.config[f"agos-{a}--a-editor"]["agent.disabled_toolsets"])
    assert "browser" in writer and "browser" not in editor
    # Never for everyone, one member allowed: off everywhere but its profile.
    autonomy.set_rule(core, a, "writer", "browser", None)
    autonomy.set_rule(core, a, "*", "commands", "never")
    autonomy.set_rule(core, a, "editor", "commands", "do")
    assert autonomy.never_toolsets(core, a) == []
    assert autonomy.never_toolsets(core, a, "writer") == ["terminal", "code_execution"]
    assert autonomy.never_toolsets(core, a, "editor") == []
    writer = json.loads(runner.config[f"agos-{a}--a-writer"]["agent.disabled_toolsets"])
    editor = json.loads(runner.config[f"agos-{a}--a-editor"]["agent.disabled_toolsets"])
    assert {"terminal", "code_execution"} <= set(writer)
    assert "terminal" not in editor and "browser" not in writer


# ---- the guard: Full access never answers the owner's own rules ---------------------

ASK = {"action": "approve", "message": "[AGOS rule: Ask me] Send messages: send_message"}


class FakeApproval(types.ModuleType):
    """Hermes's tools.approval, as much as the guard touches."""

    def __init__(self, *, bypass: bool, answer: Any = None, present: bool = True) -> None:
        super().__init__("tools.approval")
        self.bypass, self.answer, self.present = bypass, answer, present
        self.asked: list[dict[str, Any]] = []
        self._ACTION_GATE = object()

    def is_approval_bypass_active(self) -> bool:
        return self.bypass

    def get_current_session_key(self) -> str:
        return "agent:main:agos:dm:7"

    def is_approved(self, session_key: str, pattern: str) -> bool:
        return False

    def _presence(self, callback: Any) -> tuple[Any, bool, bool, bool]:
        return None, False, self.present, False

    def _human_decision(self, spec: Any, **kwargs: Any) -> dict[str, Any]:
        self.asked.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return dict(self.answer or {})


@pytest.fixture
def hermes(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(approval: FakeApproval, *, cron: bool = False) -> FakeApproval:
        tools = types.ModuleType("tools")
        context = types.ModuleType("tools.approval_context")
        # A scheduled run: Hermes's own ctx.current_cron_execution() (its plugin API).
        running = types.SimpleNamespace(job_id="j") if cron else None
        ctx = types.SimpleNamespace(current_cron_execution=lambda: running)
        monkeypatch.setitem(agos_guard._CTX, "ctx", ctx)
        monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
        monkeypatch.setitem(sys.modules, "tools", tools)
        monkeypatch.setitem(sys.modules, "tools.approval", approval)
        monkeypatch.setitem(sys.modules, "tools.approval_context", context)
        return approval

    return install


def test_outside_full_access_hermes_own_gate_asks(hermes: Any) -> None:
    approval = hermes(FakeApproval(bypass=False))
    assert agos_guard.owner_asks(dict(ASK), "send_message") == ASK
    assert agos_guard.owner_asks(None, "send_message") is None
    assert approval.asked == []


def test_under_full_access_the_guard_still_asks_him(hermes: Any) -> None:
    yes = hermes(FakeApproval(bypass=True, answer={"approved": True}))
    assert agos_guard.owner_asks({**ASK, "rule_key": "agos:messages"}, "send_message") is None
    assert yes.asked[0]["pattern_key"] == "plugin_rule:agos:messages"
    assert yes.asked[0]["is_gateway"] is True
    no = hermes(FakeApproval(bypass=True, answer={"approved": False, "message": "BLOCKED: no"}))
    assert agos_guard.owner_asks(dict(ASK), "send_message") == {
        "action": "block",
        "message": "BLOCKED: no",
    }
    assert no.asked


def test_the_owners_rule_fails_closed(hermes: Any) -> None:
    hermes(FakeApproval(bypass=True, answer=RuntimeError("gate changed")))
    blocked = agos_guard.owner_asks(dict(ASK), "send_message")
    assert blocked is not None and blocked["action"] == "block"
    nobody = hermes(FakeApproval(bypass=True, present=False))
    blocked = agos_guard.owner_asks(dict(ASK), "send_message")
    assert blocked is not None and blocked["action"] == "block" and nobody.asked == []


def test_a_scheduled_run_never_skips_his_rule(hermes: Any) -> None:
    """cron_mode: approve lets automations run commands; his "Ask me" is refused
    there (nobody can answer), with or without Full access."""
    for bypass in (False, True):
        approval = hermes(FakeApproval(bypass=bypass, answer={"approved": True}), cron=True)
        blocked = agos_guard.owner_asks(dict(ASK), "send_message")
        assert blocked is not None and blocked["action"] == "block"
        assert approval.asked == []


def test_the_access_card_holds_hermes_deny_and_allow_rules(env: Any) -> None:  # noqa: F811
    """approvals.deny / command_allowlist on the Access card: written into the
    Co-Founder and each member; a member keeps its own "Always allow" entries."""
    from agos_core.engine import config_file

    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    add_agent(client, a, "writer")
    member = f"{a}--a-writer"
    assert client.get(f"/workspaces/{a}/access-lists").json() == {"deny": [], "allow": []}
    # The member said "Always allow" for something itself (Hermes wrote it).
    core.engine._hermes(member, "config", "set", "command_allowlist", '["podman *"]')
    r = client.put(
        f"/workspaces/{a}/access-lists",
        json={"deny": ["git push --force*", " ", "git push --force*"], "allow": ["npm test"]},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"deny": ["git push --force*"], "allow": ["npm test"]}

    def have(key: str, name: str) -> object:
        return config_file.get(config_file.read(core.engine.profile_home(key)), name)

    assert have(a, "approvals.deny") == ["git push --force*"]
    assert have(member, "approvals.deny") == ["git push --force*"]
    assert have(member, "command_allowlist") == ["npm test", "podman *"]
    # Removed from the Co-Founder's list: gone from the member's too (its own stays).
    r = client.put(f"/workspaces/{a}/access-lists", json={"deny": [], "allow": []})
    assert have(member, "command_allowlist") == ["podman *"]
    assert have(member, "approvals.deny") == []
    # A new member starts with the Co-Founder's rules.
    client.put(f"/workspaces/{a}/access-lists", json={"deny": ["rm -rf *"], "allow": []})
    add_agent(client, a, "editor")
    assert have(f"{a}--a-editor", "approvals.deny") == ["rm -rf *"]
    # The page shows them as the Access card's.
    from agos_core.actions import hermes_all_settings as hall

    assert hall.card_keys()["approvals.deny"] == "access"
    assert hall.card_keys()["command_allowlist"] == "access"


def test_the_guard_never_asks_for_memory_or_skill_writes() -> None:
    """Hermes's own write_approval gate holds them (with no YOLO bypass: H:
    tools/write_approval.py evaluate_gate), so the guard asks nothing for them, even
    from an older file that says "ask"; "Never" still blocks, other actions still ask."""
    for choice in ("ask", "allow", "do"):
        policy = {"rules": {"*": {"memory": choice, "commands": "ask"}}}
        assert agos_guard.decide(policy, "", "memory", {"action": "add"}) is None
        assert agos_guard.decide(policy, "", "skill_manage", {"action": "edit"}) is None
    command = agos_guard.decide(policy, "", "terminal", {"command": "ls"})
    assert command is not None and command["action"] == "approve"
    never = agos_guard.decide({"rules": {"*": {"memory": "never"}}}, "", "memory", {})
    assert never is not None and never["action"] == "block"
