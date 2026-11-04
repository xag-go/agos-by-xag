"""Settings → Health: Hermes's own `hermes status --full` and `hermes doctor` (no
--fix) of every workspace's root, as Hermes prints them.

AGOS re-implements none of the checks: each report is Hermes's own CLI run in the
root's home with the managed scope every AGOS run has (so doctor's "Managed scope
active: N config key(s), M env key(s) pinned by <dir>" line shows, H:
hermes_cli/doctor_config.py:137 managed_scope_check).

Doctor takes 6-12 s per root (status 1.5 s), so the page never waits for it: each
root's last two reports stay in this process's memory with the time they were
taken (a restart forgets them) and the page gets them at once. Hermes is asked
again behind the page when they are older than MAX_AGE_S or when the owner asks
for a new check; the page shows "Checking…" until the new reports are in. A root
with no report yet (the first view after a start, before the read-ahead reached
it) doesn't make the page wait either: it shows as checking, Hermes's check still
running, and each root's reports come as soon as its own run ends (the page asks
again every few seconds). Those runs go on the read cache's two low-priority
background threads like every other ask behind a page (at most two at once, where
the page used to run four at once and wait), so opening it right after a start
adds no load. The Co-Founder's check in a chat always waits for new ones.

"Has problems: yes/no" is Hermes's own verdict, doctor's exit code (H:
hermes_cli/doctor.py run_doctor returns `int(bool(issues or manual_issues))`, the
CLI's exit code). Neither report has a --json, so the counts are still Hermes's ✗/⚠
marks read off its text.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine import read_cache
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.hermes_health")

REPORTS = ("status", "doctor")
# Hermes's own marks in its reports (hermes_cli/doctor.py check_ok/warn/fail).
_FAIL, _WARN = "✗", "⚠"
# A kept report older than this is checked again behind the page.
MAX_AGE_S = 300.0
# The longest a root with no report yet is waited for (hermes_check stops at 180 s).
_WAIT_S = 240.0


@dataclass
class _Slot:
    """One root's last report of one kind."""

    report: dict[str, Any] | None = None
    taken: float = 0.0  # time.time() when Hermes printed it
    running: threading.Event | None = None  # set when the check running now ends


_lock = threading.Lock()


def _summary(text: str) -> dict[str, int]:
    lines = text.splitlines()
    return {
        "problems": sum(1 for ln in lines if ln.strip().startswith(_FAIL)),
        "warnings": sum(1 for ln in lines if ln.strip().startswith(_WARN)),
    }


def _ask(engine: Any, workspace_id: str, report: str) -> dict[str, Any]:
    """Hermes's report now (or why Hermes didn't answer)."""
    try:
        text, code = engine.hermes_check(workspace_id, report)
        return {
            "text": text,
            "error": None,
            "has_problems": code != 0 if report == "doctor" else None,
            **_summary(text),
        }
    except (EngineError, OSError) as error:
        log.info("hermes %s of %s not read: %s", report, workspace_id, error)
        return {"text": "", "error": str(error), "has_problems": None, "problems": 0, "warnings": 0}


def _slot(engine: Any, key: tuple[str, str]) -> _Slot:
    with _lock:
        kept: dict[tuple[str, str], _Slot] = engine.health_kept
        return kept.setdefault(key, _Slot())


def _begin(slot: _Slot) -> threading.Event | None:
    """Marks a check as running; None when one already runs (it is shared)."""
    with _lock:
        if slot.running is not None:
            return None
        slot.running = threading.Event()
        return slot.running


def _check(engine: Any, key: tuple[str, str], slot: _Slot, done: threading.Event) -> None:
    """Runs Hermes's report now and keeps it."""
    try:
        got = _ask(engine, *key)
        with _lock:
            slot.report, slot.taken = got, time.time()
    finally:
        with _lock:
            slot.running = None
        done.set()


def _roots(core: Core, engine: Any, workspace_id: str | None) -> list[Any]:
    from agos_core.db.workspaces import list_workspaces

    return [
        w
        for w in list_workspaces(core.db)
        if (workspace_id is None or w.id == workspace_id)
        and (engine.profile_home(w.id) / "config.yaml").is_file()
    ]


def read(
    core: Core, workspace_id: str | None = None, *, fresh: bool = False, wait: bool = False
) -> dict[str, Any]:
    """Each root's two reports (or why Hermes didn't answer), as last taken, with
    when and whether a new check runs; a report not taken yet is asked behind the
    page. `fresh`: check again (behind the page unless `wait`); `wait`: return only
    new reports (the Co-Founder's check)."""
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    roots = _roots(core, engine, workspace_id)
    if workspace_id is not None and not roots:
        raise ActionError("This workspace's Hermes isn't set up yet.", status=404)
    now = time.time()
    slots: dict[tuple[str, str], _Slot] = {}
    now_jobs: list[tuple[tuple[str, str], _Slot, threading.Event]] = []
    waits: list[threading.Event] = []
    for w in roots:
        for r in REPORTS:
            key = (w.id, r)
            slot = slots[key] = _slot(engine, key)
            if slot.report is None or fresh or now - slot.taken > MAX_AGE_S:
                done = _begin(slot)
                if done is not None and wait:
                    now_jobs.append((key, slot, done))
                elif done is not None:
                    read_cache.submit(partial(_check, engine, key, slot, done))
            running = slot.running
            if running is not None and wait:
                waits.append(running)
    if now_jobs:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda job: _check(engine, *job), now_jobs))
    for done in waits:
        done.wait(_WAIT_S)
    return {"roots": [_root_view(engine, w, slots) for w in roots]}


def _root_view(engine: Any, w: Any, slots: dict[tuple[str, str], _Slot]) -> dict[str, Any]:
    with _lock:
        mine = {r: slots[(w.id, r)] for r in REPORTS}
        reports = {
            r: {**s.report, "pending": False}
            if s.report is not None
            else {
                # Not taken yet (its first run is on its way): not an error, the page
                # shows "Checking…" and asks again until Hermes's report is in.
                "text": "",
                "error": None,
                "pending": True,
                "has_problems": None,
                "problems": 0,
                "warnings": 0,
            }
            for r, s in mine.items()
        }
        taken = [s.taken for s in mine.values() if s.report is not None]
        checking = any(s.running is not None for s in mine.values())
    checked_at = (
        datetime.fromtimestamp(min(taken), UTC).isoformat(timespec="seconds")
        if len(taken) == len(REPORTS)
        else None
    )
    return {
        "workspace_id": w.id,
        "name": w.name,
        "home": str(engine.profile_home(w.id)),
        **reports,
        "checked_at": checked_at,
        "checking": checking,
    }


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): each root's reports that are not
    kept yet, one Hermes run at a time, so the page has them when it opens."""
    engine = core.engine
    if engine is None:
        return
    for w in _roots(core, engine, None):
        for r in REPORTS:
            key = (w.id, r)
            slot = _slot(engine, key)
            if slot.report is not None:
                continue
            done = _begin(slot)
            if done is not None:
                _check(engine, key, slot, done)


def as_text(found: dict[str, Any], limit: int = 6000) -> str:
    """The reports in short, for the Co-Founder's answer in a chat: each root's counts
    and Hermes's own lines that are a problem or a warning."""
    parts = []
    for root in found["roots"]:
        lines = [f"## {root['name']}"]
        for report in REPORTS:
            got = root[report]
            if got.get("pending"):
                lines.append(f"hermes {report}: Hermes is still checking (ask again in a moment)")
                continue
            if got["error"]:
                lines.append(f"hermes {report}: not read ({got['error']})")
                continue
            verdict = got.get("has_problems")
            said = "" if verdict is None else f"problems: {'yes' if verdict else 'no'}; "
            lines.append(
                f"hermes {report}: {said}{got['problems']} problem mark(s), "
                f"{got['warnings']} warning mark(s)"
            )
            if report == "doctor":
                lines += [
                    ln.strip()
                    for ln in got["text"].splitlines()
                    if ln.strip().startswith((_FAIL, _WARN, "✓ Managed scope"))
                ]
        parts.append("\n".join(lines))
    text = "\n\n".join(parts) or "No workspace's Hermes is set up yet."
    return text[:limit]
