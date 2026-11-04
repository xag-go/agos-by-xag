"""A workspace's card labels and their folders (Step 58, F29).

The label itself (name, colour, folder = a group of labels) is AGOS's `labels` row:
Hermes's board has no labels. Which cards carry it is the card's own: a block in its
Hermes body (engine/threads.py LABELS_BLOCK), written with Hermes's `kanban edit
--body` (many cards at once: kanban_board.edit_bodies, one Hermes process). The board
read already has every body, so filtering by label costs nothing more.
"""

from __future__ import annotations

import re
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import labels as labels_repo
from agos_core.db.connection import transaction
from agos_core.engine import threads as rules

COLORS = ("gray", "red", "orange", "yellow", "green", "teal", "blue", "purple", "pink")
MAX_LABELS = 200
_NAME = re.compile(r"[^\x00-\x1f]{1,40}")


def listing(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    return [
        {
            "id": int(r["id"]),
            "name": str(r["name"]),
            "color": str(r["color"]),
            "folder": str(r["folder"]),
        }
        for r in labels_repo.of_workspace(core.db, workspace_id)
    ]


def _clean(name: str, color: str, folder: str) -> tuple[str, str, str]:
    name, folder = " ".join(name.split()), " ".join(folder.split())
    if not _NAME.fullmatch(name):
        raise ActionError("Give the label a name (40 characters at most).")
    if folder and not _NAME.fullmatch(folder):
        raise ActionError("A folder name has 40 characters at most.")
    if color not in COLORS:
        raise ActionError("Pick one of the colours.")
    return name, color, folder


def _one(core: Core, workspace_id: str, label_id: int) -> dict[str, Any]:
    for label in listing(core, workspace_id):
        if label["id"] == label_id:
            return label
    raise NotFoundError("This label")


def create(
    core: Core, workspace_id: str, name: str, color: str = "gray", folder: str = ""
) -> dict[str, Any]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    name, color, folder = _clean(name, color, folder)
    existing = listing(core, workspace_id)
    if any(lb["name"].lower() == name.lower() for lb in existing):
        raise ActionError("A label with this name exists already.")
    if len(existing) >= MAX_LABELS:
        raise ActionError(f"{MAX_LABELS} labels at most.")
    with transaction(core.db):
        new = labels_repo.insert(core.db, workspace_id, name, color, folder)
    return _one(core, workspace_id, new)


def update(
    core: Core,
    workspace_id: str,
    label_id: int,
    *,
    name: str | None = None,
    color: str | None = None,
    folder: str | None = None,
) -> dict[str, Any]:
    """Rename / recolour / move to another folder: the cards keep it (they name it
    by its id)."""
    old = _one(core, workspace_id, label_id)
    new_name, new_color, new_folder = _clean(
        old["name"] if name is None else name,
        old["color"] if color is None else color,
        old["folder"] if folder is None else folder,
    )
    if new_name.lower() != old["name"].lower() and any(
        lb["name"].lower() == new_name.lower() for lb in listing(core, workspace_id)
    ):
        raise ActionError("A label with this name exists already.")
    with transaction(core.db):
        labels_repo.update(core.db, workspace_id, label_id, new_name, new_color, new_folder)
    return _one(core, workspace_id, label_id)


def rename_folder(core: Core, workspace_id: str, old: str, new: str) -> list[dict[str, Any]]:
    """A folder is its labels' group: renaming it moves them all ('' = no folder)."""
    _name, _color, new = _clean("x", "gray", new)
    old = " ".join(old.split())
    if not old:
        raise ActionError("Pick a folder.")
    with transaction(core.db):
        labels_repo.move_folder(core.db, workspace_id, old, new)
    return listing(core, workspace_id)


def remove(core: Core, workspace_id: str, label_id: int) -> None:
    """The label goes, and off every card that carries it (their Hermes bodies)."""
    _one(core, workspace_id, label_id)
    carrying = [c for c, ids in _card_labels(core, workspace_id).items() if label_id in ids]
    if carrying:
        apply(core, workspace_id, carrying, add=[], remove=[label_id])
    with transaction(core.db):
        labels_repo.delete(core.db, workspace_id, label_id)


def _bodies(core: Core, workspace_id: str) -> dict[str, str]:
    """Every card's Hermes body, from the board as listed (one cached read)."""
    from agos_core.actions import kanban_board

    return {
        str(c["id"]): str(c.get("body") or "")
        for c in kanban_board._listed(core, workspace_id)
        if isinstance(c, dict) and c.get("id")
    }


def _card_labels(core: Core, workspace_id: str) -> dict[str, list[int]]:
    return {c: rules.card_labels(b) for c, b in _bodies(core, workspace_id).items()}


def apply(
    core: Core, workspace_id: str, cards: list[str], *, add: list[int], remove: list[int]
) -> dict[str, Any]:
    """Labels on / off these cards: each changed body written by Hermes (one process
    for all of them). Returns {done, failed}."""
    from agos_core.actions import kanban_board

    known = {lb["id"] for lb in listing(core, workspace_id)}
    unknown = [i for i in add if i not in known]
    if unknown:
        raise ActionError("Unknown label.")
    bodies = _bodies(core, workspace_id)
    changed: dict[str, str] = {}
    for card in cards:
        if card not in bodies:
            raise NotFoundError(f"Card {card}")
        body = bodies[card]
        before = rules.card_labels(body)
        after = [i for i in before if i not in remove] + [
            i for i in add if i not in before and i not in remove
        ]
        if after != before:
            changed[card] = rules.with_labels(body, after)
    if not changed:
        return {"done": list(cards), "failed": {}}
    out = kanban_board.edit_bodies(core, workspace_id, changed)
    out["done"] = sorted({*out["done"], *(c for c in cards if c not in changed)})
    return out


def set_card(core: Core, workspace_id: str, card_id: str, ids: list[int]) -> dict[str, Any]:
    """Exactly these labels on the card (the modal's picker)."""
    current = _card_labels(core, workspace_id).get(card_id)
    if current is None:
        raise NotFoundError("This card")
    return apply(
        core,
        workspace_id,
        [card_id],
        add=[i for i in ids if i not in current],
        remove=[i for i in current if i not in ids],
    )


def for_agent(
    core: Core, workspace_id: str, *, action: str, card: str, names: list[str]
) -> dict[str, Any]:
    """An agent's agos_label tool, inside this workspace only."""
    labels = listing(core, workspace_id)
    if action == "list":
        return {"labels": [{"name": lb["name"], "folder": lb["folder"]} for lb in labels]}
    by_name = {lb["name"].lower(): lb["id"] for lb in labels}
    missing = [n for n in names if n.strip().lower() not in by_name]
    if missing:
        return {
            "error": f"Unknown label(s): {', '.join(missing)}. The labels are: "
            + (", ".join(lb["name"] for lb in labels) or "none yet")
            + "."
        }
    ids = [by_name[n.strip().lower()] for n in names]
    if not card:
        return {"error": "Say which card (its id, t_...)."}
    try:
        done = apply(
            core,
            workspace_id,
            [card],
            add=ids if action == "add" else [],
            remove=ids if action == "remove" else [],
        )
    except (ActionError, NotFoundError) as error:
        return {"error": str(error)}
    if done["failed"]:
        return {"error": str(next(iter(done["failed"].values())))}
    return {"ok": True, "card": card, action: [n.strip() for n in names]}
