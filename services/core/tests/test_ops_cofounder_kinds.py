"""The Automation, Team, Library, Vision, Settings, Connector and Portability services'
Co-Founder kinds are declared once in the operation registry (ops/specs/<service>.py):
the Co-Founder's catalogue, its read-vs-act rows and its do / undo come from those
declarations, a card of one is an audit row (op_runs) and its Undo is the
registry's undo of that run. A card made before the move (no run in its result)
still undoes. Inputs keep every field the Co-Founder sent."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel
from test_cofounder_hermes import _run, _undo
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.db import op_runs, workspaces
from agos_core.db.connection import open_database
from agos_core.engine.cofounder_kind import AUTOMATIONS, SKILLS, TEAM, WORKSPACE
from agos_core.ops import catalog, cofounder
from agos_core.ops.errors import OperationNotAllowed
from agos_core.ops.registry import Registry
from agos_core.ops.spec import CofounderFields, OperationSpec
from agos_core.ops.specs import SPECS

# A few kinds of each service: declared operations now, no hand-written row.
DECLARED = {
    "save_pipeline_rule": AUTOMATIONS,
    "set_heartbeat": AUTOMATIONS,
    "watch_tree": AUTOMATIONS,
    "create_group": TEAM,
    "save_kit": TEAM,
    "set_office_look": TEAM,
    "duplicate_skill": SKILLS,
    "install_skill": SKILLS,
    "set_skill_request_limit": SKILLS,
    "set_rhythm": WORKSPACE,
    "save_vision_notes": WORKSPACE,
    "set_workspace_settings": WORKSPACE,
    "set_voice": WORKSPACE,
    "remove_tool_key": WORKSPACE,
    "export_bundle": WORKSPACE,
    "install_template": WORKSPACE,
}


def test_each_services_kinds_are_declared_operations_of_their_domain() -> None:
    domains = {s.name: s.cofounder_domain for s in SPECS}
    assert {k: domains.get(k) for k in DECLARED} == DECLARED


class Members(CofounderFields):
    title: Any
    members: Any


GROUP = OperationSpec(
    name="make_group",
    input_model=Members,
    audit_title="Group {title}",
    gate="undo",
    cofounder_domain=TEAM,
    cofounder_fields="title, members (member IDs)",
    cofounder_structured=("members",),
)
LATER = OperationSpec(
    name="later_thing",
    input_model=Members,
    audit_title="Later {title}",
    gate="owner",
    cofounder_domain=TEAM,
    cofounder_fields="title, members",
    undo_after_yes=True,
)


def test_a_kinds_structured_fields_and_an_owner_gated_undo_are_declared() -> None:
    kinds = catalog.kinds((GROUP, LATER))
    assert kinds["make_group"].structured == ("members",)
    assert kinds["make_group"].required == ("title", "members")
    assert kinds["later_thing"].gate == "owner"
    registry = Registry((GROUP, LATER))
    with pytest.raises(ValueError):  # his yes first, then Undo: it needs its undo
        registry.bind(LATER, do=lambda core, ctx, data: {})
    with pytest.raises(ValueError):  # an Undo after his yes is for an owner gate only
        OperationSpec(
            name="x",
            input_model=Members,
            audit_title="x",
            gate="once",
            cofounder_domain=TEAM,
            undo_after_yes=True,
        )


def test_the_cofounders_fields_reach_its_page_action_as_sent() -> None:
    data = Members.model_validate({"title": "Ops", "members": ["a"], "note": "extra"})
    assert data.model_dump(exclude_unset=True) == {
        "title": "Ops",
        "members": ["a"],
        "note": "extra",
    }
    assert isinstance(data, BaseModel)


@pytest.fixture
def core() -> Any:
    db = open_database(":memory:")
    for each in ("ws-a", "ws-b"):
        workspaces.insert_workspace(db, workspace_id=each, name=each, description="")
    return SimpleNamespace(db=db)


def _registry(undone: list[Any]) -> Registry:
    registry = Registry((GROUP, LATER))
    registry.bind(
        GROUP,
        do=lambda core, ctx, data: {"group": data.title},
        undo=lambda core, ctx, result: undone.append((ctx.workspace_id, result)),
    )
    registry.bind(
        LATER,
        do=lambda core, ctx, data: {"later": data.title},
        undo=lambda core, ctx, result: undone.append((ctx.workspace_id, result)),
    )
    return registry


def test_a_card_made_before_the_move_still_undoes_through_the_operation(core: Any) -> None:
    undone: list[Any] = []
    does, undoes = cofounder.adapters(_registry(undone))
    assert set(undoes) == {"make_group", "later_thing"}  # the owner-gated one too
    undoes["make_group"](core, "ws-a", {"group": "Ops"})  # its result has no run
    assert undone == [("ws-a", {"group": "Ops"})]
    result = does["make_group"](core, "ws-a", {"title": "Ops", "members": []})
    undoes["make_group"](core, "ws-a", result)
    assert undone[-1] == ("ws-a", {"group": "Ops"})
    row = op_runs.get(core.db, int(result[cofounder.RUN_KEY]))
    assert row is not None and row["status"] == "undone"


def test_a_card_without_its_run_stays_inside_its_workspace(core: Any) -> None:
    undone: list[Any] = []
    _does, undoes = cofounder.adapters(_registry(undone))
    with pytest.raises(OperationNotAllowed):
        undoes["make_group"](core, "", {"group": "Ops"})
    assert undone == []


def test_a_declared_kinds_card_is_an_audit_row_and_its_undo_marks_it(
    env: Any,  # noqa: F811
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    [card] = _run(core, a, {"do": "set_skill_request_limit", "limit": 7})
    assert card["status"] == "done" and card["canUndo"], card
    run = op_runs.latest(core.db, "set_skill_request_limit")
    assert run is not None
    assert (run["actor"], run["status"], run["workspace_id"]) == ("cofounder", "done", a)
    _undo(core, a, card)
    again = op_runs.get(core.db, int(run["id"]))
    assert again is not None and again["status"] == "undone"
