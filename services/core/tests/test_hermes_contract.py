"""The Hermes contract (engine/hermes_contract.py): every Hermes internal AGOS uses is
on one list; the checker reads a Hermes source tree and says what no longer fits;
at run time a broken one is said out loud (Log + the owner's phone), once, and
AGOS keeps failing closed."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import textwrap
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from channels_rig import env, fake_telegram  # noqa: F401 - fixtures

from agos_core.engine import hermes_contract as hc
from agos_core.hermes_plugin import agos_guard
from agos_core.hermes_plugin.agos_guard import contract as plugin_contract

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"
REPO = Path(__file__).resolve().parents[3]
ROOTS = "|".join(hc.HERMES_ROOTS)


def _sources() -> dict[str, str]:
    """AGOS's code, the helper scripts it runs in Hermes's runtime (strings) included."""
    return {
        p.relative_to(SRC).as_posix(): p.read_text()
        for p in SRC.rglob("*.py")
        if not p.relative_to(SRC).as_posix().startswith("db/migrations")
        and p.name != "hermes_contract.py"
        and not p.relative_to(SRC).as_posix().startswith("engine/contract/")  # its entries
    }


def _without_comments(text: str) -> str:
    """The code without its # comments (they may name Hermes's own internals)."""
    import io
    import tokenize

    lines = text.splitlines(keepends=True)
    for tok in reversed(list(tokenize.generate_tokens(io.StringIO(text).readline))):
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col] + "\n"
    return "".join(lines)


def _on_list(name: str) -> bool:
    return name in hc.KEYS or any(k.startswith(name + ".") for k in hc.KEYS)


# ---- the list is complete ------------------------------------------------------------


def test_every_hermes_import_is_on_the_contract() -> None:
    """`from <hermes module> import x`, `import <hermes module>` and
    importlib.import_module("<hermes module>") anywhere in AGOS (helper scripts too)."""
    from_import = re.compile(
        rf"^[ \t]*from ((?:{ROOTS})(?:\.\w+)*) import (\([^)]*\)|[^\n]*)", re.M
    )
    plain = re.compile(
        rf"(?:^[ \t]*import ((?:{ROOTS})(?:\.\w+)+)|import_module\(\s*[\"']((?:{ROOTS})(?:\.\w+)*)[\"'])",
        re.M,
    )
    missing: set[tuple[str, str]] = set()
    seen = 0
    for rel, text in _sources().items():
        for m in from_import.finditer(text):
            names = re.sub(r"#[^\n]*", "", m[2]).strip("() \n").replace("\n", " ").split(",")
            for raw in names:
                name = raw.strip().split(" as ")[0].strip()
                if name and name != "*":
                    seen += 1
                    if not _on_list(f"{m[1]}.{name}"):
                        missing.add((rel, f"{m[1]}.{name}"))
        for m in plain.finditer(text):
            seen += 1
            if not _on_list(m[1] or m[2]):
                missing.add((rel, m[1] or m[2]))
    assert seen > 60  # the scan found AGOS's imports (not a broken regex)
    assert not missing, f"Hermes names used but not in hermes_contract.CONTRACT: {sorted(missing)}"


def test_every_private_hermes_name_is_on_the_contract() -> None:
    """A Hermes `_private` name AGOS reads (x._name, getattr(x, "_name")) must be on
    the list; AGOS's own private names (defined in agos_core) and its `_agos_*`
    marks on Hermes's objects are not Hermes's."""
    texts = {rel: _without_comments(t) for rel, t in _sources().items()}
    own: set[str] = set()
    for t in texts.values():
        own |= set(re.findall(r"(?:def|class)\s+(_\w+)", t))
        own |= set(re.findall(r"^\s*(_\w+)\s*(?::[^=\n]*)?=", t, re.M))
        own |= set(re.findall(r"\bself\.(_\w+)\s*(?::[^=\n]*)?=[^=]", t))
    last = {k.rsplit(".", 1)[-1] for k in hc.KEYS}
    used: dict[str, set[str]] = {}
    for rel, t in texts.items():
        for m in re.finditer(r"\b(\w+)\.(_[A-Za-z]\w*)\b", t):
            if m[1] not in ("self", "cls") and not m[2].startswith("__"):
                used.setdefault(m[2], set()).add(rel)
        for m in re.finditer(r"""(?:getattr|hasattr)\(\s*[\w.()]+\s*,\s*["'](_\w+)["']""", t):
            used.setdefault(m[1], set()).add(rel)
    off = {
        name: sorted(where)
        for name, where in used.items()
        if name not in own and not name.startswith("_agos") and name not in last
    }
    assert {"_human_decision", "_presence", "_append_event"} <= set(used)
    assert not off, f"Hermes private names used but not in hermes_contract.CONTRACT: {off}"


def test_every_reported_name_is_a_contract_entry() -> None:
    """What the plugin says broke is the contract's own name for it."""
    called = re.compile(
        r"""(?:_guard|\bbroken|_broken|\bmissing|_missing|guard)\(\s*["']([\w.]+)["']"""
        r"""|_name_of\(\s*\w+,\s*["']([\w.]+)["']"""
    )
    names = []
    for p in (SRC / "hermes_plugin" / "agos_guard").glob("*.py"):
        names += [a or b for a, b in called.findall(p.read_text())]
    assert len(names) > 30
    assert [n for n in names if n not in hc.KEYS] == []


def test_each_entry_says_what_it_is_and_what_breaks() -> None:
    keys = [(u.key, u.kind) for u in hc.CONTRACT]
    assert len(keys) == len(set(keys))
    for use in hc.CONTRACT:
        assert use.kind in hc.KINDS, use
        assert use.module.split(".")[0] in hc.HERMES_ROOTS, use
        assert use.area and use.feature, use
    # the incident behind all this: the guard's call into Hermes's approval gate
    gate = next(u for u in hc.CONTRACT if u.key == "tools.approval._human_decision")
    assert gate.area == "guard" and "Ask me" in gate.feature


# ---- the checker, on the installed Hermes ------------------------------------------


INSTALLED = hc.default_root()


@pytest.mark.skipif(not hc.is_hermes(INSTALLED), reason="no Hermes source installed here")
def test_the_installed_hermes_has_everything_agos_uses(capsys: pytest.CaptureFixture[str]) -> None:
    findings = hc.check(INSTALLED)
    broken = [f"{f.use.key}: {f.why}" for f in findings if not f.ok]
    assert broken == []
    assert len(findings) == len(hc.CONTRACT) > 200
    assert hc.main([str(INSTALLED)]) == 0
    out = capsys.readouterr().out
    assert f"{len(findings)} entries: {len(findings)} ok, 0 broken" in out


def test_the_cli_runs_as_a_module() -> None:
    if not hc.is_hermes(INSTALLED):
        pytest.skip("no Hermes source installed here")
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed argv
        [sys.executable, "-m", "agos_core.engine.hermes_contract", str(INSTALLED)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert "0 broken" in done.stdout


# ---- the checker, on made-up Hermes trees -------------------------------------------


GOOD = {
    "hermes_cli/__init__.py": "",
    "hermes_cli/plugins.py": """
        VALID_HOOKS = {"pre_tool_call", "post_tool_call"}

        class PluginContext:
            def register_hook(self, name, callback):
                pass
    """,
    "tools/__init__.py": "",
    "tools/approval.py": """
        _ACTION_GATE = object()

        def _human_decision(spec, *, command, description, pattern_key, warnings=None):
            pass

        def is_approved(session_key, pattern):
            return False
    """,
    "gateway/__init__.py": "",
    "gateway/platforms/__init__.py": "",
    "gateway/platforms/base.py": """
        from dataclasses import dataclass

        @dataclass
        class SendResult:
            success: bool
            error: str | None = None

        class BasePlatformAdapter:
            def __init__(self, config, platform):
                self.config = config

            async def send(self, chat_id, content, reply_to=None, metadata=None):
                pass
    """,
}

USES = (
    hc._u("hermes_cli.plugins", "pre_tool_call", "hook", "hooks", "the guard"),
    hc._u("hermes_cli.plugins", "PluginContext.register_hook", "method", "plugin", "hooks", pos=2),
    hc._u("tools.approval", "_ACTION_GATE", "constant", "guard", "Ask me"),
    hc._u(
        "tools.approval",
        "_human_decision",
        "function",
        "guard",
        "Ask me: his Allow / Deny card",
        pos=1,
        kw="command description pattern_key warnings",
    ),
    hc._u("tools.approval", "is_approved", "function", "guard", "Ask me", pos=2),
    hc._u("gateway.platforms.base", "SendResult", "class", "bridge", "sends", kw="success error"),
    hc._u("gateway.platforms.base", "BasePlatformAdapter", "class", "bridge", "chats", pos=2),
    hc._u("gateway.platforms.base", "BasePlatformAdapter.config", "attr", "bridge", "chats"),
    hc._u(
        "gateway.platforms.base",
        "BasePlatformAdapter.send",
        "override",
        "bridge",
        "chats",
        accepts="chat_id content reply_to metadata",
    ),
)


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text))
    return tmp_path


def _changed(tmp_path: Path, rel: str, old: str, new: str) -> Path:
    files = dict(GOOD)
    assert old in files[rel]
    files[rel] = files[rel].replace(old, new)
    return _tree(tmp_path, files)


def _broken(root: Path) -> dict[str, str]:
    return {f.use.key: f.why for f in hc.check(root, USES) if not f.ok}


def test_a_tree_with_everything_passes(tmp_path: Path) -> None:
    assert _broken(_tree(tmp_path, GOOD)) == {}


def test_a_removed_function_fails(tmp_path: Path) -> None:
    root = _changed(tmp_path, "tools/approval.py", "def is_approved(", "def is_approved_now(")
    assert _broken(root) == {"tools.approval.is_approved": "is gone"}


def test_a_renamed_keyword_fails(tmp_path: Path) -> None:
    """The v0.22 incident: Hermes dropped `warnings`, AGOS still passed it."""
    root = _changed(tmp_path, "tools/approval.py", "pattern_key, warnings=None", "pattern_key")
    assert _broken(root) == {
        "tools.approval._human_decision": "no parameter 'warnings' any more (AGOS passes it)"
    }


def test_a_keyword_hermes_takes_as_kwargs_still_fits(tmp_path: Path) -> None:
    root = _changed(tmp_path, "tools/approval.py", "pattern_key, warnings=None", "**kwargs")
    assert _broken(root) == {}


def test_a_new_required_parameter_fails(tmp_path: Path) -> None:
    root = _changed(
        tmp_path,
        "tools/approval.py",
        "pattern_key, warnings=None",
        "pattern_key, gate, warnings=None",
    )
    assert _broken(root) == {
        "tools.approval._human_decision": "new required parameter 'gate' AGOS doesn't pass"
    }
    root = _changed(
        tmp_path,
        "tools/approval.py",
        "def is_approved(session_key, pattern)",
        "def is_approved(a, b, c)",
    )
    assert "new required parameter 'c'" in _broken(root)["tools.approval.is_approved"]


def test_a_missing_class_fails(tmp_path: Path) -> None:
    root = _changed(tmp_path, "gateway/platforms/base.py", "class SendResult:", "class Sent:")
    assert _broken(root) == {"gateway.platforms.base.SendResult": "is gone"}


def test_a_dataclass_field_gone_fails(tmp_path: Path) -> None:
    root = _changed(tmp_path, "gateway/platforms/base.py", "    error: str | None = None\n", "")
    assert "no parameter 'error'" in _broken(root)["gateway.platforms.base.SendResult"]


def test_an_attribute_gone_and_a_constant_gone_fail(tmp_path: Path) -> None:
    root = _changed(
        tmp_path, "gateway/platforms/base.py", "self.config = config", "self.cfg = config"
    )
    assert _broken(root) == {"gateway.platforms.base.BasePlatformAdapter.config": "is gone"}
    root = _changed(tmp_path, "tools/approval.py", "_ACTION_GATE = object()", "GATE = object()")
    assert _broken(root) == {"tools.approval._ACTION_GATE": "is gone"}


def test_a_method_agos_replaces_must_keep_its_parameters(tmp_path: Path) -> None:
    root = _changed(
        tmp_path,
        "gateway/platforms/base.py",
        "async def send(self, chat_id, content, reply_to=None, metadata=None)",
        "async def send(self, chat_id, content, reply_to=None, metadata=None, silent=False)",
    )
    assert (
        "Hermes now passes 'silent'"
        in _broken(root)["gateway.platforms.base.BasePlatformAdapter.send"]
    )


def test_a_hook_hermes_dropped_fails(tmp_path: Path) -> None:
    root = _changed(tmp_path, "hermes_cli/plugins.py", '"pre_tool_call", ', "")
    assert _broken(root) == {"hermes_cli.plugins.pre_tool_call": "not one of Hermes's plugin hooks"}


def test_a_module_gone_fails(tmp_path: Path) -> None:
    files = {k: v for k, v in GOOD.items() if k != "tools/approval.py"}
    broken = _broken(_tree(tmp_path, files))
    assert set(broken) == {u.key for u in USES if u.module == "tools.approval"}
    assert set(broken.values()) == {"module is gone"}


def test_the_report_says_what_breaks_and_the_cli_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _changed(tmp_path, "tools/approval.py", "pattern_key, warnings=None", "pattern_key")
    monkeypatch.setattr(hc, "CONTRACT", USES)
    monkeypatch.setattr(hc.check, "__defaults__", (None, USES))
    assert hc.main([str(root)]) == 1
    out = capsys.readouterr().out
    assert "FAIL function tools.approval._human_decision" in out
    assert "[guard: Ask me: his Allow / Deny card]" in out
    assert "1 broken — DO NOT upgrade Hermes" in out
    assert hc.main([str(tmp_path / "nowhere")]) == 2


def test_the_upgrade_gate_script_is_read_only() -> None:
    """scripts/hermes-upgrade-check.sh: a temporary worktree, never a checkout of the
    installed Hermes; the doc makes it the first step of an upgrade."""
    script = (REPO / "scripts" / "hermes-upgrade-check.sh").read_text()
    assert "worktree add --quiet --detach" in script and "worktree remove --force" in script
    assert not re.search(r"git -C \"\$repo\" (checkout|switch|reset|pull)", script)
    assert "agos_core.engine.hermes_contract" in script
    doc = (REPO / "docs" / "hermes-upgrade.md").read_text()
    assert doc.index("scripts/hermes-upgrade-check.sh") < doc.index("## 1.")
    assert "**stop**" in doc


# ---- at run time: AGOS's core ------------------------------------------------------


@pytest.fixture
def told(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str, str | None]]]:
    hc.reset()
    heard: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(hc, "notifiers", [lambda *a: heard.append(a)])
    yield heard
    hc.reset()


def test_the_core_tells_a_broken_name_once(
    told: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="agos.hermes_contract"):
        assert hc.broken("tools.approval._human_decision", "TypeError: boom", "ws1") is True
        assert hc.broken("tools.approval._human_decision", "TypeError: again", "ws1") is False
    assert told == [("tools.approval._human_decision", "TypeError: boom", "ws1")]
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1 and lines[0].startswith(
        "Hermes contract broken: tools.approval._human_decision (workspace ws1)"
    )


def test_a_helper_scripts_failure_names_the_entry(told: list[Any]) -> None:
    out = textwrap.dedent(
        """
        Traceback (most recent call last):
          File "<string>", line 3, in <module>
        ImportError: cannot import name '_visible_providers' from 'hermes_cli.tools_config' (/x.py)
        """
    )
    done = subprocess.CompletedProcess(["python"], 1, stdout="", stderr=out)
    assert hc.ran(done) == ["hermes_cli.tools_config._visible_providers"]
    assert hc.ran(subprocess.CompletedProcess(["python"], 0, stdout="ok", stderr="")) == []
    ok_but_said = subprocess.CompletedProcess(
        ["python"], 0, stdout=f"{hc.SCRIPT_MARK}cron.jobs.pause_job TypeError: x\n", stderr=""
    )
    assert hc.ran(ok_but_said) == ["cron.jobs.pause_job"]
    gone = subprocess.CompletedProcess(
        ["python"], 1, stdout="", stderr="ModuleNotFoundError: No module named 'cron.executions'"
    )
    assert hc.ran(gone) == ["cron.executions"]
    other = subprocess.CompletedProcess(["python"], 1, stdout="", stderr="ValueError: bad json")
    assert hc.ran(other) == []
    assert [t[0] for t in told] == [
        "hermes_cli.tools_config._visible_providers",
        "cron.jobs.pause_job",
        "cron.executions",
    ]


# ---- at run time: inside Hermes (the agos-guard plugin) ------------------------------


@pytest.fixture
def plugin_told(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    plugin_contract.reset()
    heard: list[tuple[str, str]] = []
    monkeypatch.setattr(plugin_contract, "_tell", lambda name, detail: heard.append((name, detail)))

    class Now:
        def __init__(self, target: Any, args: tuple[Any, ...], **_: Any) -> None:
            self.target, self.args = target, args

        def start(self) -> None:
            self.target(*self.args)

    monkeypatch.setattr("threading.Thread", Now)
    yield heard
    plugin_contract.reset()


def test_the_plugin_tells_a_broken_name_once(
    plugin_told: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="agos_guard"):
        for _ in range(3):
            with plugin_contract.guard("tools.approval.is_approved"):
                raise TypeError("is_approved() takes 1 positional argument but 2 were given")
    assert [n for n, _ in plugin_told] == ["tools.approval.is_approved"]
    assert [r.getMessage().split(" (")[0] for r in caplog.records] == [
        "Hermes contract broken: tools.approval.is_approved"
    ]


def test_only_contract_shaped_failures_count(plugin_told: list[Any]) -> None:
    """A network error or Hermes's own refusal isn't a broken contract; outside
    Hermes (tests) a Hermes module that can't be imported isn't either."""
    with plugin_contract.guard("gateway.status.read_runtime_status"):
        raise OSError("connection refused")
    with plugin_contract.guard("gateway.status.read_runtime_status"):
        raise ImportError("No module named 'gateway'")
    assert plugin_contract.missing("x.y", None) is None
    assert plugin_told == []
    assert plugin_contract.name_of(
        ImportError("cannot import name '_find_skill' from 'tools.skill_manager_tool'"), "z"
    ) == ("tools.skill_manager_tool._find_skill")
    assert plugin_contract.name_of(RuntimeError("x"), "fallback") == "fallback"


def test_a_broken_gate_still_blocks_and_is_told(
    plugin_told: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hermes's approval gate changed (the v0.22 incident): the owner's 'Ask me' is
    still a block, never an allow — and now he hears why, once."""

    class Changed(types.ModuleType):
        _ACTION_GATE = object()

        def is_approval_bypass_active(self) -> bool:
            return True

        def get_current_session_key(self) -> str:
            return "agent:main:agos:dm:7"

        def is_approved(self, session_key: str, pattern: str) -> bool:
            return False

        def _presence(self, callback: Any) -> tuple[Any, bool, bool, bool]:
            return None, False, True, False

        def _human_decision(self, spec: Any, *, command: str, gate_v2: Any) -> dict[str, Any]:
            return {"approved": True}

    approval = Changed("tools.approval")
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "tools.approval", approval)
    monkeypatch.setitem(
        agos_guard._CTX, "ctx", types.SimpleNamespace(current_cron_execution=lambda: None)
    )
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)
    ask = {"action": "approve", "message": "[AGOS rule: Ask me] Send messages: send_message"}
    for _ in range(2):
        blocked = agos_guard.owner_asks(dict(ask), "send_message")
        assert blocked is not None and blocked["action"] == "block"
    assert [n for n, _ in plugin_told] == ["tools.approval._human_decision"]
    # A gate that's gone: blocked too, and its own name told.
    del Changed._ACTION_GATE
    assert agos_guard.owner_asks(dict(ask), "send_message")["action"] == "block"  # type: ignore[index]
    assert [n for n, _ in plugin_told][-1] == "tools.approval._ACTION_GATE"


def test_a_skill_check_that_broke_refuses_nothing_new(
    plugin_told: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """shared_skill falls back to Hermes's own checks (as before) and says so."""
    skills = types.ModuleType("tools.skill_manager_tool")
    skills._find_skill = lambda name, extra: None  # type: ignore[attr-defined]
    utils = types.ModuleType("agent.skill_utils")
    utils.is_external_skill_path = lambda p: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tools", types.ModuleType("tools"))
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "tools.skill_manager_tool", skills)
    monkeypatch.setitem(sys.modules, "agent.skill_utils", utils)
    assert agos_guard.shared_skill("x", {"action": "edit"}) is False
    assert [n for n, _ in plugin_told] == ["tools.skill_manager_tool._find_skill"]


# ---- the owner hears it: the Log and his phone -------------------------------------


def test_a_break_inside_hermes_reaches_the_log_and_his_phone_once(env: Any) -> None:  # noqa: F811
    from hermes_channel_rig import _hermes_bot

    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    body = {
        "name": "tools.approval._human_decision",
        "error": "TypeError: _human_decision() got an unexpected keyword argument 'warnings'",
        "gateway": "4242:1700000000",
    }
    headers = {"authorization": f"Bearer {key}"}
    first = client.post(f"/hermes-bridge/{ws}/contract-broken", json=body, headers=headers)
    again = client.post(f"/hermes-bridge/{ws}/contract-broken", json=body, headers=headers)
    assert first.json() == {"ok": True, "told": True}
    assert again.json() == {"ok": True, "told": False}
    refused = client.post(f"/hermes-bridge/{ws}/contract-broken", json=body, headers={})
    assert refused.status_code == 401

    logged = core.db.execute(
        "SELECT level, text, workspace_id FROM system_log WHERE text LIKE 'Hermes contract broken:%'"
    ).fetchall()
    assert len(logged) == 1 and logged[0]["level"] == "error" and logged[0]["workspace_id"] == ws
    assert "tools.approval._human_decision" in logged[0]["text"]
    said = core.db.execute(
        "SELECT m.body FROM message_rows m JOIN chats c ON c.id = m.chat_id"
        " WHERE c.workspace_id = ? AND m.body LIKE '%contract broken%'",
        (ws,),
    ).fetchall()
    assert len(said) == 1 and "Ask me" in said[0]["body"]
    phone = core.db.execute(
        "SELECT body FROM channel_outbox WHERE body LIKE '%Hermes contract broken%'"
    ).fetchall()
    assert len(phone) == 1

    # The next gateway start: told again (once).
    restarted = {**body, "gateway": "4343:1700000500"}
    assert client.post(
        f"/hermes-bridge/{ws}/contract-broken", json=restarted, headers=headers
    ).json()["told"]


def test_a_break_in_a_helper_script_reaches_the_owner(env: Any) -> None:  # noqa: F811
    _client, core, _fake, _tg, ws = env
    hc.reset()
    try:
        done = subprocess.CompletedProcess(
            ["python"],
            1,
            stdout="",
            stderr="AttributeError: module 'hermes_cli.webhook' has no attribute "
            "'_mutate_subscriptions'",
        )
        assert hc.ran(done, ws) == ["hermes_cli.webhook._mutate_subscriptions"]
        assert hc.ran(done, ws) == ["hermes_cli.webhook._mutate_subscriptions"]  # not told again
    finally:
        hc.reset()
    said = core.db.execute(
        "SELECT m.body FROM message_rows m JOIN chats c ON c.id = m.chat_id"
        " WHERE c.workspace_id = ? AND m.body LIKE '%contract broken%'",
        (ws,),
    ).fetchall()
    assert len(said) == 1 and "webhook" in said[0]["body"]
    logged = core.db.execute(
        "SELECT count(*) FROM system_log WHERE text LIKE 'Hermes contract broken: hermes_cli.webhook%'"
    ).fetchone()[0]
    assert logged == 1
