"""A Hermes turn shown live in AGOS: stream deltas, tool steps and API calls (a
Kanban card's token use), the answer to a /command shown in the AGOS chat, and
the members' names put on Hermes's output.

Owns: the live view of a turn sent to AGOS.
Must not: open or finish turns (bridge_hooks).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Any

__all__ = [
    "CARD_STEP",
    "LIVE_DRAIN_S",
    "LIVE_EVERY_S",
    "LIVE_QUEUE_MAX",
    "QUIET_AFTER_S",
    "api_call_done",
    "on_stream_delta",
    "on_stream_end",
    "tool_done",
    "tool_started",
    "transform_llm_output",
]

try:
    from . import bridge_core, bridge_sessions, bridge_text
except ImportError:  # loaded by file (agos_guard._sibling): bridge.py loads its parts first
    bridge_core = sys.modules["agos_guard_bridge_core"]
    bridge_text = sys.modules["agos_guard_bridge_text"]
    bridge_sessions = sys.modules["agos_guard_bridge_sessions"]


log = logging.getLogger("agos.bridge")


_live: dict[int, dict[str, Any]] = {}  # AGOS turn id → {"events": [...], "at": last send}
LIVE_EVERY_S = 0.6


def _agos_turn(session_id: Any, turn_id: Any) -> int | None:
    with bridge_core._lock:
        return bridge_core._turns.get((str(session_id or ""), str(turn_id or "")))


def _live_add(agos_turn: int, event: dict[str, Any], *, flush: bool = False) -> None:
    import time

    with bridge_core._lock:
        slot = _live.setdefault(agos_turn, {"events": [], "at": 0.0})
        events = slot["events"]
        if event:
            if (
                event.get("event") == "message.delta"
                and events
                and (events[-1].get("event") == "message.delta")
            ):
                events[-1]["delta"] += event["delta"]  # one piece per send
            else:
                events.append(event)
        now = time.monotonic()
        if not events or (not flush and now - slot["at"] < LIVE_EVERY_S):
            return
        slot["events"], slot["at"] = [], now
    _live_send((agos_turn, events))


# What the hooks show live goes to AGOS on one thread, in order: a tool call or the
# streaming never waits for AGOS (its core busy, or a page holding it up); the turn's
# end waits until it all went (_live_sent), so AGOS still gets the text first.
LIVE_QUEUE_MAX = 1000
LIVE_DRAIN_S = 15.0
_live_out: queue.Queue[tuple[int, list[dict[str, Any]]] | threading.Event] = queue.Queue(
    LIVE_QUEUE_MAX
)
_live_sender: list[threading.Thread] = []


def _live_send(item: tuple[int, list[dict[str, Any]]] | threading.Event) -> None:
    try:
        _live_out.put_nowait(item)
    except queue.Full:  # AGOS gone for long: the live view misses some (the answer doesn't)
        log.warning("AGOS bridge: live events dropped (AGOS not taking them)")
        if isinstance(item, threading.Event):
            item.set()
        return
    with bridge_core._lock:
        if not _live_sender or not _live_sender[0].is_alive():
            thread = threading.Thread(target=_live_send_forever, name="agos-live", daemon=True)
            _live_sender[:] = [thread]
            thread.start()


def _live_send_forever() -> None:
    while True:
        item = _live_out.get()
        if isinstance(item, threading.Event):
            item.set()
            continue
        agos_turn, events = item
        try:
            bridge_core.post("events", {"turnId": agos_turn, "events": events}, 10)
        except Exception:
            log.exception("AGOS bridge: live events not sent")


def _live_sent(timeout: float = LIVE_DRAIN_S) -> None:
    """Waits until what the hooks handed so far went to AGOS."""
    done = threading.Event()
    _live_send(done)
    done.wait(timeout)


def _preview(value: Any) -> str:
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    return text[:300]


def on_stream_delta(
    session_id: str = "", turn_id: str = "", delta: str = "", kind: str = "text", **_: Any
) -> None:
    agos_turn = _agos_turn(session_id, turn_id)
    if agos_turn is None or kind != "text" or not delta:
        return
    _live_add(agos_turn, {"event": "message.delta", "delta": str(delta)})


def on_stream_end(session_id: str = "", turn_id: str = "", **_: Any) -> None:
    agos_turn = _agos_turn(session_id, turn_id)
    if agos_turn is not None:
        _live_add(agos_turn, {}, flush=True)


def tool_started(
    tool_name: str = "", args: Any = None, session_id: str = "", turn_id: str = "", **_: Any
) -> dict[str, str] | None:
    agos_turn = _agos_turn(session_id, turn_id)
    if agos_turn is not None:
        _live_add(
            agos_turn,
            {"event": "tool.started", "tool": tool_name, "preview": _preview(args)},
            flush=True,
        )
    return None


def api_call_done(
    session_id: str = "",
    turn_id: str = "",
    usage: Any = None,
    **_: Any,
) -> None:
    """Each model call: in a Kanban card's run its tokens add up for the card, and
    AGOS hears the count as it grows (a card far past its usual size: the owner is
    asked; it goes on). A chat answer's tokens are Hermes's own count
    (session_model_usage): nothing is added up here for it."""
    del session_id, turn_id
    if not isinstance(usage, dict):
        return
    card = os.environ.get("HERMES_KANBAN_TASK", "")
    if card:
        _card_used(card, os.environ.get("HERMES_KANBAN_RUN_ID", ""), usage)


# A Kanban card's run (this process works one card): its tokens so far. Every
# CARD_STEP tokens the count is kept on the card in Hermes's Kanban (tokens.py),
# and AGOS hears only when the card is far past its usual size.
CARD_STEP = 500_000
_card_tokens: dict[str, int] = {}
_card_told: dict[str, int] = {}


def _card_used(card: str, run: str, usage: dict[str, Any]) -> None:
    try:
        used = int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        return
    with bridge_core._lock:
        total = _card_tokens.get(card, 0) + used
        _card_tokens[card] = total
        if total // CARD_STEP <= _card_told.get(card, 0) // CARD_STEP:
            return
        _card_told[card] = total
    threading.Thread(target=_card_record, args=(card, run, total), daemon=True).start()


def _card_record(card: str, run: str, total: int) -> None:
    from . import tokens

    try:
        told = tokens.record_in_hermes(card, run, total)
    except Exception as error:  # noqa: BLE001 — never in the agent's way
        logging.getLogger("agos_guard").info("usage count not kept: %s", error)
        bridge_core._broken(
            bridge_core._name_of(error, "hermes_cli.kanban_db._append_event"), error
        )
        return
    if told:
        bridge_core.post("card-tokens-told", {"card": card, **told}, 30)


def tool_done(
    tool_name: str = "",
    result: Any = None,
    session_id: str = "",
    turn_id: str = "",
    duration_ms: Any = None,
    status: Any = None,
    error_message: Any = None,
    **_: Any,
) -> None:
    agos_turn = _agos_turn(session_id, turn_id)
    if agos_turn is None:
        return
    failed = str(status or "").lower() in ("error", "failed") or bool(error_message)
    _live_add(
        agos_turn,
        {
            "event": "tool.completed",
            "tool": tool_name,
            "preview": _preview(result),
            "error": bool(failed),
            "duration": (float(duration_ms) / 1000)
            if isinstance(duration_ms, int | float)
            else None,
        },
        flush=True,
    )


_ended: dict[str, float] = bridge_core._shared.setdefault(
    "ended", {}
)  # address → when its last answer ended
QUIET_AFTER_S = 30.0


def _command_answer(chat_id: Any, content: Any, thread: Any = None) -> None:
    """A message Hermes sent to a chat that just got a /command: its answer. Any
    other message Hermes sends there on its own, outside an answer (a scheduled job's
    result, a reminder coming back): the AGOS chat gets it too."""
    import time

    text = str(content or "").strip()
    if not text:
        return
    with bridge_core._lock:
        waiting = bridge_core._awaiting.get(str(chat_id))
        if waiting is not None and time.monotonic() <= waiting[0]:
            if waiting[1] in bridge_core._busy.values():
                return
            command = waiting[1]
        else:
            command = ""
            address = bridge_sessions._address(chat_id, thread)
            if address in bridge_core._busy.values() or address.split(":", 1)[0] in {
                b.split(":", 1)[0] for b in bridge_core._busy.values()
            }:
                return  # part of an answer going on (Hermes's own notices)
            if time.monotonic() - _ended.get(address, 0.0) < QUIET_AFTER_S:
                return  # the answer that just ended (already in AGOS)
    if command:
        bridge_core.post("command-reply", {"chat": command, "text": text}, 15)
    else:
        bridge_core.post("platform-send", {"chat": address, "text": text}, 15)


def _plugin_root() -> Path:
    """The workspace's Hermes root: `<root>/plugins/agos-guard/` (or a member's copy
    in `<root>/profiles/<member>/plugins/agos-guard/`); HERMES_HOME when installed
    elsewhere (tests)."""
    import os

    home = Path(__file__).resolve().parents[2]
    if home.parent.name == "profiles":
        home = home.parent.parent
    if (home / "config.yaml").is_file():
        return home
    return Path(os.environ.get("HERMES_HOME") or "")


def _yaml_loader() -> Any:
    """Hermes's own YAML reader (utils.load_yaml_file_readonly, on its hermes_yaml):
    Hermes's runtime has no PyYAML. Plain PyYAML outside Hermes (tests)."""
    try:
        from utils import load_yaml_file_readonly  # type: ignore[import-not-found]

        return load_yaml_file_readonly
    except ImportError as error:
        bridge_core._broken("utils.load_yaml_file_readonly", error)
    with contextlib.suppress(ImportError):
        import yaml

        return lambda path: yaml.safe_load(Path(path).read_text())
    return None


def _member_names() -> dict[tuple[str, str], str]:
    """(chat, thread) -> the member's name, for each topic Hermes routes to a member
    (the root's gateway.profile_routes; the name is the profile's display_name).
    Read from the root this plugin is installed in (during a routed member's turn
    Hermes points HERMES_HOME at the member's profile), cached on mtime."""
    root = _plugin_root()
    config = root / "config.yaml"
    try:
        stamp = config.stat().st_mtime
    except OSError:
        return {}
    cached = bridge_core._shared.get("member_names")
    if isinstance(cached, tuple) and cached[0] == stamp:
        return dict(cached[1])
    names: dict[tuple[str, str], str] = {}
    load = _yaml_loader()
    if load is None:
        return {}
    with contextlib.suppress(Exception):
        routes = ((load(config) or {}).get("gateway") or {}).get("profile_routes") or []
        for r in routes:
            if not isinstance(r, dict) or str(r.get("platform") or "") != "telegram":
                continue
            chat, thread, profile = (
                str(r.get(k) or "") for k in ("chat_id", "thread_id", "profile")
            )
            if not (chat and thread and profile):
                continue
            meta: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                meta = load(root / "profiles" / profile / "profile.yaml") or {}
            names[(chat, thread)] = str(meta.get("display_name") or profile).strip()
    bridge_core._shared["member_names"] = (stamp, names)
    return names


def _with_member_name(chat_id: Any, thread: Any, content: Any) -> Any:
    """In a member's routed topic every line from the team's one bot says who wrote
    it, as in a group's room: \"**Language Coach:**\" first (once)."""
    if not isinstance(content, str) or not content.strip() or thread in (None, ""):
        return content
    name = _member_names().get((str(chat_id), str(thread)))
    if not name:
        return content
    head = f"**{name}:**"
    if content.lstrip().startswith((head, f"*{name}:*", f"{name}:")):
        return content
    return f"{head}\n{content}"


def transform_llm_output(response_text: Any = "", platform: str = "", **_: Any) -> str | None:
    """Hermes's transform_llm_output: a member's answer in a topic Hermes routes to it
    starts with its name, as in a group's room (the team's one bot speaks for all)."""
    if not bridge_text._is_telegram(platform) or not isinstance(response_text, str):
        return None
    try:
        from gateway.session_context import get_session_env  # type: ignore[import-not-found]
    except ImportError as error:
        bridge_core._broken("gateway.session_context.get_session_env", error)
        return None
    chat = get_session_env("HERMES_SESSION_CHAT_ID", "")
    thread = get_session_env("HERMES_SESSION_THREAD_ID", "")
    named = _with_member_name(chat, thread, response_text)
    return named if named != response_text else None


def _watch_sends(adapter: Any) -> None:
    """Hermes's answers to /commands go out through the adapter's public send: the
    AGOS chat gets a copy (nothing else changes)."""
    send = getattr(adapter, "send", None)
    if send is None or getattr(send, "_agos_watch", False):
        return
    bridge_core._ctx["send"] = send  # AGOS's outbox goes out with it, never mirrored back

    async def watched(chat_id: Any, content: Any, *args: Any, **kwargs: Any) -> Any:
        result = await send(chat_id, content, *args, **kwargs)
        if getattr(result, "success", True):
            metadata = kwargs.get("metadata") or (args[1] if len(args) > 1 else None) or {}
            thread = metadata.get("thread_id") if isinstance(metadata, dict) else None
            with contextlib.suppress(Exception):
                await asyncio.to_thread(_command_answer, chat_id, content, thread)
        return result

    watched._agos_watch = True  # type: ignore[attr-defined]
    adapter.send = watched
