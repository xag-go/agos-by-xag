"""A stand-in for the workspace's Hermes gateway on the agos platform.

AGOS hands work to Hermes through its inbox (what he wrote, /commands, Allow /
Deny); the gateway's agos platform takes it, Hermes answers, and the agos-guard
plugin reports each answer's start and end back to AGOS. `pump` does what the
gateway and the plugin do, with a fake model: a message starts an answer (a
"run" of the fake, recorded in `fake.bodies` the way the tests read it), a
message while it answers steers it, `/stop` interrupts it, and an answer the test
finished with `fake.finish(run, text)` is reported back to AGOS.
"""

from __future__ import annotations

import json
import re
from typing import Any

import hermes_store

from agos_core.actions import hermes_channel

# The fake model "calls" AGOS's Hermes tools by writing them as fenced blocks in its
# answer (the tests' shorthand): the gateway makes the tool calls during the answer,
# as the agent does, and the block isn't part of what it says.
_TOOLS = {"agos-actions": "actions"}
_CALL = re.compile(r"\s*```(agos-actions)[ \t]*\n(.*?)```", re.DOTALL)


def _call_tools(fake: Any, core: Any, ws: str, address: str, text: str) -> str:
    calls = list(_CALL.finditer(text))
    if not calls or not address:
        return text
    for call in calls:
        try:
            data = json.loads(call.group(2))
        except ValueError:
            continue  # a broken call: the tool refuses it, nothing happens
        path = _TOOLS[call.group(1)]
        body = {"chat": address, "actions": data if isinstance(data, list) else [data]}
        try:
            if hasattr(fake, "send"):
                _bridge(fake, ws, path, body, core)
            else:
                _direct(core, ws, path, body)
        except AssertionError:
            continue  # the bridge refused it (a bad field), as Hermes would show
    return _CALL.sub("", text).strip()


def _direct(core: Any, ws: str, path: str, body: dict[str, Any]) -> None:
    address = body.pop("chat")
    if path == "actions":
        hermes_channel.run_actions(core, ws, address, body["actions"])


def _session(core: Any, address: str) -> str:
    """The Hermes session of a conversation (the names the tests use)."""
    from agos_core.actions import learning
    from agos_core.db import chats as chats_repo

    if address == learning.ADDRESS:
        return "agos-learn"
    split = hermes_channel.split_agos(address)
    assert split is not None, address
    chat_id, member = split
    key = chats_repo.hermes_key(core.db, chat_id)
    return f"{key}-{member}" if member else key


def _model(fake: Any, address: str) -> dict[str, Any]:
    """The model AGOS switched this conversation to (its /model …)."""
    words = getattr(fake, "models", {}).get(address)
    if not words or len(words) < 2:
        return {}
    out: dict[str, Any] = {"model": words[1]}
    if "--provider" in words:
        out["provider"] = words[words.index("--provider") + 1]
    if "--reasoning" in words:
        out["model_options"] = {"reasoning_effort": words[words.index("--reasoning") + 1]}
    return out


def _home(core: Any, ws: str, address: str) -> Any:
    """The Hermes home that keeps this conversation (a member's own, else the root)."""
    member = hermes_channel.owner_member(core, ws, address)
    if member:
        from agos_core.actions import agent_profiles

        return core.engine.profile_home(agent_profiles.key(ws, member))
    return core.engine.profile_home(ws)


def _chat_ref(address: str) -> str:
    return address.split(":", 1)[1] if address.startswith("agos:") else address


def hermes_keeps(core: Any, ws: str, address: str, role: str, text: str, **kw: Any) -> int:
    """What the workspace's Hermes keeps of a conversation (its session store)."""
    if not address.startswith("agos:"):
        chat, _, thread = address.partition(":")
        return hermes_store.say(
            core.engine.profile_home(ws),
            chat,
            role,
            text,
            source="telegram",
            thread=None if thread in ("", "0") else thread,
            **kw,
        )
    return hermes_store.say(_home(core, ws, address), _chat_ref(address), role, text, **kw)


def _workspaces(core: Any) -> list[str]:
    return [str(r["id"]) for r in core.db.execute("SELECT id FROM workspaces")]


def follow_requests(client: Any, core: Any, fake: Any) -> None:
    """The workspace's Hermes gateway takes what AGOS hands it right away (as the real
    one does, polling): after each request, the fake gateway takes its inbox.
    `fake.gateway = False` lets a test read the inbox itself."""
    fake.gateway = True
    send = client.request
    fake.send = send  # the plugin calls AGOS's bridge over HTTP (on the app's loop)

    def request(*args: Any, **kwargs: Any) -> Any:
        answer = send(*args, **kwargs)
        if fake.gateway:
            pump(core, fake)
        return answer

    client.request = request


def _bridge(fake: Any, ws: str, path: str, body: dict[str, Any], core: Any) -> Any:
    """What the agos-guard plugin posts to AGOS (its bridge), as the real one does."""
    key = hermes_channel.bridge_key(core, ws)
    answer = fake.send(
        "POST",
        f"/hermes-bridge/{ws}/{path}",
        json=body,
        headers={"authorization": f"Bearer {key}"},
    )
    assert answer.status_code == 200, answer.text
    return answer.json()


def _finish(
    core: Any,
    fake: Any,
    ws: str,
    turn: int,
    text: str,
    failed: bool,
    error: Any,
    address: str = "",
) -> None:
    if not failed:
        text = _call_tools(fake, core, ws, address, text)
    if address and text and not failed:
        hermes_keeps(core, ws, address, "assistant", text)  # Hermes keeps its answer
    if hasattr(fake, "send"):
        body = {"turnId": turn, "text": text, "failed": failed, "error": error}
        _bridge(fake, ws, "turn-finish", body, core)
    else:
        del error
        hermes_channel.turn_finish(core, ws, turn, text)
        # Then Hermes's on_session_end: how the turn ended (the plugin's turn-end).
        hermes_channel.turn_ended(core, ws, turn, hermes_store.reason(failed))


def _streamed(fake: Any) -> bool:
    """A fake whose answers are streams of events the test pushes (the chat tests)."""
    return isinstance(getattr(fake, "events", None), dict)


def routing_yolo(home: Any, address: str, on: bool) -> None:
    """Hermes's gateway routing entry of an AGOS conversation, with its /yolo."""
    import sqlite3

    key = f"agent:main:agos:dm:{address.split(':', 1)[1]}"
    con = sqlite3.connect(home / "state.db")
    con.execute(
        "CREATE TABLE IF NOT EXISTS gateway_routing (scope TEXT NOT NULL DEFAULT '',"
        " session_key TEXT NOT NULL, entry_json TEXT NOT NULL, updated_at REAL NOT NULL,"
        " PRIMARY KEY (scope, session_key))"
    )
    entry: dict[str, Any] = {
        "session_key": key,
        "session_id": "s1",
        "updated_at": "2026-10-16T10:00:00",
    }
    # Hermes's entry carries the chat it came from (SessionEntry.origin) and lives
    # under its store's scope: the resolved sessions dir (session_persistence.py).
    entry["origin"] = {"platform": "agos", "chat_id": address.split(":", 1)[1], "chat_type": "dm"}
    scope = str((home / "sessions").resolve())
    con.execute(
        "INSERT OR REPLACE INTO gateway_routing VALUES (?, ?, ?, 1.0)",
        (scope, key, json.dumps({**entry, "yolo": on})),
    )
    con.commit()
    con.close()


def switch_access(client: Any, core: Any, ws: str, chat: int, access: str) -> int:
    """The chat's Full access switch: the PUT waits until the gateway has set Hermes's
    /yolo, so the fake gateway works meanwhile. Returns the PUT's status."""
    import threading

    got: dict[str, int] = {}

    def put() -> None:
        got["status"] = client.put(
            f"/workspaces/{ws}/chats/{chat}", json={"access": access}
        ).status_code

    worker = threading.Thread(target=put)
    worker.start()
    while worker.is_alive():
        pump(core, core.engine.runs_client)
        worker.join(0.05)
    return got["status"]


def pump(core: Any, fake: Any) -> None:
    """One round of the gateway: report finished answers, then take the inbox."""
    for _ in range(3):  # what one answer's end hands over is taken in the same round
        if not _round(core, fake):
            break


def _turns(fake: Any) -> dict[str, dict[str, Any]]:
    """run id → the answer it is (address, workspace, turn): kept apart from
    `fake.runs`, which the tests overwrite (`fake.finish`)."""
    if not hasattr(fake, "turns"):
        fake.turns = {}
    turns: dict[str, dict[str, Any]] = fake.turns
    return turns


def _live(fake: Any, address: str) -> str | None:
    if _streamed(fake):
        for run_id, turn in _turns(fake).items():
            if turn["address"] == address and not turn.get("reported"):
                return run_id
        return None
    for run_id, turn in _turns(fake).items():
        run = fake.runs.get(run_id) or {}
        if (
            turn["address"] == address
            and not turn.get("reported")
            and run.get("status")
            in (
                "running",
                "waiting",
                "waiting_for_approval",
                "requires_action",
            )
        ):
            return run_id
    return None


def _stream_round(core: Any, fake: Any) -> bool:
    """Events the test pushed since the last round go to AGOS as the plugin sends
    them: live text and tools, Allow / Deny asked, the answer's end."""
    moved = False
    for run_id, turn in list(_turns(fake).items()):
        if turn.get("reported"):
            continue
        events = fake.events.get(run_id, [])
        seen = int(turn.get("seen", 0))
        for event in events[seen:]:
            turn["seen"] = int(turn.get("seen", 0)) + 1
            moved = True
            name = str(event.get("event", ""))
            ws, address, number = turn["workspace"], turn["address"], turn["turn"]
            if name == "approval.request" and turn.get("yolo"):
                fake.yolo = [*getattr(fake, "yolo", []), run_id]  # Hermes never asks
            elif name == "approval.request":
                phone = hermes_channel.approval_asked(
                    core,
                    ws,
                    address,
                    str(event.get("command") or ""),
                    str(event.get("description") or ""),
                    str(event.get("pattern_key") or ""),
                )
                # Where the plugin has Hermes's Telegram adapter show its own card.
                fake.phone_cards = [*getattr(fake, "phone_cards", []), phone]
            elif name.startswith("run."):
                turn["reported"] = True
                status = name[4:]
                _finish(
                    core,
                    fake,
                    ws,
                    number,
                    str(event.get("output") or ""),
                    status != "completed",
                    event.get("error") or ("interrupted" if status == "cancelled" else None),
                    address,
                )
                break
            else:
                hermes_channel.live_events(core, ws, number, [event])
    return moved


def ask_me_first(core: Any, ws: str) -> None:
    """The workspace on Ask me first, as Settings saves it: AGOS's switch and its
    Hermes profiles' approvals (actions/access.py)."""
    from agos_core.actions import access

    access.set_workspace(core, ws, False)


def _approvals_off(core: Any, ws: str) -> bool:
    """The workspace's profile says `approvals.mode: off` (its Full access)."""
    runner = getattr(core.engine, "runner", None)
    config = getattr(runner, "config", {}) or {}
    return bool((config.get(f"agos-{ws}") or {}).get("approvals.mode") == "off")


def _round(core: Any, fake: Any) -> bool:
    moved = _stream_round(core, fake) if _streamed(fake) else False
    for run_id, turn in list(_turns(fake).items()) if not _streamed(fake) else []:
        run = fake.runs.get(run_id) or {}
        if turn.get("reported"):
            continue
        status = run.get("status")
        asked = run.get("approval")
        if status == "waiting_for_approval" and asked and turn.get("yolo"):
            # Full access = Hermes's YOLO for the conversation: it never asks.
            if run_id not in getattr(fake, "yolo", []):
                fake.yolo = [*getattr(fake, "yolo", []), run_id]
            run["status"] = "running"
            moved = True
        elif status == "waiting_for_approval" and asked and turn.get("asked") != asked:
            # Hermes asks Allow / Deny (the plugin's approval hook).
            turn["asked"] = asked
            moved = True
            phone = hermes_channel.approval_asked(
                core,
                turn["workspace"],
                turn["address"],
                str(asked.get("command") or ""),
                str(asked.get("description") or ""),
                str(asked.get("pattern_key") or ""),
            )
            fake.phone_cards = [*getattr(fake, "phone_cards", []), phone]
        if status in ("completed", "failed", "cancelled"):
            turn["reported"] = True
            moved = True
            _finish(
                core,
                fake,
                turn["workspace"],
                turn["turn"],
                str(run.get("output") or ""),
                status != "completed",
                run.get("error") or ("interrupted" if status == "cancelled" else None),
                turn["address"],
            )
    from agos_core.actions import agent_profiles

    for ws in _workspaces(core):
        # The workspace's gateway, and each team member's own gateway (its profile).
        takers = ["", *agent_profiles.team_names(core, ws)]
        items = _batched(
            [
                item
                for member in takers
                for item in hermes_channel.take_inbox(core, ws, agos=True, member=member)
            ]
        )
        for item in items:
            moved = True
            hermes_channel.inbox_done(core, ws, int(item["id"]), True)  # as the plugin does
            address, kind, text = str(item["chat"]), str(item["kind"]), str(item["text"])
            if item.get("replyTo"):  # Hermes's own reply context
                who = " your previous message" if item.get("replyOwn") else ""
                text = f'[Replying to{who}: "{item["replyTo"]}"]\n\n{text}'
            live = _live(fake, address)
            if kind == "command" and text == "/yolo":
                # Hermes's own /yolo: toggles the conversation's YOLO, kept on its
                # routing entry (state.db gateway_routing).
                on = not getattr(fake, "yolo_on", {}).get(address, False)
                fake.yolo_on = {**getattr(fake, "yolo_on", {}), address: on}
                routing_yolo(core.engine.profile_home(ws), address, on)
                continue
            if kind == "approval":
                if live is not None and _streamed(fake):
                    fake.approvals.append((live, text))
                    fake.events[live].append({"event": "approval.responded", "choice": text})
                    _turns(fake)[live]["seen"] = int(_turns(fake)[live].get("seen", 0)) + 1
                elif live is not None:
                    fake.answers.append((live, text))
                    fake.runs[live]["status"] = "running"
                hermes_channel.approval_answered(core, ws, address, text)
                continue
            if kind == "command" and text.startswith("/model"):
                words = text.split()
                fake.models = {**getattr(fake, "models", {}), address: words}
                member = hermes_channel.owner_member(core, ws, address)
                override = {"model": words[1]}
                if "--provider" in words:
                    override["provider"] = words[words.index("--provider") + 1]
                hermes_store.model(
                    core.engine.profile_home(ws),
                    f"a-{member}" if member else "main",
                    _chat_ref(address),
                    override,
                )
                continue
            if kind == "command" and text.startswith("/title "):
                hermes_store.title(_home(core, ws, address), _chat_ref(address), text[7:].strip())
                continue
            if kind == "command" and text.strip() == "/stop":
                if live is not None:
                    fake.stopped.append(live)
                    if _streamed(fake):
                        fake.events[live].append({"event": "run.cancelled"})
                    else:
                        fake.runs[live]["status"] = "cancelled"
                continue
            if kind == "command" and text.strip() == "/approve":
                continue  # the answer to Hermes's own confirm for /undo
            if kind == "command" and text.strip() == "/undo":
                # Hermes drops its last exchange in this conversation.
                fake.undone = [*getattr(fake, "undone", []), address]
                hermes_store.undo(_home(core, ws, address), _chat_ref(address))
                continue
            if kind == "command" and text.strip() == "/retry":
                # Hermes asks its last message again (the old exchange goes).
                text = getattr(fake, "last_input", {}).get(address, "")
                if not text:
                    continue
                hermes_store.undo(_home(core, ws, address), _chat_ref(address))
                hermes_keeps(core, ws, address, "user", text)
            if kind == "command" and text.startswith("/goal "):
                text = text[len("/goal ") :]
            if live is not None:  # Hermes's steer: it joins the answer going on
                fake.steered = [*getattr(fake, "steered", []), (live, text)]
                hermes_keeps(
                    core,
                    ws,
                    address,
                    "user",
                    f"[OUT-OF-BAND USER MESSAGE — steer]\n{text}\n[/OUT-OF-BAND USER MESSAGE]",
                    display_kind="steer",
                )
                continue
            if (
                kind != "command"
                and address.startswith("agos:")
                and not address.startswith("agos:l")
            ):
                # Hermes keeps his message (with the platform's id) as the turn starts.
                files = list(item.get("media") or [])
                notes = "".join(f"[The user sent a file: '{m.get('path')}']\n\n" for m in files)
                hermes_keeps(
                    core, ws, address, "user", notes + text, platform_id=f"agos-{item['id']}"
                )
            fake.last_input = {**getattr(fake, "last_input", {}), address: text}
            session = _session(core, address)
            if hasattr(fake, "send"):
                start = _bridge(
                    fake, ws, "turn-start", {"chat": address, "sessionId": session}, core
                )
            else:
                start = hermes_channel.turn_start(core, ws, address, session, text, "")
            number = start.get("turnId")
            if number is None:
                continue
            if _streamed(fake):
                run_id = f"run_{len(fake.bodies) + 1}"
                fake.events[run_id] = []
                fake.status[run_id] = {"status": "running"}
            else:
                run_id = f"run_{len(fake.runs) + 1}"
                fake.runs[run_id] = {"status": "running"}
            _turns(fake)[run_id] = {
                "address": address,
                "workspace": ws,
                "turn": int(number),
                # Hermes never asks: the chat's YOLO, or its profile's approvals off.
                "yolo": bool(getattr(fake, "yolo_on", {}).get(address)) or _approvals_off(core, ws),
            }
            fake.bodies.append(
                {
                    "session_id": session,
                    "input": text,
                    # What Hermes gives the model: the answering profile's SOUL.md,
                    # the conversation's topic (session context), its channel prompt.
                    "instructions": _system(core, ws, address, item, start),
                    "address": address,
                    "media": list(item.get("media") or []),
                    **_model(fake, address),
                }
            )
    return moved


def _batched(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hermes's inbound text batching: plain messages to one conversation that come
    together are one message (joined by a line break), dispatched once."""
    out: list[dict[str, Any]] = []
    for item in items:
        plain = item["kind"] in (None, "message") and not item.get("media")
        plain = plain and not item.get("replyTo")
        last = out[-1] if out else None
        if (
            plain
            and last is not None
            and last["chat"] == item["chat"]
            and last["kind"] in (None, "message")
            and not last.get("media")
            and not last.get("replyTo")
        ):
            out[-1] = {**last, "text": f"{last['text']}\n{item['text']}"}
            continue
        out.append(dict(item))
    return out


def _system(core: Any, ws: str, address: str, item: dict[str, Any], start: dict[str, Any]) -> str:
    from agos_core.actions import agent_profiles

    soul = ""
    if core.engine is not None:
        member = hermes_channel.owner_member(core, ws, address)
        home = core.engine.profile_home(agent_profiles.key(ws, member) if member else ws)
        path = home / "SOUL.md"
        soul = path.read_text(encoding="utf-8") if path.is_file() else ""
    topic = str(item.get("topic") or "")
    # Hermes's ephemeral system prompt: the conversation's channel prompt.
    parts = [
        soul,
        f"**Channel Topic:** {topic}" if topic else "",
        str(item.get("channelPrompt") or ""),
    ]
    return "\n\n".join(p for p in parts if p)
