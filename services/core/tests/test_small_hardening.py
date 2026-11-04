"""Small hardening from the security audit (F6 part, F13 part)."""

import sqlite3

from agos_core.engine import cofounder_actions as action_rules
from agos_core.hermes_gateway import kanban_move


def test_the_agent_never_approves_its_own_held_write_alone() -> None:
    """Hermes holds a memory/skill write back for the owner's review: approving it is
    his call (Allow / Deny), in every mode; rejecting it is not."""
    approve = action_rules._clean({"do": "approve_held_write", "id": "w1"})
    reject = action_rules._clean({"do": "reject_held_write", "id": "w1"})
    assert approve is not None and action_rules.needs_owner(approve)
    assert reject is not None and not action_rules.needs_owner(reject)


def test_board_table_names_are_quoted_identifiers() -> None:
    """Hermes's board file can be written by its gateway: a table name with a quote
    is counted like any other, never pasted into the SQL."""
    db = sqlite3.connect(":memory:")
    db.execute('CREATE TABLE "tasks" (id TEXT)')
    db.execute('CREATE TABLE "x"" FROM tasks; --" (id TEXT)')
    db.execute("INSERT INTO tasks VALUES ('t1')")
    assert kanban_move.counts(db) == {"tasks": 1, 'x" FROM tasks; --': 0}
