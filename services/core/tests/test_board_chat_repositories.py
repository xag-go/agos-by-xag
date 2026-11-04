"""Each table of the Board, Chat, Channel, Inbox and Docs services has ONE repository
module under db/, and only it writes the table (INSERT / UPDATE / DELETE).

The writer of each table is the ownership registry's `writer=` (db/ownership/);
`PINNED` keeps the ones already moved from being dropped there.

`OUTSIDE` is a shrink-only baseline of writers in other services' modules (their
lanes move them onto the repository); a new writer anywhere else fails here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from agos_core.db.ownership import TABLES

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

# The one writer of each table, from the ownership registry (db/ownership `writer=`).
OWNER = {name: table.writer for name, table in TABLES.items() if table.writer}

# Tables whose writer the registry must keep naming (Board, Chat, Channel, Inbox,
# Docs): a writer dropped from the registry fails here, not silently.
PINNED = {
    "chats": "db/chats.py",
    "chat_turns": "db/chat_turns.py",
    "message_rows": "db/chat_lines.py",
    "message_attachments": "db/chat_attachments.py",
    "chat_edits": "db/chat_edits.py",
    "chat_addresses": "db/chat_addresses.py",
    "channel_connections": "db/channel_connections.py",
    "channel_outbox": "db/channel_outbox.py",
    "channel_reactions": "db/channel_reactions.py",
    "hermes_inbox": "db/hermes_inbox.py",
    "group_rooms": "db/group_rooms.py",
    "room_events": "db/group_rooms.py",
    "kanban_asks": "db/kanban_asks.py",
    "inbox_marks": "db/inbox.py",
    "inbox_notes": "db/inbox.py",
    "status_cards": "db/status_cards.py",
    "labels": "db/labels.py",
    "kanban_holds": "db/kanban_holds.py",
    "artifact_reviews": "db/artifact_reviews.py",
    "card_services": "db/card_services.py",
    "card_doc_annotations": "db/card_doc_annotations.py",
    "pipeline_rules": "db/pipelines.py",
    "pipeline_seen": "db/pipelines.py",
    "feedback_votes": "db/feedback_votes.py",
}

# (module, table): writers outside the repository, in other services' modules.
OUTSIDE = {
    ("db/workspaces.py", "hermes_inbox"),
}

WRITE = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)"
    r"\s+([a-z_]+)\b",
    re.I,
)


def _writers() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith("db/migrations") or rel.startswith("db/ownership/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for table in WRITE.findall(node.value):
                    if table in OWNER and OWNER[table] != rel:
                        found.add((rel, table))
    return found


def test_the_registry_names_the_writer_of_these_tables() -> None:
    assert {t: OWNER.get(t) for t in PINNED} == PINNED


def test_only_the_repository_writes_its_table() -> None:
    extra = _writers() - OUTSIDE
    assert not extra, f"write these tables through their db/ repository: {sorted(extra)}"


def test_the_outside_baseline_only_shrinks() -> None:
    gone = OUTSIDE - _writers()
    assert not gone, f"moved onto the repository: drop from OUTSIDE {sorted(gone)}"


def test_every_repository_is_there_and_imports_no_actions_or_engine() -> None:
    for module in set(OWNER.values()):
        tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        upward = [n for n in names if n.startswith(("agos_core.actions", "agos_core.engine"))]
        assert not upward, f"{module} imports {upward}"
