"""Status cards, their definition: the row, its scope and policy checked, where its summary and changes live, its schedule.
Must not: write a summary or a cron job.

Split out of agos_core.actions.status_cards (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import status_cards
from agos_core.engine import card_docs as doc_rules
from agos_core.storage.layout import workspace_paths

__all__ = [
    "CHANGES",
    "DEFAULT_DAY",
    "DEFAULT_TIME",
    "FOLDER",
    "JOB_NAME",
    "KEY",
    "MAX_SUMMARY",
    "POLICIES",
    "PROMPT",
    "SCOPES",
    "SCRIPT",
    "SUMMARY",
    "scope_label",
    "titles",
]

log = logging.getLogger("agos.status_cards")

FOLDER = "status"  # <workspace files>/status/<id>/summary.md
SUMMARY = "summary.md"
KEY = "summary"
CHANGES = "CHANGES.md"
SCOPES = ("workspace", "goal", "project", "member", "query")
POLICIES = ("daily", "weekly", "manual")
JOB_NAME = "AGOS status card {}"
SCRIPT = "agos-status-{}.py"
MAX_SUMMARY = 20_000
_SCHEDULE = re.compile(r"^(\d{1,2}) (\d{1,2}) \* \* (\*|[0-6])$")
DEFAULT_TIME = "08:00"
DEFAULT_DAY = 1  # Monday

PROMPT = "\n".join(
    [
        "This is the status card run for “{title}” (status card {id}): write its short"
        " summary for the owner.",
        "",
        "1. Call agos_status_card with action read and card {id}: the scope ({scope}),"
        " its cards (status, who has it, comments), what moved since your last summary,"
        " the goal's key results, and your last summary.",
        "2. The read says nothing moved since your last summary and the owner did not ask"
        " for a refresh: answer `Nothing to do.` and stop without writing. This run must"
        " stay cheap.",
        "3. Otherwise write the new summary with agos_status_card: action write, card {id},"
        " summary in markdown, at most about 200 words: one first line that says where it"
        " stands (on track / at risk / blocked) and why, then Done since last time, In"
        " progress, Blocked or waiting (on whom), Next. Name each card by its id. Only"
        " facts from the read, no guesses.",
        "",
        "Never create, move or close cards in this run and never write to the owner otherwise.",
    ]
)


# ---- the rows ------------------------------------------------------------------------------


def _row(core: Core, workspace_id: str, card_id: int) -> Any:
    row = status_cards.get(core.db, workspace_id, card_id)
    if row is None:
        raise NotFoundError("This status card")
    return row


def titles(core: Core, workspace_id: str) -> dict[int, str]:
    """{card id: title} of the workspace's status cards (search reads its summaries)."""
    return status_cards.titles(core.db, workspace_id)


def _check(
    core: Core, workspace_id: str, title: str, scope: str, scope_ref: str, policy: str
) -> tuple[str, str, str, str]:
    title = " ".join(title.split())[:120]
    if not title:
        raise ActionError("Give the status card a title.")
    if scope not in SCOPES:
        raise ActionError("A scope is the workspace, a goal, a project, a member or some words.")
    if policy not in POLICIES:
        raise ActionError("It updates daily, weekly or when you ask.")
    ref = " ".join(scope_ref.split())[:200]
    if scope == "workspace":
        ref = ""
    elif scope in ("goal", "project"):
        if not ref.isdigit():
            raise ActionError(f"Pick the {scope}.")
        found = goals_repo.get(core.db, workspace_id, int(ref))
        if found is None or str(found["level"] or "goal") != scope:
            raise ActionError(f"This {scope} isn't in the workspace's plan.")
    elif scope == "member":
        from agos_core.actions import agent_profiles

        if ref not in agent_profiles.team_names(core, workspace_id):
            raise ActionError("Pick a member of this workspace's team.")
    elif scope == "query":
        from agos_core.actions.search import terms

        if not terms(ref):
            raise ActionError("Give the words the cards must have.")
    return title, scope, ref, policy


# ---- the summary document (revisions like a card's documents) --------------------------------


def _folder(core: Core, workspace_id: str, card_id: int) -> Path:
    return workspace_paths(core.layout, workspace_id).files / FOLDER / str(int(card_id))


def _paths(core: Core, workspace_id: str, card_id: int) -> tuple[Path, Path, Path]:
    folder = _folder(core, workspace_id, card_id)
    history = folder / doc_rules.REVISIONS / KEY
    return folder / SUMMARY, history, history / CHANGES


def _revisions(changes: Path) -> list[doc_rules.Revision]:
    try:
        return doc_rules.parse_changes(changes.read_text(errors="replace"))
    except OSError:
        return []


def _body(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def scope_label(core: Core, workspace_id: str, row: Any) -> str:
    scope, ref = str(row["scope"]), str(row["scope_ref"])
    if scope == "workspace":
        return "the whole workspace"
    if scope in ("goal", "project"):
        found = goals_repo.get(core.db, workspace_id, int(ref))
        return f"{scope} “{found['title']}”" if found else f"{scope} {ref} (gone)"
    if scope == "member":
        return f"@{ref}'s cards"
    return f"cards with “{ref}”"


# ---- the Hermes job -------------------------------------------------------------------------


def _schedule(time: str, day: int | None, policy: str) -> str:
    hours, minutes = time.split(":")
    return (
        f"{int(minutes)} {int(hours)} * * {day if policy == 'weekly' and day is not None else '*'}"
    )


def _when(schedule: str | None) -> tuple[str, int | None]:
    found = _SCHEDULE.match(str(schedule or "").strip())
    if found is None or int(found[1]) > 59 or int(found[2]) > 23:
        return DEFAULT_TIME, None
    return f"{int(found[2]):02d}:{int(found[1]):02d}", None if found[3] == "*" else int(found[3])
