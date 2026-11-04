"""The team's agents and automations as a GENERATED, read-only view: /workspace/playbooks.

- playbooks/agents/<id>.md and playbooks/automations/<id>.md are a copy, written by
  AGOS from Hermes (each member's profile.yaml + SOUL.md + skills.auto_load; each
  automation's Hermes cron job name/schedule/on-off, plus AGOS's own team plan and
  brief). Nothing reads them back: Hermes stays the only master.
- Why the copy must exist (verified in Hermes v0.22.2): the Co-Founder changes a
  member's role with update_agent `replace` (exact old text), so it must read the
  member's SOUL.md, and no Hermes tool shows another profile's SOUL.md (the
  delegate tool even skips SOUL.md, H: tools/delegate_tool_progress.py:199);
  mounting the members' Hermes profiles into the sandbox is ruled out (Hermes's
  private dirs). Hermes's cronjob `list` shows only `prompt_preview`, the first 100
  characters (H: tools/cronjob_job_args.py:488), and nothing of the team plan.
- Written only when a source changed: refresh_all compares a fingerprint of the
  sources (the Hermes files above, AGOS's automation rows) and of the view's own
  files, kept in memory, and rewrites nothing when it is the same (no timer
  rewrite).
- The agents read them but can't write them (read-only in their sandbox): every
  change goes through a card (update_agent / update_automation …), so it has
  Undo, the owner's Autonomy rules and a line in the history.
- Skills are NOT copied here any more: agents read them natively (Hermes's skills
  tool), from the shared library folder (skills.external_dirs) or the workspace's
  own version. The old playbooks/skills view is removed once (only the files AGOS
  wrote there, as it wrote them).
- The rest of playbooks/ (team.md, flow.md, CHANGES.md…) is the Documentation,
  unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from agos_core.actions import team
from agos_core.context import Core
from agos_core.db import library as library_repo
from agos_core.db.rows import now
from agos_core.storage.layout import workspace_paths

log = logging.getLogger(__name__)

PLAYBOOKS = "playbooks"
KINDS = ("agents", "automations")
OLD_KINDS = ("skills", *KINDS)  # what older AGOS kept in playbooks/ (moved once)
WRITTEN_KEY = "playbooks.written.{}"  # what AGOS last wrote (hash per file), per workspace
MANIFEST = ".agos-written.json"  # the old place (inside playbooks/), removed
NOTE = (
    "<!-- Written by AGOS: this is what the team uses right now. Agents read it; to change "
    "it they use an {action} card (Undo, history). Edits made here from outside the "
    "sandbox are put back. -->\n"
)
# The view's files, relative to the workspace folder (the automation's own
# instructions file, automations/<name>.md in the automations folder, is another file).
AGENT_VIEW = "playbooks/agents/{}.md"
AUTOMATION_VIEW = "playbooks/automations/{}.md"
MAX_FILE = 400_000
MAX_FILES = 200


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root(core: Core, workspace_id: str) -> Path:
    return workspace_paths(core.layout, workspace_id).files / PLAYBOOKS


# ---- what the files hold ---------------------------------------------------------


def agent_file(agent: team.Agent) -> str:
    """A member as its Hermes profile says."""
    head = {
        "title": agent.title,
        "summary": agent.summary,
        "skills": list(agent.skills),
        "reads": [dict(r) for r in agent.reads],
    }
    return (
        NOTE.format(action="update_agent")
        + "---\n"
        + json.dumps(head, ensure_ascii=False, indent=2)
        + "\n---\n\n"
        + agent.instructions.strip()
        + "\n"
    )


_AGENT = re.compile(r"\A(?:<!--.*?-->\n)?---\n(?P<head>.*?)\n---\n\n?(?P<body>.*)\Z", re.S)


def automation_file(automation: Any) -> str:
    """Shown as the team uses it: schedule and on/off from Hermes's cron, the
    instructions from the automation's own file."""
    head = {
        "name": str(automation.name),
        "schedule": str(automation.schedule or ""),
        "on": bool(automation.on),
        "agent": automation.agent or "Co-Founder",
        "steps": [s.model_dump(by_alias=False) for s in automation.steps],
    }
    hook = getattr(automation, "hook", None)
    if hook is not None:
        # Its webhook as Hermes holds it: every event and every "Only if" line, so
        # a change is made from the whole of it, never from a partial picture.
        head["webhook"] = {
            "events": list(hook.events),
            "only_if": [c.model_dump() for c in hook.conditions],
            **({"other_hermes_filters": hook.other_filters} if hook.other_filters else {}),
        }
    return (
        NOTE.format(action="update_automation")
        + "---\n"
        + json.dumps(head, ensure_ascii=False, indent=2)
        + "\n---\n\n"
        + str(automation.instructions or "").strip()
        + "\n"
    )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "automation"


# ---- skills with their files ----------------------------------------------------


def skill_files(folder: Path) -> dict[str, str]:
    """A skill folder's extra files (references, scripts…), as text."""
    out: dict[str, str] = {}
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder).as_posix()
        if not p.is_file() or rel == "SKILL.md" or any(s.startswith(".") for s in rel.split("/")):
            continue
        if "__pycache__" in rel or len(out) >= MAX_FILES or p.stat().st_size > MAX_FILE:
            continue
        try:
            out[rel] = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
    return out


def clean_files(files: Any) -> dict[str, str]:
    """Extra files of a skill: relative paths inside it, text only."""
    if not isinstance(files, dict):
        return {}
    out: dict[str, str] = {}
    for raw, text in list(files.items())[:MAX_FILES]:
        rel = str(raw).strip().strip("/")
        parts = rel.split("/")
        if (
            not rel
            or rel == "SKILL.md"
            or ".." in parts
            or any(p.startswith(".") or not p for p in parts)
            or "\\" in rel
            or not isinstance(text, str)
            or len(text) > MAX_FILE
        ):
            continue
        out[rel] = text
    return out


# ---- the mirror ------------------------------------------------------------------


def _manifest(core: Core, workspace_id: str) -> dict[str, str]:
    """Kept in AGOS's database, out of the agents' reach."""
    from agos_core.db.app_settings import get_setting

    data = get_setting(core.db, WRITTEN_KEY.format(workspace_id), None)
    return data if isinstance(data, dict) else {}


def adopted(core: Core, workspace_id: str) -> bool:
    from agos_core.db.app_settings import get_setting

    return get_setting(core.db, WRITTEN_KEY.format(workspace_id), None) is not None


def wanted(core: Core, workspace_id: str) -> dict[str, bytes]:
    """Every file AGOS shows under playbooks/{agents,automations}."""
    out: dict[str, bytes] = {}
    prefix = PLAYBOOKS + "/"
    for agent in team.members(core, workspace_id):
        out[AGENT_VIEW.format(agent.name).removeprefix(prefix)] = agent_file(agent).encode()
    from agos_core.actions import automations as automation_actions  # late: it imports us

    seen: set[str] = set()
    for automation in automation_actions.list_all(core, workspace_id):
        slug = _slug(automation.name)
        while slug in seen:
            slug += "-2"
        seen.add(slug)
        out[AUTOMATION_VIEW.format(slug).removeprefix(prefix)] = automation_file(
            automation
        ).encode()
    return out


def write(core: Core, workspace_id: str, *, adopting: bool = False) -> None:
    """playbooks/{agents,automations} = exactly what the team uses."""
    base = root(core, workspace_id)
    if not adopting and not adopted(core, workspace_id) and _has_old_masters(base):
        return  # adopt() moves them aside first (at start), then writes
    try:
        files = wanted(core, workspace_id)
        base.mkdir(parents=True, exist_ok=True)
        written: dict[str, str] = {}
        for rel, data in files.items():
            target = base / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.is_file() or target.read_bytes() != data:
                target.write_bytes(data)
            written[rel] = _hash(data)
        for kind in KINDS:
            folder = base / kind
            folder.mkdir(exist_ok=True)
            for p in sorted(folder.rglob("*"), reverse=True):
                rel = p.relative_to(base).as_posix()
                if p.is_file() and rel not in written:
                    p.unlink()
                elif p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
        before = _manifest(core, workspace_id)
        _drop_skills_view(base, before)
        if before != written or not adopted(core, workspace_id):
            from agos_core.db.app_settings import set_setting

            set_setting(core.db, WRITTEN_KEY.format(workspace_id), written)
        (base / MANIFEST).unlink(missing_ok=True)
    except OSError as error:
        log.warning("playbooks of %s not written: %s", workspace_id, error)


def _drop_skills_view(base: Path, written: dict[str, str]) -> None:
    """The old playbooks/skills view goes (once; safe to repeat): only the files
    AGOS wrote there, still as it wrote them. Anything else is left alone."""
    folder = base / "skills"
    if not folder.is_dir() or folder.is_symlink():
        return
    for p in sorted(folder.rglob("*"), reverse=True):
        rel = p.relative_to(base).as_posix()
        if p.is_symlink():
            continue
        if p.is_file() and rel in written and _hash(p.read_bytes()) == written[rel]:
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    if not any(folder.iterdir()):
        folder.rmdir()


def _has_old_masters(base: Path) -> bool:
    return any((base / k).is_dir() and any((base / k).iterdir()) for k in OLD_KINDS)


def sync(core: Core, workspace_id: str) -> None:
    """The view shows what the team uses now (AGOS's agents and automations).
    Files changed in it by hand are put back: a card is the only way to change
    them, never this view."""
    write(core, workspace_id)


# workspace -> the fingerprint of the view's sources (and its own files) when it
# was last written. Memory only: after a restart the first pass writes (only the
# files that differ) and keeps the fingerprint again.
_written_from: dict[str, str] = {}


def _stat(h: Any, path: Path) -> None:
    try:
        st = path.stat()
    except OSError:
        h.update(f"{path}:-\n".encode())
        return
    h.update(f"{path}:{st.st_mtime_ns}:{st.st_size}\n".encode())


def fingerprint(core: Core, workspace_id: str) -> str:
    """What the view is made from, cheaply (stats and AGOS's rows, no Hermes run):
    each profile's cron jobs.json, the root's webhook routes, each member's
    profile.yaml / SOUL.md / config.yaml, the profiles folder, AGOS's automation
    rows and instructions files, and the view's own files (a hand edit is put back)."""
    from agos_core.actions.hooks import SUBSCRIPTIONS
    from agos_core.db import automations as automation_repo

    h = hashlib.sha256()
    for row in automation_repo.rows(core.db, workspace_id):
        h.update(repr(tuple(row)).encode())
    autos = workspace_paths(core.layout, workspace_id).automations
    for p in sorted(autos.glob("*.md")) if autos.is_dir() else ():
        _stat(h, p)
    engine = core.engine
    if engine is not None:
        main = engine.profile_home(workspace_id)
        _stat(h, main / "cron" / "jobs.json")
        _stat(h, main / SUBSCRIPTIONS)
        _stat(h, engine.root(workspace_id) / "profiles")
        for name in team._profile_names(core, workspace_id):
            where = team.home(core, workspace_id, name)
            if where is None:
                continue
            for rel in ("profile.yaml", "SOUL.md", "config.yaml"):
                _stat(h, where / rel)
            _stat(h, where / "cron" / "jobs.json")
    base = root(core, workspace_id)
    for kind in KINDS:
        folder = base / kind
        _stat(h, folder)
        for p in sorted(folder.rglob("*")) if folder.is_dir() else ():
            _stat(h, p)
    return h.hexdigest()


def refresh_all(core: Core) -> int:
    """Every live workspace's view, rewritten only when one of its sources changed
    (an automation paused from Telegram, a member edited in Hermes). Returns how
    many views were rewritten."""
    from agos_core.db.workspaces import list_workspaces

    n = 0
    for workspace in list_workspaces(core.db):
        if not adopted(core, workspace.id):
            continue
        if _written_from.get(workspace.id) == fingerprint(core, workspace.id):
            continue
        write(core, workspace.id)
        _written_from[workspace.id] = fingerprint(core, workspace.id)
        n += 1
    return n


# ---- the one-time move -------------------------------------------------------------


def adopt(core: Core, workspace_id: str) -> dict[str, Any]:
    """Moves a workspace to the single copy, once (no manifest yet):

    - a skill's extra files kept only in playbooks/skills/<id>/ (references,
      scripts) go into the skill, when its SKILL.md is the one the team uses;
    - the old hand-kept masters (playbooks/skills, agents, automations) are moved
      to archive/playbooks-before-<date>/, nothing deleted;
    - the read-only copies in .agos/team are removed (playbooks shows them now)."""
    from agos_core.actions import library as library_actions
    from agos_core.actions import workspace_skills

    base = root(core, workspace_id)
    report: dict[str, Any] = {"files_added": [], "archived": None, "different": []}
    if adopted(core, workspace_id):
        return report
    moved = [base / k for k in OLD_KINDS if (base / k).exists()]
    archive: Path | None = None
    if moved:
        stamp = now()[:10]
        archive = base.parent / "archive" / f"playbooks-before-{stamp}"
        n = 2
        while archive.exists():
            archive = base.parent / "archive" / f"playbooks-before-{stamp}-{n}"
            n += 1
        archive.mkdir(parents=True)
        for p in moved:
            shutil.move(str(p), str(archive / p.name))
        report["archived"] = str(archive.relative_to(base.parent))
    old_skills = archive / "skills" if archive else None
    if old_skills is not None and old_skills.is_dir():
        for folder in sorted(p for p in old_skills.iterdir() if p.is_dir()):
            row = library_repo.find_item(core.db, "skill", folder.name, workspace_id)
            if row is None or not (folder / "SKILL.md").is_file():
                continue
            d = workspace_skills.definition(core, row)
            if (folder / "SKILL.md").read_text() != str(d.get("text") or ""):
                report["different"].append(folder.name)
                continue  # the master differs: the team's version stays, master archived
            extra = skill_files(folder)
            have = dict(d.get("files") or {})
            new = {k: v for k, v in extra.items() if k not in have}
            if not new:
                continue
            library_actions.save_item(
                core,
                int(row["id"]),
                kind="skill",
                name=str(row["name"]),
                title=str(row["title"]),
                summary="",
                definition={**d, "files": {**have, **new}},
                source=str(row["source"]),
                workspace_id=workspace_id,
            )
            report["files_added"] += [f"{folder.name}/{k}" for k in sorted(new)]
    team = base.parent / ".agos" / "team"
    if team.is_dir():
        shutil.rmtree(team)
    write(core, workspace_id, adopting=True)
    return report
