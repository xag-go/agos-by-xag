"""Workspace → Held-back writes: the memory and skill writes Hermes holds for the
owner's review while its `memory.write_approval` / `skills.write_approval` gate is
on (tools/write_approval.py), listed, shown with what they change, and approved or
rejected with Hermes's own /memory and /skills functions.

AGOS keeps nothing: the queue is Hermes's (each profile's <home>/pending/), read
and decided in Hermes's runtime (engine/hermes.py pending_writes, decide_pending).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.held_writes")

SUBSYSTEMS = ("memory", "skills")
# Hermes's pending ids are uuid4().hex[:8] (tools/write_approval.py stage_write).
_ID = re.compile(r"^[0-9a-f]{4,32}$")


def _profiles(core: Core, workspace_id: str) -> list[tuple[str, str]]:
    """(engine key, label) of the workspace's Co-Founder and each member."""
    from agos_core.actions.hermes_all_settings import targets

    return [(t.key, t.label) for t in targets(core, workspace_id)]


def read(core: Core, workspace_id: str) -> dict[str, Any]:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    profiles = _profiles(core, workspace_id)
    found: dict[str, dict[str, Any]] = {}
    failed: list[str] = []

    def one(item: tuple[str, str]) -> None:
        key, label = item
        try:
            found[key] = engine.pending_writes(engine.profile_home(key))
        except (EngineError, OSError, ValueError) as error:
            log.info("held writes of %s not read: %s", key, error)
            failed.append(label)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, profiles))
    items: list[dict[str, Any]] = []
    gates = {sub: False for sub in SUBSYSTEMS}
    for key, label in profiles:
        got = found.get(key)
        if not got:
            continue
        for sub in SUBSYSTEMS:
            gates[sub] = gates[sub] or bool((got.get("gates") or {}).get(sub))
        for item in got.get("items") or []:
            items.append(
                {
                    "profile": key,
                    "agent": label,
                    "id": str(item.get("id") or ""),
                    "subsystem": str(item.get("subsystem") or ""),
                    "action": str(item.get("action") or ""),
                    "summary": str(item.get("summary") or ""),
                    "target": str(item.get("target") or ""),
                    "origin": str(item.get("origin") or "foreground"),
                    "created_at": float(item.get("created_at") or 0),
                    "detail": str(item.get("detail") or ""),
                    "ops": _ops(item.get("ops")),
                }
            )
    items.sort(key=lambda i: i["created_at"])
    for i in items:
        i["group"] = _group(i)
    return {"gates": gates, "items": items, "unread": failed}


def _ops(raw: Any) -> list[dict[str, Any]]:
    """One memory write's changes, entry by entry, as Hermes's script read them:
    action (add / remove / patch / replace), the note as it is now and as it would
    be, and whether that note is already gone from the memory (the write would fail)."""
    out: list[dict[str, Any]] = []
    for op in raw if isinstance(raw, list) else []:
        if not isinstance(op, dict):
            continue
        out.append(
            {
                "action": str(op.get("action") or ""),
                "target": str(op.get("target") or "memory"),
                "before": str(op.get("before") or ""),
                "after": str(op.get("after") or ""),
                "gone": bool(op.get("gone")),
            }
        )
    return out


def _group(item: dict[str, Any]) -> str:
    """Held writes that ask for the same thing again: the same agent, removing or
    changing the same notes and adding the same ones; only a changed note's new
    wording may differ (Hermes's background review proposes it again after each
    chat while it waits). The owner decides them as one: the newest is applied."""
    shape: list[tuple[str, ...]]
    if item["subsystem"] == "memory" and item["ops"]:
        shape = [
            (op["action"], op["target"], op["after"] if op["action"] == "add" else op["before"])
            for op in item["ops"]
        ]
    else:
        shape = [(item["subsystem"], item["action"], item["target"], item["detail"])]
    seed = json.dumps([item["profile"], item["subsystem"], sorted(shape)], ensure_ascii=False)
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


def decide(
    core: Core,
    workspace_id: str,
    profile: str,
    subsystem: str,
    pending_id: str,
    approve: bool,
    *,
    keep: bool = False,
) -> dict[str, Any]:
    """Hermes's own approve or reject of one held write; the list as it is now.
    `keep`: also "undo", what undo() needs to take it back (a Co-Founder's card)."""
    if subsystem not in SUBSYSTEMS or not _ID.match(pending_id):
        raise ActionError("No such held write.", status=404)
    if profile not in {key for key, _label in _profiles(core, workspace_id)}:
        raise ActionError("No such agent in this workspace.", status=404)
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    try:
        done = engine.decide_pending(
            engine.profile_home(profile), subsystem, pending_id, approve, keep=keep
        )
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    if not done.get("found"):
        raise ActionError("That write isn't held any more.", status=404)
    if not done.get("gone"):
        raise ActionError(f"Hermes didn't apply it: {done.get('text') or 'no answer'}", status=502)
    out = {**read(core, workspace_id), "said": str(done.get("text") or "")}
    if keep:
        out["undo"] = done.get("undo")
    return out


def groups(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The held writes as the owner decides them: one per request, the same request
    asked again folded in (oldest first in `ids`, the newest is the one applied),
    with a plain title. Nothing kept: re-derived from Hermes's queue each time."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for item in read(core, workspace_id)["items"]:
        by_key.setdefault(item["group"], []).append(item)
    out: list[dict[str, Any]] = []
    for key, same in by_key.items():
        same.sort(key=lambda i: i["created_at"])
        newest = same[-1]
        out.append(
            {
                "group": key,
                "profile": newest["profile"],
                "agent": newest["agent"],
                "subsystem": newest["subsystem"],
                "target": newest["target"],
                "origin": newest["origin"],
                "ids": [i["id"] for i in same],
                "id": newest["id"],
                "first_at": same[0]["created_at"],
                "last_at": newest["created_at"],
                "ops": newest["ops"],
                "detail": "" if newest["ops"] else newest["detail"],
                "stale": any(op["gone"] for op in newest["ops"]),
                "left": sum(1 for op in newest["ops"] if not op["gone"]),
                "title": title(newest),
            }
        )
    out.sort(key=lambda g: g["last_at"])
    return out


def title(item: dict[str, Any]) -> str:
    """What the agent wants, in plain words: "Manager wants to remove a note and
    update a note in its memory"."""
    who = item["agent"] or "An agent"
    if item["subsystem"] == "skills":
        name = f"the skill “{item['target']}”" if item["target"] else "a skill"
        verb = {"create": "create", "delete": "delete"}.get(item["action"], "change")
        return f"{who} wants to {verb} {name}"
    counts = {"remove": 0, "update": 0, "add": 0}
    about_you = False
    for op in item["ops"]:
        kind = "update" if op["action"] in ("patch", "replace") else op["action"]
        if kind in counts:
            counts[kind] += 1
        about_you = about_you or op["target"] == "user"
    parts = [f"{verb} {'a note' if n == 1 else f'{n} notes'}" for verb, n in counts.items() if n]
    if not parts:
        return f"{who} wants to change its memory"
    words = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    where = "in its notes about you" if about_you else "in its memory"
    return f"{who} wants to {words} {where}"


def waiting(core: Core, workspace_id: str) -> int:
    """How many requests wait (the Inbox badge): none without asking Hermes when no
    profile of the workspace has a held write file (Hermes's pending store,
    tools/write_approval.py _pending_path); else its cached read."""
    engine = core.engine
    if engine is None:
        return 0
    for key, _label in _profiles(core, workspace_id):
        pending = engine.profile_home(key) / "pending"
        if any(next((pending / sub).glob("*.json"), None) for sub in SUBSYSTEMS):
            break
    else:
        return 0
    try:
        return len(groups(core, workspace_id))
    except ActionError:
        return 0


def decide_group(
    core: Core, workspace_id: str, profile: str, subsystem: str, ids: list[str], approve: bool
) -> dict[str, Any]:
    """One request asked several times: Approve applies the newest (Hermes's own
    approve) and drops the older copies; Reject drops them all (Hermes's reject).
    A copy already gone is skipped. Hermes's queue is read once, at the end."""
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    ids = [i for i in ids if isinstance(i, str)][:50]
    if not ids or subsystem not in SUBSYSTEMS or not all(_ID.match(i) for i in ids):
        raise ActionError("No such held write.", status=404)
    if profile not in {key for key, _label in _profiles(core, workspace_id)}:
        raise ActionError("No such agent in this workspace.", status=404)
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    home = engine.profile_home(profile)
    said = ""
    try:
        newest = next(
            (
                i
                for i in read(core, workspace_id)["items"]
                if (i["profile"], i["id"]) == (profile, ids[-1])
            ),
            None,
        )
        if approve and newest is not None and any(op["gone"] for op in newest["ops"]):
            # Part of it is already done: Hermes's approve would refuse the whole
            # batch, so what still applies is saved and the rest skipped.
            done = engine.apply_pending_rest(home, ids[-1])
            if not done.get("gone"):
                raise ActionError(
                    f"Hermes didn't apply it: {done.get('text') or 'no answer'}", status=502
                )
            said = str(done.get("text") or "")
        elif approve:
            done = engine.decide_pending(home, subsystem, ids[-1], True)
            if not done.get("found"):
                raise ActionError("That write isn't held any more.", status=404)
            if not done.get("gone"):
                raise ActionError(
                    f"Hermes didn't apply it: {done.get('text') or 'no answer'}", status=502
                )
            said = str(done.get("text") or "")
        for pending_id in ids[:-1] if approve else ids:
            done = engine.decide_pending(home, subsystem, pending_id, False)
            if not approve and done.get("found"):
                said = str(done.get("text") or said)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    return {"said": said, "waiting": len(groups(core, workspace_id))}


# What Hermes's auxiliary model said about a held write, by what it was asked
# (its agent and changes): asked again only for a new write, never kept on disk.
_EXPLAINED: dict[str, str] = {}
_EXPLAINED_MAX = 500
_EXPLAIN_LOCK = threading.Lock()
EXPLAIN_CHARS = 6_000  # of each note / diff the model gets (the plugin's argv carries it)


def explain(core: Core, workspace_id: str, profile: str, subsystem: str, pending_id: str) -> str:
    """One or two plain sentences on what the held write would change and why,
    from Hermes's auxiliary model (`hermes agos-explain`, the agos-guard plugin)."""
    item = next(
        (
            i
            for i in read(core, workspace_id)["items"]
            if (i["profile"], i["subsystem"], i["id"]) == (profile, subsystem, pending_id)
        ),
        None,
    )
    if item is None:
        raise ActionError("That write isn't held any more.", status=404)
    job = {
        "agent": item["agent"],
        "kind": subsystem,
        "target": item["target"],
        "changes": [
            {
                "action": op["action"],
                "where": "notes about the owner" if op["target"] == "user" else "own notes",
                "before": op["before"][:EXPLAIN_CHARS],
                "after": op["after"][:EXPLAIN_CHARS],
            }
            for op in item["ops"]
        ],
        "diff": "" if item["ops"] else item["detail"][:EXPLAIN_CHARS],
    }
    key = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()
    with _EXPLAIN_LOCK:
        if key in _EXPLAINED:
            return _EXPLAINED[key]
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    try:
        said = hermes_cli.walled_cli(
            engine, workspace_id, "agos-explain", json.dumps(job, ensure_ascii=False), timeout=120
        )
    except EngineError as error:
        raise ActionError(f"Hermes didn't explain it: {error}", status=502) from error
    found = _last_json(said)
    text = str(found.get("text") or "").strip()
    if not found.get("ok") or not text:
        raise ActionError(
            f"Hermes couldn't explain it: {found.get('reason') or 'no answer'}", status=502
        )
    with _EXPLAIN_LOCK:
        if len(_EXPLAINED) >= _EXPLAINED_MAX:
            _EXPLAINED.pop(next(iter(_EXPLAINED)))
        _EXPLAINED[key] = text
    return text


def _last_json(said: str) -> dict[str, Any]:
    for line in reversed(said.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                found = json.loads(line)
            except ValueError:
                continue
            if isinstance(found, dict):
                return found
    return {}


def find(core: Core, workspace_id: str, pending_id: str) -> dict[str, Any]:
    """The held write with this id in the workspace (its Co-Founder's or a member's)."""
    wanted = pending_id.strip().lower()
    for item in read(core, workspace_id)["items"]:
        if item["id"] == wanted:
            return dict(item)
    raise ActionError(f"No held write {pending_id} in this workspace.", status=404)


def undo(core: Core, workspace_id: str, profile: str, subsystem: str, kept: Any) -> None:
    """Takes back an approve or reject decide(keep=True) did: a rejected write is
    held again, an approved one is put back as it was, only while Hermes's file is
    still as that approval left it (engine/hermes.py undo_pending)."""
    if profile not in {key for key, _label in _profiles(core, workspace_id)}:
        raise ActionError("That agent isn't in this workspace any more.", status=404)
    if not isinstance(kept, dict):
        raise ActionError("Hermes gave nothing to put it back with.", status=409)
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    try:
        done = engine.undo_pending(engine.profile_home(profile), subsystem, kept)
    except (EngineError, OSError, ValueError) as error:
        raise ActionError(f"Hermes didn't take it: {error}", status=502) from error
    if not done.get("ok"):
        raise ActionError(str(done.get("error") or "Hermes didn't put it back."), status=409)


def read_ahead(core: Core) -> None:
    """engine/read_ahead.py: Hermes's held writes of every profile of each
    workspace, asked once after a start (one profile after the other), so the
    first Held-back writes page doesn't wait for Hermes."""
    from agos_core.db import workspaces as workspaces_repo

    engine = core.engine
    if engine is None:
        return
    for ws in workspaces_repo.list_workspaces(core.db):
        if not (engine.profile_home(ws.id) / "config.yaml").is_file():
            continue  # no Hermes root yet: nothing to ask
        for key, _label in _profiles(core, ws.id):
            try:
                engine.pending_writes(engine.profile_home(key))
            except (EngineError, OSError, ValueError) as error:
                log.info("held writes of %s not read ahead: %s", key, error)
