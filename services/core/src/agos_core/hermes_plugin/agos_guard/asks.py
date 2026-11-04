"""The agents' two tools for the owner: `agos_propose` (a hire, a change to its own
instructions, a plan) and `agos_ask_owner` (a typed question). Both are Hermes
Kanban cards AGOS makes for the agent through Hermes's own CLI, blocked for the
owner (needs_input), in the same shape AGOS's parsers read (engine/proposals.py,
engine/questions.py), so no agent hand-writes a fenced block.

A question asked while working a card (HERMES_KANBAN_TASK) is linked as that card's
parent — by this worker itself, with its run id (Hermes's own rule: only the owning
run may link a parent onto a running card, hermes_cli/kanban_db.py link_tasks) — and
the agent is told to block its card as a `dependency`: Hermes then wakes it when the
question card is completed with the answer (recompute_ready), with the answer in
its context (_ctx_parent_results). No needs_input re-block of the working card, so
Hermes's unblock-loop breaker (BLOCK_RECURRENCE_LIMIT) never sends it to triage.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

log = logging.getLogger("agos_guard")

TOOL_WAIT_S = 120

PROPOSE_SCHEMA = {
    "name": "agos_propose",
    "description": (
        "Propose something to the owner: a hire (kind 'hire', the ONLY way to a new "
        "agent: payload name, title, role, skills (only ones this workspace has), model "
        "(required, sized to the work: {model: the exact id of one version the "
        "workspace's provider lists in Hermes's catalog, never a bare family, effort: "
        "low|medium|high}; small repetitive work = small model + low, deep work = big + "
        "high; nothing else in it), model_why (required, its own field: one line), "
        "telegram_topic, reports_to, why: the gap against the goal and why no member "
        "covers it, goal_id: the number of the goal or project it serves (required while "
        "the workspace has one open), source_card: the card the need came from, if any, "
        "and kit (required and whole: tools, skills, docs and onboarding {task, "
        "criteria}, none empty, at least one skill from this workspace's library; team "
        "context too); AGOS refuses a hire missing any of it and says what; follow your "
        "team-design skill), a whole kit for a member ALREADY on the team (kind 'kit': "
        "payload member, kit (as a hire's, whole), model and model_why (as a hire's), why, "
        "source_card; the owner approves it in his Inbox), a goal change (kind "
        "'goal', the payload agos_goals describes), a change to your own instructions "
        "(kind 'instructions': payload target SOUL.md|config.yaml|AGENTS.md|profile.yaml, "
        "diff, sha256 of the WHOLE new file, summary) or a plan he must OK before work "
        "starts (kind 'plan': payload title, markdown). AGOS puts it on a Kanban card in "
        "his Inbox (Approve / Revise / Reject); his answer comes back on the card. After a "
        "revise, propose again with revises=<the old card>."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["hire", "instructions", "plan", "goal", "kit"]},
            "payload": {"type": "object", "additionalProperties": True},
            "words": {"type": "string", "description": "Your own words to the owner (optional)."},
            "revises": {"type": "string", "description": "The card of the round he sent back."},
        },
        "required": ["kind", "payload"],
    },
}

ASK_OWNER_SCHEMA = {
    "name": "agos_ask_owner",
    "description": (
        "Ask the owner a typed question and wait for his answer on a Kanban card: kind "
        "'ask' (free text), 'confirm' (yes / no), 'choice' (one of options), 'checkbox' "
        "(several of options), 'verdicts' (approve / reject each of items), "
        "'suggest_tasks' (tasks he accepts one by one; each accepted one becomes a card). "
        "Working a card: the tool links the question to it; then block YOUR card with "
        "kanban_block(kind='dependency', reason=<the tool's reason>) and stop — it comes "
        "back to you with his answer. From a chat: the question card comes back to you "
        "with the answer. Ask one thing per call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["ask", "confirm", "choice", "checkbox", "verdicts", "suggest_tasks"],
            },
            "question": {"type": "string"},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "choice / checkbox: the options (2 to 30, short labels).",
            },
            "items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "verdicts: what he approves or rejects, one per entry.",
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "member": {"type": "string"},
                    },
                    "required": ["title"],
                },
                "description": "suggest_tasks: the cards you suggest (title, body, member).",
            },
            "continuation": {
                "type": "string",
                "enum": ["wake_assignee", "none"],
                "description": "wake_assignee (default): you get the answer; none: he just records it.",
            },
        },
        "required": ["kind", "question"],
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


def propose_tool(
    args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    body: dict[str, Any] = {
        "member": member,
        "kind": str(args.get("kind") or ""),
        "payload": args.get("payload") if isinstance(args.get("payload"), dict) else {},
        "words": str(args.get("words") or "")[:20_000],
        "revises": str(args.get("revises") or "")[:64],
        "card": _card(),
    }
    answer = post("propose", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; nothing was proposed."})
    if answer.get("error"):
        return json.dumps(answer)
    return json.dumps(
        {
            **answer,
            "next": (
                f"Your proposal is on card {answer.get('card')} in the owner's Inbox. Go on "
                "with your work (or finish); his decision comes back as a comment on that "
                "card, and the card comes back to you when it needs you."
            ),
        }
    )


def ask_owner_tool(
    args: dict[str, Any], *, member: str, post: Callable[..., dict[str, Any] | None]
) -> str:
    card = _card()
    payload: dict[str, Any] = {"question": str(args.get("question") or "")}
    for key in ("options", "items", "tasks"):
        if isinstance(args.get(key), list):
            payload[key] = args[key]
    body = {
        "member": member,
        "kind": str(args.get("kind") or "ask"),
        "payload": payload,
        "continuation": str(args.get("continuation") or "wake_assignee"),
        "card": card,
    }
    answer = post("ask-owner", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; nothing was asked."})
    if answer.get("error"):
        return json.dumps(answer)
    question = str(answer.get("card") or "")
    if not card:
        return json.dumps(
            {
                **answer,
                "next": f"Card {question} waits for the owner. His answer comes back to you "
                "on that card; nothing to do now.",
            }
        )
    linked, why = _link_parent(question, card)
    if linked:
        reason = f"waiting for the owner's answer on {question}"
        return json.dumps(
            {
                **answer,
                "linked": True,
                "next": f'Now call kanban_block(kind="dependency", reason="{reason}") and stop. '
                f"Hermes brings this card back to you with his answer (card {question}).",
            }
        )
    return json.dumps(
        {
            **answer,
            "linked": False,
            "next": f"Card {question} waits for the owner ({why}). Finish what you can, say in "
            f"your result that {question} holds the open question, and complete this card; "
            "his answer lands on that card.",
        }
    )


def _link_parent(parent: str, child: str) -> tuple[bool, str]:
    """Hermes's own link, by the owning run: `parent` gates `child`."""
    try:
        from hermes_cli import kanban_db as kb  # type: ignore[import-not-found]
        from hermes_cli import kanban_db_connect as kbc
    except ImportError as error:
        return False, f"not inside Hermes: {error}"
    run_id = _run_id()
    if run_id is None:
        return False, "this run has no id to prove it owns the card"
    try:
        conn = kbc.connect()
        try:
            kb.link_tasks(conn, parent, child, expected_child_run_id=run_id)
        finally:
            conn.close()
    except Exception as error:  # noqa: BLE001 — Hermes said no: the agent is told why
        log.info("AGOS: question %s not linked to %s: %s", parent, child, error)
        return False, str(error)[:200]
    return True, ""


def register(
    ctx: Any, *, member_of: Callable[[], str], post: Callable[..., Any], guard: Any
) -> None:
    def propose(args: dict[str, Any], **_: Any) -> str:
        return propose_tool(args, member=member_of(), post=post)

    def ask_owner(args: dict[str, Any], **_: Any) -> str:
        return ask_owner_tool(args, member=member_of(), post=post)

    for schema, handler, emoji in (
        (PROPOSE_SCHEMA, propose, "📋"),
        (ASK_OWNER_SCHEMA, ask_owner, "❓"),
    ):
        with guard("hermes_cli.plugins.PluginContext.register_tool"):
            ctx.register_tool(
                name=str(schema["name"]),
                toolset="agos",
                schema=schema,
                handler=handler,
                description=str(schema["description"]),
                emoji=emoji,
            )
