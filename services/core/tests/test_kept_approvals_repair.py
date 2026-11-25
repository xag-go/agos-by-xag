"""Migration 148: approvals kept as JSON text by migration 122 (an SQLite that drops
the JSON subtype through a subquery) become a list again; a list stays as it is."""

from __future__ import annotations

import json
import sqlite3

from agos_core.db.migrations import MIGRATIONS

REPAIR = next(m for m in MIGRATIONS if "'$.kept') = 'text'" in m)


def test_kept_text_becomes_a_list_and_a_list_is_untouched() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE chat_turns (id INTEGER PRIMARY KEY, activity TEXT)")
    item = [{"kind": "approval", "title": "Run rm?", "status": "done"}]
    rows = [
        json.dumps({"kept": json.dumps(item)}),  # the broken shape
        json.dumps({"kept": item}),  # already right
        json.dumps({"kept": "not json ["}),  # text that is no JSON: left alone
        "[]",
    ]
    db.executemany("INSERT INTO chat_turns (activity) VALUES (?)", [(r,) for r in rows])
    for _ in range(2):  # safe to run again
        db.executescript(REPAIR)
    got = [r[0] for r in db.execute("SELECT activity FROM chat_turns ORDER BY id")]
    assert json.loads(got[0]) == {"kept": item}
    assert json.loads(got[1]) == {"kept": item}
    assert json.loads(got[2]) == {"kept": "not json ["}
    assert got[3] == "[]"
