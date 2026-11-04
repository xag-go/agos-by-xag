"""The library rows: AGOS's ids of what each workspace has (rows only).

Skills, agents and MCP servers belong to ONE workspace (`workspace_id`); tools,
plugins and the owner's MCP templates are global.
"""

import sqlite3
from typing import Any

from agos_core.db.rows import dump_json, load_json, now

# Kinds whose rows belong to one workspace (the same name can be in two of them).
OWNED = ("agent", "mcp", "skill")


def list_items(
    db: sqlite3.Connection, kind: str | None = None, workspace_id: str | None = None
) -> list[sqlite3.Row]:
    """Everything of this kind. With a workspace: the global items plus THAT
    workspace's own skills and MCP servers, never another workspace's. Without one
    (Settings): no skills or MCP servers (each belongs to a workspace). Never
    agents: a team is its members' Hermes profiles (actions/team.py); their rows
    are only ids."""
    where, args = ["kind != 'agent'"], []
    if kind:
        where.append("kind = ?")
        args.append(kind)
    if workspace_id is not None:
        where.append("(kind NOT IN ('mcp', 'skill') OR workspace_id = ?)")
        args.append(workspace_id)
    else:
        where.append("kind NOT IN ('mcp', 'skill')")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return list(db.execute(f"SELECT * FROM library_items {clause} ORDER BY kind, title", args))


def workspace_skills(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    """The skills of ONE workspace."""
    return list(
        db.execute(
            "SELECT * FROM library_items WHERE kind = 'skill' AND workspace_id = ? ORDER BY name",
            (workspace_id,),
        )
    )


def every_skill(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace's skills (AGOS's own upkeep only: read-ahead, the move)."""
    return list(db.execute("SELECT * FROM library_items WHERE kind = 'skill' ORDER BY id"))


def list_templates(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """The owner's shared MCP server definitions (Settings → Connectors): no
    workspace, no key, no login. Each workspace adds its own copy."""
    return list(
        db.execute(
            "SELECT * FROM library_items WHERE kind = 'mcp' AND workspace_id IS NULL"
            " AND source = 'template' ORDER BY title"
        )
    )


def template_copies(db: sqlite3.Connection, template_id: int) -> list[sqlite3.Row]:
    """The workspaces' own servers added from that shared definition."""
    return list(
        db.execute(
            "SELECT * FROM library_items WHERE kind = 'mcp' AND workspace_id IS NOT NULL"
            " AND source = ? ORDER BY workspace_id",
            (f"template:{template_id}",),
        )
    )


def get_item(db: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = db.execute(
        "SELECT * FROM library_items WHERE id = ?", (item_id,)
    ).fetchone()
    return row


def find_item(
    db: sqlite3.Connection, kind: str, name: str, workspace_id: str | None = None
) -> sqlite3.Row | None:
    """Plugins, tools: by name. Agents, skills and MCP servers: by name IN that
    workspace (None = an agent not given to any workspace yet)."""
    if kind in OWNED:
        row: sqlite3.Row | None = db.execute(
            "SELECT * FROM library_items WHERE kind = ? AND name = ? AND workspace_id IS ?",
            (kind, name, workspace_id),
        ).fetchone()
        return row
    row = db.execute(
        "SELECT * FROM library_items WHERE kind = ? AND name = ?", (kind, name)
    ).fetchone()
    return row


def insert_item(
    db: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    title: str,
    summary: str,
    definition: dict[str, Any],
    source: str,
    workspace_id: str | None = None,
) -> int:
    at = now()
    title, summary, definition = _kept(kind, name, title, summary, definition)
    cursor = db.execute(
        """INSERT INTO library_items (kind, name, title, summary, definition, source, created_at,
             updated_at, workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (kind, name, title, summary, dump_json(definition), source, at, at, workspace_id),
    )
    return int(cursor.lastrowid or 0)


def update_item(
    db: sqlite3.Connection, item_id: int, *, title: str, summary: str, definition: dict[str, Any]
) -> bool:
    row = db.execute("SELECT kind, name FROM library_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return False
    title, summary, definition = _kept(
        str(row["kind"]), str(row["name"]), title, summary, definition
    )
    changed = (
        db.execute(
            "UPDATE library_items SET title = ?, summary = ?, definition = ?, updated_at = ? WHERE id = ?",
            (title, summary, dump_json(definition), now(), item_id),
        ).rowcount
        > 0
    )
    return changed


def _kept(
    kind: str, name: str, title: str, summary: str, definition: dict[str, Any]
) -> tuple[str, str, dict[str, Any]]:
    """What a row keeps of an item Hermes holds. A tool (a Hermes toolset) keeps
    only its id: its label and words are Hermes's catalog. A skill keeps no summary
    (its SKILL.md description) and no title equal to its SKILL.md name; only a
    display name the owner gave it (Hermes has no field for one) and where it came
    from (`identifier`/`hash`, actions/library.py _stored: the text and files are
    its folder's)."""
    if kind == "tool":
        return "", "", {}
    if kind == "skill":
        return ("" if title.strip() == name else title), "", definition
    return title, summary, definition


def delete_item(db: sqlite3.Connection, item_id: int) -> bool:
    return db.execute("DELETE FROM library_items WHERE id = ?", (item_id,)).rowcount > 0


def definition(row: sqlite3.Row) -> dict[str, Any]:
    value = load_json(row["definition"])
    return value if isinstance(value, dict) else {}


def own_servers(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace's own MCP servers (not a template's copy, not found on the
    machine), oldest first: the ones that may become shared templates."""
    return db.execute(
        """SELECT * FROM library_items WHERE kind = 'mcp' AND workspace_id IS NOT NULL
             AND source NOT LIKE 'template:%' AND source != 'machine' ORDER BY id"""
    ).fetchall()


def set_source(db: sqlite3.Connection, item_id: int, source: str) -> None:
    db.execute("UPDATE library_items SET source = ? WHERE id = ?", (source, item_id))


def old_shared_skills(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Skills of the old shared library (no workspace), oldest first."""
    return list(
        db.execute(
            "SELECT * FROM library_items WHERE kind = 'skill' AND workspace_id IS NULL ORDER BY id"
        )
    )


def agent_ids(db: sqlite3.Connection, workspace_id: str) -> dict[str, int]:
    """A workspace's agent rows: name -> id."""
    return {
        str(r["name"]): int(r["id"])
        for r in db.execute(
            "SELECT id, name FROM library_items WHERE kind = 'agent' AND workspace_id = ?",
            (workspace_id,),
        )
    }
