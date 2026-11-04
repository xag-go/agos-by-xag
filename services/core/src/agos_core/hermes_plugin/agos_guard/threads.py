"""Card threads, labels and the Board's bulk actions inside Hermes (Step 58).

- `post_tool_call` on Hermes's own `kanban_comment` tool: AGOS is told a comment
  landed (the card and Hermes's comment id, posted off the agent's turn). AGOS reads
  the comment back from Hermes's board and wakes only whom it names: the card's
  assignee is Hermes's own business (a running worker gets it steered in by Hermes,
  tools/kanban_tools.py inject_new_comments_from_env), an `@member` is subscribed to
  the card and woken once, `@owner` lands in his Inbox (actions/threads.py).
- `agos_label(action, card, labels)`: an agent lists the workspace's labels, or puts
  them on / takes them off a card (AGOS writes the card's Hermes body).
- `hermes agos-bulk <op> …`: the Board's bulk assign / label edits in ONE Hermes
  process, through Hermes's own writers (kanban_db.assign_task / edit_task) — its
  CLI takes one card per `assign` / `edit`. Prints {"done": [...], "failed": {...}}.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from typing import Any

TOOL_WAIT_S = 60
COMMENT_TOOL = "kanban_comment"

LABEL_SCHEMA = {
    "name": "agos_label",
    "description": (
        "The workspace's card labels. action 'list': the labels (by folder). action "
        "'add' / 'remove' (card, labels: names): put labels on a card or take them off. "
        "Use only labels the list has."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove"]},
            "card": {"type": "string", "description": "The card id (t_...)."},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action"],
    },
}


def label_tool(args: dict[str, Any], *, member: str, post: Callable[..., Any]) -> str:
    action = str(args.get("action") or "list")
    raw = args.get("labels")
    body = {
        "member": member,
        "action": action if action in ("list", "add", "remove") else "list",
        "card": str(args.get("card") or "")[:64],
        "labels": [str(n)[:60] for n in raw][:20] if isinstance(raw, list) else [],
    }
    answer = post("labels", body, TOOL_WAIT_S)
    if answer is None:
        return json.dumps({"error": "AGOS can't be reached; try again later."})
    return json.dumps(answer, ensure_ascii=False)


def _result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    try:
        found = json.loads(str(result or ""))
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def commented(
    tool_name: str = "",
    args: Any = None,
    result: Any = None,
    *,
    post: Callable[..., Any],
    **_: Any,
) -> bool:
    """After Hermes's kanban_comment: tell AGOS (in a thread: never in the turn's way).
    True when a post was started."""
    if tool_name != COMMENT_TOOL:
        return False
    done = _result(result)
    card = str(done.get("task_id") or (args or {}).get("task_id") or "")
    comment = done.get("comment_id")
    if not card or not isinstance(comment, int) or isinstance(comment, bool):
        return False  # refused (no id): nothing landed
    threading.Thread(
        target=post,
        args=("card-comment", {"card": card[:64], "comment": comment}, 30),
        name="agos-card-comment",
        daemon=True,
    ).start()
    return True


# ---- `hermes agos-bulk` ------------------------------------------------------------


def setup(parser: Any) -> None:
    parser.add_argument("ops", nargs="+", help='JSON ops: {"op": "assign"|"body", "card": ...}')


def apply_ops(ops: list[dict[str, Any]], kb: Any, conn: Any) -> dict[str, Any]:
    """Each op through Hermes's own writer; one failing card never stops the rest."""
    done: list[str] = []
    failed: dict[str, str] = {}
    for op in ops:
        card = str(op.get("card") or "")
        try:
            if op.get("op") == "assign":
                to = str(op.get("to") or "")
                ok = kb.assign_task(conn, card, None if to in ("", "none") else to)
            elif op.get("op") == "body":
                ok = kb.edit_task(conn, card, body=str(op.get("body") or ""))
            else:
                failed[card] = "unknown op"
                continue
        except Exception as error:  # noqa: BLE001 — Hermes's refusal, said per card
            failed[card] = f"{type(error).__name__}: {error}"[:200]
            continue
        if ok:
            done.append(card)
        else:
            failed[card] = "no such card"
    return {"done": done, "failed": failed}


def handle(args: Any) -> int:
    try:
        ops = [json.loads(o) for o in args.ops]
        from hermes_cli import kanban_db  # type: ignore[import-not-found]
        from hermes_cli.kanban_db_connect import (  # type: ignore[import-not-found]
            connect_closing,
        )

        with connect_closing() as conn:
            print(json.dumps(apply_ops([o for o in ops if isinstance(o, dict)], kanban_db, conn)))
    except Exception as error:  # noqa: BLE001 — AGOS falls back to one CLI per card
        with contextlib.suppress(Exception):
            from . import bridge

            bridge._broken(bridge._name_of(error, "hermes_cli.kanban_db.edit_task"), error)
        print(json.dumps({"error": f"{type(error).__name__}: {error}"[:300]}))
    return 0


def register(
    ctx: Any, *, member_of: Callable[[], str], post: Callable[..., Any], guard: Any
) -> None:
    def label(args: dict[str, Any], **_: Any) -> str:
        return label_tool(args, member=member_of(), post=post)

    def after_tool(tool_name: str = "", args: Any = None, result: Any = None, **kw: Any) -> None:
        with contextlib.suppress(Exception):  # an observer never breaks a tool call
            commented(tool_name, args, result, post=post, **kw)

    with guard("hermes_cli.plugins.PluginContext.register_tool"):
        ctx.register_tool(
            name=str(LABEL_SCHEMA["name"]),
            toolset="agos",
            schema=LABEL_SCHEMA,
            handler=label,
            description=str(LABEL_SCHEMA["description"]),
            emoji="🏷️",
        )
    ctx.register_hook("post_tool_call", after_tool)
    with guard("hermes_cli.plugins.PluginContext.register_cli_command"):
        ctx.register_cli_command("agos-bulk", "Bulk card edits for AGOS's Board", setup, handle)
