"""Hermes's own errors in Settings → Errors (source "hermes").

Each workspace's Hermes keeps its warnings and errors in its own `errors.log`
(its gateway, its agents, its tools). AGOS doesn't parse or rotate that file
itself: it asks Hermes's CLI (`hermes logs errors --level ERROR`, engine
`hermes_check(ws, "errors")`) in the workspace's root, every `EVERY_S`, only when
the file changed since the last look (its size and time), and counts each new
ERROR entry on its issue (error_issues.py), tagged with the workspace. Hermes's
lines go to the issues only, not to the workspace Log (the Log reads Hermes's own
logs already).

What was already counted is remembered per workspace (`errors.hermes_seen.<ws>`:
the last entry's time stamp). The first look at a workspace counts its recent
errors without alerting the owner (they are old news).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from agos_core.db.app_settings import get_setting, set_setting

log = logging.getLogger("agos.hermes_errors")

SEEN = "errors.hermes_seen."  # + workspace id: {"at": last entry's stamp, "file": [size, mtime]}
EVERY_S = 300
_ENTRY = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:,\d+)?) (ERROR|CRITICAL) (?:\[[^\]]*\] )?([\w.\-]+): ?(.*)$"
)
_STAMPED = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
_TYPE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))(?::\s*(.*))?$")


def entries(text: str) -> list[dict[str, Any]]:
    """Hermes's printed errors: one entry per stamped ERROR line, with the lines
    after it (its traceback) until the next stamped line."""
    found: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            continue  # the CLI's header
        hit = _ENTRY.match(line)
        if hit:
            current = {
                "at": hit.group(1),
                "logger": hit.group(3),
                "message": hit.group(4).strip(),
                "trace": [],
            }
            found.append(current)
        elif _STAMPED.match(line):
            current = None  # a WARNING/INFO line: not ours
        elif current is not None and line.strip():
            current["trace"].append(line.rstrip())
    for entry in found:
        trace: list[str] = entry["trace"]
        error_type = ""
        for line in reversed(trace):
            typed = _TYPE.match(line.strip())
            if typed:
                error_type = typed.group(1).rsplit(".", 1)[-1]
                break
        entry["type"] = error_type
        entry["trace"] = "\n".join(trace)
    return found


def _when(stamp: str) -> datetime | None:
    try:
        # Hermes stamps its log in the machine's local time.
        return datetime.strptime(stamp.split(",")[0], "%Y-%m-%d %H:%M:%S").astimezone()
    except ValueError:
        return None


def _file_mark(core: Any, workspace_id: str) -> list[float] | None:
    path = core.engine.profile_home(workspace_id) / "logs" / "errors.log"
    try:
        stat = path.stat()
    except OSError:
        return None
    return [float(stat.st_size), float(stat.st_mtime)]


def read(core: Any, workspace_id: str) -> int:
    """Counts this workspace's new Hermes errors; returns how many were new."""
    from agos_core.engine.hermes import EngineError

    mark = _file_mark(core, workspace_id)
    seen = get_setting(core.db, SEEN + workspace_id, {})
    seen = seen if isinstance(seen, dict) else {}
    if mark is None or seen.get("file") == mark:
        return 0
    try:
        text, _code = core.engine.hermes_check(workspace_id, "errors", timeout=60)
    except (EngineError, OSError) as error:
        log.info("Hermes errors of %s not read: %s", workspace_id, error)
        return 0
    first = "at" not in seen
    last = str(seen.get("at") or "")
    new = [e for e in entries(text) if e["at"] > last]
    for entry in new:
        log.error(
            "%s",
            entry["message"] or entry["logger"],
            extra={
                "agos_source": "hermes",
                "agos_where": entry["logger"],
                "agos_type": entry["type"],
                "agos_trace": entry["trace"],
                "agos_frames": [entry["logger"]],
                "agos_workspace": workspace_id,
                "agos_issue_only": True,
                "agos_quiet": first,
                "agos_at": _when(entry["at"]),
            },
        )
    set_setting(
        core.db,
        SEEN + workspace_id,
        {"at": max([last, *(e["at"] for e in new)]), "file": mark},
    )
    return len(new)


def read_all(core: Any) -> int:
    from agos_core.db.workspaces import list_workspaces

    if core.engine is None:
        return 0
    total = 0
    for workspace in list_workspaces(core.db, include_archived=True):
        try:
            total += read(core, workspace.id)
        except Exception as error:  # noqa: BLE001 - one root never stops the others
            log.warning("Hermes errors of %s not counted: %s", workspace.id, type(error).__name__)
    return total


async def run_forever(core: Any) -> None:
    """Hermes's errors and the dead-man's Telegram place, every few minutes."""
    from agos_core.actions import deadman

    while True:
        try:
            await asyncio.to_thread(read_all, core)
            await asyncio.to_thread(deadman.write_place, core)
        except Exception:
            log.exception("errors loop failed")
        await asyncio.sleep(EVERY_S)
