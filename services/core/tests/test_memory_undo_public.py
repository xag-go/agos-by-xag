"""#25: an approved memory write's Undo is Hermes's own public inverse op when the
approval made one change (H: tools/memory_tool_store.py MemoryStore.add / replace /
remove, under Hermes's own lock); only a batch of several changes still restores the
snapshot through MemoryStore._mutate."""

from agos_core.engine.hermes import _UNDO_PENDING, memory_undo_ops


def test_an_add_is_undone_by_remove() -> None:
    before = {"memory": ["a"], "user": ["u"]}
    after = {"memory": ["a", "b"], "user": ["u"]}
    assert memory_undo_ops(before, after) == [
        {"op": "remove", "target": "memory", "old": "b", "new": None}
    ]


def test_a_remove_is_undone_by_add() -> None:
    before = {"memory": ["a"], "user": ["u", "v"]}
    after = {"memory": ["a"], "user": ["v"]}
    assert memory_undo_ops(before, after) == [
        {"op": "add", "target": "user", "old": None, "new": "u"}
    ]


def test_a_replace_is_undone_by_replace_back() -> None:
    before = {"memory": ["a", "b", "c"], "user": []}
    after = {"memory": ["a", "B!", "c"], "user": []}
    assert memory_undo_ops(before, after) == [
        {"op": "replace", "target": "memory", "old": "B!", "new": "b"}
    ]


def test_several_changes_have_no_single_inverse() -> None:
    before = {"memory": ["a", "b"], "user": []}
    after = {"memory": ["x", "y", "z"], "user": []}
    assert memory_undo_ops(before, after) is None
    assert memory_undo_ops({"memory": ["a"], "user": []}, {"memory": ["a"], "user": []}) == []


def test_the_undo_script_uses_hermess_public_methods() -> None:
    assert "store.add(" in _UNDO_PENDING
    assert "store.replace(" in _UNDO_PENDING and "store.remove(" in _UNDO_PENDING
    assert "matched_entry=" in _UNDO_PENDING
