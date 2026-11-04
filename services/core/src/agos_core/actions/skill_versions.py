"""A workspace skill's versions: derived from Hermes's skill ledger, kept as one
immutable snapshot per version beside the root's skills (engine/skill_versions.py
says why and where), diffed server-side, restored through Hermes's own skill tool.

- Reading (the Versions tab, a card's pins): the ledger is asked again only when it
  moved since (engine.ledger_stamp); the folder itself is compared each time, so a
  change the ledger never saw (Hermes's hub install / update) is a version too.
- A restore is ONE skill_manage batch (actions/skill_writes.py: SKILL.md and every
  text file under Hermes's skill folders that differs, removed files included), so
  Hermes's ledger records it like any write and it comes back as the next version,
  "restored from vN". Restoring the current state writes nothing (no version).
- AGOS's own writes name their versions (owner / Co-Founder, what was done) with
  the ledger ids the write made; everything else is labelled from the ledger.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.engine import skill_versions as sv
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.skill_versions")

_lock = threading.Lock()
# (home, skill) -> the ledger stamp the last reconcile saw: no Hermes start while
# the ledger stands still (the folder is still compared).
_seen: dict[tuple[str, str], tuple[int, ...]] = {}
# (home, skill) -> labels AGOS's own writes left for their ledger entries
# (ids, author, action, summary), applied when those entries become a version.
_labels: dict[tuple[str, str], list[tuple[frozenset[str], str, str, str]]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _places(core: Core, workspace_id: str, name: str) -> tuple[Path, Path]:
    from agos_core.actions import workspace_skills

    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    home = core.engine.profile_home(workspace_id)
    folder = workspace_skills.skill_dir(core, workspace_id, name)
    assert folder is not None
    return home, folder


def _row(core: Core, workspace_id: str, item_id: int) -> Any:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This skill")
    return row


def _observed_as(row: Any) -> tuple[str, str, str]:
    """Who a change the ledger didn't see is put down to (author, action, the action
    when it is the skill's first version): Hermes's hub for a skill installed from
    the web (its install / update write no ledger entry), else 'outside' (a file
    copied beside the skill, an editor)."""
    if row is not None and str(row["source"] or "") == "web":
        return "hub", "update", "install"
    return "outside", "observed", "observed"


def reconcile(core: Core, workspace_id: str, name: str, row: Any = None) -> list[sv.Version]:
    """The skill's versions, oldest first, brought up to date with Hermes's ledger
    and the folder (new ones written). Hermes's runtime runs only when the ledger
    moved since the last look."""
    home, folder = _places(core, workspace_id, name)
    key = (str(home), name)
    with _lock:
        stored = sv.load_all(home, name)
        history: list[dict[str, Any]] = []
        stamp = core.engine.ledger_stamp(home) if core.engine is not None else ()
        if _seen.get(key) != stamp:
            known = [e for v in stored for e in v.entries]
            try:
                history = core.engine.skill_history(home, folder, name, known)  # type: ignore[union-attr]
            except (EngineError, OSError, ValueError) as error:
                log.warning("skill ledger of %s/%s not read: %s", workspace_id, name, error)
                return stored  # nothing observed either: a ledger entry may explain it
            _seen[key] = stamp
        author, action, first_action = _observed_as(row)
        new = sv.derive(
            stored,
            history,
            sv.read_folder(folder),
            now=_now(),
            observed_author=author,
            observed_action=action,
            first_action=first_action,
        )
        new = [_labelled(key, v) for v in new]
        for version in new:
            sv.save_for(home, name, version)
        return stored + new


def _labelled(key: tuple[str, str], version: sv.Version) -> sv.Version:
    pending = _labels.get(key) or []
    for i, (ids, author, action, summary) in enumerate(pending):
        if version.entries and set(version.entries) <= ids:
            del pending[i]
            return dataclasses.replace(version, author=author, action=action, summary=summary)
    return version


def record(
    core: Core,
    workspace_id: str,
    name: str,
    entries: list[str],
    *,
    author: str,
    action: str,
    summary: str,
    now: bool = False,
) -> None:
    """An AGOS write just made these ledger entries: its version gets this label
    when it is next derived (`now`: at once, one Hermes run)."""
    if not entries:
        return
    home, _folder = _places(core, workspace_id, name)
    key = (str(home), name)
    with _lock:
        _labels.setdefault(key, []).append((frozenset(entries), author, action, summary))
    if now:
        reconcile(core, workspace_id, name)


# ---- reading --------------------------------------------------------------------------


def versions(core: Core, workspace_id: str, item_id: int) -> list[dict[str, Any]]:
    """The Versions tab: newest first, no content."""
    row = _row(core, workspace_id, item_id)
    found = reconcile(core, workspace_id, str(row["name"]), row)
    return [v.listed() for v in reversed(found)]


def current(core: Core, workspace_id: str, name: str) -> int:
    """The skill's version number now (0: nothing known of it)."""
    row = repo.find_item(core.db, "skill", name, workspace_id)
    found = reconcile(core, workspace_id, name, row)
    return found[-1].number if found else 0


def pins(core: Core, workspace_id: str, names: list[str]) -> dict[str, int]:
    """The version of each of these workspace skills now (for a card's pins);
    a name that isn't one of the workspace's skills is left out."""
    from agos_core.actions import workspace_skills

    mine = workspace_skills.names(core, workspace_id)
    return {n: current(core, workspace_id, n) for n in names if n in mine}


def _version(found: list[sv.Version], number: int) -> sv.Version:
    for v in found:
        if v.number == number:
            return v
    raise NotFoundError(f"Version {number}")


def diff(core: Core, workspace_id: str, item_id: int, a: int, b: int) -> list[dict[str, str]]:
    """Unified diff per file from version a to version b."""
    row = _row(core, workspace_id, item_id)
    found = reconcile(core, workspace_id, str(row["name"]), row)
    return sv.unified_diff(_version(found, a), _version(found, b))


def content(core: Core, workspace_id: str, item_id: int, number: int) -> dict[str, str | None]:
    """One version's text files (None for a binary one)."""
    row = _row(core, workspace_id, item_id)
    found = reconcile(core, workspace_id, str(row["name"]), row)
    return {rel: sv.as_text(data) for rel, data in sorted(_version(found, number).files.items())}


# ---- restore --------------------------------------------------------------------------


def restore(core: Core, workspace_id: str, item_id: int, number: int) -> dict[str, Any]:
    """The skill's folder becomes version `number`, in ONE Hermes skill_manage batch
    (its ledger records it; it comes back as the next version, 'restored from vN').
    Already that state: nothing is written, no version. Returns {restored, version
    (the new number, or the current one), skipped (files Hermes's tool can't write)}."""
    from agos_core.actions import skill_writes, workspace_skills
    from agos_core.actions.skill_text_files import HERMES_FILE_DIRS

    row = _row(core, workspace_id, item_id)
    name = str(row["name"])
    found = reconcile(core, workspace_id, name, row)
    target = _version(found, number)
    home, folder = _places(core, workspace_id, name)
    if not (folder / "SKILL.md").is_file():
        raise ActionError("This skill has nothing in it yet.", 409)
    text, files, skipped = sv.restore_plan(target, sv.read_folder(folder), HERMES_FILE_DIRS)
    if text is None and not files:
        return {"restored": False, "version": found[-1].number, "skipped": skipped}
    entries = skill_writes.write(core, home, name, folder, text, files)
    record(
        core,
        workspace_id,
        name,
        entries,
        author="owner",
        action="restore",
        summary=f"restored from v{number}",
        now=True,
    )
    workspace_skills.applied(core, workspace_id)
    latest = sv.load_all(home, name)
    return {
        "restored": bool(entries),
        "version": latest[-1].number if latest else number,
        "skipped": skipped,
    }
