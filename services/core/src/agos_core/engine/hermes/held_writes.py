"""Writes Hermes holds for the owner's approval (memory and skills): the list, a
decision, the rest of a partly applied memory write, and the Undo of an approval.

Owns: The scripts run in Hermes's runtime for those, and the held-writes cache.

Must not: Decide who may approve (actions/held_writes.py) or write a skill directly
(skills.py).

Part of engine/hermes (HermesEngine binds these functions as its methods).
"""

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.engine import hermes_reports, read_cache
from agos_core.engine.hermes.managed_scope import managed_files
from agos_core.engine.hermes.stamps import _held_stamp

if TYPE_CHECKING:
    from agos_core.engine.hermes import HermesEngine

__all__ = [
    "_APPLY_REST",
    "_DECIDE_PENDING",
    "_PENDING",
    "_SKILL_LEDGER",
    "_UNDO_PENDING",
    "apply_pending_rest",
    "decide_pending",
    "hermes_check",
    "memory_undo_ops",
    "pending_writes",
    "undo_pending",
]


# Run in Hermes's runtime by pending_writes: the memory/skill writes Hermes held back
# for review (its `<subsystem>.write_approval` gate: tools/write_approval.py, the
# pending store under <home>/pending/), with what each would change, the way its
# own /memory and /skills commands show them (hermes_cli/write_approval_commands.py).
_PENDING = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import write_approval as wa
from hermes_cli.write_approval_commands import _matched_entries
from tools.memory_tool import load_on_disk_store
out = {"gates": {}, "items": []}
live = None
for sub in (wa.MEMORY, wa.SKILLS):
    out["gates"][sub] = bool(wa.write_approval_enabled(sub))
    for r in wa.list_pending(sub):
        p = r.get("payload") or {}
        item = {k: r.get(k) for k in ("id", "subsystem", "action", "summary", "origin", "created_at")}
        if sub == wa.MEMORY:
            lines = []
            try:
                lines += list(_matched_entries(p))
            except Exception:
                pass
            batch = p.get("action") == "batch" and isinstance(p.get("operations"), list)
            ops = p.get("operations") if batch else [p]
            if live is None:
                try:
                    st = load_on_disk_store()
                    live = {"memory": list(st.memory_entries), "user": list(st.user_entries)}
                except Exception:
                    live = {}
            plain = []
            for op in ops:
                op = op or {}
                if op.get("old_text"):
                    lines.append("- " + str(op.get("old_text")))
                new = str(op.get("content") or op.get("new_text") or "")
                if new:
                    lines.append("+ " + new)
                act = str(op.get("action") or "")
                tgt = str(op.get("target") or p.get("target") or "memory")
                entry = str(op.get("matched_entry") or "")
                old = str(op.get("old_text") or "")
                after = new
                if act == "patch":
                    after = entry.replace(old, new, 1) if entry and old and old in entry else ""
                elif act == "remove":
                    after = ""
                plain.append({
                    "action": act, "target": tgt, "before": entry or old, "after": after,
                    "gone": bool(entry) and bool(live) and entry not in (live.get(tgt) or []),
                })
            item["detail"] = "\n".join(lines)
            item["target"] = str(p.get("target") or "")
            item["ops"] = plain
        else:
            try:
                item["detail"] = wa.skill_pending_diff(r)
            except Exception as error:
                item["detail"] = "(Hermes couldn't show the change: %s)" % error
            item["target"] = str(p.get("name") or "")
        out["items"].append(item)
print("AGOS-PENDING " + json.dumps(out, default=str))
"""

# Run in Hermes's runtime by apply_pending_rest: a held memory batch part of which is
# already done (a note it removes or changes is gone, so Hermes's own approve would
# refuse the whole batch): what still applies (its adds, its changes of notes still
# there) goes through Hermes's own replay (tools/memory_tool.py apply_memory_pending)
# and the held write is dropped (write_approval.discard_pending).
_APPLY_REST = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import write_approval as wa
from tools.memory_tool import apply_memory_pending, load_on_disk_store
job = json.loads(@JOB@)
record = wa.get_pending(wa.MEMORY, job["id"])
out = {"found": record is not None, "gone": False, "text": "", "kept": 0, "skipped": 0}
if record is not None:
    p = record.get("payload") or {}
    store = load_on_disk_store()
    live = {"memory": list(store.memory_entries), "user": list(store.user_entries)}
    ops = p.get("operations") if p.get("action") == "batch" else [p]
    target = p.get("target") or "memory"
    rest = []
    for op in ops or []:
        op = dict(op or {})
        if op.get("matched_entry") and op["matched_entry"] not in live.get(op.get("target") or target, []):
            out["skipped"] += 1
            continue
        rest.append(op)
    result = {"success": True}
    if rest:
        if p.get("action") == "batch":
            result = apply_memory_pending({"action": "batch", "target": target, "operations": rest}, store)
        else:
            result = apply_memory_pending(rest[0], store)
    if result.get("success"):
        wa.discard_pending(wa.MEMORY, job["id"])
        out["kept"] = len(rest)
        out["text"] = "Saved %d change(s); %d already done before." % (len(rest), out["skipped"])
    else:
        out["text"] = str(result.get("error") or "Hermes refused it")
    out["gone"] = wa.get_pending(wa.MEMORY, job["id"]) is None
print("AGOS-REST " + json.dumps(out, default=str))
"""

# Run in Hermes's runtime by decide_pending: Hermes's own /memory and /skills
# approve|reject (hermes_cli/write_approval_commands.py handle_pending_subcommand;
# memory applied to a fresh on-disk store like the gateway's /memory does:
# gateway/slash_commands.py _handle_memory_command).
_DECIDE_PENDING = r"""
import json, logging
logging.disable(logging.CRITICAL)
from tools import write_approval as wa
from hermes_cli.write_approval_commands import handle_pending_subcommand
from tools.memory_tool import load_on_disk_store
@SKILLS@
job = json.loads(@JOB@)
sub = wa.MEMORY if job["subsystem"] == "memory" else wa.SKILLS
store = None
if sub == wa.MEMORY:
    store = load_on_disk_store()
record = wa.get_pending(sub, job["id"])
before = record is not None
undo = None
if before and job.get("keep"):
    if not job["approve"]:
        undo = {"record": record}
    elif sub == wa.MEMORY:
        undo = {"before": {"memory": list(store.memory_entries), "user": list(store.user_entries)}}
    else:
        undo = {"before": _skills(_names(record))}
text = handle_pending_subcommand(
    sub, ["approve" if job["approve"] else "reject", job["id"]], memory_store=store) or ""
gone = wa.get_pending(sub, job["id"]) is None
if undo is not None and job["approve"] and gone:
    if sub == wa.MEMORY:
        after = load_on_disk_store()
        undo["after"] = {"memory": list(after.memory_entries), "user": list(after.user_entries)}
    else:
        had = undo.pop("before")
        made = []
        for name, ids in _skills(_names(record)).items():
            old = set(had.get(name) or [])
            made += [i for i in ids if i not in old]
        at = {e.get("id"): e.get("ts") or "" for e in skill_ledger.list_entries()}
        made.sort(key=lambda i: at.get(i, ""), reverse=True)  # newest first
        undo = {"skills": _names(record), "entries": made} if made else None
print("AGOS-DECIDED " + json.dumps({
    "found": before, "gone": gone, "text": text, "undo": undo if gone else None}, default=str))
"""

# The skills one held write touches (its name and its batch's names) and, per skill,
# the ids of Hermes's skill ledger (tools/skill_ledger.py: every skill_manage
# mutation, the replay of an approved write too, is one entry with before/after
# blobs by content hash), so an Undo is Hermes's own rollback_entry.
_SKILL_LEDGER = r"""
from tools import skill_ledger


def _names(record):
    p = (record or {}).get("payload") or {}
    ops = p.get("ops") if isinstance(p.get("ops"), list) else []
    found = [p.get("name")] + [o.get("name") for o in ops if isinstance(o, dict)]
    return sorted({str(n) for n in found if n})


def _skills(names):
    return {name: [e.get("id") for e in skill_ledger.list_entries(name)] for name in names}
"""


def memory_undo_ops(
    before: dict[str, list[str]], after: dict[str, list[str]]
) -> list[dict[str, Any]] | None:
    """The public MemoryStore ops that take back one approved memory change (an
    add -> remove, a remove -> add, a replace -> replace back); [] when nothing
    changed, None when the approval made several changes (no single inverse)."""
    ops: list[dict[str, Any]] = []
    for target in ("memory", "user"):
        was, now = list(before.get(target) or []), list(after.get(target) or [])
        if was == now:
            continue
        if len(now) == len(was) + 1 and now[:-1] == was:
            ops.append({"op": "remove", "target": target, "old": now[-1], "new": None})
        elif len(was) == len(now) + 1:
            gone = [i for i in range(len(was)) if was[:i] + was[i + 1 :] == now]
            if not gone:
                return None
            ops.append({"op": "add", "target": target, "old": None, "new": was[gone[0]]})
        elif len(was) == len(now):
            changed = [i for i in range(len(was)) if was[i] != now[i]]
            if len(changed) != 1:
                return None
            i = changed[0]
            ops.append({"op": "replace", "target": target, "old": now[i], "new": was[i]})
        else:
            return None
    return ops if len(ops) <= 1 else None


# Run in Hermes's runtime by undo_pending: an Undo of AGOS's own approve or reject.
# A reject comes back as a held write again (Hermes's own stage_write); an approved
# memory write is taken back only while the file is still as the approval left it:
# one change by Hermes's own public inverse op (MemoryStore.add / replace / remove,
# `memory_undo_ops`), a batch of several by the snapshot under Hermes's memory-file
# lock (MemoryStore._mutate, what every memory write runs); an approved skill write is Hermes's own skill-ledger rollback of each entry
# the approval made, newest first (rollback_entry: fail-closed, by content hash,
# with its own safety entry), only while no newer ledger entry exists for the skill.
_UNDO_PENDING = r"""
import json, logging
logging.disable(logging.CRITICAL)
from pathlib import Path
from tools import write_approval as wa
@SKILLS@
job = json.loads(@JOB@)
undo = job["undo"]
sub = wa.MEMORY if job["subsystem"] == "memory" else wa.SKILLS
out = {"ok": True}
if "record" in undo:
    r = undo["record"]
    made = wa.stage_write(sub, r.get("payload") or {}, summary=r.get("summary") or "", origin=r.get("origin") or "foreground")
    out["id"] = made.get("id")
elif sub == wa.MEMORY:
    from tools.memory_tool import load_on_disk_store
    store = load_on_disk_store()
    now = {"memory": list(store.memory_entries), "user": list(store.user_entries)}
    if now != undo["after"]:
        out = {"ok": False, "error": "the memory changed since; Undo would lose the newer entries"}
    elif job.get("ops") is not None:
        # One change: Hermes's own public inverse op, pinned to the exact entry.
        for o in job["ops"]:
            if o["op"] == "remove":
                done = store.remove(o["target"], o["old"], matched_entry=o["old"])
            elif o["op"] == "add":
                done = store.add(o["target"], o["new"])
            else:
                done = store.replace(o["target"], o["old"], o["new"], matched_entry=o["old"])
            if not done.get("success", True):
                out = {"ok": False, "error": str(done.get("error") or done)[:300]}
                break
    else:
        # Several changes in one approval (a batch): the snapshot back, under
        # Hermes's own memory-file lock.
        for target in ("memory", "user"):
            if undo["before"][target] != undo["after"][target]:
                done = store._mutate(target, lambda entries, limit, t=target: (list(undo["before"][t]), "undone"), skip_drift=True)
                if not done.get("success", True):
                    out = {"ok": False, "error": str(done.get("error") or done)[:300]}
elif "entries" not in undo:
    out = {"ok": False, "error": "this approval was made before AGOS used Hermes's skill ledger; nothing to roll back"}
else:
    ours = list(undo["entries"])  # newest first
    newest = {n: [e.get("id") for e in skill_ledger.list_entries(n, limit=1)] for n in undo["skills"]}
    if any(ids and ids[0] not in ours for ids in newest.values()):
        out = {"ok": False, "error": "the skill changed since; Undo would lose the newer edit"}
    else:
        for entry_id in ours:
            ok, text = skill_ledger.rollback_entry(entry_id)
            if not ok:
                out = {"ok": False, "error": str(text)[:300]}
                break
print("AGOS-UNDONE " + json.dumps(out, default=str))
"""


def pending_writes(self: "HermesEngine", home: Path) -> dict[str, Any]:
    """The memory/skill writes Hermes holds for review in this home, and whether
    each gate is on: {"gates": {...}, "items": [...]}. Hermes is asked again
    only when what its script reads changed (_held_stamp, the managed
    config.yaml) or after AGOS decided one (decide_pending, undo_pending)."""

    def ask() -> dict[str, Any]:
        found: dict[str, Any] = json.loads(self._in_runtime(home, _PENDING, "AGOS-PENDING"))
        return found

    scope_stamp = read_cache.file_stamp(managed_files(self.settings.managed_home)[0])
    return copy.deepcopy(self._held.get(str(home), (_held_stamp(home), scope_stamp), ask))


def decide_pending(
    self: "HermesEngine",
    home: Path,
    subsystem: str,
    pending_id: str,
    approve: bool,
    *,
    keep: bool = False,
) -> dict[str, Any]:
    """Hermes's own approve / reject of one held write (its /memory, /skills).
    `keep`: also what an Undo needs ("undo": the write as held, or what the
    approval changed)."""
    job = {"subsystem": subsystem, "id": pending_id, "approve": approve, "keep": keep}
    script = _DECIDE_PENDING.replace("@SKILLS@", _SKILL_LEDGER).replace(
        "@JOB@", repr(json.dumps(job))
    )
    try:
        found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-DECIDED"))
    finally:
        self._held.drop(str(home))  # the list as Hermes has it after the decision
    return found


def hermes_check(
    self: "HermesEngine", workspace_id: str, command: str, *, timeout: float = 180
) -> tuple[str, int]:
    """Hermes's own status / doctor / errors report (engine/hermes_reports.py)."""
    return hermes_reports.run(self, workspace_id, command, timeout=timeout)


def apply_pending_rest(self: "HermesEngine", home: Path, pending_id: str) -> dict[str, Any]:
    """A held memory write part of which is already done: what still applies goes
    through Hermes's own replay, the held write is dropped (_APPLY_REST)."""
    script = _APPLY_REST.replace("@JOB@", repr(json.dumps({"id": pending_id})))
    try:
        found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-REST"))
    finally:
        self._held.drop(str(home))
    return found


def undo_pending(
    self: "HermesEngine", home: Path, subsystem: str, undo: dict[str, Any]
) -> dict[str, Any]:
    """Takes back AGOS's own approve / reject of a held write (decide_pending's
    "undo"): {"ok": bool, "error"?: str, "id"?: the held write's new id}."""
    job: dict[str, Any] = {"subsystem": subsystem, "undo": undo}
    if subsystem == "memory" and "before" in undo and "after" in undo:
        job["ops"] = memory_undo_ops(undo["before"], undo["after"])
    script = _UNDO_PENDING.replace("@SKILLS@", _SKILL_LEDGER).replace(
        "@JOB@", repr(json.dumps(job))
    )
    try:
        found: dict[str, Any] = json.loads(self._in_runtime(home, script, "AGOS-UNDONE"))
    finally:
        self._held.drop(str(home))  # a rejected write is held again
    return found
