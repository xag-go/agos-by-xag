"""Read vs act, in the core: which conversation or run read untrusted content.

The workspace's agos-guard plugin tells AGOS (bridge `/taint`) the moment a session
reads something from outside: a web page, a fetched URL, an app's email or message,
an app or MCP server's answer (unless the owner trusts that app), a file from a
folder outside the workspace. AGOS also knows by itself when a turn's input is not
the owner's: a Telegram message from someone else (turn-start), a card a webhook
delivery made or a child of one (its Hermes idempotency key, engine/automation_run.py,
and the board's parent links), a card or a scheduled job a tainted session made
(marked for its whole address).

A mark is keyed by the conversation's Hermes SESSION (owner, 2026-11-03: it lasts
until the chat session ends, not just the turn): another sender's turn in the same
Telegram group has its own session, so it never clears this one's, and a new session
of the chat (/new, Hermes's reset) starts clean. A run's mark (cron, card) times out.
Until then every POWER action (engine/power.py) waits for the owner's yes
(actions/owner_gate.py), and turn-start tells the plugin (`untrusted`) so its memory
and skill writes are held too.

Kept on disk (data/system/read-vs-act.json, 0600): a core restart forgets nothing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from agos_core.context import Core

log = logging.getLogger("agos.read_vs_act")

# A run (cron, card) has no turn-start: its mark ends after this long.
MARK_FOR_S = 3600
_MAX = 5000
# (workspace, address, session) -> (what was read first, when: wall clock). Session ""
# = the whole address (a tainted job or card, kept until it is gone).
_marks: dict[tuple[str, str, str], tuple[str, float]] = {}
_lock = threading.Lock()
_loaded: set[str] = set()
# card id -> (why it is untrusted, "" = it isn't; when looked up): a card's origin never changes. Only a
# lookup that worked is kept (a board error is never cached: fail closed).
_cards: dict[tuple[str, str], tuple[str, float]] = {}
CARD_LOOK_S = 600
FILE = "read-vs-act.json"
_RUNS = ("cron:", "kanban:")

TELEGRAM_OTHER = "a Telegram message from someone who isn't the owner"
WEBHOOK = "a webhook delivery from an outside app"
CHILD = "a card made under a card that read untrusted content"
BOARD_UNREADABLE = "a card whose origin AGOS couldn't read (its board didn't answer)"


def _file(core: Core) -> Path:
    return Path(core.settings.data_dir) / "system" / FILE


def _load(core: Core) -> None:
    """The marks kept on disk, read once per data folder (caller holds _lock)."""
    path = _file(core)
    if str(path) in _loaded:
        return
    _loaded.add(str(path))
    try:
        rows = json.loads(path.read_text())
    except (OSError, ValueError):
        return
    for row in rows if isinstance(rows, list) else []:
        with contextlib.suppress(TypeError, ValueError):
            ws, address, session, source, at = row
            _marks.setdefault((str(ws), str(address), str(session)), (str(source), float(at)))


def _save(core: Core) -> None:
    """Written aside, then renamed over the old file (caller holds _lock)."""
    path = _file(core)
    rows = [[*key, source, at] for key, (source, at) in _marks.items()]
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(rows, handle)
        tmp.replace(path)
    except OSError as error:  # in memory it still holds; a restart re-reads the plugin's
        log.warning("read-vs-act marks not saved: %s", type(error).__name__)


# A chat's mark that came without its session (an older plugin): every session of
# that chat, for an hour (a chat's address is never marked whole: it would never end).
ANY = "-"


def _stale(key: tuple[str, str, str], at: float, now: float) -> bool:
    """A run's session mark times out; a chat session's lasts (and the whole address)."""
    timed = key[1].startswith(_RUNS) or key[2] == ANY
    return bool(key[2]) and timed and now - at > MARK_FOR_S


def mark(core: Core, workspace_id: str, address: str, source: str, *, session: str = "") -> None:
    """This session of a conversation (or run) read untrusted content: `source` says
    what. No session: the whole address (a job or a card made in a tainted session)."""
    if not workspace_id or not address or not source:
        return
    now = time.time()
    if not session and not address.startswith(_RUNS):
        session = ANY
    key = (workspace_id, address, session[:200])
    with _lock:
        _load(core)
        kept = _marks.get(key)
        if kept is not None and not _stale(key, kept[1], now):
            if key[2] and now - kept[1] > 60:  # a run's mark lives while it reads
                _marks[key] = (kept[0], now)
                _save(core)
            return  # the first source read stays the one named (what started it)
        if len(_marks) >= _MAX:
            for old in [k for k, (_, t) in _marks.items() if _stale(k, t, now)]:
                del _marks[old]
            while len(_marks) >= _MAX:
                del _marks[min(_marks, key=lambda k: _marks[k][1])]
        _marks[key] = (source[:200], now)
        _save(core)


def source_of(core: Core, workspace_id: str, address: str, session: str = "") -> str:
    """What untrusted content this session of a conversation or run read ("" = none).
    No session given (an older plugin, a run's own path): any recent mark of the
    address counts (fail closed)."""
    now = time.time()
    with _lock:
        _load(core)
        whole = _marks.get((workspace_id, address, ""))
        if whole is not None:
            return whole[0]
        if session:
            for key in ((workspace_id, address, session[:200]), (workspace_id, address, ANY)):
                kept = _marks.get(key)
                if kept is not None and not _stale(key, kept[1], now):
                    return kept[0]
        else:
            for (ws, where, _s), (source, at) in _marks.items():
                if ws == workspace_id and where == address and now - at <= MARK_FOR_S:
                    return source
    if address.startswith("kanban:"):
        return _card_source(core, workspace_id, address[7:])
    return ""


def _card_source(core: Core, workspace_id: str, card: str) -> str:
    try:
        return _card_reason(core, workspace_id, card)
    except Exception:  # noqa: BLE001 - its board didn't answer: untrusted (fail closed)
        log.warning("card %s of %s: origin not read, marked untrusted", card, workspace_id)
        return BOARD_UNREADABLE


def _card_reason(core: Core, workspace_id: str, card: str, depth: int = 0) -> str:
    """Why a card is untrusted ("" = it isn't): a webhook delivery made it (a webhook
    run's step, a ticket card), a tainted session made it, or it is a child of such a
    card (the board's parent links). Raises when the board can't be read (and that
    is never cached)."""
    if not card:
        return ""
    at = time.monotonic()
    with _lock:
        known = _cards.get((workspace_id, card))
        whole = _marks.get((workspace_id, f"kanban:{card}", ""))
    if whole is not None:
        return whole[0]
    if known is not None and at - known[1] <= CARD_LOOK_S:
        return known[0]
    from agos_core.engine import automation_run

    key, parents = _card_row(core, workspace_id, card)
    hooked = key.startswith(automation_run.TICKET_PREFIX) or (
        key.startswith(automation_run.PREFIX) and ":webhook:" in key
    )
    found = WEBHOOK if hooked else ""
    for parent in parents if not found and depth < 5 else ():
        if _card_reason(core, workspace_id, parent, depth + 1):
            found = CHILD
            break
    with _lock:
        if len(_cards) >= _MAX:
            _cards.clear()
        _cards[(workspace_id, card)] = (found, at)
    return found


def _card_row(core: Core, workspace_id: str, card: str) -> tuple[str, list[str]]:
    """A card's Hermes idempotency key and parents, read from its board (read only).
    sqlite3.Error (a locked board) is raised: the caller fails closed."""
    from agos_core.actions import agent_profiles
    from agos_core.hermes_gateway import hermes_db

    if core.engine is None:
        return "", []
    board = agent_profiles.board_db(core, workspace_id)
    if not board.is_file():
        return "", []
    with contextlib.closing(hermes_db.connect_ro(board, timeout=5)) as db:
        row = db.execute("SELECT idempotency_key FROM tasks WHERE id = ?", (card,)).fetchone()
        links = db.execute("SELECT parent_id FROM task_links WHERE child_id = ?", (card,))
        parents = [str(p[0]) for p in links.fetchall()]
    return (str(row[0] or "") if row else ""), parents


def telegram_turn(
    core: Core, workspace_id: str, address: str, sender: str, session: str = ""
) -> None:
    """A Telegram turn opens: its session is marked when the person writing is not
    the owner (the owner's own session in the same group stays his)."""
    from agos_core.actions import telegram_people

    if not sender or address.startswith(("agos:", "cron:", "kanban:", "room:")):
        return
    try:
        owner = telegram_people.owner_id(core, workspace_id)
    except Exception:  # noqa: BLE001 - who the owner is unknown: untrusted (fail closed)
        log.warning("owner of %s's Telegram not read: marked untrusted", workspace_id)
        owner = ""
    if str(sender) != str(owner):
        who = session or f"sender:{sender}"
        mark(core, workspace_id, address, TELEGRAM_OTHER, session=who)


def kept(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """What is marked now in this workspace."""
    with _lock:
        _load(core)
        return [
            {"address": a, "session": s, "source": src}
            for (ws, a, s), (src, _at) in _marks.items()
            if ws == workspace_id
        ]
