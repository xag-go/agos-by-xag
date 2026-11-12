"""Moving a hire forward: the onboarding test, its grade and retries, the owner's choices, the sweep.
Must not: store or fill a kit.

Split out of agos_core.actions.hire_kit (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.hire import kit_files  # sync_dispatch: looked up there
from agos_core.actions.services.hire.kit_files import _give
from agos_core.actions.services.hire.kit_store import (
    _CLOSED,
    FIX_KEY,
    ONBOARD_KEY,
    OWNER_CHOICES,
    READY_KEY,
    _advance_guard,
    _advance_locks,
    kit_members,
    kit_of,
)
from agos_core.actions.services.hire.readiness import _cards, readiness, state_of
from agos_core.context import Core
from agos_core.db import member_readiness as readiness_repo
from agos_core.db.connection import transaction
from agos_core.engine import hire_kit as rules
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "advance",
    "choose",
    "sweep",
]

log = logging.getLogger("agos.hire_kit")  # the old module's logger (one name)


def _set_choice(
    core: Core, workspace_id: str, member: str, item: str, choice: str, reason: str
) -> None:
    with transaction(core.db):
        readiness_repo.save(
            core.db, workspace_id, member, item[:200], choice, reason.strip()[:2000]
        )


def choose(
    core: Core, workspace_id: str, member: str, item: str, choice: str, reason: str = ""
) -> dict[str, Any]:
    """The owner's button on one item: Not needed (with his reason), Start anyway,
    Skip test, Retry (the onboarding test again), Make topic, or clear (undo of his
    choice). Readiness moves on right after."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    view = readiness(core, workspace_id, member)
    if view is None:
        raise NotFoundError("This member's kit")
    ids = {i["id"] for i in view["items"]}
    if choice == "not_needed":
        if item not in ids or item == "onboarding":
            raise ActionError("Not an item of this member's checklist.")
        _set_choice(core, workspace_id, member, item, choice, reason or "the owner: not needed")
    elif choice == "start_anyway":
        _set_choice(core, workspace_id, member, "member", choice, reason or "the owner started it")
    elif choice == "skip_test":
        _set_choice(core, workspace_id, member, "onboarding", choice, reason or "the owner")
    elif choice == "clear":
        target = "member" if item == "member" else item
        with transaction(core.db):
            readiness_repo.clear(core.db, workspace_id, member, target, OWNER_CHOICES)
    elif choice == "retry":
        onboarding = view.get("onboarding")
        if not onboarding or not onboarding.get("task"):
            raise ActionError("This member has no onboarding test.")
        if any(t["status"] not in _CLOSED for t in onboarding["tries"]):
            raise ActionError("Its test is running now.", 409)
        if view["state"] == "not_ready":
            raise ActionError("Make it ready first: its test runs once every item is there.", 409)
        _new_try(core, workspace_id, member, len(onboarding["tries"]) + 1, parents=None)
    elif choice == "make_topic":
        from agos_core.actions import hermes_channel, workers

        dm = workers.open_dm(core, workspace_id, member)
        hermes_channel.topic_for(core, workspace_id, dm)
    else:
        raise ActionError("Choose not_needed, start_anyway, skip_test, retry, make_topic or clear.")
    shown = advance(core, workspace_id, member)
    assert shown is not None
    return shown


# ---- moving on ---------------------------------------------------------------------------


def _lock(workspace_id: str) -> threading.Lock:
    with _advance_guard:
        return _advance_locks.setdefault(workspace_id, threading.Lock())


def advance(core: Core, workspace_id: str, member: str) -> dict[str, Any] | None:
    """Readiness moves on: what AGOS can give it is given (library skills, files),
    then the Co-Founder's card for what is still missing, or the onboarding test,
    and Hermes's dispatcher list follows. Safe to repeat (cards are keyed)."""
    if kit_of(core, workspace_id, member) is None or core.engine is None:
        return None
    with _lock(workspace_id):
        view = readiness(core, workspace_id, member)
        if view is None:
            return None
        if view["state"] != "ready":
            changed = _give(core, workspace_id, member, view)
            if changed:
                view = readiness(core, workspace_id, member) or view
        if view["state"] == "not_ready":
            _ask_cofounder(core, workspace_id, member, view)
        elif view["state"] == "onboarding":
            _onboard(core, workspace_id, member, view)
        kit_files.sync_dispatch(core, workspace_id)
        return readiness(core, workspace_id, member)


def _ask_cofounder(core: Core, workspace_id: str, member: str, view: dict[str, Any]) -> str | None:
    """ONE card on the Co-Founder for what is missing now (the same missing set is
    the same card: Hermes's idempotency key)."""
    from agos_core.actions import kanban_board

    missing = [i for i in view["items"] if i["state"] == "missing" and i["action"] != "wait"]
    if not missing:
        return None
    key = f"{READY_KEY}{member}:{rules.missing_digest([i['id'] for i in missing])}"
    found = [c for c in _cards(core, workspace_id, f"{READY_KEY}{member}:") if c["key"] == key]
    if found:
        return str(found[0]["id"])
    try:
        return kanban_board.create(
            core,
            workspace_id,
            f"Make @{member} ready",
            rules.gap_body(member, view["title"], [rules.gap_line(i) for i in missing]),
            kanban_board.COFOUNDER,
            once=key,
        )
    except ActionError as error:
        log.warning("readiness card of %s not made: %s", member, error.message)
        return None


def _new_try(
    core: Core, workspace_id: str, member: str, n: int, *, parents: list[str] | None
) -> str | None:
    from agos_core.actions import kanban_board

    kit = kit_of(core, workspace_id, member) or {}
    test = kit.get("onboarding") or {}
    try:
        return kanban_board.create(
            core,
            workspace_id,
            f"Onboarding test of @{member}" + (f" (try {n})" if n > 1 else ""),
            rules.onboard_body(
                member, str(test.get("task") or ""), list(test.get("criteria") or []), n
            ),
            member,
            parents=parents,
            once=f"{ONBOARD_KEY}{member}:{n}",
        )
    except ActionError as error:
        log.warning("onboarding card %s of %s not made: %s", n, member, error.message)
        return None


def _onboard(core: Core, workspace_id: str, member: str, view: dict[str, Any]) -> None:
    """The onboarding test: its first card, the grade of a finished one, and after a
    failure the Co-Founder's fix card with the next try waiting on it."""
    from agos_core.actions import kanban_board

    onboarding = view["onboarding"]
    if onboarding is None or onboarding["escalated"]:
        return
    tries = onboarding["tries"]
    if not tries:
        _new_try(core, workspace_id, member, 1, parents=None)
        return
    last = tries[-1]
    if last["status"] != "done" or last["grade"] is not None:
        return
    cards = {str(c["id"]): c for c in _cards(core, workspace_id, f"{ONBOARD_KEY}{member}:")}
    output = str(cards.get(last["card"], {}).get("result") or "")
    passed, notes = _grade(
        core,
        workspace_id,
        rules.grade_job(member, onboarding["task"], onboarding["criteria"], output),
    )
    if passed is None:
        return  # not graded now (the grader failed): the next look tries again
    _set_choice(
        core,
        workspace_id,
        member,
        f"onboard:{last['card']}",
        "passed" if passed else "failed",
        notes,
    )
    if passed:
        return
    failed = sum(1 for t in tries if t["grade"] == "failed") + 1
    if failed >= rules.MAX_TRIES:
        return  # the owner decides (his Inbox)
    try:
        fix = kanban_board.create(
            core,
            workspace_id,
            f"Fix @{member}'s onboarding (try {last['n']} failed)",
            rules.fix_body(member, last["n"], notes, onboarding["task"]),
            kanban_board.COFOUNDER,
            once=f"{FIX_KEY}{member}:{last['n']}",
        )
    except ActionError as error:
        log.warning("onboarding fix card of %s not made: %s", member, error.message)
        return
    _new_try(core, workspace_id, member, last["n"] + 1, parents=[fix])


def _grade(core: Core, workspace_id: str, job: dict[str, str]) -> tuple[bool | None, str]:
    """Skill Studio's grader (`hermes agos-grade`, the auxiliary model): (passed,
    notes), (None, why) when it couldn't grade."""
    from agos_core.actions import skill_tests
    from agos_core.engine.hermes import EngineError

    if core.engine is None:
        return None, "The engine isn't set up."
    try:
        said = hermes_cli.walled_cli(
            core.engine,
            workspace_id,
            "agos-grade",
            json.dumps(job, ensure_ascii=False),
            timeout=120,
        )
    except EngineError as error:
        log.warning("onboarding test of %s not graded: %s", job.get("skill"), error)
        return None, str(error)
    found = skill_tests._last_json(said)
    if not found.get("ok"):
        return None, str(found.get("reason") or "no answer")
    return bool(found.get("pass")), str(found.get("notes") or "")


def sweep(core: Core, workspace_id: str) -> int:
    """Hermes's dispatcher ticked or a card moved: every member not ready yet moves
    on (a connector the owner connected, a skill the Co-Founder wrote, a finished
    test). Returns how many were looked at. Never raises."""
    looked = 0
    for member in kit_members(core, workspace_id):
        try:
            if state_of(core, workspace_id, member) == "ready":
                continue
            looked += 1
            advance(core, workspace_id, member)
        except Exception:
            log.exception("readiness of %s in %s not moved on", member, workspace_id)
    return looked
