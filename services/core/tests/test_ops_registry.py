"""The operation registry (agos_core/ops): one declaration of an operation (its
input model, gate, audit title, do and undo) is what every caller runs: the API,
the Co-Founder's agos_action kind and the agent tool. Each run is an audit row
(op_runs); an idempotency key makes a retry return the first result."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from agos_core.db import op_runs, workspaces
from agos_core.db.connection import open_database
from agos_core.ops import catalog, cofounder
from agos_core.ops.errors import OperationNotAllowed, UnknownOperation
from agos_core.ops.operation import AGENT, COFOUNDER, OWNER, Actor
from agos_core.ops.registry import Registry
from agos_core.ops.spec import OperationSpec


class NewNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    text: str


@pytest.fixture
def core() -> Any:
    db = open_database(":memory:")
    db.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, ws TEXT, text TEXT)")
    for ws in ("ws-a", "ws-b"):
        workspaces.insert_workspace(db, workspace_id=ws, name=ws, description="")
    return SimpleNamespace(db=db)


NOTE = OperationSpec(
    name="add_note",
    input_model=NewNote,
    audit_title="Add the note {text}",
    gate="undo",
    effect="work",
    web_action="addNote",
    cofounder_domain="workspace",
    cofounder_fields="text",
    agent_tool="Adds a note to the workspace.",
    idempotent=True,
)
OWNER_THING = OperationSpec(
    name="owner_thing",
    input_model=NewNote,
    audit_title="Owner thing",
    gate="once",
    web_action="ownerThing",
    owner_only="his alone",
)


def _registry() -> tuple[Registry, list[str]]:
    calls: list[str] = []
    registry = Registry((NOTE, OWNER_THING))

    def add(core: Any, ctx: Any, data: NewNote) -> dict[str, Any]:
        calls.append(f"{ctx.actor.label}:{data.text}")
        cursor = core.db.execute(
            "INSERT INTO notes (ws, text) VALUES (?, ?)", (data.workspace_id, data.text)
        )
        return {"note_id": cursor.lastrowid}

    def remove(core: Any, ctx: Any, result: dict[str, Any]) -> None:
        core.db.execute("DELETE FROM notes WHERE id = ?", (result["note_id"],))

    registry.bind(NOTE, do=add, undo=remove)
    registry.bind(OWNER_THING, do=lambda core, ctx, data: {"ok": True})
    return registry, calls


def _notes(core: Any) -> list[str]:
    return [r[0] for r in core.db.execute("SELECT text FROM notes ORDER BY id").fetchall()]


def test_a_run_validates_its_input_does_it_and_writes_its_audit_row(core: Any) -> None:
    registry, calls = _registry()
    result = registry.run(
        core, "add_note", {"workspace_id": "ws-a", "text": "hi"}, actor=OWNER, workspace_id="ws-a"
    )
    assert _notes(core) == ["hi"]
    assert calls == ["owner:hi"]
    run = op_runs.latest(core.db, "add_note")
    assert run is not None
    assert (run["status"], run["actor"], run["title"], run["workspace_id"]) == (
        "done",
        "owner",
        "Add the note hi",
        "ws-a",
    )
    assert op_runs.result_of(run) == result
    with pytest.raises(ValidationError):
        registry.run(core, "add_note", {"workspace_id": "ws-a", "txt": "x"}, actor=OWNER)
    with pytest.raises(UnknownOperation):
        registry.run(core, "nope", {}, actor=OWNER)


def test_a_failed_run_is_audited_as_failed_and_raises(core: Any) -> None:
    registry = Registry((OWNER_THING,))

    def broken(core: Any, ctx: Any, data: NewNote) -> dict[str, Any]:
        raise RuntimeError("Hermes said no")

    registry.bind(OWNER_THING, do=broken)
    with pytest.raises(RuntimeError, match="Hermes said no"):
        registry.run(core, "owner_thing", {"workspace_id": "ws-a", "text": "x"}, actor=OWNER)
    run = op_runs.latest(core.db, "owner_thing")
    assert run is not None and run["status"] == "failed" and "Hermes said no" in run["error"]


def test_the_same_idempotency_key_returns_the_first_result_without_doing_it_again(
    core: Any,
) -> None:
    registry, calls = _registry()
    data = {"workspace_id": "ws-a", "text": "once"}
    first = registry.run(core, "add_note", data, actor=OWNER, idempotency_key="k-1")
    again = registry.run(core, "add_note", data, actor=OWNER, idempotency_key="k-1")
    other = registry.run(core, "add_note", data, actor=OWNER, idempotency_key="k-2")
    assert first == again != other
    assert _notes(core) == ["once", "once"]
    assert len(calls) == 2


def test_a_double_click_running_at_the_same_time_does_the_work_once(core: Any) -> None:
    registry = Registry((NOTE,))
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def slow(core: Any, ctx: Any, data: NewNote) -> dict[str, Any]:
        calls.append(1)
        started.set()
        release.wait(5)
        return {"note_id": len(calls)}

    registry.bind(NOTE, do=slow, undo=lambda core, ctx, result: None)
    results: list[dict[str, Any]] = []
    data = {"workspace_id": "ws-a", "text": "x"}

    def click() -> None:
        results.append(registry.run(core, "add_note", data, actor=OWNER, idempotency_key="dbl"))

    first = threading.Thread(target=click)
    first.start()
    started.wait(5)
    second = threading.Thread(target=click)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert calls == [1]
    assert results == [{"note_id": 1}, {"note_id": 1}]


def test_a_failed_first_try_can_be_retried_with_the_same_key(core: Any) -> None:
    registry = Registry((NOTE,))
    tries: list[int] = []

    def flaky(core: Any, ctx: Any, data: NewNote) -> dict[str, Any]:
        tries.append(1)
        if len(tries) == 1:
            raise ConnectionError("Hermes down")
        return {"note_id": 9}

    registry.bind(NOTE, do=flaky, undo=lambda core, ctx, result: None)
    data = {"workspace_id": "ws-a", "text": "x"}
    with pytest.raises(ConnectionError):
        registry.run(core, "add_note", data, actor=OWNER, idempotency_key="r")
    assert registry.run(core, "add_note", data, actor=OWNER, idempotency_key="r") == {"note_id": 9}


def test_a_key_given_to_an_operation_without_keys_is_refused(core: Any) -> None:
    registry, _ = _registry()
    with pytest.raises(ValueError, match="idempotency"):
        registry.run(
            core,
            "owner_thing",
            {"workspace_id": "ws-a", "text": "x"},
            actor=OWNER,
            idempotency_key="k",
        )


def test_owner_only_operations_refuse_the_cofounder_and_agents(core: Any) -> None:
    registry, _ = _registry()
    data = {"workspace_id": "ws-a", "text": "x"}
    for actor in (COFOUNDER, AGENT("writer")):
        with pytest.raises(OperationNotAllowed):
            registry.run(core, "owner_thing", data, actor=actor, workspace_id="ws-a")
    assert registry.run(core, "owner_thing", data, actor=OWNER) == {"ok": True}


def test_a_cofounder_or_agent_run_stays_inside_its_workspace(core: Any) -> None:
    registry, calls = _registry()
    other = {"workspace_id": "ws-b", "text": "x"}
    with pytest.raises(OperationNotAllowed):
        registry.run(core, "add_note", other, actor=COFOUNDER, workspace_id="ws-a")
    with pytest.raises(OperationNotAllowed):
        registry.run(core, "add_note", other, actor=AGENT("writer"))  # no workspace given
    assert calls == []
    registry.run(core, "add_note", other, actor=AGENT("writer"), workspace_id="ws-b")
    assert calls == ["agent:writer:x"]


def test_a_reused_key_from_another_workspace_is_refused(core: Any) -> None:
    registry, _ = _registry()
    registry.run(
        core,
        "add_note",
        {"workspace_id": "ws-a", "text": "x"},
        actor=COFOUNDER,
        workspace_id="ws-a",
        idempotency_key="same",
    )
    with pytest.raises(OperationNotAllowed):
        registry.run(
            core,
            "add_note",
            {"workspace_id": "ws-b", "text": "x"},
            actor=COFOUNDER,
            workspace_id="ws-b",
            idempotency_key="same",
        )


def test_undo_runs_the_operations_own_undo_and_marks_the_run(core: Any) -> None:
    registry, _ = _registry()
    registry.run(core, "add_note", {"workspace_id": "ws-a", "text": "x"}, actor=OWNER)
    run = op_runs.latest(core.db, "add_note")
    assert run is not None
    registry.undo(core, int(run["id"]), actor=OWNER)
    assert _notes(core) == []
    again = op_runs.latest(core.db, "add_note")
    assert again is not None and again["status"] == "undone"
    with pytest.raises(OperationNotAllowed):
        registry.undo(core, int(run["id"]), actor=OWNER)  # once


def test_the_cofounder_kind_runs_through_the_registry_with_undo(core: Any) -> None:
    registry, calls = _registry()
    does, undoes = cofounder.adapters(registry)
    assert set(does) == {"add_note"} and set(undoes) == {"add_note"}
    result = does["add_note"](core, "ws-a", {"text": "from chat"})
    assert calls == ["cofounder:from chat"]
    assert _notes(core) == ["from chat"]
    undoes["add_note"](core, "ws-a", result)
    assert _notes(core) == []
    with pytest.raises(OperationNotAllowed):  # another workspace's run
        undoes["add_note"](core, "ws-b", result)


def test_the_catalogue_derives_every_callers_table_from_the_declarations() -> None:
    specs = (NOTE, OWNER_THING)
    kinds = catalog.kinds(specs)
    assert set(kinds) == {"add_note"}
    assert (kinds["add_note"].domain, kinds["add_note"].gate) == ("workspace", "undo")
    assert kinds["add_note"].required == ("text",)  # workspace_id comes from the chat
    assert catalog.effects(specs) == {"add_note": "work"}
    assert catalog.web_do(specs) == {"addNote": "do:add_note"}
    assert catalog.owner_only(specs) == {"ownerThing": "his alone"}
    tools = catalog.agent_tools(specs)
    assert [t["name"] for t in tools] == ["add_note"]
    assert "text" in tools[0]["parameters"]["properties"]
    assert "workspace_id" not in tools[0]["parameters"]["properties"]


def test_a_declaration_must_say_who_may_run_it() -> None:
    with pytest.raises(ValueError):
        OperationSpec(name="x", input_model=NewNote, audit_title="x", gate="once")
    with pytest.raises(ValueError):
        OperationSpec(
            name="x",
            input_model=NewNote,
            audit_title="x",
            gate="once",
            owner_only="his",
            cofounder_domain="workspace",
        )
    with pytest.raises(ValueError):  # Undo promised on its card, but nothing to undo with
        Registry((NOTE,)).bind(NOTE, do=lambda core, ctx, data: {})


def test_an_unbound_declaration_is_reported(core: Any) -> None:
    registry = Registry((NOTE, OWNER_THING))
    assert registry.unbound() == ["add_note", "owner_thing"]
    with pytest.raises(UnknownOperation):
        registry.run(core, "add_note", {"workspace_id": "ws-a", "text": "x"}, actor=OWNER)


def test_actor_labels() -> None:
    assert [OWNER.label, COFOUNDER.label, AGENT("writer").label] == [
        "owner",
        "cofounder",
        "agent:writer",
    ]
    assert Actor("owner") == OWNER
