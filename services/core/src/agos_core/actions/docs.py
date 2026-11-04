"""The workspace's Documentation: read, edit, version, check.

Files are in the workspace's own folder (/workspace/playbooks, the agents see
them there). Every save keeps a version (who, why), adds a line to CHANGES.md,
and returns the checks. A workspace without documentation gets the template
(README, team, flow, CHANGES) — existing files are never overwritten.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import agent_versions as agent_versions_repo
from agos_core.db import docs as doc_rows
from agos_core.db import library as library_repo
from agos_core.db.connection import transaction
from agos_core.db.rows import dump_json, load_json, now
from agos_core.engine import docs as rules
from agos_core.engine import read_cache
from agos_core.storage.layout import workspace_paths

log = logging.getLogger("agos.docs")

MAX_FILE = 2_000_000
TEXT_TYPES = (".md", ".txt")
# The most .md names a pointer may find elsewhere in /workspace (the walk stops past it).
MAX_OTHER = 5_000


def folder(core: Core, workspace_id: str) -> Path:
    return workspace_paths(core.layout, workspace_id).files / rules.FOLDER


def _safe(core: Core, workspace_id: str, path: str) -> Path:
    """A path inside the workspace's playbooks folder, never outside it."""
    clean = path.strip().strip("/")
    if not clean or ".." in clean.split("/") or clean.startswith(".") or "\\" in clean:
        raise ActionError("Use a file name like team.md or agents/notes.md.")
    if not clean.endswith(TEXT_TYPES):
        raise ActionError("Documentation files end in .md or .txt.")
    if clean.split("/")[0] in ("skills", "agents", "automations"):
        raise ActionError(
            "Skills are Hermes's (change one with update_skill); playbooks/agents and "
            "automations show what the team uses: change them with update_agent / "
            "update_automation. Send that action yourself right now — they are "
            "not locked to you."
        )
    base = folder(core, workspace_id).resolve()
    target = (base / clean).resolve()
    if base not in target.parents:
        raise ActionError("Documentation files stay in the playbooks folder.")
    return target


def ensure(core: Core, workspace_id: str) -> bool:
    """Creates the Documentation from the template when the workspace has none.
    True when it was created."""
    workspace = require_workspace(core, workspace_id)
    base = folder(core, workspace_id)
    if base.exists() and any(base.glob("*.md")):
        return False
    base.mkdir(parents=True, exist_ok=True)
    for name, text in rules.template(workspace.name).items():
        target = base / name
        if not target.exists():
            target.write_text(text)
            _version(core, workspace_id, name, text, "AGOS", "Documentation created")
    return True


def _read(target: Path) -> str:
    if target.stat().st_size > MAX_FILE:
        raise ActionError("This file is too big to open here.")
    return target.read_text(errors="replace")


def all_docs(core: Core, workspace_id: str) -> dict[str, str]:
    base = folder(core, workspace_id)
    if not base.is_dir():
        return {}
    out = {}
    for p in sorted(base.rglob("*")):
        if (
            p.is_file()
            and p.suffix in TEXT_TYPES
            and not any(part.startswith(".") for part in p.relative_to(base).parts)
            and p.relative_to(base).parts[0] not in ("skills", "agents", "automations")
        ):
            try:
                out[str(p.relative_to(base))] = _read(p)
            except (OSError, ActionError):
                continue
    return out


def readers(
    core: Core, workspace_id: str, members: list[Any] | None = None
) -> dict[str, list[dict[str, str]]]:
    """For each file: the agents that read it, and how (always / on demand).
    `members`: team.members already read for this request."""
    from agos_core.actions import team

    out: dict[str, list[dict[str, str]]] = {}
    for agent in team.members(core, workspace_id) if members is None else members:
        for read in agent.reads:
            mode = str(read.get("mode") or "always")
            who = out.setdefault(str(read.get("path")), [])
            same = next((w for w in who if w["agent"] == agent.name), None)
            if same is None:
                who.append({"agent": agent.name, "title": agent.title, "mode": mode})
            elif mode == "always":
                same["mode"] = "always"  # a part on every job wins over "when needed"
    return out


def page(core: Core, workspace_id: str) -> dict[str, Any]:
    """The Documentation page (GET /docs): its files, what the checks found, the
    setting and the deleted agents, with the team and the files read once for
    all of them (each read walks the docs folder or every member's profile)."""
    from agos_core.actions import team

    require_workspace(core, workspace_id)
    ensure(core, workspace_id)
    members = team.members(core, workspace_id)
    docs = all_docs(core, workspace_id)
    return {
        "files": list_docs(core, workspace_id, members=members, docs=docs),
        "findings": check(core, workspace_id, members=members, docs=docs),
        "latinOnly": latin_only(core, workspace_id),
        "deletedAgents": deleted_agents(core, workspace_id),
    }


def list_docs(
    core: Core,
    workspace_id: str,
    *,
    members: list[Any] | None = None,
    docs: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """`members`, `docs`: team.members and all_docs already read for this request."""
    require_workspace(core, workspace_id)
    ensure(core, workspace_id)
    base = folder(core, workspace_id)
    who = readers(core, workspace_id, members)
    out: list[dict[str, Any]] = []
    for path, text in (all_docs(core, workspace_id) if docs is None else docs).items():
        target = base / path
        out.append(
            {
                "path": path,
                "size": len(text),
                "updatedAt": target.stat().st_mtime,
                "rule": path in rules.rule_files({path: text}),
                "sections": [f"{s.number}. {s.title}" for s in rules.sections(text)],
                "readBy": who.get(path, []),
            }
        )
    order = {rules.MAP: 0, "team.md": 1, "flow.md": 2}
    out.sort(
        key=lambda d: (
            order.get(d["path"], 3 if "/" not in d["path"] else 5),
            d["path"] == rules.LOG,
            d["path"],
        )
    )
    return out


def get_doc(core: Core, workspace_id: str, path: str) -> dict[str, Any]:
    require_workspace(core, workspace_id)
    target = _safe(core, workspace_id, path)
    if not target.is_file():
        raise NotFoundError("This file")
    text = _read(target)
    return {
        "path": path,
        "text": text,
        "hash": rules.digest(text),
        "sections": [f"{s.number}. {s.title}" for s in rules.sections(text)],
        "readBy": readers(core, workspace_id).get(path, []),
        "versions": versions(core, workspace_id, path),
    }


def _version(core: Core, workspace_id: str, path: str, text: str, who: str, why: str) -> None:
    doc_rows.add_version(core.db, workspace_id, path, text, rules.digest(text), who, why, now())


def versions(core: Core, workspace_id: str, path: str) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "at": r["created_at"],
            "author": r["author"],
            "why": r["why"],
            "size": len(r["body"]),
        }
        for r in doc_rows.versions(core.db, workspace_id, path)
    ]


def version_diff(core: Core, workspace_id: str, version_id: int) -> dict[str, Any]:
    """What this version changed compared with the one before it."""
    row = doc_rows.version(core.db, workspace_id, version_id)
    if row is None:
        raise NotFoundError("This version")
    before = doc_rows.previous_body(core.db, workspace_id, str(row["path"]), version_id) or ""
    diff = difflib.unified_diff(
        before.splitlines(), str(row["body"]).splitlines(), "before", "after", lineterm="", n=2
    )
    return {"id": version_id, "path": row["path"], "text": row["body"], "diff": "\n".join(diff)}


def save_doc(
    core: Core,
    workspace_id: str,
    path: str,
    text: str,
    why: str,
    *,
    who: str = "Owner",
    base_hash: str | None = None,
) -> dict[str, Any]:
    """Writes a rule file: a version, a CHANGES.md line (with why), then the checks."""
    require_workspace(core, workspace_id)
    if not why.strip():
        raise ActionError("Say why you change it (it goes in CHANGES.md).")
    target = _safe(core, workspace_id, path)
    if target.name == rules.LOG and target.parent == folder(core, workspace_id).resolve():
        raise ActionError("CHANGES.md is written by AGOS: change the rule file instead.")
    before = _read(target) if target.is_file() else ""
    if base_hash and target.is_file() and rules.digest(before) != base_hash:
        raise ActionError("This file changed since you opened it. Reload it, then save again.", 409)
    if before == text:
        return {"saved": False, "findings": check(core, workspace_id)}
    with transaction(core.db):
        if before and not doc_rows.has_versions(core.db, workspace_id, path):
            _version(core, workspace_id, path, before, "before AGOS", "the file as it was")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        _version(core, workspace_id, path, text, who, why)
        changed = rules.changed_sections(before, text) if before else ["new file"]
        log_file = folder(core, workspace_id) / rules.LOG
        current = log_file.read_text() if log_file.is_file() else ""
        log_file.write_text(rules.add_to_log(current, rules.log_entry(path, who, why, changed)))
        from agos_core.db.activity import add_activity

        add_activity(
            core.db,
            workspace_id,
            kind="docs.changed",
            text=f"Documentation: {path} changed by {who} ({why.strip()[:120]})",
        )
    return {"saved": True, "findings": check(core, workspace_id)}


def restore(
    core: Core, workspace_id: str, version_id: int, why: str, who: str = "Owner"
) -> dict[str, Any]:
    row = doc_rows.version(core.db, workspace_id, version_id)
    if row is None:
        raise NotFoundError("This version")
    reason = (
        why.strip() or f"back to the version of {str(row['created_at'])[:16].replace('T', ' ')}"
    )
    return save_doc(core, workspace_id, str(row["path"]), str(row["body"]), reason, who=who)


def delete_doc(core: Core, workspace_id: str, path: str, why: str) -> None:
    target = _safe(core, workspace_id, path)
    if not target.is_file():
        raise NotFoundError("This file")
    if (
        target.name in (rules.MAP, rules.LOG)
        and target.parent == folder(core, workspace_id).resolve()
    ):
        raise ActionError("README.md and CHANGES.md stay: they are the map and the log.")
    text = _read(target)
    with transaction(core.db):
        _version(core, workspace_id, path, text, "Owner", f"deleted: {why.strip()}")
        target.unlink()
        log_file = folder(core, workspace_id) / rules.LOG
        current = log_file.read_text() if log_file.is_file() else ""
        log_file.write_text(
            rules.add_to_log(
                current, rules.log_entry(path, "Owner", f"deleted: {why}", ["whole file"])
            )
        )


# ---- what each agent reads ---------------------------------------------------------


def reads_of(definition: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for r in definition.get("reads") or []:
        if isinstance(r, dict) and str(r.get("path") or "").strip():
            out.append(
                {
                    "path": str(r["path"]).strip().strip("/"),
                    "section": str(r.get("section") or "").strip(),
                    "mode": "demand" if r.get("mode") == "demand" else "always",
                }
            )
    return out


def agent_block(core: Core, workspace_id: str, definition: dict[str, Any]) -> str:
    """The rules an agent gets on every job (chat, board task, automation step)."""
    reads = reads_of(definition)
    if not reads:
        return ""
    base = folder(core, workspace_id)
    always: list[tuple[str, str]] = []
    demand: list[str] = []
    for r in reads:
        if r["mode"] == "demand":
            demand.append(r["path"] + (f" (section {r['section']})" if r["section"] else ""))
            continue
        try:
            target = _safe(core, workspace_id, r["path"])
            text = _read(target) if target.is_file() else ""
        except (ActionError, OSError):
            text = ""
        if not text:
            continue
        if r["section"]:
            part = rules.section_text(text, r["section"])
            if part:
                always.append((f"{r['path']} section {r['section']}", part))
            continue
        always.append((r["path"], text))
    block = rules.agent_block(always, demand)
    if always and base.is_dir():
        block += (
            "\n\n(The files above are given to you in full here: no need to open them again "
            "unless the owner says they just changed.)"
        )
    return block


# ---- checks ---------------------------------------------------------------------------


def latin_only(core: Core, workspace_id: str) -> bool:
    return doc_rows.latin_only(core.db, workspace_id)


def set_latin_only(core: Core, workspace_id: str, on: bool) -> None:
    require_workspace(core, workspace_id)
    doc_rows.set_latin_only(core.db, workspace_id, on)


def check(
    core: Core,
    workspace_id: str,
    *,
    members: list[Any] | None = None,
    docs: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """`members`, `docs`: team.members and all_docs already read for this request."""
    docs = all_docs(core, workspace_id) if docs is None else docs
    from agos_core.actions import team

    agents: dict[str, str] = {}
    reads: dict[str, list[str]] = {}
    for agent in team.members(core, workspace_id) if members is None else members:
        agents[agent.title] = agent.instructions
        reads[agent.title] = [x["path"] for x in agent.reads]
    skills: dict[str, str] = {}
    from agos_core.actions import hermes_config, workspace_skills
    from agos_core.actions.library import title_of

    on = hermes_config.here(core, workspace_id).skills
    for r in workspace_skills.shown(core, workspace_id):
        name = str(r["name"])
        if name not in on:
            continue
        # The skill as the whole team reads it: the workspace's one folder.
        source = workspace_skills.existing_dir(core, workspace_id, name)
        text = (source / "SKILL.md").read_text() if source else ""
        # Its title from that SKILL.md (the text just read), unless the owner named it.
        head = None if str(r["title"] or "").strip() or source is None else _frontmatter(text)
        skills[title_of(core, r, head)] = text
    from agos_core.actions import automations as automation_actions  # late: heavy imports

    automations = {
        a.name: a.instructions
        + " "
        + json.dumps([s.model_dump() for s in a.steps], ensure_ascii=False)
        for a in automation_actions.list_all(core, workspace_id)
    }
    src = rules.Sources(
        docs=docs,
        agents=agents,
        skills=skills,
        automations=automations,
        reads=reads,
        other_files=_other_names(workspace_paths(core.layout, workspace_id).files),
        latin_only=latin_only(core, workspace_id),
    )
    fingerprint = rules.fingerprint(src)
    # Keyed on what was read too: two views reading different texts at once never
    # share an answer (the check works from texts already read, not from the files).
    found = _FOUND.get((workspace_id, fingerprint), fingerprint, lambda: tuple(rules.check(src)))
    return [{"kind": f.kind, "where": f.where, "detail": f.detail, "other": f.other} for f in found]


def _frontmatter(text: str) -> dict[str, str]:
    """A SKILL.md's frontmatter as library.title_of reads it ({} when it has none)."""
    from agos_core.engine import library as lib

    try:
        return lib.parse_skill(text)[0]
    except lib.LibraryError:
        return {}


# What the checks found, kept while everything they look at is the same (the texts,
# the names, the setting: rules.fingerprint, worked out from what this view read).
# The duplicate check splits every text into runs of words and compares each agent,
# skill and automation with the rule files: 0.06 s of each view on the biggest workspace.
_FOUND: read_cache.ReadCache[tuple[rules.Finding, ...]] = read_cache.ReadCache(
    "docs-findings", max_entries=64
)


# ---- the .md names elsewhere in the workspace ------------------------------------------


@dataclass(frozen=True)
class _Names:
    """A workspace folder's .md names as one walk found them, with every folder it
    listed and their stamps, each taken just before its listing."""

    names: frozenset[str]
    folders: tuple[Path, ...]
    stamp: tuple[int, ...]
    whole: bool  # every folder could be listed (else the names are used once, never kept)


# Each workspace folder's .md names (a pointer may cite a file outside playbooks/),
# kept while every folder the walk listed has the same stamp: a file added, removed
# or renamed changes its folder's. The walk was most of the Documentation page
# (0.15 s of 0.24 s on the biggest workspace: 13,600 folders); their stamps take ~0.016 s.
_NAMES: read_cache.ReadCache[_Names] = read_cache.ReadCache("docs-md-names", max_entries=64)


def _other_names(files: Path) -> set[str]:
    """The .md names anywhere in the workspace folder, at most MAX_OTHER + 1."""
    if not files.is_dir():
        return set()
    try:
        return _md_names(files)
    except Exception:  # the walk the check always did, below
        log.warning("the workspace's .md names were not kept", exc_info=True)
    other: set[str] = set()
    for p in files.rglob("*.md"):
        if len(other) > MAX_OTHER:
            break
        other.add(p.name)
    return other


def _md_names(files: Path) -> set[str]:
    key = str(files)
    kept = _NAMES.peek(key)
    stamp = read_cache.file_stamp(*kept.folders) if kept is not None else None
    if kept is not None and stamp == kept.stamp:
        return set(kept.names)
    found = _NAMES.get(key, stamp, lambda: _walk(files))
    if not found.whole:
        _NAMES.drop(key)
    return set(found.names)


def _walk(files: Path) -> _Names:
    """The names Python's own `files.rglob("*.md")` gives, in its order (a folder's
    matches when it is found, its subfolders last in, first out; hidden ones are
    walked, a symlinked folder isn't entered), stopping past MAX_OTHER like the check
    always did. Each folder is listed once (rglob lists each twice)."""
    names: set[str] = set()
    folders: list[Path] = []
    stamp: list[int] = []
    whole = True

    def listing(folder: Path) -> list[os.DirEntry[str]]:
        nonlocal whole
        folders.append(folder)
        stamp.extend(read_cache.file_stamp(folder))  # before the listing
        try:
            with os.scandir(folder) as entries:
                return list(entries)
        except OSError:
            whole = False
            return []

    def matches(entries: list[os.DirEntry[str]]) -> bool:
        """Adds the entries' .md names; False when the walk stops."""
        for entry in entries:
            if entry.name.endswith(".md"):
                if len(names) > MAX_OTHER:
                    return False
                names.add(entry.name)
        return True

    top = listing(files)
    going = matches(top)
    stack = [top]
    while going and stack:
        for entry in stack.pop():
            try:
                folder = entry.is_dir(follow_symlinks=False)
            except OSError:
                whole, folder = False, False
            if not folder:
                continue
            below = listing(Path(entry.path))
            if not matches(below):
                going = False
                break
            stack.append(below)
    return _Names(frozenset(names), tuple(folders), tuple(stamp), whole)


# ---- agent text versions -------------------------------------------------------------------


def keep_agent_version(core: Core, agent: Any, event: str) -> None:
    """Before an agent changes or is deleted: its text, title and reads are kept
    (AGOS's own history: Hermes keeps none of a SOUL.md). `agent`: actions/team.Agent."""
    if agent is None:
        return
    agent_versions_repo.add(
        core.db,
        agent.workspace_id,
        agent.name,
        title=agent.title,
        summary=agent.summary,
        definition=dump_json({**agent.definition, "local": agent.local}),
        event=event,
        created_at=now(),
    )


def agent_versions(core: Core, workspace_id: str, name: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "title": r["title"],
            "event": r["event"],
            "at": r["created_at"],
            "size": len(str((library_repo.definition(r)).get("instructions") or "")),
        }
        for r in agent_versions_repo.history(core.db, workspace_id, name)
    ]


def deleted_agents(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """Agents deleted from this team (their last text), not re-created since."""
    out: list[dict[str, Any]] = []
    for v in agent_versions(core, workspace_id):
        if v["event"] != "deleted" or any(o["name"] == v["name"] for o in out):
            continue
        from agos_core.actions import team

        if team.get(core, workspace_id, str(v["name"])) is not None:
            continue
        out.append(v)
    return out


def restore_agent(core: Core, workspace_id: str, version_id: int) -> int:
    """Back to a kept version: same ID (@mention), text, reads. Re-creates a
    deleted agent the same way."""
    from agos_core.actions import library as library_actions

    row = agent_versions_repo.get(core.db, workspace_id, version_id)
    if row is None:
        raise NotFoundError("This version")
    from agos_core.actions import team

    current = team.get(core, workspace_id, str(row["name"]))
    kept = load_json(row["definition"]) or {}
    return library_actions.save_item(
        core,
        current.id if current else None,
        kind="agent",
        name=str(row["name"]),
        title=str(row["title"]),
        summary=str(row["summary"]),
        definition={k: v for k, v in kept.items() if k != "local"},
        workspace_id=workspace_id,
    )
