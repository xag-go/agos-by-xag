"""Skill Studio rows (AGOS's own; the run itself is a Hermes Kanban card): a skill's
saved test inputs, its run template and checklist, and each run's link to its card
with the output read from the card and the grader's verdict."""

from __future__ import annotations

import sqlite3
from typing import Any

from agos_core.db.rows import now

# What a run's prompt is made of when the skill has no template of its own.
DEFAULT_TEMPLATE = (
    "This is a test run of the skill `{skill}`. Use that skill on the input below and "
    "answer with the result only (no questions, no plan).\n\nInput:\n{input}"
)


def inputs(db: sqlite3.Connection, item_id: int) -> list[sqlite3.Row]:
    return list(
        db.execute("SELECT * FROM skill_test_inputs WHERE item_id = ? ORDER BY id", (item_id,))
    )


def get_input(db: sqlite3.Connection, input_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM skill_test_inputs WHERE id = ?", (input_id,)
    ).fetchone()
    return row


def add_input(
    db: sqlite3.Connection, workspace_id: str, item_id: int, name: str, text: str, expected: str
) -> int:
    cur = db.execute(
        "INSERT INTO skill_test_inputs (workspace_id, item_id, name, text, expected, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (workspace_id, item_id, name, text, expected, now()),
    )
    return int(cur.lastrowid or 0)


def update_input(
    db: sqlite3.Connection, input_id: int, name: str, text: str, expected: str
) -> None:
    db.execute(
        "UPDATE skill_test_inputs SET name = ?, text = ?, expected = ? WHERE id = ?",
        (name, text, expected, input_id),
    )


def delete_input(db: sqlite3.Connection, input_id: int) -> None:
    db.execute("DELETE FROM skill_test_inputs WHERE id = ?", (input_id,))


def settings(db: sqlite3.Connection, item_id: int) -> dict[str, str]:
    row = db.execute("SELECT * FROM skill_test_settings WHERE item_id = ?", (item_id,)).fetchone()
    if row is None:
        return {"template": "", "checklist": ""}
    return {"template": str(row["template"]), "checklist": str(row["checklist"])}


def save_settings(
    db: sqlite3.Connection, workspace_id: str, item_id: int, template: str, checklist: str
) -> None:
    db.execute(
        "INSERT INTO skill_test_settings (item_id, workspace_id, template, checklist, updated_at)"
        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (item_id) DO UPDATE SET template = excluded.template,"
        " checklist = excluded.checklist, updated_at = excluded.updated_at",
        (item_id, workspace_id, template, checklist, now()),
    )


def runs(db: sqlite3.Connection, item_id: int, limit: int = 50) -> list[sqlite3.Row]:
    return list(
        db.execute(
            "SELECT * FROM skill_test_runs WHERE item_id = ? ORDER BY id DESC LIMIT ?",
            (item_id, limit),
        )
    )


def get_run(db: sqlite3.Connection, run_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM skill_test_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return row


def add_run(db: sqlite3.Connection, **values: Any) -> int:
    values["created_at"] = now()
    keys = sorted(values)
    cur = db.execute(
        f"INSERT INTO skill_test_runs ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
        [values[k] for k in keys],
    )
    return int(cur.lastrowid or 0)


def set_card(db: sqlite3.Connection, run_id: int, card: str) -> None:
    db.execute("UPDATE skill_test_runs SET card = ? WHERE id = ?", (card, run_id))


def finish(db: sqlite3.Connection, run_id: int, status: str, output: str) -> None:
    db.execute(
        "UPDATE skill_test_runs SET status = ?, output = ?, finished_at = ? WHERE id = ?",
        (status, output, now() if status != "running" else None, run_id),
    )


def grade(
    db: sqlite3.Connection, run_id: int, verdict: str, notes: str, score: float | None = None
) -> None:
    db.execute(
        "UPDATE skill_test_runs SET grade = ?, notes = ?, score = ?, graded_at = ? WHERE id = ?",
        (verdict, notes, score, now(), run_id),
    )


def delete_run(db: sqlite3.Connection, run_id: int) -> None:
    db.execute("DELETE FROM skill_test_runs WHERE id = ?", (run_id,))


def last_graded(db: sqlite3.Connection, item_id: int, input_id: int, version: Any) -> int | None:
    """The newest pass/fail run of this input on this version (None: none yet)."""
    kept = db.execute(
        """SELECT id FROM skill_test_runs WHERE item_id = ? AND input_id = ? AND version = ?
             AND grade IN ('pass', 'fail') ORDER BY id DESC LIMIT 1""",
        (item_id, input_id, version),
    ).fetchone()
    return int(kept["id"]) if kept is not None else None


def card_waits_on_test(db: sqlite3.Connection, workspace_id: str, card: str) -> bool:
    """This board card is a test run of a skill whose request or candidate is under test."""
    hit = db.execute(
        """SELECT 1 FROM skill_test_runs t WHERE t.workspace_id = ? AND t.card = ? AND (
             EXISTS (SELECT 1 FROM skill_requests r WHERE r.workspace_id = t.workspace_id
                       AND r.item_id = t.item_id AND r.status = 'testing')
             OR EXISTS (SELECT 1 FROM skill_candidates c WHERE c.workspace_id = t.workspace_id
                       AND c.item_id = t.item_id AND c.status = 'testing')) LIMIT 1""",
        (workspace_id, card),
    ).fetchone()
    return hit is not None


def failed_since(db: sqlite3.Connection, workspace_id: str, since: str) -> list[sqlite3.Row]:
    """The workspace's runs graded fail since then, with their skill's name."""
    return list(
        db.execute(
            """SELECT t.id, t.input_name, t.notes, i.name FROM skill_test_runs t
               JOIN library_items i ON i.id = t.item_id
               WHERE t.workspace_id = ? AND t.grade = 'fail' AND t.graded_at >= ? ORDER BY t.id""",
            (workspace_id, since),
        )
    )
