"""The sandbox broker's refusals, told to the owner.

agos-sandboxd (engine/sandboxd.py) writes each request it refuses to its events file
(`<policies>/events.jsonl`). Docker only shows the agent "exit status 125", so a
wrong policy once left every team member without a terminal for days, unseen
(live 2026-11-04..08). Each round this reads the lines written since the last one
and logs every refused sandbox start as an ERROR on "agos.sandbox" with its
workspace: it lands in that workspace's Log, in Settings -> Errors, and a new issue
is told to the owner (actions/system_log.py, error_issues.py, error_alerts.py).

Only refused starts (`POST /containers/create`) count: the cleanup Hermes runs after
a failed start (`DELETE /containers/<name>: no such container`) is noise.

Owns: the read position in the events file and the report. Must not: change a
policy or the broker (engine/cage.py, engine/sandbox_broker.py do).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path

__all__ = ["OFFSET_NAME", "report_new"]

log = logging.getLogger("agos.sandbox")

OFFSET_NAME = "events.offset"  # beside events.jsonl: how far the last round read
_CREATE = "POST /containers/create"
_NAME = re.compile(r"hermes-[0-9a-f]{8}")
MAX_BYTES = 4 * 1024 * 1024  # one round reads at most this much (a flood never stalls it)


def _offset(path: Path, size: int) -> int:
    try:
        at = int(path.read_text().strip())
    except (OSError, ValueError):
        return -1
    return at if 0 <= at <= size else 0  # the file was cut or replaced: from the start


def report_new(policies_dir: Path, profile_prefix: str) -> int:
    """Logs each refused sandbox start since the last round (once per workspace and
    reason per round); returns how many refusals it read. The first round ever only
    marks the end of the file: older refusals were already there before this check."""
    events = policies_dir / "events.jsonl"
    marker = policies_dir / OFFSET_NAME
    try:
        size = events.stat().st_size
    except OSError:
        return 0
    start = _offset(marker, size)
    if start < 0:
        with contextlib.suppress(OSError):
            marker.write_text(f"{size}\n")
        return 0
    with events.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read(MAX_BYTES)
    whole = chunk.rfind(b"\n") + 1  # a half-written last line waits for the next round
    seen: dict[tuple[str, str], int] = {}
    for raw in chunk[:whole].splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("event") != "denied":
            continue
        detail = str(event.get("detail") or "")
        if not detail.startswith(_CREATE):
            continue
        key = (str(event.get("profile") or ""), _NAME.sub("hermes-…", detail))
        seen[key] = seen.get(key, 0) + 1
    for (profile, detail), count in sorted(seen.items()):
        workspace = profile.removeprefix(profile_prefix).split("--", 1)[0]
        log.error(
            "a team sandbox could not start (refused %d time(s)): %s",
            count,
            detail,
            extra={"agos_workspace": workspace} if workspace else None,
        )
    with contextlib.suppress(OSError):
        marker.write_text(f"{start + whole}\n")
    return sum(seen.values())
