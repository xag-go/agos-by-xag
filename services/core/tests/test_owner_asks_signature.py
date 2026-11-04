"""The owner's "Ask me" card on Full access goes through Hermes's own
tools/approval.py `_human_decision`. AGOS passes only what that function takes in
the installed Hermes: v0.22.2 dropped `warnings`, and passing it raised a TypeError
that blocked the action with no card."""

import ast
import os
from pathlib import Path

import pytest

from agos_core.hermes_plugin import agos_guard

PLUGIN = Path(agos_guard.owner_approval.__file__)  # owner_asks lives there
HERMES = Path(os.environ.get("HERMES_AGENT_SRC") or Path.home() / ".hermes" / "hermes-agent")


def _params_of_hermes() -> set[str]:
    source = HERMES / "tools" / "approval.py"
    if not source.is_file():
        pytest.skip(f"no Hermes source at {HERMES}")
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_human_decision":
            args = node.args
            return {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    raise AssertionError("Hermes has no tools/approval.py _human_decision any more")


def _keywords_agos_passes() -> set[str]:
    tree = ast.parse(PLUGIN.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "_accepted")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "_accepted")
            )
            and node.args
            and ast.unparse(node.args[0]) == "approval._human_decision"
        ):
            return {k.arg for k in node.keywords if k.arg}
    raise AssertionError("owner_asks no longer filters its arguments through _accepted")


def test_every_argument_agos_passes_is_one_hermes_takes() -> None:
    hermes = _params_of_hermes()
    passed = _keywords_agos_passes()
    assert "warnings" not in passed
    assert passed <= hermes, f"Hermes doesn't take: {sorted(passed - hermes)}"


def test_a_dropped_parameter_is_left_out_not_a_type_error() -> None:
    def human_decision(spec: object, *, command: str, session_key: str) -> dict[str, str]:
        return {"command": command, "session_key": session_key}

    kwargs = agos_guard._accepted(human_decision, command="ls", session_key="k", warnings=[])
    assert kwargs == {"command": "ls", "session_key": "k"}
    assert human_decision(None, **kwargs) == {"command": "ls", "session_key": "k"}


def test_a_function_taking_any_keyword_gets_them_all() -> None:
    def flexible(spec: object, **kw: object) -> dict[str, object]:
        return kw

    assert agos_guard._accepted(flexible, a=1, b=2) == {"a": 1, "b": 2}
