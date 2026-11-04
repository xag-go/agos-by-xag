"""How Hermes found a provider key when it last used it: its credential pool.

Hermes seeds an env-backed key into `auth.json` `credential_pool.<provider>` (source
`env:<VAR>`, agent/credential_pool.py; save_provider_env_credential runs load_pool
so the entry exists right after a save) and records on each entry how the last use
went: `last_status` ("ok", "exhausted", "dead"), `last_status_at` and the
`last_error_*` fields (agent/credential_pool.py:193-197, PooledCredential). AGOS
reads that with Hermes's own read_credential_pool in every home that holds the key
(the shared home and each workspace's root, which General Settings copies the key
into: engine.hermes_logins, `pool`) and keeps no record. AGOS never opens auth.json.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class KeyStatus:
    status: str  # Hermes's last_status ("ok", "exhausted", "dead", …); "" = not used yet
    at: str  # ISO time Hermes set it ("" when unknown)
    problem: str  # Hermes's last error, when the status isn't ok


NONE = KeyStatus("", "", "")


def _epoch(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def status(pools: Iterable[list[dict[str, Any]]], env_names: list[str]) -> KeyStatus:
    """The newest status Hermes recorded for the key under any of these variables
    (`pools`: each home's pool entries as Hermes read them)."""
    sources = {f"env:{n}" for n in env_names if n}
    best: tuple[float, dict[str, Any]] | None = None
    for entries in pools:
        for entry in entries:
            if entry.get("source") not in sources or not entry.get("last_status"):
                continue
            at = _epoch(entry.get("last_status_at"))
            if best is None or at > best[0]:
                best = (at, entry)
    if best is None:
        return NONE
    at, entry = best
    state = str(entry.get("last_status") or "")
    problem = ""
    if state != "ok":
        problem = str(entry.get("last_error_message") or entry.get("last_error_reason") or "")[:300]
    when = datetime.fromtimestamp(at, UTC).isoformat() if at else ""
    return KeyStatus(state, when, problem)
