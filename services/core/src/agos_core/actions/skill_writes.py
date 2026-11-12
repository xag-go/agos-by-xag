"""Every skill write AGOS makes for the owner or the Co-Founder goes through Hermes's
own skill tool, in the Hermes home that holds the skill.

- `skill_manage` (H: tools/skill_manager_tool.py) applies Hermes's validation and
  per-skill lock, as an atomic batch; replayed past the agents' write_approval gate
  the way Hermes's own /skills approve does (`apply_skill_pending`).
- Every mutation is an entry of Hermes's skill ledger (H: tools/skill_ledger.py
  record_mutation: before/after blobs by content hash, no size or type cut). AGOS
  keeps only the entry ids; an Undo is Hermes's rollback_entry of them.
- Only the files named change: SKILL.md, a file given with its text, a file given
  as "" (removed). Every other file of the skill (binary, big, hidden, any count)
  stays as it is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine.hermes import EngineError


def ops_for(
    folder: Path | None,
    text: str | None,
    files: dict[str, str] | None,
    *,
    create: bool,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """skill_manage's batch for this change: SKILL.md (create, or a full rewrite
    when it differs), then each named file (write_file, or remove_file for "").
    `category`: the folder of the home's skills/ a new skill goes in (Hermes's own
    create category: skills/<category>/<name>)."""
    ops: list[dict[str, Any]] = []
    current = folder / "SKILL.md" if folder is not None else None
    if create:
        op: dict[str, Any] = {"action": "create", "content": str(text or "")}
        if category:
            op["category"] = category
        ops.append(op)
    elif text is not None:
        try:
            have = current.read_text(encoding="utf-8-sig") if current else None
        except OSError:
            have = None
        if have != text:
            ops.append({"action": "patch", "content": text})
    for rel, body in (files or {}).items():
        target = folder / rel if folder is not None else None
        exists = target is not None and target.is_file()
        if body == "":
            if exists:
                ops.append({"action": "remove_file", "file_path": rel})
            continue
        try:
            same = exists and target is not None and target.read_text() == body
        except (OSError, UnicodeDecodeError):
            same = False
        if create or not same:
            ops.append({"action": "write_file", "file_path": rel, "file_content": body})
    return ops


def _engine(core: Core) -> Any:
    if core.engine is None:
        raise ActionError("The engine isn't available.", 503)
    return core.engine


def write(
    core: Core,
    home: Path,
    name: str,
    folder: Path | None,
    text: str | None,
    files: dict[str, str] | None = None,
    *,
    create: bool = False,
    category: str | None = None,
    actor: str = "user",
) -> list[str]:
    """Creates or changes the skill by Hermes's skill_manage in `home`; the ledger
    ids it made (newest first, [] when nothing changed)."""
    ops = ops_for(folder, text, files, create=create, category=category)
    if not ops:
        return []
    return _run(core, home, name, ops=ops, actor=actor)


def delete(core: Core, home: Path, name: str, *, actor: str = "user") -> list[str]:
    """Hermes's skill_manage delete (its ledger keeps the whole package)."""
    return _run(core, home, name, delete=True, actor=actor)


def check_new(
    core: Core, home: Path, name: str, text: str, files: dict[str, str] | None = None
) -> None:
    """Hermes's own checks of a NEW skill (what its create checks first: the name, the
    description within the skill index's budget, the sizes), before AGOS writes
    anything: a refusal here changes nothing anywhere and says Hermes's reason."""
    try:
        done = _engine(core).skill_check(home, name, text, files or {})
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine didn't take it: {error}", 502) from error
    if not done.get("ok"):
        raise ActionError(f"The engine refused it: {done.get('error') or 'no answer'}")


def _run(
    core: Core,
    home: Path,
    name: str,
    *,
    ops: list[dict[str, Any]] | None = None,
    delete: bool = False,
    actor: str,
) -> list[str]:
    try:
        done = _engine(core).skill_manage(home, name, ops, delete=delete, actor=actor)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine didn't take it: {error}", 502) from error
    if not done.get("ok"):
        raise ActionError(f"The engine refused it: {done.get('error') or 'no answer'}")
    return [str(i) for i in done.get("entries") or []]


def rollback(core: Core, home: Path, skills: list[str], entries: list[str]) -> None:
    """Hermes's rollback_entry of a change's ledger entries; refused (nothing
    changed) when the skill was changed again since."""
    if not entries:
        return
    try:
        done = _engine(core).skill_rollback(home, skills, entries)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"The engine didn't take it: {error}", 502) from error
    if not done.get("ok"):
        raise ActionError(str(done.get("error") or "The engine didn't put it back."), 409)
