"""Skill writes through Hermes's own skill_manage and ledger: write, check, roll back,
the ledger of changes, a skill's history, and the bundled skills.

Owns: The scripts run in Hermes's runtime for those and the skill-ledger cache.

Must not: Hold an agent's write for approval (held_writes.py) or decide who may write
(actions/).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import contextlib
import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine.hermes.stamps import _ledger_stamp
from agos_core.hermes_gateway.errors import EngineError

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_SKILL_CHANGES",
    "_SKILL_CHECK",
    "_SKILL_HISTORY",
    "_SKILL_MANAGE",
    "_SKILL_ROLLBACK",
    "bundled_skills",
    "ledger_stamp",
    "skill_changes",
    "skill_check",
    "skill_history",
    "skill_manage",
    "skill_rollback",
]


# Run in Hermes's runtime by skill_manage: the owner's (or the Co-Founder's) skill
# create / edit / delete through Hermes's own skill tool (tools/skill_manager_tool.py
# skill_manage: its validation, its per-skill lock, its atomic batch) replayed the way
# Hermes's /skills approve does (apply_skill_pending: past the skills.write_approval
# gate, which is for the agents' own writes). Every mutation is one entry of Hermes's
# skill ledger (tools/skill_ledger.py record_mutation, with before/after blobs by
# content hash); their ids, newest first, are what an Undo rolls back.
_SKILL_MANAGE = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import skill_ledger
from tools.skill_manager_tool import apply_skill_pending
job = json.loads(@JOB@)
name = job["name"]
had = {e.get("id") for e in skill_ledger.list_entries(name)}
token = skill_ledger.set_ledger_actor(job["actor"])
try:
    payload = {"action": "delete", "name": name} if job.get("delete") else {
        "name": name, "operations": job["ops"]}
    said = json.loads(apply_skill_pending(payload) or "{}")
finally:
    skill_ledger.reset_ledger_actor(token)
made = [e.get("id") for e in skill_ledger.list_entries(name) if e.get("id") not in had]
print("AGOS-SKILL " + json.dumps({
    "ok": bool(said.get("success")), "error": str(said.get("error") or "")[:500],
    "entries": made}, default=str))
"""

# Run in Hermes's runtime by skill_check: the checks Hermes's own skill_manage makes
# before it creates a skill (tools/skill_manager_tool.py _create_skill: the name, the
# frontmatter with new_skill=True — the skill index's description budget —, the size;
# each supporting file as its _write_file checks it), so AGOS can refuse a new skill
# before it touches the library or any workspace. A check this Hermes no longer has
# is skipped and reported (the create itself still checks everything).
_SKILL_CHECK = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import skill_manager_tool as smt
job = json.loads(@JOB@)
def ask(name, check):
    try:
        return check()
    except (AttributeError, TypeError) as error:
        print("AGOS-CONTRACT-BROKEN tools.skill_manager_tool." + name + " " + str(error)[:200])
        return None
def too_big(body):
    size = len(body.encode("utf-8"))
    limit = smt.MAX_SKILL_FILE_BYTES
    if size > limit:
        return (f"File content is {size:,} bytes (limit: {limit:,} bytes / 1 MiB). "
                "Consider splitting into smaller files.")
    return None
text = job["text"]
said = (ask("_validate_name", lambda: smt._validate_name(job["name"]))
        or ask("_validate_frontmatter", lambda: smt._validate_frontmatter(text, new_skill=True))
        or ask("_validate_content_size", lambda: smt._validate_content_size(text)))
for rel, body in (job.get("files") or {}).items():
    if said:
        break
    said = (ask("_validate_file_path", lambda: smt._validate_file_path(rel))
            or ask("MAX_SKILL_FILE_BYTES", lambda: too_big(body))
            or ask("_validate_content_size", lambda: smt._validate_content_size(body, label=rel)))
print("AGOS-CHECKED " + json.dumps({"ok": not said, "error": str(said or "")[:500]}))
"""

# Run in Hermes's runtime by skill_rollback: Hermes's own rollback_entry of each
# ledger entry one AGOS change made, newest first, only while no newer entry exists
# for the skill (rollback_entry: fail-closed, by content hash, with its safety entry).
_SKILL_ROLLBACK = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import skill_ledger
job = json.loads(@JOB@)
ours = list(job["entries"])
out = {"ok": True}
newest = {n: [e.get("id") for e in skill_ledger.list_entries(n, limit=1)] for n in job["skills"]}
if any(ids and ids[0] not in ours for ids in newest.values()):
    out = {"ok": False, "error": "the skill changed since; Undo would lose the newer edit"}
else:
    for entry_id in ours:
        ok, text = skill_ledger.rollback_entry(entry_id)
        if not ok:
            out = {"ok": False, "error": str(text)[:300]}
            break
print("AGOS-ROLLED " + json.dumps(out, default=str))
"""

# Run in Hermes's runtime by skill_changes: a home's skill ledger as Hermes reads
# it (list_entries, newest first, under its own compaction rules) with each entry's
# SKILL.md text before and after (read_blob of the entry's SKILL.md by path: an
# entry holds every changed file of the skill, sorted by path) and its changed files.
_SKILL_CHANGES = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from tools import skill_ledger
job = json.loads(@JOB@)
rows = skill_ledger.list_entries(limit=job["limit"])
undone = {str((e.get("evidence") or {}).get("rollback_target") or "")
          for e in skill_ledger.list_entries() if e.get("action") == "rollback"}
def skill_md(items):
    found = sorted((str(i.get("path") or "") for i in items or []
                    if Path(str(i.get("path") or "")).name == "SKILL.md"), key=len)
    if not found:
        return None
    sha = next(str(i.get("sha256") or "") for i in items if str(i.get("path") or "") == found[0])
    blob = skill_ledger.read_blob(sha)
    return None if blob is None else blob.decode("utf-8", "replace")
out = []
for e in rows:
    paths = sorted({Path(str(i.get("path") or "")).name for i in
                    (e.get("before") or []) + (e.get("after") or [])})
    out.append({
        "id": str(e.get("id") or ""), "ts": str(e.get("ts") or ""),
        "actor": str(e.get("actor") or ""), "action": str(e.get("action") or ""),
        "skill": str(e.get("skill") or ""),
        "session": str((e.get("evidence") or {}).get("session_id") or ""),
        "before": skill_md(e.get("before")), "after": skill_md(e.get("after")),
        "files": paths, "undone": str(e.get("id") or "") in undone})
print("AGOS-LEDGER " + json.dumps(out, default=str))
"""

# Run in Hermes's runtime by skill_history: ONE skill's ledger entries as Hermes
# reads them (list_entries(skill), oldest first) with, for the entries AGOS hasn't
# turned into a version yet (`known` left out), every changed file's content before
# and after (read_blob by the entry's hashes; None when Hermes garbage-collected the
# blob), by path relative to the skill's folder. Paths outside the folder (an
# archived copy's) are left out. engine/skill_versions.py derives the versions.
_SKILL_HISTORY = r"""
import base64, json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from tools import skill_ledger
job = json.loads(@JOB@)
folder = Path(job["folder"])
known = set(job["known"])
def rel(p):
    try:
        return Path(str(p or "")).relative_to(folder).as_posix()
    except ValueError:
        return None
def side(items):
    out = {}
    for i in items or []:
        r = rel(i.get("path"))
        if r is None:
            continue
        blob = skill_ledger.read_blob(str(i.get("sha256") or ""))
        out[r] = None if blob is None else base64.b64encode(blob).decode("ascii")
    return out
out = []
for e in reversed(skill_ledger.list_entries(job["skill"])):
    ev = e.get("evidence") or {}
    item = {
        "id": str(e.get("id") or ""), "ts": str(e.get("ts") or ""),
        "actor": str(e.get("actor") or ""), "action": str(e.get("action") or ""),
        "evidence": {k: str(ev[k]) for k in ("session_id", "rollback_target") if ev.get(k)},
        "paths": sorted({r for r in (rel(i.get("path")) for i in
                         (e.get("before") or []) + (e.get("after") or [])) if r})}
    if item["id"] not in known:
        item["before"], item["after"] = side(e.get("before")), side(e.get("after"))
    out.append(item)
print("AGOS-HISTORY " + json.dumps(out, default=str))
"""


def skill_manage(
    self: "HermesEngine",
    home: Path,
    name: str,
    ops: list[dict[str, Any]] | None = None,
    *,
    delete: bool = False,
    actor: str = "user",
) -> dict[str, Any]:
    """One skill change by Hermes's own skill_manage in this home (an atomic batch
    of `ops`: create / patch / write_file / remove_file; or `delete`), recorded
    in Hermes's skill ledger: {"ok", "error", "entries": ledger ids, newest first}."""
    job = {"name": name, "ops": ops or [], "delete": delete, "actor": actor}
    script = _SKILL_MANAGE.replace("@JOB@", repr(json.dumps(job)))
    found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-SKILL"))
    return found


def skill_check(
    self: "HermesEngine", home: Path, name: str, text: str, files: dict[str, str] | None = None
) -> dict[str, Any]:
    """Hermes's own checks of a NEW skill (what its skill_manage create checks
    first), nothing written: {"ok": bool, "error": Hermes's reason}."""
    job = {"name": name, "text": text, "files": files or {}}
    script = _SKILL_CHECK.replace("@JOB@", repr(json.dumps(job)))
    found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-CHECKED"))
    return found


def skill_rollback(
    self: "HermesEngine", home: Path, skills: list[str], entries: list[str]
) -> dict[str, Any]:
    """Hermes's rollback_entry of these ledger entries (newest first), refused
    when a skill changed since: {"ok": bool, "error"?: str}."""
    job = {"skills": list(skills), "entries": list(entries)}
    script = _SKILL_ROLLBACK.replace("@JOB@", repr(json.dumps(job)))
    found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-ROLLED"))
    return found


def skill_changes(self: "HermesEngine", home: Path, limit: int = 200) -> list[dict[str, Any]]:
    """This home's skill ledger as Hermes reads it, newest first, with each
    entry's SKILL.md text before / after. Kept while the ledger and its blobs
    are unchanged (_ledger_stamp)."""

    def ask() -> list[dict[str, Any]]:
        script = _SKILL_CHANGES.replace("@JOB@", repr(json.dumps({"limit": limit})))
        found: list[dict[str, Any]] = json.loads(self._in_runtime(home, script, "AGOS-LEDGER"))
        return found

    return copy.deepcopy(self._ledger.get((str(home), limit), _ledger_stamp(home), ask))


def skill_history(
    self: "HermesEngine", home: Path, folder: Path, skill: str, known: list[str]
) -> list[dict[str, Any]]:
    """One skill's ledger entries as Hermes reads them, oldest first, with the
    changed files' content (before / after, base64 by path relative to `folder`)
    for the entries not in `known`. Not kept: engine/skill_versions.py turns
    the answer into stored versions, and actions/skill_versions.py asks again
    only when the ledger moved (_ledger_stamp)."""
    job = {"folder": str(folder), "skill": skill, "known": list(known)}
    script = _SKILL_HISTORY.replace("@JOB@", repr(json.dumps(job)))
    found: list[dict[str, Any]] = json.loads(self._in_runtime(home, script, "AGOS-HISTORY"))
    return found


def ledger_stamp(self: "HermesEngine", home: Path) -> tuple[int, ...]:
    """Where this home's skill ledger stands (its file and blobs): the same
    stamp skill_changes is kept by."""
    return _ledger_stamp(home)


def bundled_skills(self: "HermesEngine", workspace_id: str) -> None:
    """A profile made without Hermes's bundled skills (older AGOS) gets them."""
    if (self.profile_home(workspace_id) / ".no-bundled-skills").exists():
        with contextlib.suppress(EngineError, OSError):
            self._hermes(workspace_id, "skills", "opt-in", "--sync", timeout=300)
