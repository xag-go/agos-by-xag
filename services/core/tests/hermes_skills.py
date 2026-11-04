"""A stand-in for Hermes's skill tool and skill ledger in the tests' fake homes
(the real ones run in Hermes's runtime: test_skill_writes_live.py checks them with
the installed Hermes). Same shapes as Hermes: an atomic batch of create / patch /
write_file / remove_file (only under references/ templates/ scripts/ assets/), or
a delete; one ledger entry per op in <home>/skills/.curator_ledger.jsonl with only
the changed files' {path, sha256} before and after, blobs under
<home>/.curator_backups/blobs; rollback restores the before blobs and removes the
files the entry created, refused when a newer entry exists."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED = {"references", "templates", "scripts", "assets"}

# Hermes's budget for a NEW skill's description (agent/skill_utils.py
# SKILL_PROMPT_DESC_LIMIT, checked by tools/skill_manager_tool.py _validate_frontmatter
# with new_skill=True on create only; edits keep an existing longer one).
DESC_LIMIT = 60


def new_skill_problem(text: str) -> str | None:
    """What Hermes's create says about this SKILL.md before it writes (None: fine)."""
    from agos_core.engine.library import parse_skill

    if not text.lstrip("\ufeff").startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). See existing skills for format."
    head, body = parse_skill(text)
    for field in ("name", "description"):
        if field not in head:
            return f"Frontmatter must include '{field}' field."
    desc = str(head["description"]).strip().strip("'\"")
    if len(desc) > DESC_LIMIT:
        return (
            f"Description is {len(desc)} chars — new skills must fit the {DESC_LIMIT}-char "
            "system-prompt budget (one sentence, trigger first, ends with a period). The "
            f"skill index truncates longer descriptions to {DESC_LIMIT - 3} chars + '...', "
            "destroying the routing signal. Move detail into the skill body."
        )
    if not body.strip():
        return "SKILL.md must have content after the frontmatter (instructions, procedures, etc.)."
    return None


def check_new(
    home: Path, name: str, text: str, files: dict[str, str] | None = None
) -> dict[str, Any]:
    """Hermes's checks before a create, nothing written (engine skill_check)."""
    said = new_skill_problem(text)
    return {"ok": said is None, "error": said or ""}


def _ledger(home: Path) -> Path:
    return home / "skills" / ".curator_ledger.jsonl"


def _blob(home: Path, data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    path = home / ".curator_backups" / "blobs" / sha
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return sha


def _snap(home: Path, folder: Path | None) -> dict[str, str]:
    if folder is None or not folder.is_dir():
        return {}
    return {str(p): _blob(home, p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()}


def find(home: Path, name: str) -> Path | None:
    root = home / "skills"
    if not root.is_dir():
        return None
    for md in sorted(root.rglob("SKILL.md")):
        rel = md.relative_to(root).parts
        if md.parent.name == name and not any(p.startswith(".") for p in rel):
            return md.parent
    return None


def entries(home: Path) -> list[dict[str, Any]]:
    """Newest first (list_entries)."""
    path = _ledger(home)
    rows = (
        [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        if path.is_file()
        else []
    )
    return list(reversed(rows))


def _append(
    home: Path,
    action: str,
    skill: str,
    was: dict[str, str],
    now: dict[str, str],
    actor: str,
    **ev: Any,
) -> str:
    keys = sorted(set(was) | set(now))
    changed = [k for k in keys if was.get(k) != now.get(k)] if action != "pre-rollback" else keys
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(UTC).isoformat(),
        "actor": actor,
        "action": action,
        "skill": skill,
        "evidence": ev,
        "before": [{"path": k, "sha256": was[k]} for k in changed if k in was],
        "after": [{"path": k, "sha256": now[k]} for k in changed if k in now],
    }
    path = _ledger(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    return str(entry["id"])


def skill_manage(
    home: Path, name: str, ops: list[dict[str, Any]] | None, *, delete: bool, actor: str
) -> dict[str, Any]:
    had = {e["id"] for e in entries(home)}
    folder = find(home, name)
    if delete:
        if folder is None:
            return {"ok": False, "error": f"Skill '{name}' not found.", "entries": []}
        was = _snap(home, folder)
        shutil.rmtree(folder)
        _append(home, "delete", name, was, {}, actor)
    else:
        aside = None
        if folder is not None:
            aside = home / ".batch-aside"
            shutil.rmtree(aside, ignore_errors=True)
            shutil.copytree(folder, aside)
        for i, op in enumerate(ops or []):
            folder = find(home, name)
            act, rel = op["action"], str(op.get("file_path") or "")
            if act == "create":
                if folder is not None:
                    return {"ok": False, "error": f"'{name}' already exists", "entries": []}
                said = new_skill_problem(str(op["content"]))
                if said is not None:
                    refused = f"operations[{i}] (create on '{name}') failed: {said}"
                    return {"ok": False, "error": refused, "entries": []}
                # Hermes's create category: skills/<category>/<name>.
                folder = home / "skills" / str(op.get("category") or "") / name
                folder.mkdir(parents=True)
                (folder / "SKILL.md").write_text(op["content"])
                _append(home, "create", name, {}, _snap(home, folder), actor)
                continue
            error = None
            if folder is None:
                error = f"Skill '{name}' not found."
            elif act in ("write_file", "remove_file") and Path(rel).parts[:1] not in [
                (d,) for d in ALLOWED
            ]:
                error = f"File must be under one of: {', '.join(sorted(ALLOWED))}. Got: '{rel}'"
            if error is not None:
                if aside is not None and folder is not None:
                    shutil.rmtree(folder)
                    shutil.copytree(aside, folder)
                return {"ok": False, "error": f"operations[{i}] failed: {error}", "entries": []}
            assert folder is not None
            was = _snap(home, folder)
            if act == "patch":
                (folder / "SKILL.md").write_text(op["content"])
            elif act == "write_file":
                (folder / rel).parent.mkdir(parents=True, exist_ok=True)
                (folder / rel).write_text(op["file_content"])
            elif act == "remove_file":
                (folder / rel).unlink()
            _append(home, act, name, was, _snap(home, folder), actor)
        if aside is not None:
            shutil.rmtree(aside, ignore_errors=True)
    made = [e["id"] for e in entries(home) if e["id"] not in had]
    return {"ok": True, "error": "", "entries": made}


def rollback(home: Path, skills: list[str], ours: list[str]) -> dict[str, Any]:
    rows = entries(home)
    for name in skills:
        newest = next((e for e in rows if e["skill"] == name), None)
        if newest is not None and newest["id"] not in ours:
            return {"ok": False, "error": "the skill changed since; Undo would lose the newer edit"}
    for entry_id in ours:
        entry = next(e for e in entries(home) if e["id"] == entry_id)
        touched = {i["path"] for i in entry["before"] + entry["after"]}
        now = {p: _blob(home, Path(p).read_bytes()) for p in sorted(touched) if Path(p).is_file()}
        _append(home, "pre-rollback", entry["skill"], now, now, "user", rollback_target=entry_id)
        for item in entry["before"]:
            p = Path(item["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes((home / ".curator_backups" / "blobs" / item["sha256"]).read_bytes())
        before = {i["path"] for i in entry["before"]}
        for item in entry["after"]:
            if item["path"] not in before:
                Path(item["path"]).unlink(missing_ok=True)
        restored = {i["path"]: i["sha256"] for i in entry["before"]}
        _append(home, "rollback", entry["skill"], now, restored, "user", rollback_target=entry_id)
    return {"ok": True}


def history(home: Path, folder: Path, skill: str, known: list[str]) -> list[dict[str, Any]]:
    """One skill's entries, oldest first, with the changed files' content (base64,
    by path relative to the skill's folder) for the entries not in `known`
    (engine skill_history, engine/hermes.py _SKILL_HISTORY)."""
    import base64

    def rel(p: str) -> str | None:
        try:
            return Path(p).relative_to(folder).as_posix()
        except ValueError:
            return None

    def side(items: list[dict[str, str]]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for i in items:
            r = rel(i["path"])
            if r is None:
                continue
            blob = home / ".curator_backups" / "blobs" / i["sha256"]
            out[r] = base64.b64encode(blob.read_bytes()).decode() if blob.is_file() else None
        return out

    out = []
    for e in reversed(entries(home)):
        if e["skill"] != skill:
            continue
        ev = e.get("evidence") or {}
        item: dict[str, Any] = {
            "id": e["id"],
            "ts": e["ts"],
            "actor": e["actor"],
            "action": e["action"],
            "evidence": {k: str(ev[k]) for k in ("session_id", "rollback_target") if ev.get(k)},
            "paths": sorted(
                {r for r in (rel(i["path"]) for i in e.get("before", []) + e.get("after", [])) if r}
            ),
        }
        if e["id"] not in set(known):
            item["before"], item["after"] = side(e.get("before", [])), side(e.get("after", []))
        out.append(item)
    return out


def changes(home: Path, limit: int = 200) -> list[dict[str, Any]]:
    rows = entries(home)
    undone = {
        str((e.get("evidence") or {}).get("rollback_target"))
        for e in rows
        if e["action"] == "rollback"
    }

    def text(items: list[dict[str, str]]) -> str | None:
        found = sorted(
            (i for i in items if Path(i["path"]).name == "SKILL.md"), key=lambda i: len(i["path"])
        )
        if not found:
            return None
        return (home / ".curator_backups" / "blobs" / found[0]["sha256"]).read_text()

    return [
        {
            "id": e["id"],
            "ts": e["ts"],
            "actor": e["actor"],
            "action": e["action"],
            "skill": e["skill"],
            "session": str((e.get("evidence") or {}).get("session_id") or ""),
            "before": text(e.get("before") or []),
            "after": text(e.get("after") or []),
            "files": sorted(
                {Path(i["path"]).name for i in (e.get("before") or []) + (e.get("after") or [])}
            ),
            "undone": e["id"] in undone,
        }
        for e in rows[:limit]
    ]
