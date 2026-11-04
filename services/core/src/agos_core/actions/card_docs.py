"""A card's documents: markdown files in the workspace folder, one revision per save.

Where they live (the agents read and write them with their file tools, at
/workspace in their sandbox):

    <workspace files>/cards/<card id>/<key>.md                 the document
    <workspace files>/cards/<card id>/.revisions/<key>/v<N>.md revision N as written
    <workspace files>/cards/<card id>/.revisions/<key>/CHANGES.md  one line per
        revision: `- v<N> | <when> | <who> | <why>` (engine/card_docs.py)

Every save checks the revision the writer read (`base_revision`): a save on a
document that moved since is refused with 409 and the words that say how to go on
(STALE), both for the owner's editor and for an agent's `agos_card_document` tool
(the guard's documents.py, through api/hermes_bridge.py). A document written
directly by a file tool (no revision for what is on disk) gets that text kept as a
revision first, so the next save sees it moved. Restore writes a new revision with
an old one's text; nothing is ever rewritten.

Passage comments (annotations) are AGOS rows (Hermes has no record for a comment
anchored in a file); on every new revision the open ones are anchored again
(engine/card_docs.py reanchor): active / stale / orphaned.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import card_doc_annotations as annotations_repo
from agos_core.db.activity import add_activity
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.engine import card_docs as rules
from agos_core.storage.layout import workspace_paths

log = logging.getLogger("agos.card_docs")

MAX_FILE = 2_000_000
CHANGES = "CHANGES.md"  # one line per revision, beside the revision files
REVISION_FILE = "v{}.md"  # a revision's text as written
CARD = r"^[A-Za-z0-9_-]{1,64}$"
STALE = (
    "document moved to revision {n} since you read it; read it again and resend with "
    "base_revision={n}"
)


def _card_folder(core: Core, workspace_id: str, card_id: str) -> Path:
    if not re.fullmatch(CARD, card_id):
        raise NotFoundError("This card")
    return workspace_paths(core.layout, workspace_id).files / rules.FOLDER / card_id


def _key(key: str) -> str:
    clean = rules.clean_key(key)
    if clean is None:
        raise ActionError(
            "A document key is letters, digits, - or _ (like notes or launch-plan); "
            "AGOS adds the .md."
        )
    return clean


def _paths(core: Core, workspace_id: str, card_id: str, key: str) -> tuple[Path, Path, Path]:
    """(the document, its revisions folder, its CHANGES.md)."""
    folder = _card_folder(core, workspace_id, card_id)
    history = folder / rules.REVISIONS / key
    return folder / (key + ".md"), history, history / CHANGES


def _read(target: Path) -> str:
    if target.stat().st_size > MAX_FILE:
        raise ActionError("This document is too big to open here.")
    return target.read_text(errors="replace")


def _revisions(changes: Path) -> list[rules.Revision]:
    try:
        return rules.parse_changes(changes.read_text(errors="replace"))
    except OSError:
        return []


# ---- the list and one document ---------------------------------------------------------------


def list_docs(core: Core, workspace_id: str, card_id: str) -> list[dict[str, Any]]:
    """The card's documents: one listing of its folder plus each CHANGES.md."""
    folder = _card_folder(core, workspace_id, card_id)
    if not folder.is_dir():
        return []
    out = []
    try:
        with os.scandir(folder) as entries:
            names = sorted(e.name for e in entries if e.is_file() and e.name.endswith(".md"))
    except OSError:
        return []
    for name in names:
        key = rules.clean_key(name)
        if key is None:
            continue
        revisions = _revisions(folder / rules.REVISIONS / key / CHANGES)
        last = revisions[-1] if revisions else None
        try:
            size = (folder / name).stat().st_size
        except OSError:
            size = 0
        out.append(
            {
                "key": key,
                "revision": last.n if last else 0,
                "size": size,
                "updatedAt": last.at if last else "",
                "who": last.who if last else "",
                "openAnnotations": 0,
            }
        )
    if out:
        counts = annotations_repo.open_counts(core.db, workspace_id, card_id)
        for d in out:
            d["openAnnotations"] = counts.get(str(d["key"]), 0)
    return out


def get_doc(core: Core, workspace_id: str, card_id: str, key: str) -> dict[str, Any]:
    """The document as it is on disk, its revisions (newest first) and its comments."""
    require_workspace(core, workspace_id)
    key = _key(key)
    target, history, changes = _paths(core, workspace_id, card_id, key)
    if not target.is_file():
        raise NotFoundError("This document")
    text = _read(target)
    revisions = _revisions(changes)
    current = revisions[-1].n if revisions else 0
    from agos_core.actions import feedback

    votes = feedback.votes_of(core, workspace_id, "revision", f"{card_id}:{key}:")
    return {
        "key": key,
        "content": text,
        "revision": current,
        # The text on disk isn't the last revision's: a file tool wrote it.
        "dirty": bool(revisions) and _body(_history_file(history, current)) != text,
        "revisions": [
            {
                "n": r.n,
                "at": r.at,
                "who": r.who,
                "why": r.why,
                "vote": votes.get(f"{card_id}:{key}:{r.n}", 0),
            }
            for r in reversed(revisions)
        ],
        "annotations": list_annotations(core, workspace_id, card_id, key),
    }


def _history_file(history: Path, n: int) -> Path:
    return history / REVISION_FILE.format(n)


def _body(revision: Path) -> str | None:
    try:
        return revision.read_text(errors="replace")
    except OSError:
        return None


def revision(core: Core, workspace_id: str, card_id: str, key: str, n: int) -> dict[str, Any]:
    """One revision's text and what it changed against the one before."""
    require_workspace(core, workspace_id)
    key = _key(key)
    _target, history, _changes = _paths(core, workspace_id, card_id, key)
    text = _body(_history_file(history, n))
    if text is None:
        raise NotFoundError("This revision")
    before = _body(_history_file(history, n - 1)) or "" if n > 1 else ""
    diff = difflib.unified_diff(
        before.splitlines(), text.splitlines(), f"v{n - 1}", f"v{n}", lineterm="", n=2
    )
    return {"n": n, "content": text, "diff": "\n".join(diff)}


# ---- writing ------------------------------------------------------------------------------------


def save(
    core: Core,
    workspace_id: str,
    card_id: str,
    key: str,
    content: str,
    *,
    who: str,
    why: str,
    base_revision: int | None,
) -> dict[str, Any]:
    """A new revision, when `base_revision` is the document's current one (None:
    only for a document that doesn't exist yet). 409 with STALE otherwise."""
    require_workspace(core, workspace_id)
    key = _key(key)
    if len(content) > MAX_FILE:
        raise ActionError("This document is too big (2 MB at most).")
    target, history, changes = _paths(core, workspace_id, card_id, key)
    with transaction(core.db):
        revisions = _revisions(changes)
        on_disk = _read(target) if target.is_file() else None
        current = revisions[-1].n if revisions else 0
        if on_disk is not None and (
            not revisions or _body(_history_file(history, current)) != on_disk
        ):
            # Written by a file tool since the last revision: kept as one first.
            current = _write_revision(
                history,
                changes,
                key,
                current + 1,
                on_disk,
                "a file tool",
                "written directly in the workspace folder",
            )
        if base_revision is None and current:
            raise ActionError(STALE.format(n=current), 409)
        if base_revision is not None and base_revision != current:
            raise ActionError(STALE.format(n=current), 409)
        if on_disk == content:
            return {"saved": False, "revision": current}
        n = _write_revision(history, changes, key, current + 1, content, who, why)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        moved = _reanchor_all(core, workspace_id, card_id, key, content)
        add_activity(
            core.db,
            workspace_id,
            kind="docs.changed",
            text=f"Card {card_id}: document {key} v{n} by {who} ({' '.join(why.split())[:120]})",
        )
    return {"saved": True, "revision": n, "annotations": moved}


def _write_revision(
    history: Path, changes: Path, key: str, n: int, text: str, who: str, why: str
) -> int:
    history.mkdir(parents=True, exist_ok=True)
    _history_file(history, n).write_text(text)
    line = rules.changes_line(rules.Revision(n, now(), who, why))
    if changes.is_file():
        with changes.open("a") as out:
            out.write(line)
    else:
        changes.write_text(rules.changes_header(key) + line)
    return n


def restore(
    core: Core, workspace_id: str, card_id: str, key: str, n: int, *, who: str
) -> dict[str, Any]:
    """Back to revision N: a NEW revision with its text ("restored from vN")."""
    require_workspace(core, workspace_id)
    key = _key(key)
    _target, history, changes = _paths(core, workspace_id, card_id, key)
    text = _body(_history_file(history, n))
    if text is None:
        raise NotFoundError("This revision")
    revisions = _revisions(changes)
    current = revisions[-1].n if revisions else 0
    return save(
        core,
        workspace_id,
        card_id,
        key,
        text,
        who=who,
        why=f"restored from v{n}",
        base_revision=current,
    )


# ---- passage comments -----------------------------------------------------------------------------


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "revision": int(r["revision"]),
        "quote": r["quote"],
        "prefix": r["prefix"],
        "suffix": r["suffix"],
        "start": int(r["pos_start"]),
        "end": int(r["pos_end"]),
        "body": r["body"],
        "author": r["author"],
        "anchor": r["anchor"],
        "anchoredRevision": int(r["anchored_revision"]),
        "resolved": r["resolved_at"] is not None,
        "createdAt": r["created_at"],
    }


def list_annotations(core: Core, workspace_id: str, card_id: str, key: str) -> list[dict[str, Any]]:
    return [_row(r) for r in annotations_repo.of_doc(core.db, workspace_id, card_id, key)]


def annotate(
    core: Core,
    workspace_id: str,
    card_id: str,
    key: str,
    *,
    start: int,
    end: int,
    body: str,
    author: str = "Owner",
) -> dict[str, Any]:
    """A comment on a passage of the document as it is now (its current revision)."""
    require_workspace(core, workspace_id)
    key = _key(key)
    if not body.strip():
        raise ActionError("Write the comment first.")
    target, _history, changes = _paths(core, workspace_id, card_id, key)
    if not target.is_file():
        raise NotFoundError("This document")
    text = _read(target)
    anchor = rules.anchor_of(text, start, end)
    if anchor is None:
        raise ActionError("Select a passage of the document first.")
    revisions = _revisions(changes)
    current = revisions[-1].n if revisions else 0
    at = now()
    new = annotations_repo.add(
        core.db,
        {
            "workspace_id": workspace_id,
            "card": card_id,
            "key": key,
            "revision": current,
            "quote": anchor.quote,
            "prefix": anchor.prefix,
            "suffix": anchor.suffix,
            "pos_start": anchor.start,
            "pos_end": anchor.end,
            "body": body.strip(),
            "author": author,
            "at": at,
        },
    )
    found = annotations_repo.get(core.db, workspace_id, new)
    assert found is not None  # written just now, in this connection
    return _row(found)


def resolve(core: Core, workspace_id: str, annotation_id: int, resolved: bool) -> None:
    if not annotations_repo.set_resolved(
        core.db, workspace_id, annotation_id, now() if resolved else None, now()
    ):
        raise NotFoundError("This comment")


def remove_annotation(core: Core, workspace_id: str, annotation_id: int) -> None:
    if not annotations_repo.delete(core.db, workspace_id, annotation_id):
        raise NotFoundError("This comment")


def _reanchor_all(
    core: Core, workspace_id: str, card_id: str, key: str, text: str
) -> dict[str, int]:
    """Every open comment of the document, anchored in the new text: how many
    are active / stale / orphaned now."""
    counts = {"active": 0, "stale": 0, "orphaned": 0}
    rows = annotations_repo.open_of_doc(core.db, workspace_id, card_id, key)
    if not rows:
        return counts
    revisions = _revisions(_paths(core, workspace_id, card_id, key)[2])
    current = revisions[-1].n if revisions else 0
    for r in rows:
        anchor = rules.reanchor(
            rules.Anchor(
                r["quote"],
                r["prefix"],
                r["suffix"],
                int(r["pos_start"]),
                int(r["pos_end"]),
                r["anchor"],
            ),
            text,
        )
        counts[anchor.state] += 1
        annotations_repo.set_anchor(
            core.db,
            workspace_id,
            int(r["id"]),
            anchor.start,
            anchor.end,
            anchor.state,
            current,
            now(),
        )
    return counts


# ---- the agents' tool (api/hermes_bridge.py card-document) ----------------------------------


def tool(
    core: Core,
    workspace_id: str,
    *,
    member: str,
    card_id: str,
    key: str,
    action: str,
    content: str,
    base_revision: int | None,
    why: str,
) -> dict[str, Any]:
    """`agos_card_document` as the agents call it: read / write (CAS) / annotations.
    Refusals come back as {"error": ...} with the current revision, never as HTTP
    errors (the agent reads the words)."""
    who = member or "Co-Founder"
    try:
        if action == "annotations":
            return {
                "card": card_id,
                "key": _key(key),
                "annotations": [
                    {k: a[k] for k in ("id", "quote", "body", "author", "anchor", "revision")}
                    for a in list_annotations(core, workspace_id, card_id, _key(key))
                    if not a["resolved"]
                ],
            }
        if action == "read":
            if not key.strip():
                return {"card": card_id, "documents": list_docs(core, workspace_id, card_id)}
            doc = get_doc(core, workspace_id, card_id, key)
            return {
                "card": card_id,
                "key": doc["key"],
                "revision": doc["revision"],
                "content": doc["content"],
                "openAnnotations": [
                    {k: a[k] for k in ("id", "quote", "body", "anchor")}
                    for a in doc["annotations"]
                    if not a["resolved"]
                ],
            }
        saved = save(
            core,
            workspace_id,
            card_id,
            key,
            content,
            who=who,
            why=why.strip() or f"written by {who}",
            base_revision=base_revision,
        )
        return {"card": card_id, "key": _key(key), **saved}
    except ActionError as error:
        answer: dict[str, Any] = {"error": error.message}
        if error.status == 409:
            revisions = _revisions(_paths(core, workspace_id, card_id, _key(key))[2])
            answer["current_revision"] = revisions[-1].n if revisions else 0
        return answer


# ---- every card's documents (the Artifacts page) ------------------------------------------------


def all_docs(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Every card's documents in the workspace: one walk of cards/*/."""
    base = workspace_paths(core.layout, workspace_id).files / rules.FOLDER
    if not base.is_dir():
        return []
    out = []
    try:
        with os.scandir(base) as cards:
            folders = sorted(e.name for e in cards if e.is_dir() and not e.name.startswith("."))
    except OSError:
        return []
    for card_id in folders:
        if not re.fullmatch(CARD, card_id):
            continue
        for d in list_docs(core, workspace_id, card_id):
            out.append({**d, "card": card_id})
    return out
