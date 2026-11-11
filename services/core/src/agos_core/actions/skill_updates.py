"""Auto-update of a workspace skill installed from the web (F78): a per-skill flag,
and ONE Hermes cron job per workspace that runs `hermes skills update <name>` for
the flagged skills.

- The flag is the skill row's `auto_update` (library_items.definition): Hermes's hub
  lock knows the source of an installed skill, not whether the owner wants it to
  follow its source (tools/skills_hub.py HubLockFile has no such field).
- The job is Hermes's own: a no-agent script job in the workspace's root
  (`agos-skill-updates`, like the digest's), run daily by the root's scheduler, its
  script written by AGOS into the root's scripts folder (engine/cron.py
  write_run_script's way). The script is Hermes's hub CLI per flagged skill (the
  same `hermes skills update --force` AGOS's Update button runs, in the root, so the
  root's hub lock is the record), standard library only. No token: the hub's GitHub
  token stays in AGOS's library home and is never written into a root.
- The new version: Hermes's hub writes no skill-ledger entry, so the next read of
  the skill's versions sees the folder changed and keeps it as a version by "hub"
  (actions/skill_versions.py reconcile).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db import library as repo
from agos_core.db.connection import transaction
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.skill_updates")

FLAG = "auto_update"  # in the skill row's definition
JOB = "agos-skill-updates"  # the Hermes cron job's name in each root (not an agent's)
SCRIPT = "agos-skill-updates.py"  # in the root's Hermes scripts folder
SCHEDULE = "0 4 * * *"  # Hermes's cron, in the owner's timezone: nightly

# Run by Hermes's cron (no agent): Hermes's own hub update of each flagged skill,
# in this root (its hub lock). Prints one line per skill for the job's output.
SCRIPT_TEXT = r'''"""AGOS: auto-update of this workspace's skills from their source (no agent).

The engine's cron runs this in the workspace's root; each flagged skill is updated
with the engine's own `hermes skills update` (the root's hub lock keeps the source).
Written by AGOS (actions/skill_updates.py); rewritten when the flagged skills change."""

import json
import subprocess
import sys

PLAN = json.loads(@PLAN@)


def main() -> int:
    failed = 0
    for name in PLAN["skills"]:
        done = subprocess.run(  # noqa: S603 - the engine's own CLI, fixed argv, no shell
            [PLAN["hermes"], "skills", "update", name, "--force"],
            capture_output=True,
            text=True,
            timeout=600,
            env={str(k): str(v) for k, v in PLAN["env"].items()},
            check=False,
        )
        said = (done.stdout or done.stderr or "").strip().splitlines()
        last = said[-1][:200] if said else "no output"
        if done.returncode != 0:
            failed += 1
            print(f"{name}: not updated ({last})")
        else:
            print(f"{name}: {last}")
    if not PLAN["skills"]:
        print("No skill set to auto-update.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
'''


def _row(core: Core, workspace_id: str, item_id: int) -> Any:
    from agos_core.actions.workspaces import require_workspace

    require_workspace(core, workspace_id)
    row = repo.get_item(core.db, item_id)
    if row is None or row["kind"] != "skill" or row["workspace_id"] != workspace_id:
        raise NotFoundError("This skill")
    return row


def is_on(row: Any) -> bool:
    return bool(repo.definition(row).get(FLAG))


def flagged(core: Core, workspace_id: str) -> list[str]:
    """The names of this workspace's web skills set to follow their source."""
    return sorted(
        str(r["name"])
        for r in repo.workspace_skills(core.db, workspace_id)
        if r["source"] == "web" and is_on(r)
    )


def set_flag(core: Core, workspace_id: str, item_id: int, on: bool) -> str:
    """The owner's choice for one skill; the workspace's job follows at once
    (returns what keep_job did)."""
    row = _row(core, workspace_id, item_id)
    if on and str(row["source"] or "") != "web":
        raise ActionError("Only a skill installed from the web can follow its source.")
    definition = {k: v for k, v in repo.definition(row).items() if k != FLAG}
    if on:
        definition[FLAG] = True
    with transaction(core.db):
        repo.update_item(
            core.db,
            item_id,
            title=str(row["title"] or ""),
            summary=str(row["summary"] or ""),
            definition=definition,
        )
    return keep_job(core, workspace_id)


# ---- the Hermes cron job ---------------------------------------------------------------


def _job(home: Path) -> dict[str, Any] | None:
    """The job as Hermes saved it (the root's cron/jobs.json, read only)."""
    try:
        data = json.loads((home / "cron" / "jobs.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if isinstance(jobs, dict):
        jobs = [{**v, "id": v.get("id") or k} for k, v in jobs.items() if isinstance(v, dict)]
    return next(
        (j for j in jobs or [] if isinstance(j, dict) and j.get("id") and j.get("name") == JOB),
        None,
    )


def script_text(core: Core, workspace_id: str, names: list[str]) -> str:
    assert core.engine is not None
    plan = {
        "hermes": core.engine.settings.hermes_bin,
        "env": {
            **core.engine.hermes_env(workspace_id),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "NO_COLOR": "1",
        },
        "skills": list(names),
    }
    return SCRIPT_TEXT.replace("@PLAN@", json.dumps(json.dumps(plan, sort_keys=True)))


def _write_script(home: Path, text: str) -> bool:
    scripts = home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / SCRIPT
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.chmod(0o600)
    tmp.replace(path)
    return True


def keep_job(core: Core, workspace_id: str) -> str:
    """The workspace's job in Hermes's cron matches its flagged skills: made with the
    first flag, its script rewritten as the flags change, removed with the last.
    Returns what was done: "made", "rewritten", "removed" or ""."""
    from agos_core.engine.hermes import EngineError

    engine = core.engine
    if engine is None or engine.not_migrated(workspace_id):
        return ""
    home = engine.root(workspace_id)
    if not (home / "config.yaml").is_file():
        return ""
    names = flagged(core, workspace_id)
    job = _job(home)
    try:
        if not names:
            if job is None:
                return ""
            hermes_cli.cli(engine, workspace_id, "cron", "remove", str(job["id"]))
            return "removed"
        rewritten = _write_script(home, script_text(core, workspace_id, names))
        if job is None:
            said = hermes_cli.cli(
                engine,
                workspace_id,
                "cron",
                "create",
                f"--name={JOB}",
                "--deliver=local",
                "--failure-deliver=local",
                f"--script={SCRIPT}",
                "--no-agent",
                "--",
                SCHEDULE,
                timeout=120,
            )
            if not re.search(r"Created job: (\S+)", said or ""):
                log.warning(
                    "skill updates job not made in %s: %s", workspace_id, (said or "")[-200:]
                )
                return ""
            return "made"
        return "rewritten" if rewritten else ""
    except (EngineError, OSError) as error:
        log.warning("skill updates job of %s not kept: %s", workspace_id, error)
    return ""


def keep_job_soon(core: Core, workspace_id: str) -> None:
    def go() -> None:
        try:
            keep_job(core, workspace_id)
        except Exception:
            log.exception("skill updates job of %s not kept", workspace_id)

    threading.Thread(target=go, name=f"skill-updates-{workspace_id}", daemon=True).start()


def job_ids(core: Core, workspace_id: str) -> set[str]:
    """The job's id (AGOS's, not an agent's: Ongoing leaves it out)."""
    if core.engine is None:
        return set()
    job = _job(core.engine.profile_home(workspace_id))
    return {str(job["id"])} if job else set()
