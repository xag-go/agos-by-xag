"""What Hermes keeps per account, read for the pages: provider logins, its
credential pool (redacted, as Hermes lists it), and the gateway's session lanes
(routing rows) of each home.

Owns: Reads Hermes's own login, pool and routing stores through Hermes's runtime, and
keeps each answer while its stamp holds.

Must not: Write a login, a key or a lane (Hermes's CLI and actions/key_pools.py do), or
start and stop a gateway (gateway_run.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine.hermes.managed_scope import managed_files
from agos_core.engine.hermes.stamps import _routing_stamp
from agos_core.hermes_gateway.errors import EngineError

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_LANES",
    "_LOGINS",
    "_POOL",
    "credential_pool",
    "hermes_lanes",
    "hermes_logins",
]


# Run in Hermes's runtime by credential_pool: Hermes's credential pool of one home,
# as Hermes has it (hermes_cli/web_routers/ops.py list_credential_pool: redacted),
# after Hermes's own .env load (hermes_cli/env_loader.py load_hermes_dotenv: the
# managed .env applied last, so its numbered <VAR>_2.. keys join every pool:
# agent/credential_pool.py _env_key_var_candidates / _seed_from_env). Also, per
# provider, the .env name Hermes seeds its keys from (`bases`: the pool's own
# un-numbered env:<VAR> row, else the registry's first api_key_env_vars name) and,
# for the one-time move only, the keys AGOS once added by hand to every home
# ("manual" rows, with Hermes's fingerprint) and their removal by fingerprint with
# the dashboard's sticky remove_credential_pool_entry. A key leaves this script only
# for the move (to the managed .env writer, on stdin).
# Run in Hermes's runtime by hermes_logins: what one home is signed in with, read by
# Hermes's own functions (no AGOS parse of auth.json or config.yaml): the model's
# provider (load_config, managed overlay included) and its auth type (Hermes's
# PROVIDER_REGISTRY), the persisted credential pool (read_credential_pool: under
# Hermes's lock, no seeding, no network) with each entry's source, kind and last
# status, whether Hermes calls the entry's source borrowed
# (agent/credential_persistence.py is_borrowed_credential_source: a reference Hermes
# doesn't own; an `env:<VAR>` line of the home's own .env is a key the home holds),
# the providers with a saved sign-in state (get_provider_auth_state) and, when asked,
# `hermes auth status <provider>` (get_auth_status: can it reach its model; for a
# provider without a registry row, its pool from load_pool). No secret leaves the
# script.
_LOGINS = r"""
import json, logging
logging.disable(logging.CRITICAL)
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()
from hermes_cli.config import load_config
from hermes_cli.auth import (
    PROVIDER_REGISTRY, read_credential_pool, get_provider_auth_state, get_auth_status)
from agent.credential_persistence import is_borrowed_credential_source
job = json.loads(@JOB@)
out = {}
try:
    model = load_config().get("model")
    provider = str((model.get("provider") if isinstance(model, dict) else "") or "").strip().lower()
    reg = PROVIDER_REGISTRY.get(provider)
    pool = []
    for slug, entries in sorted(read_credential_pool().items()):
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict):
                continue
            source = str(e.get("source") or "")
            pool.append({
                "provider": str(slug), "label": str(e.get("label") or ""), "source": source,
                "auth_type": str(e.get("auth_type") or ""),
                "borrowed": is_borrowed_credential_source(source, slug)
                            and not source.startswith("env:"),
                "last_status": e.get("last_status") or "",
                "last_status_at": e.get("last_status_at") or "",
                "last_error_message": str(e.get("last_error_message") or "")[:300],
                "last_error_reason": str(e.get("last_error_reason") or "")[:300]})
    states = sorted(p for p in PROVIDER_REGISTRY if get_provider_auth_state(p))
    out = {"provider": provider, "auth_type": str(getattr(reg, "auth_type", "") or ""),
           "pool": pool, "signed_in_state": states}
    if job.get("status") and provider:
        # `hermes auth status`; a provider with no registry row (OpenRouter) has no
        # status there, so Hermes's own pool (its .env keys seeded) answers too.
        from agent.credential_pool import load_pool
        out["logged_in"] = bool(get_auth_status(provider).get("logged_in")) or bool(
            load_pool(provider).has_credentials())
except Exception as error:
    out = {"error": "%s: %s" % (type(error).__name__, error)}
print("AGOS-LOGINS " + json.dumps(out, default=str))
"""

# Run in Hermes's runtime by hermes_lanes: the gateway's session routing index of
# each home, read with Hermes's own functions and nothing written (a SessionStore
# would prune and save on load: gateway/session_persistence.py
# _prune_stale_sessions_locked): state.db's gateway_routing rows of the gateway
# store's scope (its resolved sessions dir, session_persistence.py _routing_scope)
# through SessionDB(read_only).load_gateway_routing_entries, then the legacy
# sessions.json for keys the DB lacks (Hermes's own import rule), each entry read by
# SessionEntry.from_dict: its key, /yolo, last activity and origin (the chat it
# came from).
_LANES = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from hermes_state import SessionDB
from gateway.session import SessionEntry
job = json.loads(@JOB@)
out = {}
for home in job["homes"]:
    home_p = Path(home)
    raw = {}
    state = home_p / "state.db"
    if state.is_file():
        db = SessionDB(db_path=state, read_only=True)
        scopes = []
        for d in (Path(job["root"]) / "sessions", home_p / "sessions"):
            scope = str(d.resolve())
            if scope not in scopes:
                scopes.append(scope)
        try:
            for scope in scopes:
                for k, v in db.load_gateway_routing_entries(scope=scope).items():
                    raw.setdefault(k, v)
        finally:
            close = getattr(db, "close", None)
            if callable(close):
                close()
    try:
        legacy = json.loads((home_p / "sessions" / "sessions.json").read_text())
    except Exception:
        legacy = {}
    for k, v in (legacy.items() if isinstance(legacy, dict) else ()):
        if not str(k).startswith("_") and isinstance(v, dict):
            raw.setdefault(str(k), json.dumps(v))
    lanes = []
    for k, v in raw.items():
        try:
            data = json.loads(v)
        except Exception:
            continue
        try:
            e = SessionEntry.from_dict(data)
            o = e.origin
            lane = {"yolo": bool(e.yolo), "updated_at": e.updated_at.isoformat(),
                    "platform": getattr(getattr(o, "platform", None), "value", "") if o else "",
                    "chat_id": str(o.chat_id or "") if o else "",
                    "thread_id": str(o.thread_id or "") if o else ""}
        except Exception:
            # A plugin platform (AGOS's "agos") is known only in a gateway that loaded
            # it (gateway/config.py Platform: plugin names resolve only once registered): the
            # entry's own fields, as
            # SessionEntry.to_dict / SessionSource.to_dict wrote them.
            o = data.get("origin") if isinstance(data.get("origin"), dict) else {}
            lane = {"yolo": data.get("yolo") is True, "updated_at": str(data.get("updated_at") or ""),
                    "platform": str(o.get("platform") or ""), "chat_id": str(o.get("chat_id") or ""),
                    "thread_id": str(o.get("thread_id") or "")}
        lanes.append({"key": k, **lane})
    out[home] = lanes
print("AGOS-LANES " + json.dumps(out))
"""

_POOL = r"""
import asyncio, json, logging, re
logging.disable(logging.CRITICAL)
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()
from hermes_cli.web_routers import ops
from hermes_cli.auth import PROVIDER_REGISTRY
from agent.credential_pool import (
    load_pool, get_pool_strategy, SUPPORTED_POOL_STRATEGIES, AUTH_TYPE_API_KEY)
from agent.credential_persistence import fingerprint_secret_value
job = json.loads(@JOB@)
def base_of(provider, entries):
    for e in entries:
        name = (e.source or "").split(":", 1)[1] if (e.source or "").startswith("env:") else ""
        if name and not re.search(r"_[0-9]+$", name):
            return name
    pconfig = PROVIDER_REGISTRY.get(provider)
    if pconfig and pconfig.auth_type == AUTH_TYPE_API_KEY and pconfig.api_key_env_vars:
        return list(pconfig.api_key_env_vars)[0]
    return None
out = {}
try:
    if job["do"] == "drop":
        pool = load_pool(job["provider"])
        gone = 0
        while True:
            index = next((i for i, e in enumerate(pool.entries(), start=1)
                          if e.source == "manual" and e.auth_type == AUTH_TYPE_API_KEY
                          and fingerprint_secret_value(e.access_token) in job["fps"]), None)
            if index is None:
                break
            asyncio.run(ops.remove_credential_pool_entry(job["provider"], index))
            pool = load_pool(job["provider"])
            gone += 1
        out["dropped"] = gone
    if job["do"] == "remove":
        # An old hand-added key (a provider Hermes reads no .env key for): out of
        # this home's pool by its label, with the dashboard's own remove.
        pool = load_pool(job["provider"])
        index = next((i for i, e in enumerate(pool.entries(), start=1)
                      if e.source == "manual" and e.label == job["label"]), None)
        if index is not None:
            asyncio.run(ops.remove_credential_pool_entry(job["provider"], index))
        out["removed"] = index is not None
    listed = asyncio.run(ops.list_credential_pool())
    names = {p["provider"] for p in listed["providers"]} | set(job.get("providers") or [])
    entries = {p: load_pool(p).entries() for p in sorted(names)}
    out.update({"pool": listed, "strategies": sorted(SUPPORTED_POOL_STRATEGIES),
                "strategy": {p: get_pool_strategy(p) for p in sorted(names)},
                "bases": {p: base_of(p, e) for p, e in entries.items()}})
    if job["do"] == "manual":
        out["manual"] = {p: [{"label": e.label, "key": e.access_token,
                              "fp": fingerprint_secret_value(e.access_token)}
                             for e in es if e.source == "manual"
                             and e.auth_type == AUTH_TYPE_API_KEY and e.access_token]
                         for p, es in entries.items()}
except Exception as error:
    out = {"error": "%s: %s" % (type(error).__name__, error)}
print("AGOS-POOL " + json.dumps(out, default=str))
"""


def hermes_lanes(
    self: "HermesEngine", root: Path, homes: list[Path]
) -> dict[str, list[dict[str, Any]]]:
    """The gateway's session routing index of each home (a root and its members),
    as Hermes reads it (the _LANES script): {home: [{"key", "yolo", "updated_at",
    "platform", "chat_id", "thread_id"}]}. Kept per root while what the script
    reads is unchanged: each home's routing rows in its state.db (read only) and
    its sessions.json."""
    key = (str(root), *map(str, homes))

    def ask() -> dict[str, list[dict[str, Any]]]:
        job = {"root": str(root), "homes": [str(h) for h in homes]}
        script = _LANES.replace("@JOB@", repr(json.dumps(job)))
        found: dict[str, list[dict[str, Any]]] = json.loads(
            self._in_runtime(root, script, "AGOS-LANES")
        )
        return found

    routing_stamp = tuple(_routing_stamp(home) for home in homes)
    return copy.deepcopy(self._lanes.get(key, routing_stamp, ask))


def hermes_logins(self: "HermesEngine", home: Path, *, status: bool = False) -> dict[str, Any]:
    """What this home is signed in with, as Hermes has it (one runtime run, the
    _LOGINS script): {"provider", "auth_type", "pool": [entry...],
    "signed_in_state": [provider...], "logged_in"?: bool (with `status`: Hermes's
    `auth status` of the model's provider)}. Kept while the home's auth.json,
    config.yaml and .env and the managed scope's files are unchanged."""

    def mark() -> tuple[int, ...]:
        out = []
        for path in (
            home / "auth.json",
            home / "config.yaml",
            home / ".env",
            *managed_files(self.settings.managed_home),
        ):
            try:
                out.append(path.stat().st_mtime_ns)
            except OSError:
                out.append(0)
        return tuple(out)

    key = (str(home), status)
    seen = self._logins_seen.get(key)
    if seen is not None and seen[0] == mark():
        return copy.deepcopy(seen[1])
    script = _LOGINS.replace("@JOB@", repr(json.dumps({"status": status})))
    found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-LOGINS"))
    if found.get("error"):
        raise EngineError(str(found["error"])[:300])
    # Marked after the run: Hermes's own read may tidy auth.json.
    self._logins_seen[key] = (mark(), found)
    return copy.deepcopy(found)


def credential_pool(self: "HermesEngine", home: Path, job: dict[str, Any]) -> dict[str, Any]:
    """Hermes's credential pool of one home (redacted), after an optional change:
    {"do": "list" | "add" | "remove" | "priority", ...}."""
    script = _POOL.replace("@JOB@", repr(json.dumps(job)))
    found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-POOL"))
    if found.get("error"):
        raise EngineError(str(found["error"])[:300])
    return found
