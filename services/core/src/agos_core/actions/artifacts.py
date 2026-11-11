"""The workspace's Artifacts: every card's files and documents in one gallery.

Files are Hermes's own card attachments (task_attachments, read from the board
database the way Hermes's CLI reads it: engine/hermes_board.py all_attachments,
one query for the whole board); documents are the cards' markdown files in the
workspace folder (actions/card_docs.py). AGOS adds only what Hermes has no record
for: the owner's review of an artifact (approved / needs work), one row per
artifact; and Promote, which turns a markdown attachment into a card document
(the file's text as its first revision).
"""

from __future__ import annotations

import logging
from typing import Any

from agos_core.actions import card_docs, kanban_board
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import artifact_reviews
from agos_core.engine import card_docs as rules

log = logging.getLogger("agos.artifacts")

STATES = ("approved", "needs_work")
MAX_PROMOTE = 2_000_000


def _attachments(core: Core, workspace_id: str) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Every card's files and every card's title, from Hermes's board database (one
    read); without it, the titles from the board already read (its cache) and a
    note that says why the files are missing."""
    from agos_core.engine import hermes_board

    try:
        files, titles = hermes_board.all_attachments(kanban_board._board_file(core, workspace_id))
    except hermes_board.Unread as why:
        return (
            [],
            _titles_from_board(core, workspace_id),
            f"The board's files can't be listed here ({why}).",
        )
    return files, titles, ""


def _titles_from_board(core: Core, workspace_id: str) -> dict[str, str]:
    try:
        board = kanban_board.board(core, workspace_id)
    except ActionError as error:
        log.info("the board of %s not read for the artifacts: %s", workspace_id, error)
        return {}
    return {str(c["id"]): str(c["title"]) for c in board["cards"]}


def page(core: Core, workspace_id: str) -> dict[str, Any]:
    """GET /artifacts: every attachment and document, with its type, card, member,
    time and the owner's review; one board read, one folder walk, one query."""
    require_workspace(core, workspace_id)
    files, titles, note = _attachments(core, workspace_id)
    members = kanban_board._members(core, workspace_id)
    cofounder = core.engine.hermes_name(workspace_id) if core.engine else ""
    reviews = artifact_reviews.of_workspace(core.db, workspace_id)
    items: list[dict[str, Any]] = []
    for a in files:
        card = str(a["task_id"])
        ref = f"attachment:{card}:{a['id']}"
        who = str(a.get("uploaded_by") or "")
        items.append(
            {
                "ref": ref,
                "source": "attachment",
                "card": card,
                "cardTitle": titles.get(card, ""),
                "name": str(a["filename"]),
                "kind": rules.kind_of(str(a["filename"])),
                "size": int(a["size"] or 0),
                "member": kanban_board._creator(who, members, cofounder),
                "at": int(a["created_at"] or 0),
                "attachmentId": int(a["id"]),
                "key": "",
                "revision": 0,
                "review": reviews.get(ref, {}).get("state", ""),
                "reviewNote": reviews.get(ref, {}).get("note", ""),
            }
        )
    for d in card_docs.all_docs(core, workspace_id):
        card = str(d["card"])
        ref = f"document:{card}:{d['key']}"
        items.append(
            {
                "ref": ref,
                "source": "document",
                "card": card,
                "cardTitle": titles.get(card, ""),
                "name": str(d["key"]) + ".md",
                "kind": "md",
                "size": int(d["size"]),
                "member": str(d["who"]),
                "at": _epoch(str(d["updatedAt"])),
                "attachmentId": None,
                "key": str(d["key"]),
                "revision": int(d["revision"]),
                "review": reviews.get(ref, {}).get("state", ""),
                "reviewNote": reviews.get(ref, {}).get("note", ""),
            }
        )
    items.sort(key=lambda i: -int(i["at"]))
    return {"items": items, "note": note}


def _epoch(iso: str) -> int:
    """A CHANGES.md time (db/rows.now) as seconds, 0 when it can't be read."""
    from datetime import datetime

    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, OSError):
        return 0


def review(core: Core, workspace_id: str, artifact: str, state: str, note: str = "") -> None:
    """The owner's review of one artifact; "" takes it back."""
    require_workspace(core, workspace_id)
    if not artifact.startswith(("attachment:", "document:")):
        raise NotFoundError("This artifact")
    if not state:
        artifact_reviews.delete(core.db, workspace_id, artifact)
        return
    if state not in STATES:
        raise ActionError("A review is approved or needs work.")
    artifact_reviews.put(core.db, workspace_id, artifact, state, note.strip()[:2000])


def promote(
    core: Core, workspace_id: str, card_id: str, attachment_id: int, key: str = ""
) -> dict[str, Any]:
    """A markdown attachment becomes a document of its card: its text is the first
    revision ("promoted from <file>"). Refused when that key already exists."""
    require_workspace(core, workspace_id)
    found = kanban_board.attachment_path(core, workspace_id, card_id, attachment_id)
    if rules.kind_of(found.name) != "md":
        raise ActionError("Only a markdown or text file can become a document.")
    if found.stat().st_size > MAX_PROMOTE:
        raise ActionError("That file is too big to be a document (2 MB at most).")
    text = found.read_text(errors="replace")
    wanted = rules.clean_key(key) if key.strip() else rules.slug(found.name)
    if wanted is None:
        raise ActionError("A document key is letters, digits, - or _.")
    try:
        saved = card_docs.save(
            core,
            workspace_id,
            card_id,
            wanted,
            text,
            who="Owner",
            why=f"promoted from the attachment {found.name}",
            base_revision=None,
        )
    except ActionError as error:
        if error.status == 409:
            raise ActionError(
                f"Card {card_id} already has a document {wanted}; pick another key."
            ) from error
        raise
    return {"card": card_id, "key": wanted, "revision": int(saved["revision"])}
