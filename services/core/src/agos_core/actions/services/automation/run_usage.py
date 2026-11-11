"""What an automation's work used, as Hermes counted it: the sessions that worked
each Kanban card of a run (or a one-agent automation's cron runs), and their tokens
and cost summed. Hermes counts and prices every session itself (its `sessions`
table); AGOS only finds which sessions belong to which step and adds them up.

Which sessions worked a card (each read from the workspace's own Hermes root only):
- the session Hermes's gateway admitted for an attempt (`owner_admitted`: its id and
  the store it lives in, used only when that store is one of this root's profiles);
- the session Hermes stamped on the attempt when the worker completed or blocked
  (`task_runs.metadata.worker_session_id`), in the attempt profile's store;
- the attempt profile's Kanban sessions opened on this card (`work kanban task <card>`);
- and every session started from those (subagents, continuations).

Owns: that linking and the sums. Must not: price anything (a session Hermes did not
price stays unpriced), write a Hermes store, or read another workspace's root.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agos_core.actions.services.board import kanban_db
from agos_core.context import Core
from agos_core.db.records import Usage
from agos_core.hermes_gateway import session_usage

__all__ = [
    "CardWork",
    "card_work",
    "cron_sessions",
    "of_session",
    "total",
]

log = logging.getLogger("agos.automations")

_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
_NOT_A_PROFILE = ("", "none", "owner", "user")


def _int(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _amount(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def of_session(row: dict[str, Any]) -> Usage:
    """One Hermes session's counts. Its cost is Hermes's actual one, else its
    estimate; none when Hermes said `unknown` or gave no amount for its tokens."""
    counts = {
        k: _int(row.get(k))
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    }
    tokens = sum(counts.values())
    amount = _amount(row.get("actual_cost_usd"))
    if amount is None:
        amount = _amount(row.get("estimated_cost_usd"))
    status = str(row.get("cost_status") or "").lower()
    if tokens == 0:
        cost, priced = amount or 0.0, True
    elif status == "unknown" or amount is None:
        cost, priced = None, False
    else:
        cost, priced = amount or 0.0, True
    return Usage(**counts, tokens=tokens, cost_usd=cost, priced=priced, sessions=1)


def total(parts: Iterable[Usage]) -> Usage:
    """The sum. Its cost is the sum of the priced parts; none when no part with
    tokens was priced; `priced` only when every part was."""
    items = list(parts)
    costs = [u.cost_usd for u in items if u.cost_usd is not None]
    tokens = sum(u.tokens for u in items)
    priced_tokens = any(u.cost_usd is not None and u.tokens > 0 for u in items)
    unpriced_tokens = any(u.cost_usd is None and u.tokens > 0 for u in items)
    cost: float | None = round(sum(costs), 6)
    if unpriced_tokens and not priced_tokens:
        cost = None
    return Usage(
        input_tokens=sum(u.input_tokens for u in items),
        output_tokens=sum(u.output_tokens for u in items),
        cache_read_tokens=sum(u.cache_read_tokens for u in items),
        cache_write_tokens=sum(u.cache_write_tokens for u in items),
        tokens=tokens,
        cost_usd=cost,
        priced=all(u.priced for u in items),
        sessions=sum(u.sessions for u in items),
    )


def _store_of(core: Core, workspace_id: str, profile: str) -> Path | None:
    """The state.db of a profile of THIS workspace's root (a name Hermes gave it)."""
    if core.engine is None or profile in _NOT_A_PROFILE or not _PROFILE.match(profile):
        return None
    store = core.engine.home_in(workspace_id, profile) / "state.db"
    return store if store.is_file() else None


def _inside(core: Core, workspace_id: str, store: Any) -> Path | None:
    """`store` when it is the state.db of one of this workspace's own profiles."""
    if core.engine is None or not isinstance(store, str) or not store:
        return None
    try:
        root = core.engine.root(workspace_id).resolve()
        path = Path(store).resolve()
    except (OSError, RuntimeError):
        return None
    home = path.parent
    ours = path.name == "state.db" and (
        home == root or (home.parent == root / "profiles" and bool(_PROFILE.match(home.name)))
    )
    return path if ours and path.is_file() else None


class CardWork:
    """What one card's attempts were and what its sessions used."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.sessions: dict[tuple[str, str], Usage] = {}  # (store, session) -> usage

    @property
    def usage(self) -> Usage:
        return total(self.sessions.values())


class _Wanted:
    """Which sessions to read in each store: named ones, and cards to find by prompt."""

    def __init__(self) -> None:
        self.named: dict[Path, dict[str, set[str]]] = {}  # store -> card -> sessions
        self.searched: dict[Path, set[str]] = {}  # store -> cards

    def name(self, store: Path | None, card: str, session: Any) -> None:
        if store is not None and session:
            self.named.setdefault(store, {}).setdefault(card, set()).add(str(session))

    def search(self, store: Path | None, card: str) -> None:
        if store is not None:
            self.searched.setdefault(store, set()).add(card)


def card_work(core: Core, workspace_id: str, cards: list[dict[str, Any]]) -> dict[str, CardWork]:
    """Each card's attempts and the usage of the sessions that worked it."""
    ids = [str(c["id"]) for c in cards]
    work = {i: CardWork() for i in ids}
    runs, admitted = kanban_db.attempts(core, workspace_id, ids)
    wanted = _Wanted()
    for run in (r for r in runs if str(r["card"]) in work):
        card = str(run["card"])
        work[card].attempts.append(run)
        store = _store_of(core, workspace_id, str(run.get("profile") or ""))
        wanted.search(store, card)
        wanted.name(store, card, (run.get("metadata") or {}).get("worker_session_id"))
    for event in (e for e in admitted if e["card"] in work):
        payload = event.get("payload") or {}
        store = _inside(core, workspace_id, payload.get("db"))
        wanted.name(store, event["card"], payload.get("session_id"))
    for c in cards:
        wanted.search(_store_of(core, workspace_id, str(c.get("assignee") or "")), str(c["id"]))
    for store in {*wanted.named, *wanted.searched}:
        _read_store(store, wanted.named.get(store, {}), wanted.searched.get(store, set()), work)
    return work


def _read_store(
    store: Path, named: dict[str, set[str]], searched: set[str], work: dict[str, CardWork]
) -> None:
    taken: set[str] = set()
    try:
        with session_usage.opened(store) as sessions:
            for card in sorted({*named, *searched}):
                rows = sessions.by_ids(sorted(named.get(card, set())))
                if card in searched:
                    # an older store without messages: the named ones only
                    with contextlib.suppress(sqlite3.Error):
                        rows += sessions.worked_card(card)
                for row in sessions.with_children(_unique(rows)):
                    sid = str(row["id"])
                    if sid in taken:
                        continue
                    taken.add(sid)
                    work[card].sessions[(str(store), sid)] = of_session(row)
    except sqlite3.Error as error:
        log.warning("sessions of %s can't be read: %s", store, error)


def _unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({str(r["id"]): r for r in rows}.values())


def cron_sessions(
    core: Core, home: Path, job: str, since: float, until: float
) -> list[tuple[float, Usage]]:
    """A one-agent automation's cron sessions (Hermes names them `cron_<job>_…`) in
    the profile home that holds its job, started in [since, until): each with its
    start and its usage, its subagents' included. `home` is the caller's checked
    home of this workspace (cron.home_of)."""
    store = home / "state.db"
    if not job or not store.is_file():
        return []
    try:
        with session_usage.opened(store) as sessions:
            tops = sessions.with_prefix(f"cron_{job}_", since, until)
            rows = sessions.with_children(tops)
    except sqlite3.Error as error:
        log.warning("cron sessions of %s can't be read: %s", store, error)
        return []
    parent = {str(r["id"]): str(r.get("parent_session_id") or "") for r in rows}
    top_ids = {str(r["id"]) for r in tops}

    def top_of(sid: str) -> str:
        seen = set()
        while sid not in top_ids and sid in parent and sid not in seen:
            seen.add(sid)
            sid = parent[sid]
        return sid

    started = {str(r["id"]): float(r.get("started_at") or 0) for r in tops}
    grouped: dict[str, list[Usage]] = {}
    for r in rows:
        grouped.setdefault(top_of(str(r["id"])), []).append(of_session(r))
    return [(started[t], total(u)) for t, u in grouped.items() if t in started]
