"""Workspaces are fully isolated: SQL that picks rows by id names the workspace, or its
function re-checks ownership. The scan's baseline (workspace_scope_baseline.json) only
shrinks; see workspace_scope_scan.py for the rule and the risk levels."""

import json
from pathlib import Path
from typing import Any

from security import workspace_scope_callers as callers
from security import workspace_scope_scan as scan

SCOPED = {"cards", "chats"}
SCOPED_TABLES = SCOPED
ADVICE = "run `python tests/security/workspace_scope_scan.py --update` from services/core"


def test_an_update_by_id_with_no_workspace_is_found() -> None:
    source = (
        "def rename(core, chat_id, title):\n"
        "    core.db.execute('UPDATE chats SET title = ? WHERE id = ?', (title, chat_id))\n"
    )
    (found,) = scan.scan_source(source, "actions/x.py", SCOPED)
    assert (found.kind, found.table, found.column, found.risk) == ("UPDATE", "chats", "id", "high")


def test_a_query_that_names_the_workspace_is_scoped() -> None:
    source = (
        "def rename(core, ws, chat_id, title):\n"
        "    core.db.execute('UPDATE chats SET title = ? WHERE id = ? AND workspace_id = ?',\n"
        "                    (title, chat_id, ws))\n"
    )
    assert scan.scan_source(source, "actions/x.py", SCOPED) == []


def test_a_function_that_loads_the_row_through_a_scoped_helper_rechecks() -> None:
    source = (
        "def _one(core, workspace_id, chat_id):\n"
        "    return core.db.execute('SELECT * FROM chats WHERE workspace_id = ? AND id = ?',\n"
        "                           (workspace_id, chat_id)).fetchone()\n"
        "def rename(core, workspace_id, chat_id, title):\n"
        "    _one(core, workspace_id, chat_id)\n"
        "    core.db.execute('UPDATE chats SET title = ? WHERE id = ?', (title, chat_id))\n"
    )
    assert scan.scan_source(source, "actions/x.py", SCOPED) == []


def test_a_comparison_on_the_rows_workspace_is_a_recheck() -> None:
    source = (
        "def rename(core, ws, chat_id, title):\n"
        "    row = core.db.execute('SELECT workspace_id FROM chats WHERE id = ?', (chat_id,)).fetchone()\n"
        "    if row['workspace_id'] != ws:\n"
        "        raise LookupError\n"
        "    core.db.execute('UPDATE chats SET title = ? WHERE id = ?', (title, chat_id))\n"
    )
    assert scan.scan_source(source, "actions/x.py", SCOPED) == []


def test_ids_picked_by_a_subquery_on_the_table_itself_are_not_from_a_caller() -> None:
    source = (
        "def prune(db):\n"
        "    db.execute('DELETE FROM chats WHERE id IN (SELECT id FROM chats ORDER BY at LIMIT -1 OFFSET ?)', (9,))\n"
    )
    assert scan.scan_source(source, "actions/x.py", SCOPED) == []
    by_list = "def f(db, ids):\n    db.execute('DELETE FROM chats WHERE id IN (?, ?)', ids)\n"
    assert [f.risk for f in scan.scan_source(by_list, "actions/x.py", SCOPED)] == ["high"]


def test_risk_follows_the_table_and_the_layer() -> None:
    read = "def f(db, i):\n    db.execute('SELECT * FROM chats WHERE id = ?', (i,))\n"
    child = "def f(db, i):\n    db.execute('DELETE FROM chat_lines WHERE chat_id = ?', (i,))\n"
    repo = "def f(db, i):\n    db.execute('DELETE FROM cards WHERE id = ?', (i,))\n"
    assert [f.risk for f in scan.scan_source(read, "actions/x.py", SCOPED)] == ["medium"]
    assert [f.risk for f in scan.scan_source(child, "actions/x.py", SCOPED)] == ["low"]
    assert [f.risk for f in scan.scan_source(repo, "db/x.py", SCOPED)] == ["medium"]


def test_the_real_schema_is_read_for_workspace_tables() -> None:
    tables = scan.workspace_tables()
    assert {"chats", "automations", "kanban_asks"} <= tables
    assert "chat_lines" not in tables and "app_settings" not in tables


def test_the_workspace_scope_baseline_only_shrinks() -> None:
    recorded: dict[str, str] = json.loads(scan.BASELINE.read_text())
    now = scan.keyed(scan.findings())
    new = sorted(set(now) - set(recorded))
    worse = sorted(k for k in set(now) & set(recorded) if _rank(now[k]) > _rank(recorded[k]))
    assert not new, f"new SQL by id without the workspace (scope it or re-check): {new}"
    assert not worse, f"findings got riskier: {worse}"
    fixed = sorted(set(recorded) - set(now))
    assert not fixed, f"fixed findings are still in the baseline: {fixed}; {ADVICE}"


def _rank(risk: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}[risk]


def _graph(tmp_path: Path, files: dict[str, str]) -> Any:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return callers.build(tmp_path)


def _rechecks(graph: Any) -> Any:
    guards = scan._guards(graph)
    ctx = scan._Context(graph, guards, {})
    return ctx.rechecks


REPO = "def rename(db, chat_id, t):\n    db.execute('UPDATE chats SET t = ? WHERE id = ?', (t, chat_id))\n"
SCOPED_ROW = (
    "def chat_row(db, workspace_id, chat_id):\n"
    "    return db.execute('SELECT * FROM chats WHERE id = ? AND workspace_id = ?',\n"
    "                      (chat_id, workspace_id)).fetchone()\n"
)


def test_a_repository_write_is_scoped_when_every_caller_rechecks(tmp_path: Path) -> None:
    checked = (
        "from agos_core.db import chats\n"
        "def rename(core, workspace_id, chat_id, t):\n"
        "    if chats.chat_row(core.db, workspace_id, chat_id) is None:\n"
        "        raise LookupError\n"
        "    chats.rename(core.db, chat_id, t)\n"
    )
    graph = _graph(tmp_path, {"db/chats.py": REPO + SCOPED_ROW, "actions/a.py": checked})
    assert graph.checked("db/chats.py", "rename", _rechecks(graph))
    # One caller that hands the id on unchecked keeps it a finding.
    loose = "from agos_core.db import chats\ndef go(core, chat_id):\n    chats.rename(core.db, chat_id, 'x')\n"
    graph = _graph(tmp_path, {"actions/b.py": loose})
    assert not graph.checked("db/chats.py", "rename", _rechecks(graph))
    assert graph.blockers("db/chats.py", "rename", _rechecks(graph)) == [
        "actions/b.py::go (named by nothing: a route or a registry entry)"
    ]


def test_a_function_named_in_a_table_or_by_nobody_is_not_scoped_by_callers(
    tmp_path: Path,
) -> None:
    table = "from agos_core.db import chats\nDO = {'rename': chats.rename}\n"
    graph = _graph(tmp_path, {"db/chats.py": REPO, "actions/t.py": table})
    assert not graph.checked("db/chats.py", "rename", _rechecks(graph))
    graph = _graph(tmp_path / "none", {"db/chats.py": REPO})
    assert not graph.checked("db/chats.py", "rename", _rechecks(graph))


def test_a_thread_runner_call_is_read_as_the_call_it_makes(tmp_path: Path) -> None:
    route = (
        "import asyncio\nfrom agos_core.db import chats\n"
        "async def put(core, workspace_id, chat_id):\n"
        "    await asyncio.to_thread(chats.chat_row, core.db, workspace_id, chat_id)\n"
        "    chats.rename(core.db, chat_id, 'x')\n"
    )
    graph = _graph(tmp_path, {"db/chats.py": REPO + SCOPED_ROW, "api/c.py": route})
    assert graph.checked("db/chats.py", "rename", _rechecks(graph))


def test_owner_pages_count_but_workspace_and_bridge_routes_do_not(tmp_path: Path) -> None:
    def route(path: str, prefix: str = "") -> str:
        made = f"APIRouter(prefix='{prefix}')" if prefix else "APIRouter()"
        return (
            f"from fastapi import APIRouter\nfrom agos_core.db import chats\nrouter = {made}\n"
            f"@router.put('{path}')\ndef put(core, chat_id):\n    chats.rename(core.db, chat_id, 'x')\n"
        )

    graph = _graph(tmp_path, {"db/chats.py": REPO, "api/errors.py": route("/errors/{chat_id}")})
    assert graph.checked("db/chats.py", "rename", _rechecks(graph))
    for rel, text in {
        "api/errors.py": route("/workspaces/{workspace_id}/chats/{chat_id}"),
        "api/bridge_x.py": route("/x/{chat_id}"),  # a workspace's Hermes, its bridge key
        "api/y.py": route("/x", "/hermes-bridge/{workspace_id}"),
    }.items():
        for other in ("api/errors.py", "api/bridge_x.py", "api/y.py"):
            (tmp_path / other).unlink(missing_ok=True)
        graph = _graph(tmp_path, {rel: text})
        assert not graph.checked("db/chats.py", "rename", _rechecks(graph)), rel


def test_only_an_ownership_helper_by_name_is_a_recheck() -> None:
    # `tell_owner` and `shown` once passed for ownership helpers (a substring match).
    for call in ("tell_owner(core, ws, 'x')", "shown(x)", "unknown()"):
        source = f"def f(core, ws, i):\n    {call}\n    core.db.execute('DELETE FROM chats WHERE id = ?', (i,))\n"
        assert [f.risk for f in scan.scan_source(source, "actions/x.py", SCOPED_TABLES)] == ["high"]
    # A bare check of the caller's own argument is no re-check of the row.
    bare = "def f(core, workspace_id, i):\n    if workspace_id is None:\n        return\n    core.db.execute('DELETE FROM chats WHERE id = ?', (i,))\n"
    assert [f.risk for f in scan.scan_source(bare, "actions/x.py", SCOPED_TABLES)] == ["high"]


def test_every_allowed_entry_point_names_its_guard_and_is_still_needed() -> None:
    allowed = scan.allowed_roots()
    graph = scan._context().graph
    for root, reason in allowed.items():
        path, _, name = root.partition("::")
        assert (path, name) in graph.functions, f"{root}: no such function"
        assert ".py" in reason and len(reason) > 30, f"{root}: name the guard (file:function)"
    stale = sorted(set(allowed) - scan.used_roots())
    assert not stale, f"allowed entry points no finding reaches any more: {stale}"


def test_no_high_or_medium_finding_is_left_unexplained() -> None:
    open_ = [f"{f.risk} {f.key}" for f in scan.findings() if f.risk != "low"]
    assert not open_, f"scope it, re-check it, or record its entry point's guard: {open_}"
