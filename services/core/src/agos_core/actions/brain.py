"""AGOS Brain: ways of working the whole team learned, shared by every workspace.

Three layers keep projects apart (the owner's rule: nothing of one project leaks
into another):
- the owner's rules (owner_rules.py): about him, every workspace;
- the Brain (here): HOW to do a kind of work well, written without any project's
  names, topics, files or data ("read the whole error before trying again"),
  every workspace, unless a workspace turned that method off ("Not here");
- a project's own work (playbooks, skills, memory): never leaves its workspace.

The Brain lives in Hermes, not in AGOS's database: each method is a Hermes skill
(`agos-brain-<n>/SKILL.md`) in ONE shared folder that every workspace's profile
reads (`skills.external_dirs`, Hermes's way to share skills), and "Not here" is
that profile's own `skills.disabled`. AGOS's Settings → Brain only reads and writes
those. Agents see each method's name and open it when it fits; the agos-guard
plugin keeps them from changing it (only the owner does, in AGOS, or by approving a
Co-Founder's `add_method` card).

Workspaces stay closed to each other: a skill holds only the method's text. Which
workspace proposed it is kept beside the folder (`origins.json`), never in what
the agents read.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.rows import now
from agos_core.hermes_gateway import cli as hermes_cli

PREFIX = "agos-brain-"  # the skills' names; agents can't change them (agos-guard)
_BODY = "<!-- the method, as the owner wrote it: -->\n"


def _clean(text: str) -> str:
    from agos_core.engine.identity import clean

    value = clean(str(text or ""))
    if not value:
        raise ActionError("Write the method.")
    return value


def skills_dir(core: Core) -> Path:
    return core.layout.root / "brain" / "skills"


def _origins_file(core: Core) -> Path:
    # Beside the skills folder, not in it: no agent ever reads it.
    return core.layout.root / "brain" / "origins.json"


def skill_name(method_id: int) -> str:
    return f"{PREFIX}{method_id}"


# ---- the methods: Hermes skill files ------------------------------------------------


def _origins(core: Core) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_origins_file(core).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_origins(core: Core, data: dict[str, dict[str, Any]]) -> None:
    path = _origins_file(core)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".origins.json.agos")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    name = path.parent.name
    if not name.startswith(PREFIX) or not name[len(PREFIX) :].isdigit() or _BODY not in text:
        return None
    return {"id": int(name[len(PREFIX) :]), "text": text.split(_BODY, 1)[1].rstrip("\n")}


def _all(core: Core) -> list[dict[str, Any]]:
    folder = skills_dir(core)
    if not folder.is_dir():
        return []
    origins = _origins(core)
    found = [_read(p) for p in folder.glob(f"{PREFIX}*/SKILL.md")]
    return sorted(
        (
            {
                **m,
                "fromWorkspace": (origins.get(str(m["id"])) or {}).get("from") or None,
                "createdAt": str((origins.get(str(m["id"])) or {}).get("at") or ""),
            }
            for m in found
            if m is not None
        ),
        key=lambda m: int(m["id"]),
    )


def _write(core: Core, method_id: int, text: str) -> None:
    first = " ".join(text.split())
    about = first if len(first) <= 200 else first[:197] + "..."
    content = (
        f"---\nname: {skill_name(method_id)}\n"
        f"description: {json.dumps('Way of working (AGOS Brain): ' + about)}\n"
        "---\n\n# A way of working the team learned (every workspace)\n\n"
        "General, not about any project; this workspace's own playbooks and skills win on "
        "its project. Only the owner changes it, in AGOS.\n\n"
        f"{_BODY}{text}\n"
    )
    path = skills_dir(core) / skill_name(method_id) / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".SKILL.md.agos")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def list_methods(core: Core, workspace_id: str | None = None) -> list[dict[str, Any]]:
    off = set(_disabled(core, workspace_id)) if workspace_id is not None else set()
    return [{**m, "usedHere": skill_name(int(m["id"])) not in off} for m in _all(core)]


def _exists(core: Core, method_id: int) -> None:
    if not any(int(m["id"]) == method_id for m in _all(core)):
        raise NotFoundError("This method")


def add(core: Core, text: str, *, from_workspace: str | None = None) -> int:
    value = _clean(text)
    methods = _all(core)
    for m in methods:
        if str(m["text"]).lower() == value.lower():
            return int(m["id"])
    origins = _origins(core)
    # A number is never used twice: a workspace's old "Not here" can't hit a new one.
    last = int((origins.get("_next") or {}).get("id") or 0)
    method_id = max([last, *(int(m["id"]) for m in methods)]) + 1
    _write(core, method_id, value)
    origins[str(method_id)] = {"from": from_workspace, "at": now()}
    origins["_next"] = {"id": method_id}
    _save_origins(core, origins)
    return method_id


def edit(core: Core, method_id: int, text: str) -> None:
    _exists(core, method_id)
    _write(core, method_id, _clean(text))


def delete(core: Core, method_id: int) -> None:
    shutil.rmtree(skills_dir(core) / skill_name(method_id), ignore_errors=True)
    origins = _origins(core)
    if origins.pop(str(method_id), None) is not None:
        _save_origins(core, origins)
    # Gone from every workspace's "Not here" too (Hermes's skills.disabled).
    from agos_core.db.workspaces import list_workspaces

    name = skill_name(method_id)
    for w in list_workspaces(core.db, include_archived=True):
        off = _disabled(core, w.id)
        if name in off and core.engine is not None:
            hermes_cli.cli(
                core.engine,
                w.id,
                "config",
                "set",
                "skills.disabled",
                json.dumps(sorted(n for n in off if n != name)),
            )


# ---- "Not here": the workspace's own Hermes setting (skills.disabled) --------------


def _parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw or raw in ("[]", "null", "None"):
        return []
    try:
        value: Any = json.loads(raw)
    except ValueError:
        value = [
            line.strip()[2:].strip() for line in raw.splitlines() if line.strip().startswith("- ")
        ]
    return [str(v) for v in value] if isinstance(value, list) else []


def _disabled(core: Core, workspace_id: str | None) -> list[str]:
    """The profile's skills.disabled, as Hermes has it: read as Hermes reads it
    (engine.as_hermes_reads, the profile's config.yaml with the managed scope on
    top, kept while those files are unchanged), so no Hermes starts per page.
    Unset is no list, like `hermes config get` (no default for it); that CLI is
    still asked when the read fails."""
    if core.engine is None or workspace_id is None:
        return []
    from agos_core.engine.hermes import EngineError

    home = core.engine.profile_home(workspace_id)
    try:
        cfg = core.engine.as_hermes_reads([home]).get(str(home))
        if not isinstance(cfg, dict):
            raise EngineError("no read of the profile's config")
        skills = cfg.get("skills")
        value = skills.get("disabled") if isinstance(skills, dict) else None
        if isinstance(value, str):
            return _parse_list(value)  # what the CLI prints for it, read the same way
        return [str(v) for v in value] if isinstance(value, list) else []
    except (EngineError, OSError, ValueError):
        pass
    try:
        raw = hermes_cli.cli(core.engine, workspace_id, "config", "get", "skills.disabled")
    except (EngineError, OSError):
        return []
    return _parse_list(raw)


def off_here(core: Core, workspace_id: str) -> list[str]:
    """Skills off in this workspace (Hermes's own list; a Brain method that is gone
    is dropped from it)."""
    have = {skill_name(int(m["id"])) for m in _all(core)}
    return [n for n in _disabled(core, workspace_id) if not n.startswith(PREFIX) or n in have]


def set_used_here(core: Core, workspace_id: str, method_id: int, used: bool) -> None:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    _exists(core, method_id)
    name = skill_name(method_id)
    off = [n for n in off_here(core, workspace_id) if n != name]
    if not used:
        off.append(name)
    if core.engine is not None:
        hermes_cli.cli(
            core.engine, workspace_id, "config", "set", "skills.disabled", json.dumps(sorted(off))
        )
