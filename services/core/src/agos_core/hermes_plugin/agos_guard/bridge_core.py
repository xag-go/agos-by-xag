"""The bridge's kernel: the state every copy of the plugin in one gateway shares, the
bridge file and the HTTP call to AGOS (post), the profile home, and the report of a
Hermes internal that failed (contract.py). Readers of Hermes's events are bridge_text.

Owns: process-wide state and the one way to talk to AGOS.
Must not: hold any hook or feature logic (the other bridge_* modules do).

Part of the agos-guard bridge (moved out of bridge.py, which re-exports every name).
Runs inside Hermes: imports no agos_core package, reaches its siblings itself."""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

__all__ = [
    "AGOS_ADDRESS",
    "AGOS_BUTTONS",
    "AGOS_PLATFORM",
    "ANSWERED_IN_AGOS",
    "BRIDGE_FILE",
    "COMMAND_WINDOW_S",
    "FROM_AGOS",
    "INBOUND_MAX",
    "KEEP_EYES_MAX",
    "OLD_KEYS_FILE",
    "SENT_FILE",
    "SENT_MAX",
    "bridge",
    "post",
]

log = logging.getLogger("agos.bridge")


BRIDGE_FILE = "agos-bridge.json"

_cache: dict[str, Any] = {"path": None, "mtime": None, "bridge": None}
_ctx: dict[str, Any] = {"ctx": None, "poller": None, "adapter": None, "loop": None}


def _process() -> dict[str, Any]:
    """What every profile's copy of this plugin shares inside the root's one gateway
    (Hermes loads the plugin once per profile it serves): the Telegram adapter of
    the workspace's bot, its loop, and its Allow / Deny cards."""
    import types

    holder = sys.modules.get(_PROCESS)
    if holder is None:
        holder = types.ModuleType(_PROCESS)
        holder.__dict__["state"] = {"telegram": None, "loop": None, "cards": {}, "phone": {}}
        sys.modules[_PROCESS] = holder
    state: dict[str, Any] = holder.__dict__["state"]
    return state


_PROCESS = "agos_guard_process_state"
# What the root's copy of this plugin and its members' copies share: a member's
# topic is received by the root's bot, admitted and answered in the member's
# profile (gateway.profile_routes), so each step may run in another copy.
_shared = _process()
# session key → (chat id, message id) of Hermes's Allow/Deny card waiting in Telegram.
_cards: dict[str, tuple[str, str]] = _shared["cards"]
# session key → where Hermes shows its Telegram card for an approval in an AGOS chat.
_phone: dict[str, dict[str, str]] = _shared["phone"]
# Telegram chat id → (until when, address): Hermes's answer to a /command sent there
# is shown in the AGOS chat too. Addresses with an agent's answer working are skipped
# (that answer reaches AGOS through post_llm_call).
_awaiting: dict[str, tuple[float, str]] = _shared.setdefault("awaiting", {})
# (session, turn) → address
_busy: dict[tuple[str, str], str] = _shared.setdefault("busy", {})
# His messages from AGOS going into a Telegram place (address -> their texts): the
# admission hook leaves them out of the AGOS chat, which has them already. Not a fake
# Telegram message id: Hermes's Telegram adapter replies to ids as numbers.
_from_agos: dict[str, list[str]] = _shared.setdefault("from_agos", {})
COMMAND_WINDOW_S = 60.0
# address → Hermes's source of his last message there
_sources: dict[str, Any] = _shared.setdefault("sources", {})
# (Telegram chat id, message id) of his messages AGOS answers itself: Hermes keeps
# its 👀 on them until AGOS says that answer is out (then Hermes's own 👍 / 👎).
_keep_eyes: set[tuple[str, str]] = _shared.setdefault("keep_eyes", set())
KEEP_EYES_MAX = 500
FROM_AGOS = "agos_from_web"
# address → how AGOS gets what Hermes read there ("store": a /command that became a
# request; "replace": a voice note / file shown with Hermes's transcript).
_unread: dict[str, str] = _shared.setdefault("unread", {})
# (Telegram chat id, message id) → what only Hermes's event carries (his files, the
# topic's name), kept from pre_gateway_dispatch until Hermes admits the message.
_inbound: dict[tuple[str, str], dict[str, Any]] = _shared.setdefault("inbound", {})
INBOUND_MAX = 200
AGOS_PLATFORM = "agos"  # AGOS's own conversations, as a Hermes platform
AGOS_ADDRESS = "agos:"
# AGOS's own command in Telegram: the one-time link that makes him the bot's owner
# (everything else, /task too, is Hermes's: /task is a shared skill command).
ANSWERED_IN_AGOS = {"once": "🖥 Allowed once in AGOS", "deny": "🖥 Denied in AGOS"}
# Telegram chat id → this gateway's session key for it (learned from his messages),
# in memory only: after a restart Hermes's own session index answers (_key_in_hermes).
_keys: dict[str, str] = _shared.setdefault("keys", {})
OLD_KEYS_FILE = "agos-bridge-sessions.json"  # the copy kept before; removed once
# AGOS's outbox rows this gateway already put on Telegram (row id → message id), so
# a row handed out again (its "sent" never reached AGOS) is never sent twice.
_sent: dict[int, str] = _shared.setdefault("sent", {})
SENT_FILE = "agos-bridge-sent.json"
SENT_MAX = 2000
# (Hermes session id, Hermes turn id) → AGOS turn id
_turns: dict[tuple[str, str], int] = {}
# (Hermes session id, Hermes turn id) → Hermes's session key of that conversation (its
# agent_loop_stopped names only the key).
_turn_keys: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


def _contract() -> Any:
    """contract.py beside this file (a Hermes internal that failed, told once)."""
    return _beside("contract")


def _beside(stem: str) -> Any:
    """A module beside this file, however Hermes loaded us (agos_guard._sibling)."""
    import importlib.util

    if __package__:
        return importlib.import_module(f"{__package__}.{stem}")
    name = f"agos_guard_{stem}"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / (stem + ".py"))
        if spec is None or spec.loader is None:
            raise ImportError(stem)
        sys.modules[name] = module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return sys.modules[name]


# AGOS's own button data (guard_contract.py, shared with the core).
AGOS_BUTTONS: str = _beside("guard_contract").AGOS_BUTTONS


def _taint() -> Any:
    return _beside("taint")  # read vs act (taint.py)


def _broken(name: str, error: BaseException | str | None = None) -> None:
    with contextlib.suppress(Exception):
        _contract().broken(name, error)


def _missing(name: str, value: Any) -> Any:
    with contextlib.suppress(Exception):
        _contract().missing(name, value)
    return value


def _guard(name: str) -> Any:
    """contextlib.suppress(Exception) around a Hermes internal, as before, plus the
    report of a contract-shaped failure (contract.py)."""
    try:
        return _contract().guard(name)
    except Exception:  # noqa: BLE001 — never worse than before
        return contextlib.suppress(Exception)


def _name_of(error: BaseException, fallback: str) -> str:
    try:
        return str(_contract().name_of(error, fallback))
    except Exception:  # noqa: BLE001
        return fallback


def _home() -> Path | None:
    """The profile this plugin is installed in (<profile>/plugins/agos-guard/): the
    same from any thread, unlike Hermes's per-context home."""
    here = Path(__file__).resolve().parent
    if here.parent.name == "plugins" and (here.parent.parent / "config.yaml").is_file():
        return here.parent.parent
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        return Path(get_hermes_home())
    except ImportError as error:
        _broken("hermes_constants.get_hermes_home", error)
        return None


def bridge() -> dict[str, str] | None:
    home = _home()
    if home is None:
        return None
    path = home / BRIDGE_FILE
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _cache["path"] != path or _cache["mtime"] != mtime:
        try:
            data = json.loads(path.read_text())
            ok = isinstance(data, dict) and all(
                isinstance(data.get(k), str) and data.get(k) for k in ("core", "workspace", "key")
            )
            _cache.update(path=path, mtime=mtime, bridge=data if ok else None)
        except (OSError, ValueError):
            _cache.update(path=path, mtime=mtime, bridge=None)
    found: dict[str, str] | None = _cache["bridge"]
    return found


# What a team member's own gateway takes: only its own (AGOS filters by it).
_MEMBER_PATHS = {"next", "platform-next", "outbox"}


def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any] | None:
    return _post(path, body, timeout)[0]


def _post(path: str, body: dict[str, Any], timeout: float) -> tuple[dict[str, Any] | None, bool]:
    """AGOS's answer, and whether the wait for it ran out (a timeout is not
    "unreachable": AGOS may still be doing it, and finish it)."""
    b = bridge()
    if b is None or not b["core"].startswith(("http://127.0.0.1", "http://localhost")):
        return None, False  # AGOS's core is on this machine, nowhere else
    if path in _MEMBER_PATHS and isinstance(b.get("member"), str) and b.get("member"):
        body = {**body, "member": b["member"]}
    request = urllib.request.Request(  # noqa: S310 — loopback URL checked above
        f"{b['core'].rstrip('/')}/hermes-bridge/{b['workspace']}/{path}",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "authorization": f"Bearer {b['key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            answer = json.loads(response.read() or b"{}")
            return (answer if isinstance(answer, dict) else None), False
    except (urllib.error.URLError, OSError, ValueError) as error:
        log.warning("AGOS bridge %s failed: %s", path, error)
        late = isinstance(error, TimeoutError) or isinstance(
            getattr(error, "reason", None), TimeoutError
        )
        return None, late
