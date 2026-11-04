"""The agents' review tool, `agos_review` (Step 52), and the guard's check on the
finishing calls of a card under review rules.

AGOS decides (api/hermes_bridge.py review -> actions/reviews.py verdict): whether
the caller may give this verdict now, and the ONE Hermes step that follows. This
module takes that step on Hermes's own board, with Hermes's own functions and the
agent's own run id (hermes_cli/kanban_db.py request_review / request_changes /
complete_task / block_task / schedule_task / assign_task / unblock_task /
link_tasks / add_comment), exactly as Hermes's kanban_* tools would from this run:
- hand: to the next reviewer (a profile Hermes's dispatcher wakes in its review
  lane, or `owner`, a name no profile has, so it waits for him). From the
  implementer's own run that is request_review; from a reviewer's run the card goes
  back to the implementer first (schedule, assign, unblock), so the review handoff
  Hermes records names the real implementer (request_changes / reopen_review route
  on it, hermes_cli/kanban_db.py request_review `implementer`);
- done: complete_task (the last stage approved);
- back: request_changes (Hermes routes it to the implementer);
- return: the plan accepted, the card back to its implementer to work (after its
  plan's task cards are linked as the cards it waits for);
- stuck: block_task needs_input "waiting for the owner: stuck in review after N
  rounds" (the round cap).
Then the marker comment AGOS gave, and AGOS hears it landed (the owner is told when
the card waits for him).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

log = logging.getLogger("agos_guard")

TOOL_WAIT_S = 120
CHECK_WAIT_S = 20
# The kanban tools of a card's own worker the guard asks AGOS about.
CHECKED = ("kanban_complete", "kanban_request_review", "kanban_request_changes", "kanban_create")

SCHEMA = {
    "name": "agos_review",
    "description": (
        "Review and plan-first on a Kanban card. When AGOS refuses kanban_complete because "
        "the card has review stages, finish with verdict 'submit' (summary: what you did and "
        "how you checked it): AGOS hands it to the stage's reviewer (your lead, the "
        "Co-Founder, the owner). A card that needs a plan first: write the plan as the card "
        "document 'plan' (agos_card_document; a '## Tasks' list of '- <title> @<member>' "
        "lines becomes cards on accept), then verdict 'plan_ready', and stop until it is "
        "accepted. When Hermes wakes you on a card in Review (or a plan to accept): read it, "
        "then verdict 'approve' (note optional) or 'changes' with a note saying what to "
        "change; only the current stage's reviewer may answer. After any verdict, stop. "
        'Cards get stages from a body block: ```agos-review {"stages": ["lead", '
        '"cofounder", "owner"], "plan": true}```.'
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "card": {"type": "string", "description": "The card id (default: your card)."},
            "verdict": {
                "type": "string",
                "enum": ["submit", "plan_ready", "approve", "changes"],
            },
            "note": {"type": "string", "description": "changes: what to change (required)."},
            "summary": {
                "type": "string",
                "description": "submit: what you did, how you checked it.",
            },
        },
        "required": ["verdict"],
    },
}


def _card() -> str:
    return os.environ.get("HERMES_KANBAN_TASK", "")


def _run_id() -> int | None:
    raw = os.environ.get("HERMES_KANBAN_RUN_ID", "")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def review_tool(
    args: dict[str, Any],
    *,
    member: str,
    me: str,
    post: Callable[..., dict[str, Any] | None],
    board: Callable[[], Any] | None = None,
) -> str:
    card = str(args.get("card") or _card() or "")
    if not card:
        return json.dumps({"error": "Say which card (card=<id>): you are not working one now."})
    body = {
        "member": member,
        "card": card,
        "verdict": str(args.get("verdict") or ""),
        "note": str(args.get("note") or "")[:4000],
        "summary": str(args.get("summary") or "")[:4000],
        "working": _card(),
    }
    answer = post("review", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; nothing changed."})
    if answer.get("error") or not isinstance(answer.get("step"), dict):
        return json.dumps({"error": str(answer.get("error") or "AGOS gave no step.")})
    done, why = take(answer["step"], card, me, str(answer.get("comment") or ""), board=board)
    if not done:
        return json.dumps({"error": f"Hermes refused the step: {why}. Nothing changed."})
    post("review", {**body, "verdict": "landed"}, TOOL_WAIT_S)
    return json.dumps({"ok": True, "card": card, "next": str(answer.get("say") or "")})


def _connect() -> Any:
    from hermes_cli import kanban_db_connect as kbc  # type: ignore[import-not-found]

    return kbc.connect()


def take(
    step: dict[str, Any],
    card: str,
    me: str,
    comment: str,
    *,
    board: Callable[[], Any] | None = None,
) -> tuple[bool, str]:
    """AGOS's step on Hermes's board, from this run; then its marker comment."""
    try:
        from hermes_cli import kanban_db as kb
    except ImportError as error:
        return False, f"not inside Hermes: {error}"
    run = _run_id()
    if run is None:
        return False, "this run has no id to prove it owns the card"
    try:
        conn = (board or _connect)()
    except Exception as error:  # noqa: BLE001 — no board: the agent is told
        return False, str(error)[:200]
    try:
        ok, why = _step(kb, conn, step, card, run, me)
        if ok and comment:
            kb.add_comment(conn, card, me or "agent", comment)
    except Exception as error:  # noqa: BLE001 — Hermes said no: the agent is told why
        log.info("AGOS: review step on %s refused: %s", card, error)
        return False, str(error)[:300]
    finally:
        conn.close()
    return ok, why


def _step(
    kb: Any, conn: Any, step: dict[str, Any], card: str, run: int, me: str
) -> tuple[bool, str]:
    do = str(step.get("do") or "")
    implementer = str(step.get("implementer") or "")
    if do == "hand":
        to = str(step.get("to") or "")
        summary = str(step.get("summary") or "")
        if implementer and me != implementer:
            # A reviewer's run: back to the implementer first, so Hermes's review
            # handoff records the real implementer.
            if not kb.schedule_task(conn, card, reason=summary, expected_run_id=run):
                return False, "the card isn't running with this run"
            kb.assign_task(conn, card, implementer)
            kb.unblock_task(conn, card)
            run_guard: int | None = None
        else:
            run_guard = run
        result = kb.request_review(
            conn, card, summary=summary, reviewer=to, expected_run_id=run_guard, with_reason=True
        )
        ok, why = result if isinstance(result, tuple) else (bool(result), "")
        return bool(ok), str(why or "")
    if do == "done":
        summary = str(step.get("summary") or "Approved.")
        ok = kb.complete_task(conn, card, summary=summary, result=summary, expected_run_id=run)
        return bool(ok), "" if ok else "the card isn't running with this run"
    if do == "back":
        ok, routed = kb.request_changes(
            conn, card, reason=str(step.get("reason") or ""), expected_run_id=run
        )
        if ok and implementer and routed != implementer:
            kb.assign_task(conn, card, implementer)
        return bool(ok), "" if ok else str(routed or "")
    if do == "return":
        for parent in step.get("link") or []:
            kb.link_tasks(conn, str(parent), card, expected_child_run_id=run)
        if not kb.schedule_task(
            conn, card, reason=str(step.get("reason") or ""), expected_run_id=run
        ):
            return False, "the card isn't running with this run"
        kb.assign_task(conn, card, implementer)
        kb.unblock_task(conn, card)
        return True, ""
    if do == "stuck":
        ok = kb.block_task(
            conn,
            card,
            reason=str(step.get("reason") or ""),
            kind="needs_input",
            expected_run_id=run,
        )
        return bool(ok), "" if ok else "the card isn't running with this run"
    return False, f"unknown step {do!r}"


def guard(
    tool: str, args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    """The refusal of a finishing call on a card under review rules ("" = let it go).
    Only a card's own worker is asked about; AGOS out of reach lets Hermes decide."""
    card = _card()
    if tool not in CHECKED or not card:
        return ""
    if tool != "kanban_create" and str(args.get("task_id") or card) != card:
        return ""
    try:
        answer = post("review-check", {"member": member, "card": card, "tool": tool}, CHECK_WAIT_S)
    except Exception as error:  # noqa: BLE001 — AGOS out of reach: Hermes decides
        log.info("AGOS: review check of %s skipped: %s", card, error)
        return ""
    if not isinstance(answer, dict):
        return ""
    return str(answer.get("refuse") or "")


def register(
    ctx: Any,
    *,
    member_of: Callable[[], str],
    me: Callable[[], str],
    post: Callable[..., Any],
    guard: Any,
) -> None:
    def handler(args: dict[str, Any], **_: Any) -> str:
        return review_tool(args, member=member_of(), me=me(), post=post)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(SCHEMA["name"]),
            toolset="agos",
            schema=SCHEMA,
            handler=handler,
            description=str(SCHEMA["description"]),
            emoji="🔎",
        )
