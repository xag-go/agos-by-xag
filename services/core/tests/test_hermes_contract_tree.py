"""The Hermes contract checker (engine/contract/tree.py) on a small Hermes-shaped
source tree made here: each kind of entry, re-exports, class members and bases,
dataclass fields, overrides, the report and the CLI. Needs no Hermes install."""

from __future__ import annotations

from pathlib import Path

import pytest

from agos_core.engine.contract import tree as contract
from agos_core.engine.contract.base import Use

FILES = {
    "hermes_cli/__init__.py": "",
    "hermes_cli/plugins.py": 'VALID_HOOKS: set[str] = {"pre_tool_call", "on_session_end"}\n',
    "hermes_cli/config.py": (
        "from .helpers import load_config as load_config\n"
        "from . import helpers\n"
        "import tools.approval as approval\n"
        "DEFAULT_CONFIG = {}\n"
        "LIMIT: int = 3\n"
        "def save_config(config, *, path=None):\n    pass\n"
    ),
    "hermes_cli/helpers.py": "def load_config(path=None):\n    return {}\n",
    "hermes_cli/lazy.py": "def __getattr__(name):\n    raise AttributeError(name)\n",
    "hermes_cli/broken.py": "def (:\n",
    "tools/__init__.py": "",
    "tools/approval.py": (
        "def _human_decision(command, reason, *, timeout=60):\n    pass\n"
        "def new_required(command, owner):\n    pass\n"
    ),
    "gateway/__init__.py": "",
    "gateway/base.py": (
        "from dataclasses import dataclass, field\n"
        "from typing import ClassVar\n"
        "class BasePlatformAdapter:\n"
        "    def __init__(self, config, platform):\n"
        "        self.config, self.platform = config, platform\n"
        "        self.queue: list = []\n"
        "    @property\n"
        "    def name(self):\n        return 'x'\n"
        "    async def send(self, chat_id, text, reply_to=None, **kwargs):\n        pass\n"
        "    alias = send\n"
        "    LIMIT = 4096\n"
        "@dataclass\n"
        "class Message:\n"
        "    text: str\n"
        "    kind: str = 'text'\n"
        "    extra: dict = field(default_factory=dict)\n"
        "    sent: bool = field(init=False)\n"
        "    needed: int = field()\n"
        "    shared: ClassVar[int] = 0\n"
        "@dataclass()\n"
        "class Reply(Message):\n"
        "    to: int = 0\n"
        "class Plain:\n"
        "    pass\n"
    ),
    "gateway/telegram.py": (
        "from gateway import base\n"
        "from gateway.base import BasePlatformAdapter\n"
        "class TelegramAdapter(base.BasePlatformAdapter):\n"
        "    def _pop_text_batch(self, chat_id, limit):\n        pass\n"
        "class Other(BasePlatformAdapter):\n"
        "    pass\n"
        "TOP = 1\n"
    ),
}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for name, text in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def _use(module: str, name: str, kind: str, **more: object) -> Use:
    return Use(module, name, kind, "engine", "a test feature", **more)  # type: ignore[arg-type]


def _why(root: Path, use: Use) -> tuple[bool, str]:
    [found] = contract.check(root, [use])
    return found.ok, found.why


def test_kinds_that_only_need_the_name(root: Path) -> None:
    assert contract.is_hermes(root) and not contract.is_hermes(root / "gateway")
    assert _why(root, _use("x", "pre_tool_call", "hook")) == (True, "")
    assert _why(root, _use("x", "post_everything", "hook"))[1] == "not one of Hermes's plugin hooks"
    assert _why(root, _use("tools.approval", "", "module"))[0]
    assert _why(root, _use("tools.gone", "", "module"))[1] == "module is gone"
    assert _why(root, _use("tools.approval", "", "text", text="_human_decision"))[0]
    assert "no longer says" in _why(root, _use("tools.approval", "", "text", text="nope"))[1]
    assert _why(root, _use("hermes_cli.config", "DEFAULT_CONFIG", "constant"))[0]
    assert _why(root, _use("hermes_cli.config", "LIMIT", "constant"))[0]
    assert _why(root, _use("hermes_cli.broken", "x", "function"))[1] == "module is gone"
    assert _why(root, _use("hermes_cli.config", "gone", "function"))[1] == "is gone"
    assert _why(root, _use("hermes_cli.lazy", "anything", "function")) == (
        True,
        "module __getattr__: not checked further",
    )


def test_functions_are_followed_through_re_exports_and_their_calls_checked(root: Path) -> None:
    assert _why(root, _use("hermes_cli.config", "load_config", "function", pos=1))[0]
    assert _why(root, _use("hermes_cli.config", "helpers", "attr"))[0]
    assert _why(root, _use("hermes_cli.config", "approval", "attr"))[0]
    assert _why(root, _use("hermes_cli.config", "save_config", "function", pos=1, kw=("path",)))[0]
    ok, why = _why(root, _use("hermes_cli.config", "save_config", "function", pos=2))
    assert not ok and "positional" in why
    ok, why = _why(root, _use("tools.approval", "new_required", "function", pos=1))
    assert not ok and "'owner'" in why
    assert _why(
        root, _use("tools.approval", "_human_decision", "function", pos=2, kw=("timeout",))
    )[0]


def test_class_members_come_from_the_class_its_init_and_its_bases(root: Path) -> None:
    tg = "gateway.telegram"
    assert _why(root, _use(tg, "TelegramAdapter._pop_text_batch", "method", pos=2))[0]
    # From the base class, reached through `base.BasePlatformAdapter`.
    assert _why(root, _use(tg, "TelegramAdapter.send", "method", pos=2, kw=("reply_to",)))[0]
    assert _why(root, _use(tg, "Other.queue", "attr"))[0]  # self.queue in __init__
    assert _why(root, _use(tg, "Other.platform", "attr"))[0]  # a tuple assignment
    assert _why(root, _use(tg, "Other.LIMIT", "constant"))[0]
    assert _why(root, _use(tg, "Other.name", "method"))[0]  # a property
    assert _why(root, _use(tg, "Other.alias", "method")) == (
        True,
        "not a def (an alias); signature not checked",
    )
    assert _why(root, _use(tg, "Other.missing", "method"))[1] == "is gone"
    assert _why(root, _use(tg, "TOP.x", "method"))[1] == "'TOP' is no longer a class"
    # A class called: its __init__.
    assert _why(root, _use(tg, "Other", "class", pos=2))[0]
    assert _why(root, _use(tg, "Other", "function", pos=2))[0]
    ok, why = _why(root, _use(tg, "Other", "class", pos=3))
    assert not ok and "positional" in why
    assert _why(root, _use(tg, "TOP", "class"))[1] == "is no longer a class"
    assert _why(root, _use(tg, "TelegramAdapter", "class"))[0]


def test_dataclass_fields_are_what_a_call_may_name(root: Path) -> None:
    gw = "gateway.base"
    assert _why(root, _use(gw, "Message", "class", kw=("text", "needed", "extra")))[0]
    ok, why = _why(root, _use(gw, "Message", "class", kw=("text",)))
    assert not ok and "'needed'" in why
    ok, why = _why(root, _use(gw, "Message", "class", kw=("text", "needed", "sent")))
    assert not ok and "sent" in why
    # Inherited fields, and the subclass's own.
    assert _why(root, _use(gw, "Reply", "class", kw=("text", "needed", "to")))[0]
    assert _why(root, _use(gw, "Plain", "class", kw=("x",))) == (
        True,
        "no __init__ / dataclass fields to check",
    )
    assert _why(root, _use(gw, "Plain", "function"))[0]


def test_an_override_must_take_what_hermes_passes(root: Path) -> None:
    send = "TelegramAdapter.send"
    tg = "gateway.telegram"
    good = _use(tg, send, "override", accepts=("chat_id", "text", "reply_to"), more=True)
    assert _why(root, good)[0]
    ok, why = _why(root, _use(tg, send, "override", accepts=("chat_id", "text")))
    assert not ok and "Hermes now passes 'reply_to'" in why
    ok, why = _why(root, _use(tg, send, "override", accepts=("chat_id", "text", "reply_to", "x")))
    assert not ok and "no parameter 'x'" in why
    ok, why = _why(root, _use(tg, send, "override", accepts=("text", "chat_id", "reply_to")))
    assert not ok and "parameter order" in why
    ok, why = _why(root, _use(tg, send, "override", accepts=("text",), more=True))
    assert not ok and "AGOS reads (text) first" in why


def test_the_report_and_the_cli(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    uses = [_use("tools.approval", "", "module"), _use("tools.gone", "", "module")]
    text = contract.report(contract.check(root, uses), root)
    assert "OK   module   tools.approval" in text
    assert "FAIL module   tools.gone — module is gone  [engine: a test feature]" in text
    assert "2 entries: 1 ok, 1 broken — DO NOT upgrade Hermes" in text
    assert contract.main([str(root / "gateway")]) == 2
    assert "not a Hermes source tree" in capsys.readouterr().err
    assert contract.main([str(root)]) in (0, 1)  # AGOS's real entries on this small tree
    assert "Hermes contract check:" in capsys.readouterr().out
