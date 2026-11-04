"""The Co-Founder's tools on a Hermes turn: agos_action and agos_capability run
through the owner gate, Kanban/cron runs joined to their chat turn, clarify asks.

Owns: running AGOS's agent tools for a Hermes turn, once the owner gate answered.
Must not: decide itself what needs the owner (actions/owner_gate.py is the gate), or
run a call the gate refused.

Part of the Cofounder service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from agos_core.actions.services.channel import gateway_mirror, gateway_platform, hermes_addresses
from agos_core.actions.services.chat import chat_writes
from agos_core.context import Core
from agos_core.db import automations as automations_repo
from agos_core.db import chat_turns
from agos_core.db import cofounder_actions as cards_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import now

__all__ = [
    "RUN_JOIN_S",
    "RUN_MARK",
    "RUN_PREFIXES",
    "ask_capability",
    "clarify_asked",
    "is_run",
    "run_actions",
]


# (actions/owner_gate.py, re-exported above for its callers)


def _chat_turn(core: Core, workspace_id: str, address: str) -> tuple[int, int] | None:
    from agos_core.db import chats as repo

    if is_run(address):
        return _run_turn(core, workspace_id, address)
    chat_id = hermes_addresses.chat_at(core, workspace_id, address)
    if chat_id is None:
        return None
    turn = repo.live_turn(core.db, chat_id)
    return (chat_id, turn.id) if turn is not None else None


# Where AGOS's tools are called with no chat: a Kanban card's worker (Hermes's
# dispatcher) or an automation's run (Hermes's cron), and their subagents.
RUN_PREFIXES = ("kanban:", "cron:")
# Its cards (each with Undo) go into the Co-Founder chat, on one record per run:
# hermes_run_id "run:<address>" (db/chats.py shows it on its own, never inside an
# answer of the chat). A later call of the same run within this long joins it.
RUN_MARK = "run:"
RUN_JOIN_S = 30 * 60


def is_run(address: str) -> bool:
    return address.startswith(RUN_PREFIXES)


def _run_title(core: Core, workspace_id: str, address: str) -> str:
    kind, _, ref = address.partition(":")
    if kind == "kanban":
        from agos_core.actions import kanban_board

        try:
            title = str(
                kanban_board.facts(core, workspace_id, [ref]).get(ref, {}).get("title") or ""
            )
        except Exception:  # noqa: BLE001 — the card's name is only a label here
            title = ""
        return f"From the board card “{title}” ({ref})" if title else f"From the board card {ref}"
    name = automations_repo.name_of_job(core.db, workspace_id, ref)
    return f"From the automation “{name}”" if name else "From a scheduled run"


def _run_turn(core: Core, workspace_id: str, address: str) -> tuple[int, int] | None:
    """The Co-Founder chat's record of this run (made on its first call)."""

    chat_id = gateway_platform.cofounder_chat(core, workspace_id)
    if chat_id is None:
        return None
    mark = RUN_MARK + address
    since = (
        datetime.fromtimestamp(time.time() - RUN_JOIN_S, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    with transaction(core.db):
        joined = chat_turns.run_turn_since(core.db, workspace_id, chat_id, mark, since)
        if joined is not None:
            return chat_id, joined
        # Made already ended: inserted as 'starting', it was refused while the
        # Co-Founder was answering in his chat (one live turn per chat), and the
        # card's worker got "AGOS can't be reached".
        turn_id = chat_writes.insert_turn(
            core.db,
            chat_id=chat_id,
            workspace_id=workspace_id,
            asked_up_to=0,
            status="completed",
        )
        note = {"kind": "note", "title": _run_title(core, workspace_id, address), "detail": ""}
        chat_writes.set_turn(
            core.db,
            turn_id,
            hermes_run_id=mark,
            status="completed",
            activity={"own": [note]},
            ended_at=now(),
        )
    return chat_id, turn_id


def run_actions(
    core: Core, workspace_id: str, address: str, raw: list[dict[str, Any]]
) -> dict[str, Any]:
    """The Co-Founder's agos_action tool: each action is done now (the owner already
    said yes, or he lets the Co-Founder act like Hermes); each shows as a card with Undo
    in the chat."""
    from agos_core.actions import agent_power, cofounder_actions, owner_gate
    from agos_core.engine import cofounder_actions as action_rules

    where = _chat_turn(core, workspace_id, address)
    if where is None:
        return {"error": "Actions are done from a chat with the owner; nothing was done."}
    chat_id, turn_id = where
    refused: list[dict[str, Any]] = []
    readable: list[dict[str, Any]] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        bad = action_rules.unreadable(a)
        if bad:
            # Never a "done" for a change AGOS only half read: nothing of it is done.
            refused.append(
                {
                    "title": str(a.get("do") or "action"),
                    "status": "failed",
                    "error": f"AGOS doesn't know the field(s) {', '.join(bad)}: nothing "
                    "was done. Use the fields your instructions list"
                    + (
                        f" ({', '.join(sorted(known))})."
                        if (known := action_rules.KNOWN_FIELDS.get(str(a.get("do") or "")))
                        else "."
                    ),
                }
            )
        else:
            readable.append(a)
    items = [action_rules._clean(a) for a in readable]
    actions = [a for a in items if a is not None]
    skipped = len(items) - len(actions)
    if not actions:
        if refused:
            return {"results": refused}
        return {"error": "No valid action (check the 'do' and its required fields)."}
    # From a card or an automation's run, what needs his yes waits for it on its card
    # (also every power action after an untrusted read: actions/owner_gate.py).
    source = owner_gate.tainted(core, workspace_id, address) if is_run(address) else ""
    waits = [is_run(address) and w for w in owner_gate.held_kinds(core, actions, source=source)]
    actions = owner_gate.marked(actions, waits, source)
    with transaction(core.db):
        ids = cofounder_actions.save(core, workspace_id, chat_id, turn_id, actions)
    done = []
    for action_id, wait in zip(ids, waits, strict=False):
        row: Any = cards_repo.get(core.db, action_id)
        if wait:
            done.append(
                {
                    "title": row["title"],
                    "status": "proposed",
                    "error": None,
                    "waiting": "The owner says yes or no on its card in his Co-Founder chat: "
                    "don't send it again; go on with what doesn't depend on it.",
                }
            )
            continue
        cofounder_actions._run(core, row)
        row = cards_repo.get(core.db, action_id)
        said: dict[str, Any] = {
            "title": row["title"],
            "status": row["status"],
            "error": row["error"] or None,
        }
        if row["status"] == "done" and row["result"]:
            # A read-only action's answer (Hermes's own data), or what Hermes said.
            got = json.loads(row["result"])
            for key in ("report", "said", "now"):
                if isinstance(got, dict) and got.get(key):
                    said[key] = str(got[key])[:8000]
        done.append(said)
    agent_power.noted(
        core, workspace_id, address, [a.do for a, w in zip(actions, waits, strict=True) if not w]
    )
    out: dict[str, Any] = {"results": [*refused, *done]}
    if skipped:
        out["skipped"] = f"{skipped} invalid action(s) left out"
    return out


def ask_capability(
    core: Core, workspace_id: str, address: str, kind: str, name: str, on: bool, why: str
) -> dict[str, Any]:
    """The Co-Founder's agos_capability tool: turned on/off now; an app the owner never
    logged in to waits on its card for his login."""
    from agos_core.actions import agent_power, capabilities, cofounder_actions, owner_gate
    from agos_core.actions import apps as apps_actions
    from agos_core.engine import capabilities as eng

    where = _chat_turn(core, workspace_id, address)
    if where is None:
        return {"error": "Asked from a chat with the owner only; nothing changed."}
    chat_id, turn_id = where
    with transaction(core.db):
        ids = capabilities.save(
            core, workspace_id, chat_id, turn_id, [eng.Ask(kind, name, on, why[:500])]
        )
    if not ids:
        return {"error": "Not available here (unknown, locked, or already like that)."}
    row = capabilities._row(core, workspace_id, ids[0])
    if is_run(address) and (
        cofounder_actions.mode(core) == "ask" or owner_gate.tainted(core, workspace_id, address)
    ):
        return {"waiting": "The owner says yes or no on its card in his Co-Founder chat."}
    if row["kind"] == "app" and row["turn_on"] and row["name"] != apps_actions.NOUS_APP:
        app = apps_actions.catalog(core).get(row["name"])
        if app is None or app.locked or not apps_actions._is_connected(core, workspace_id, app):
            return {"waiting": "The owner logs in to this app on the card first; you'll be told."}
    capabilities._finish(core, row, tell=False)
    agent_power.noted(core, workspace_id, address, ["agos_capability"])
    row = capabilities._row(core, workspace_id, ids[0])
    return {"status": row["status"], "error": row["error"] or None}


def clarify_asked(
    core: Core, workspace_id: str, address: str, question: str, choices: list[str]
) -> bool:
    """Hermes's clarify in an AGOS conversation: said there (his next message
    answers it)."""
    text = question.strip()
    if choices:
        text += "\n" + "\n".join(f"{i}. {c}" for i, c in enumerate(choices, 1))
    return gateway_mirror.platform_said(core, workspace_id, address, text)
