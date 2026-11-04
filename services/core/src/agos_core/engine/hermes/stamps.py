"""The stamps that tell when Hermes must be asked again: what a home's gateway files,
routing rows, held writes and skill ledger say now (engine/read_cache.py).

Owns: Cheap read-only stamps of Hermes's files and rows.

Must not: Ask Hermes anything or cache an answer (the part that asks keeps its cache).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from agos_core.engine import read_cache

__all__ = [
    "_LAMP_GATEWAY_KEYS",
    "_LAMP_PLATFORM_KEYS",
    "_gateway_files",
    "_held_stamp",
    "_ledger_stamp",
    "_routing_stamp",
]

# What a bot's lamp shows from a gateway snapshot (gateway/status.py
# write_runtime_status): the gateway's own state and each platform's state and
# error. Not what moves on every tick: the heartbeat stamps, the active agents and
# work, the metrics (each re-stamps a platform's updated_at).
_LAMP_GATEWAY_KEYS = ("pid", "start_time", "gateway_state", "exit_reason", "restart_requested")
_LAMP_PLATFORM_KEYS = ("state", "error_code", "error_message", "needs_attention", "retrying_since")


def _gateway_files(home: Path) -> tuple[Any, ...]:
    """What a home's gateway files say now, for engine.gateway_shown: what its
    snapshot (gateway_state.json) says about the gateway and its platforms, whether
    the process it names is still the same one (its start time in /proc, what
    Hermes's own pid guard compares) and its pid file. Only decides when Hermes is
    asked again; the verdict itself is Hermes's (gateway/status.py)."""
    try:
        raw = (home / "gateway_state.json").read_bytes()
    except OSError:
        raw = b""
    try:
        record = json.loads(raw)
    except ValueError:
        record = None
    if not isinstance(record, dict):
        return hashlib.sha256(raw).hexdigest(), None, read_cache.file_stamp(home / "gateway.pid")
    platforms = record.get("platforms")
    said = json.dumps(
        {
            "gateway": {k: record.get(k) for k in _LAMP_GATEWAY_KEYS},
            "platforms": {
                str(name): {k: entry.get(k) for k in _LAMP_PLATFORM_KEYS}
                for name, entry in (platforms.items() if isinstance(platforms, dict) else ())
                if isinstance(entry, dict)
            },
        },
        sort_keys=True,
        default=str,
    )
    pid, start = record.get("pid"), None
    if isinstance(pid, int) and pid > 0:
        try:
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError):
            start = None
    return said, (pid, start), read_cache.file_stamp(home / "gateway.pid")


def _routing_stamp(home: Path) -> tuple[Any, ...]:
    """What engine.hermes_lanes' script reads in a home: its gateway routing rows
    (state.db's gateway_routing, read only: H: hermes_state_common.py) and its
    legacy sessions.json. When the rows can't be read, the files' own stamps."""
    import sqlite3

    index = read_cache.file_stamp(home / "sessions" / "sessions.json")
    state = home / "state.db"
    if not state.is_file():
        return ("no state", index)
    digest = hashlib.sha256()
    try:
        with contextlib.closing(
            sqlite3.connect(f"file:{state}?mode=ro", uri=True, timeout=2)
        ) as db:
            for row in db.execute(
                "SELECT scope, session_key, entry_json FROM gateway_routing"
                " ORDER BY scope, session_key"
            ):
                digest.update(repr(tuple(row)).encode())
    except sqlite3.Error:
        return (read_cache.sqlite_stamp(state), index)
    return (digest.hexdigest(), index)


def _held_stamp(home: Path) -> tuple[Any, ...]:
    """What engine.pending_writes' script reads in a home: the writes Hermes holds
    (<home>/pending/{memory,skills}/*.json, H: tools/write_approval.py
    _pending_path/_pending_files) and its config.yaml (the gates). While a memory
    write is held, also the memory files its lines are matched in; while a skill
    write is held, the skills folder and the half minute (a diff is shown against
    the skill's files, which may live outside the home: skills.external_dirs)."""
    held: list[Any] = []
    for sub in ("memory", "skills"):
        folder = home / "pending" / sub
        try:
            names = sorted(p.name for p in folder.glob("*.json"))
        except OSError:
            names = []
        held.append(tuple((n, read_cache.file_stamp(folder / n)) for n in names))
    extra: list[Any] = []
    if held[0]:
        extra.append(
            read_cache.file_stamp(home / "memories" / "MEMORY.md", home / "memories" / "USER.md")
        )
    if held[1]:
        extra.append((read_cache.file_stamp(home / "skills"), int(time.time() // 30)))
    return (tuple(held), read_cache.file_stamp(home / "config.yaml"), tuple(extra))


def _ledger_stamp(home: Path) -> tuple[int, ...]:
    """What engine.skill_changes' script reads in a home: Hermes's skill ledger
    and its folder of blobs (H: tools/skill_ledger.py ledger_path, blobs_dir; a
    blob is named by its hash, so a new one shows in the folder's stamp). Hermes's
    own rollback appends to the ledger, so an Undo moves the stamp too."""
    return read_cache.file_stamp(
        home / "skills" / ".curator_ledger.jsonl", home / ".curator_backups" / "blobs"
    )
