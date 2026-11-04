"""Status cards, their summary: the Co-Founder's summary written with a revision, and a revision read back.
Must not: decide the card's scope.

Split out of agos_core.actions.status_cards (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import difflib
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.board.status_defs import (
    KEY,
    MAX_SUMMARY,
    _body,
    _paths,
    _revisions,
    _row,
)
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import status_cards
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.engine import card_docs as doc_rules

__all__ = [
    "revision",
    "write_summary",
]


def write_summary(
    core: Core, workspace_id: str, card_id: int, text: str, *, who: str, why: str
) -> dict[str, Any]:
    """A new revision of the card's summary (none when the text is the same)."""
    row = _row(core, workspace_id, card_id)
    text = text.strip()
    if not text:
        raise ActionError("Write the summary first.")
    if len(text) > MAX_SUMMARY:
        raise ActionError("A status card's summary is short: 20,000 letters at most.")
    target, history, changes = _paths(core, workspace_id, card_id)
    with transaction(core.db):
        revisions = _revisions(changes)
        current = revisions[-1].n if revisions else 0
        if _body(target) == text + "\n":
            return {"saved": False, "revision": current}
        n = current + 1
        history.mkdir(parents=True, exist_ok=True)
        (history / f"v{n}.md").write_text(text + "\n")
        line = doc_rules.changes_line(doc_rules.Revision(n, now(), who, why))
        if changes.is_file():
            with changes.open("a") as out:
                out.write(line)
        else:
            changes.write_text(doc_rules.changes_header(KEY) + line)
        target.write_text(text + "\n")
        status_cards.written(core.db, card_id)
        add_activity(
            core.db,
            workspace_id,
            kind="status.written",
            text=f"Status card “{row['title']}”: summary v{n} by {who}",
        )
    return {"saved": True, "revision": n}


def revision(core: Core, workspace_id: str, card_id: int, n: int) -> dict[str, Any]:
    """One revision's text and what it changed against the one before."""
    require_workspace(core, workspace_id)
    _row(core, workspace_id, card_id)
    _target, history, _changes = _paths(core, workspace_id, card_id)
    text = _body(history / f"v{n}.md")
    if text is None:
        raise NotFoundError("This revision")
    before = (_body(history / f"v{n - 1}.md") or "") if n > 1 else ""
    diff = difflib.unified_diff(
        before.splitlines(), text.splitlines(), f"v{n - 1}", f"v{n}", lineterm="", n=2
    )
    return {"n": n, "content": text, "diff": "\n".join(diff)}
