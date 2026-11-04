"""His yes under Full access is asked OUTSIDE Hermes's hook timeout.

agos-guard used to wait for the owner inside `pre_tool_call`, which Hermes cuts at
`plugins.hook_callback_timeout` (H: hermes_cli/plugins_dispatch.py:176-180, fail-closed
block at :233-236), so 925047d set that key to 0 and switched Hermes's hang guard off
for every plugin hook. Hermes's own place for a step that may take as long as it
needs is a `tool_execution` middleware: it wraps the tool's dispatch with no timeout
(H: hermes_cli/middleware.py:143-150 `run_tool_execution_middleware`, :169-214
`_run_execution_chain`), and in the agent loop it runs BEFORE the pre_tool_call hook
(H: agent/tool_executor.py:756-818 `_run_agent_tool_execution_middleware` →
`_dispatch_authorized_once` → `_pre_tool_block`, :688-716). So the guard asks him in
the middleware, and the hook only reads his answer for that same call. Anywhere the
hook runs first (a tool called from execute_code), it still asks inside the hook,
under Hermes's own cap (600 s), and fails closed when cut.
"""

import json
import shutil
import types
from pathlib import Path
from typing import Any

import pytest
from test_access import ASK, FakeApproval, hermes  # noqa: F401 - fixture

from agos_core.engine import time_limits
from agos_core.hermes_plugin import agos_guard


class Ctx:
    def __init__(self) -> None:
        self.hooks: dict[str, Any] = {}
        self.middleware: dict[str, Any] = {}

    def register_hook(self, name: str, callback: Any) -> None:
        self.hooks[name] = callback

    def register_middleware(self, kind: str, callback: Any) -> None:
        self.middleware[kind] = callback

    def register_cli_command(self, *args: Any) -> None:
        pass

    def current_cron_execution(self) -> None:
        return None


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch, hermes: Any) -> Any:  # noqa: F811
    bridge = types.SimpleNamespace(
        agent_of_session=lambda session: "",
        register=lambda ctx: None,
        owner_decides=lambda tool, args, session: None,
    )
    monkeypatch.setattr(agos_guard.runtime, "_bridge_module", lambda: bridge)
    monkeypatch.setattr(agos_guard.policy, "_policy", lambda: {})
    monkeypatch.setattr(agos_guard.tool_checks, "fresh_read", lambda tool, task: None)
    monkeypatch.setattr(agos_guard.policy, "decide", lambda policy, agent, tool, args: dict(ASK))
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    ctx = Ctx()
    agos_guard.register(ctx)
    monkeypatch.setitem(agos_guard._CTX, "ctx", ctx)
    return ctx


def _ids(call: str = "call-1") -> dict[str, str]:
    return {"task_id": "t", "session_id": "s", "tool_call_id": call, "turn_id": "u"}


def test_the_guard_registers_hermess_tool_execution_middleware(guard: Ctx) -> None:
    assert "pre_tool_call" in guard.hooks
    assert "tool_execution" in guard.middleware


def test_his_yes_is_asked_in_the_middleware_and_the_hook_only_reads_it(
    guard: Ctx,
    hermes: Any,  # noqa: F811
) -> None:
    approval = hermes(FakeApproval(bypass=True, answer={"approved": True}))
    ran: list[dict[str, Any]] = []

    def next_call(args: dict[str, Any]) -> str:
        # Hermes's agent loop: the hook runs inside the middleware's next_call.
        verdict = guard.hooks["pre_tool_call"](tool_name="send_message", args=args, **_ids())
        ran.append({"verdict": verdict})
        return "sent"

    out = guard.middleware["tool_execution"](
        tool_name="send_message", args={"to": "x"}, next_call=next_call, **_ids()
    )
    assert out == "sent"
    assert len(approval.asked) == 1  # asked once, in the middleware
    assert ran == [{"verdict": None}]  # the hook let his yes through without asking again


def test_his_no_in_the_middleware_never_runs_the_tool(guard: Ctx, hermes: Any) -> None:  # noqa: F811
    approval = hermes(FakeApproval(bypass=True, answer={"approved": False, "message": "No."}))
    called: list[Any] = []
    out = guard.middleware["tool_execution"](
        tool_name="send_message", args={}, next_call=called.append, **_ids()
    )
    assert called == []
    assert json.loads(out) == {"error": "No."}
    assert len(approval.asked) == 1


def test_outside_full_access_the_middleware_leaves_it_to_hermess_gate(
    guard: Ctx,
    hermes: Any,  # noqa: F811
) -> None:
    approval = hermes(FakeApproval(bypass=False))
    seen: list[Any] = []

    def next_call(args: dict[str, Any]) -> str:
        seen.append(guard.hooks["pre_tool_call"](tool_name="send_message", args=args, **_ids()))
        return "ok"

    assert (
        guard.middleware["tool_execution"](
            tool_name="send_message", args={}, next_call=next_call, **_ids()
        )
        == "ok"
    )
    assert approval.asked == []
    assert seen == [ASK]  # Hermes's own gate asks (outside the hook too)


def test_an_answer_is_for_that_one_call_only(guard: Ctx, hermes: Any) -> None:  # noqa: F811
    approval = hermes(FakeApproval(bypass=True, answer={"approved": True}))
    inner: list[Any] = []

    def next_call(args: dict[str, Any]) -> str:
        # another call (other id) inside this one is asked on its own
        inner.append(
            guard.hooks["pre_tool_call"](tool_name="send_message", args={}, **_ids("call-2"))
        )
        return "ok"

    guard.middleware["tool_execution"](
        tool_name="send_message", args={}, next_call=next_call, **_ids()
    )
    assert len(approval.asked) == 2 and inner == [None]
    # and after the call, the hook asks again for the same id
    assert guard.hooks["pre_tool_call"](tool_name="send_message", args={}, **_ids()) is None
    assert len(approval.asked) == 3


def test_where_the_hook_runs_first_it_still_asks_and_fails_closed(
    guard: Ctx,
    hermes: Any,  # noqa: F811
) -> None:
    approval = hermes(FakeApproval(bypass=True, answer=RuntimeError("gate changed")))
    blocked = guard.hooks["pre_tool_call"](tool_name="send_message", args={}, **_ids())
    assert blocked is not None and blocked["action"] == "block"
    assert len(approval.asked) == 1


def test_hermess_hang_guard_is_back_for_every_other_hook() -> None:
    """Hermes's cap (600 s) instead of 0: a stuck plugin hook can't freeze a chat
    for good, and his yes is no longer under it."""
    limit = {t.key: t for t in time_limits.TIME_LIMITS}["plugins.hook_callback_timeout"]
    assert limit.default == 600
    assert time_limits.owner_defaults()["plugins.hook_callback_timeout"] == "600"
    assert "every plugin" in limit.hint


def test_hermess_middleware_has_no_timeout_while_its_hook_has_one() -> None:
    """Against the installed Hermes: a 2 s step is cut in pre_tool_call at a 1 s
    hook timeout (fail-closed), and runs to the end as tool_execution middleware."""
    python = sorted(Path.home().glob(".hermes/tools/python-3.*/bin/python3"))
    src = Path.home() / ".hermes" / "hermes-agent"
    if not python or not (src / "hermes_cli" / "middleware.py").is_file():
        pytest.skip("no Hermes install on this machine")
    import subprocess
    import tempfile

    script = f"""
import sys, time, json
sys.path.insert(0, {str(src)!r})
import hermes_bootstrap
from hermes_cli import plugins
from hermes_cli.middleware import run_tool_execution_middleware
mgr = plugins.get_plugin_manager()
plugins._resolve_hook_callback_timeout = lambda: 1.0
def slow_hook(**kw):
    time.sleep(2)
def slow_mw(**kw):
    time.sleep(2)
    return kw["next_call"](kw["args"])
mgr._hooks.setdefault("pre_tool_call", []).append(slow_hook)
mgr._middleware.setdefault("tool_execution", []).append(slow_mw)
hook = mgr.invoke_hook("pre_tool_call", tool_name="x", args={{}}, tool_call_id="c")
mw = run_tool_execution_middleware("x", {{}}, lambda a: "RAN", tool_call_id="c")
print("AGOS-PROBE " + json.dumps({{"hook": hook, "mw": mw}}))
"""
    home = Path(tempfile.mkdtemp(dir=Path.home() / ".hermes" / "cache"))
    try:
        done = subprocess.run(  # noqa: S603 - Hermes's own interpreter
            [str(python[-1]), "-I", "-"],
            input=script,
            capture_output=True,
            text=True,
            timeout=120,
            env={"HOME": str(Path.home()), "HERMES_HOME": str(home), "PATH": "/usr/bin:/bin"},
            check=False,
        )
    finally:
        shutil.rmtree(home, ignore_errors=True)
    line = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-PROBE ")]
    assert line, done.stderr[-500:]
    found = json.loads(line[-1][len("AGOS-PROBE ") :])
    assert found["hook"] and found["hook"][0]["action"] == "block"
    assert found["mw"] == "RAN"
