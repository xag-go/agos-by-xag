"""A Kanban card's files: Hermes's own attachments of the card (listed from its board
database the way its CLI lists them, else asked from the CLI), downloading one,
adding one he uploads, removing one.

Split out of agos_core.actions.kanban_board (its `attachments`, `attachment_path`,
`attach`, `remove_attachment`).

Owns: those reads and writes, and the checks that keep a download inside the
board's own files.
Must not: hold any other part of the card.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board import card_members, kanban_cli, kanban_db
from agos_core.context import Core

__all__ = [
    "attach",
    "attached",
    "attachment_path",
    "attachments",
    "remove_attachment",
]

log = logging.getLogger("agos.kanban_board")


def attached(core: Core, workspace_id: str, card_id: str) -> list[Any]:
    """`hermes kanban attachments <card> --json`: read from Hermes's board database
    the way the CLI reads it (engine/hermes_board.py), else asked from the CLI.
    ActionError when the card isn't on the board (the CLI's "no such task")."""
    from agos_core.engine import hermes_board

    try:
        found = hermes_board.attachments(kanban_db.board_file(core, workspace_id), card_id)
    except hermes_board.Unread as why:
        log.debug("files of %s in %s from Hermes's CLI: %s", card_id, workspace_id, why)
    else:
        if found is None:
            raise NotFoundError("This card")
        return found
    raw = kanban_cli.answer(
        kanban_cli.run(core, workspace_id, "attachments", card_id, "--json") or "[]"
    )
    return raw if isinstance(raw, list) else []


def attachments(core: Core, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
    try:
        raw = attached(core, workspace_id, card_id)
    except ActionError:
        return []
    return [
        {
            "id": int(a.get("id") or 0),
            "name": str(a.get("filename") or ""),
            "size": int(a.get("size") or 0),
            "by": "You"
            if a.get("uploaded_by") in (card_members.OWNER, "user")
            else str(a.get("uploaded_by") or ""),
            "at": int(a.get("created_at") or 0),
        }
        for a in raw
        if isinstance(a, dict)
    ]


def attachment_path(core: Core, workspace_id: str, card_id: str, attachment_id: int) -> Path:
    """Where Hermes keeps one of the card's files (for downloading it)."""
    from agos_core.actions import agent_profiles

    for a in attached(core, workspace_id, card_id):
        if isinstance(a, dict) and int(a.get("id") or 0) == attachment_id:
            path = Path(str(a.get("stored_path") or "")).resolve()
            # Hermes's attachments live under <board home>/kanban (attachments_root).
            home = (agent_profiles.board_home(core, workspace_id) / "kanban").resolve()
            if path.is_file() and path.is_relative_to(home):
                return path
    raise NotFoundError("This file")


def attach(core: Core, workspace_id: str, card_id: str, name: str, data: bytes) -> None:
    """A file he adds to the card: Hermes's own attachment (copied into its board)."""
    import re
    import tempfile

    from agos_core.actions import agent_profiles

    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(" .")[:120] or "file"
    if len(data) > 50 * 1024 * 1024:
        raise ActionError("That file is too big (50 MB at most).")
    folder = agent_profiles.board_home(core, workspace_id) / "kanban"  # Hermes's board files
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        path = Path(tmp) / safe
        path.write_bytes(data)
        kanban_cli.run(
            core,
            workspace_id,
            "attach",
            card_id,
            str(path),
            "--name",
            safe,
            "--author",
            card_members.OWNER,
        )


def remove_attachment(core: Core, workspace_id: str, card_id: str, attachment_id: int) -> None:
    if not any(a["id"] == attachment_id for a in attachments(core, workspace_id, card_id)):
        raise NotFoundError("This file")
    kanban_cli.run(core, workspace_id, "attach-rm", str(attachment_id))
