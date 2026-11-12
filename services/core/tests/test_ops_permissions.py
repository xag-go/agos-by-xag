"""Every Co-Founder action answers the three permission questions, in one list.

Who runs it: `owner_only` (with why) xor a `cofounder_domain` (OperationSpec checks it).
May agents run it: `agent_tool`, written literally in every spec's constructor call.
Does it need the owner's yes: `gate`.

The Co-Founder's kinds, their required fields and their read-vs-act rows are all
derived from these declarations: no hand-written row is left for a declared op.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agos_core.api import app  # noqa: F401 - every router, so every service's binding
from agos_core.engine import cofounder_actions, cofounder_parity, power
from agos_core.ops import catalog
from agos_core.ops import specs as specs_package
from agos_core.ops.specs import SPECS

SPEC_DIR = Path(specs_package.__file__).parent


def _constructor_calls() -> list[tuple[str, ast.Call]]:
    found: list[tuple[str, ast.Call]] = []
    for path in sorted(SPEC_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "OperationSpec"
            ):
                found.append((path.name, node))
    return found


def test_every_cofounder_action_comes_from_the_catalog() -> None:
    """Zero hand-written kind / required-fields / effect rows."""
    kinds = catalog.kinds(SPECS)
    assert set(cofounder_actions.ACTIONS) == set(kinds)
    assert {n: k.required for n, k in kinds.items()} == cofounder_actions.ACTIONS
    assert kinds == cofounder_parity.KINDS
    assert {**catalog.effects(SPECS), "bundle": "power"} == power.EFFECT
    assert len(cofounder_actions.ACTIONS) == 140


def test_no_hand_written_kind_tables_are_left() -> None:
    parity_dir = Path(cofounder_parity.__file__).parent
    for module in ("board", "workspace", "prefs"):
        assert not (parity_dir / f"{module}.py").exists(), module
    for file in ("catalog.py", "web_actions.py"):
        assert "Kind(" not in (parity_dir / file).read_text(), file
    assert not [d for d, v in cofounder_parity.DO.items() if v.startswith("do:")] or {
        d: v for d, v in cofounder_parity.DO.items() if v.startswith("do:")
    } == catalog.web_do(SPECS)


def test_every_spec_says_literally_whether_agents_may_run_it() -> None:
    calls = _constructor_calls()
    assert len(calls) >= len(SPECS)
    for file, call in calls:
        keywords = {k.arg for k in call.keywords}
        name = next((k.value for k in call.keywords if k.arg == "name"), None)
        shown = ast.unparse(name) if name is not None else "?"
        assert "agent_tool" in keywords, f"{file}: {shown} must write agent_tool= literally"
        assert "gate" in keywords, f"{file}: {shown} must write gate= literally"


def test_every_spec_answers_who_runs_it_and_its_gate() -> None:
    for spec in SPECS:
        assert (spec.owner_only is None) != (spec.cofounder_domain is None), spec.name
        assert spec.gate in ("undo", "owner", "once"), spec.name


def test_no_agent_gets_an_agos_action() -> None:
    # The owner decided (2026-11-11): agents keep ZERO agos actions, so agent_tool is
    # None on every spec. Only the owner may change this: never set one to make a test
    # or a feature pass.
    assert [s.name for s in SPECS if s.agent_tool is not None] == []
    assert catalog.agent_tools(SPECS) == []
