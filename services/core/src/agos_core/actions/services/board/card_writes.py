"""Writes on one Kanban card through Hermes's own Kanban CLI: make it, comment on it,
give it to a member, press one of its buttons (unblock, archive, done, block), and
Hermes's own estimate of it.

Split out of agos_core.actions.kanban_board (its `create`, `comment`, `assign`, `act`,
`estimate`, `_moved`).

Owns: the argv of those Hermes commands and the checks before them (a title, a
known skill or parent card, a member of the team), and telling the card's pipeline
rules when AGOS moved it.
Must not: read the board for a page (board_list.py, card_detail.py) or write many
cards at once (card_bulk.py).
"""

from __future__ import annotations

import re
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.actions.services.board import card_members, kanban_cli
from agos_core.actions.services.board.card_text import PINS_BLOCK, complete_args, with_criteria
from agos_core.context import Core
from agos_core.engine.hermes import EngineError

__all__ = [
    "ACTIONS",
    "act",
    "assign",
    "comment",
    "create",
    "estimate",
    "moved",
]

_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")  # a skill's or a card's id, as Hermes takes it

ACTIONS = {
    "unblock": ("unblock",),
    "archive": ("archive",),
    "done": ("complete",),
    "block": ("block",),
}


def create(
    core: Core,
    workspace_id: str,
    title: str,
    body: str,
    member: str,
    *,
    criteria: list[str] | None = None,
    model: dict[str, Any] | None = None,
    goal: bool = False,
    parents: list[str] | None = None,
    triage: bool = False,
    once: str = "",
    created_by: str = card_members.OWNER,
    blocked: bool = False,
    skills: list[str] | None = None,
    goal_id: int | None = None,
    founder: bool = False,
) -> str:
    """One card by Hermes's `kanban create`. `goal_id`: the sub-goal it serves (its
    body starts with that '## Goal' line). `blocked`: born blocked (Hermes's
    --initial-status blocked, untyped), so the dispatcher never sees it ready before
    the typed `kanban block` that follows classifies it in place (hermes_cli/kanban_db.py
    block_task). `skills`: the workspace skills Hermes force-loads for the worker (its
    `--skill`, tasks.skills); the skill versions at this moment go into the body as a
    pins block, so the run's output can be traced to the exact text the worker read
    (actions/skill_versions.py). `founder`: the owner's or the Co-Founder's call, so
    the member may be `founder`, the owner himself (actions/founder.py)."""
    title = title.strip()
    if not title:
        raise ActionError("Give the card a title.")
    args = ["create", title[:200], "--json", "--created-by", created_by or card_members.OWNER]
    text = with_criteria(body, criteria or [])
    skill_args, text = _skills(core, workspace_id, skills or [], text)
    args += skill_args
    if goal_id:
        from agos_core.actions import goals

        # The sub-goal it serves: the body's first section, the line its agent reads.
        text = f"{goals.card_line(core, workspace_id, goal_id)}\n\n{text}".strip()
    if text:
        args += ["--body", text]
    profile = card_members.profile_of(core, workspace_id, member, founder=founder)
    if profile != "none":
        args += ["--assignee", profile]
    args += _model_args(model)
    args += _flags(goal=goal, parents=parents or [], triage=triage, once=once, blocked=blocked)
    raw = kanban_cli.answer(kanban_cli.run(core, workspace_id, *args))
    card_id = str((raw.get("task") or raw).get("id") or "") if isinstance(raw, dict) else ""
    if not card_id:
        raise ActionError("Hermes's Kanban didn't make the card.")
    return card_id


def _skills(core: Core, workspace_id: str, skills: list[str], text: str) -> tuple[list[str], str]:
    """`--skill` for each skill Hermes force-loads, and the body with their pins block."""
    from agos_core.engine import card_blocks

    wanted = [s.strip() for s in skills if s.strip()]
    if not wanted:
        return [], text
    from agos_core.actions import skill_versions

    args: list[str] = []
    for name in wanted:
        if not _NAME.fullmatch(name):
            raise ActionError("Unknown skill to load.")
        args += ["--skill", name]
    pins = skill_versions.pins(core, workspace_id, wanted)
    if pins:
        text = card_blocks.with_block(text, PINS_BLOCK, pins)
    return args, text


def _model_args(model: dict[str, Any] | None) -> list[str]:
    """`--provider` / `--model` of a card's own model (none: the member's)."""
    if not (model and model.get("model") and model.get("provider")):
        return []
    from agos_core.engine.models import hermes_slug

    return [
        "--provider",
        hermes_slug(str(model["provider"]), str(model.get("mode") or "subscription")),
        "--model",
        str(model["model"]),
    ]


def _flags(*, goal: bool, parents: list[str], triage: bool, once: str, blocked: bool) -> list[str]:
    """The rest of `kanban create`'s flags: goal mode, the cards it waits for, triage,
    Hermes's own dedup key, born blocked."""
    args = ["--goal"] if goal else []
    for parent in parents:
        if not _NAME.fullmatch(parent):
            raise ActionError("Unknown card to wait for.")
        args += ["--parent", parent]
    if triage:
        args.append("--triage")
    if once:
        # Hermes's own dedup: the same work asked again is the same card.
        args += ["--idempotency-key", once]
    if blocked:
        args += ["--initial-status", "blocked"]
    return args


def estimate(core: Core, workspace_id: str, card_id: str) -> dict[str, Any]:
    """Hermes's own estimate (its auxiliary model): rough tokens and S / M / L."""
    if core.engine is None:
        raise ActionError("Hermes isn't set up yet.")
    try:
        # A plugin command: Hermes imports the root's plugins, so it runs walled.
        out = kanban_cli.plugin(core, workspace_id, "agos-estimate", card_id, timeout=120)
    except EngineError as error:
        raise ActionError(f"Hermes didn't estimate it: {error}") from error
    found = kanban_cli.answer(out)
    if not isinstance(found, dict) or not found.get("ok"):
        reason = found.get("reason") if isinstance(found, dict) else ""
        raise ActionError(f"Hermes couldn't estimate it: {reason or 'no answer'}.")
    return {
        "tokens": int(found.get("est_tokens") or 0),
        "complexity": str(found.get("complexity") or ""),
        "why": str(found.get("rationale") or ""),
    }


def comment(core: Core, workspace_id: str, card_id: str, text: str) -> None:
    if not text.strip():
        raise ActionError("Write something first.")
    kanban_cli.run(
        core, workspace_id, "comment", card_id, text.strip(), "--author", card_members.OWNER
    )


def assign(
    core: Core, workspace_id: str, card_id: str, member: str, *, founder: bool = False
) -> None:
    profile = card_members.profile_of(core, workspace_id, member, founder=founder)
    kanban_cli.run(core, workspace_id, "assign", card_id, profile)
    moved(core, workspace_id, card_id)
    if profile == "founder":
        from agos_core.actions import founder as founder_actions

        founder_actions.tell(core, workspace_id)


def moved(core: Core, workspace_id: str, card_id: str) -> None:
    """AGOS moved the card itself: its pipeline rules look at once (Hermes's hook in
    the CLI process tells it too; the rules act once per move: actions/pipelines.py)."""
    from agos_core.actions import pipelines

    pipelines.card_moved(core, workspace_id, card_id)


def act(core: Core, workspace_id: str, card_id: str, action: str, summary: str = "") -> None:
    if action not in ACTIONS:
        raise ActionError("Unknown action.")
    if action == "done":
        kanban_cli.run(core, workspace_id, *complete_args(card_id, summary))
    else:
        args = [*ACTIONS[action], card_id]
        if action == "block":
            args.append("Stopped by the owner.")
        kanban_cli.run(core, workspace_id, *args)
    moved(core, workspace_id, card_id)
