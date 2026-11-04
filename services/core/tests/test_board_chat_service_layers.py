"""The Board, Chat, Channel, Inbox and System services keep to the service layer
(ARCHITECTURE.md §10): the modules listed here hold no SQL of their own. AGOS's
tables are read and written through their repositories (db/<table>.py); Hermes's
own databases (kanban.db, state.db) through the Hermes Gateway (hermes_gateway/).

Their routers reach the database and Hermes only through actions.

The layer ratchet (scripts/layer_ratchet.py) counts the whole core; this pins the
modules already moved, so one of them can't slide back while the totals still fall.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

SQL_FREE = [
    # Board
    "actions/services/board",
    "actions/kanban_asks.py",
    "actions/kanban_board.py",
    "actions/pipelines.py",
    "actions/card_docs.py",
    "actions/card_services.py",
    "actions/holds.py",
    "actions/labels.py",
    "actions/blocked.py",
    "actions/artifacts.py",
    "actions/questions.py",
    "actions/threads.py",
    # Chat
    "actions/services/chat",
    "actions/chat.py",
    "actions/chat_store.py",
    "actions/rooms.py",
    "actions/search.py",
    "actions/voice.py",
    # Channel
    "actions/services/channel",
    "actions/channels.py",
    "actions/hermes_channel.py",
    # Inbox
    "actions/inbox.py",
    "actions/today.py",
    # System
    "actions/services/system",
    "actions/docs.py",
    "actions/learning.py",
    "actions/access.py",
    "actions/member_topics.py",
    "actions/backups.py",
    "actions/diagnostics.py",
]

ROUTERS = [
    "api/chats.py",
    "api/channels.py",
    "api/kanban.py",
    "api/kanban_schemas.py",
    "api/log.py",
    "api/bridge_access.py",
    "api/bridge_approvals.py",
    "api/bridge_rooms.py",
    "api/bridge_telegram.py",
    "api/bridge_tools.py",
    "api/bridge_turns.py",
    "api/bridge_upkeep.py",
    "api/bridge_waits.py",
    "api/hermes_bridge.py",
    "api/inbox.py",
]
_BELOW_ACTIONS = ("db", "engine", "hermes_gateway", "storage", "security")
_DTO = {"agos_core.db.records"}


def _files(entries: list[str]) -> list[Path]:
    out: list[Path] = []
    for entry in entries:
        path = SRC / entry
        assert path.exists(), f"{entry} is gone: update this list"
        out += sorted(path.glob("*.py")) if path.is_dir() else [path]
    return out


def _sql_calls(path: Path) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "executemany", "executescript")
    ]


def test_these_services_hold_no_sql_of_their_own() -> None:
    hits = [f"{p.relative_to(SRC)}:{n}" for p in _files(SQL_FREE) for n in _sql_calls(p)]
    assert not hits, "SQL outside a repository (db/) or the Gateway:\n" + "\n".join(hits)


def _imported(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
    return [(n, m) for n, m in found if m.startswith("agos_core.")]


def _below(module: str) -> bool:
    parts = module.split(".")
    if len(parts) < 3 or parts[1] not in _BELOW_ACTIONS:
        return False
    return not any(module == d or module.startswith(d + ".") for d in _DTO)


def test_these_routers_reach_the_database_and_hermes_only_through_actions() -> None:
    hits = [
        f"{p.relative_to(SRC)}:{n} {m}"
        for p in _files(ROUTERS)
        for n, m in _imported(p)
        if _below(m)
    ]
    assert not hits, "a router reaches below actions:\n" + "\n".join(hits)
