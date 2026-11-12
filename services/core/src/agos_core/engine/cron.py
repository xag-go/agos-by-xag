"""Automations run by the workspace's own Hermes cron (ADR 0010, step 5).

Hermes's job is the one place for an automation's timing: its schedule, on/off
(paused), next and last run, last result, and its runs (executions and output
files). Its scheduler fires it, never runs it twice, catches up after downtime
and pauses while an account limit is hit. AGOS keeps only what Hermes has no
place for (who does it, team steps, webhook, "check with me first", the link to
the job). A one-agent job's prompt is the one copy of its instructions (what
`hermes cron edit --prompt` changes); a Kanban automation's instructions live in
its readable `.md` file (no Hermes job holds them).

A Kanban automation (team steps, "check with me first", a webhook) has a no-agent
job: Hermes runs a script AGOS wrote (engine/automation_run.py with the
automation's plan), which puts the run's cards on the board with Hermes's own
Kanban CLI. Its webhook route runs the same script per delivery.

Writes are Hermes's own CLI in the profile's home (`hermes cron create|edit|
resume|remove|run`); a one-agent Run now is its API (`POST /api/jobs/{id}/run`
on the root's gateway). Three things have no public form in Hermes v0.22.2, so
the bridge calls Hermes's `cron.jobs` inside the profile (the scheduler's own
lock): a pause with AGOS's reason (`hermes cron pause` and `/api/jobs/{id}/pause`
take none: hermes_cli/subcommands/cron.py, gateway/platforms/api_server.py), a
job with its executions (`cron list`/`cron runs` print text only, no --json),
and a schedule check (`parse_schedule`, no CLI). Reads of the job's state come
straight from the profile's `cron/jobs.json` (read-only, no Hermes process); a
run's report is read from the job's output files.
"""

from __future__ import annotations

import builtins
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

JOB_PREFIX = "agos-automation-"
# Why AGOS paused a job (Hermes keeps it as the job's paused_reason). An archived
# workspace's job is not "off": it comes back when the workspace is restored.
OFF_REASON = "Turned off in AGOS"
ARCHIVED_REASON = "Workspace archived in AGOS"
# The owner's account pause is Hermes's own `hermes pause` since Step 33; this
# reason is the sentinel's prefix, and the mark of jobs the OLD pause held
# (account_pause.move_old_pause resumes those once, at start).
PAUSE_REASON = "Account pause in AGOS"
# Off-hours (actions/work_hours.py): held from check-out to check-in, still "on".
WORK_HOURS_REASON = "Off-hours in AGOS (work hours)"
AGOS_REASONS = (OFF_REASON, ARCHIVED_REASON, PAUSE_REASON, WORK_HOURS_REASON, "Paused by AGOS")
# Paused by AGOS for a while (archive, account pause, off-hours): the owner's job is on.
HELD_REASONS = (ARCHIVED_REASON, PAUSE_REASON, WORK_HOURS_REASON)
# Hermes delivers a failed run's notice there (agos-guard's platform: its home chat
# is the Co-Founder chat), not only into the job's output.
FAILURES_TO = "agos"

_BRIDGE = r"""
import json, sys
from pathlib import Path
request = json.loads(sys.stdin.read())
from cron import jobs as J
from cron import executions as E

def view(job):
    if job is None:
        return None
    out_dir = J.get_cron_output_dir() / job["id"]
    files = sorted(out_dir.glob("*.md")) if out_dir.is_dir() else []
    outputs = [{"name": p.name, "mtime": p.stat().st_mtime, "text": p.read_text(errors="replace")[-20000:]}
               for p in files[-20:]]
    runs = [
        {k: r.get(k) for k in ("id", "status", "source", "claimed_at", "started_at", "finished_at", "error")}
        for r in E.list_executions(job_id=job["id"], limit=20)
    ]
    return {
        "id": job["id"], "name": job.get("name"), "enabled": bool(job.get("enabled")),
        "state": J.effective_job_state(job), "next_run_at": job.get("next_run_at"),
        "last_run_at": job.get("last_run_at"), "last_status": job.get("last_status"),
        "last_error": job.get("last_error"), "paused_reason": job.get("paused_reason"),
        "model": job.get("model"), "provider": job.get("provider"),
        "reasoning_effort": job.get("reasoning_effort"), "prompt": job.get("prompt"),
        "skills": list(job.get("skills") or []),
        "schedule": job.get("schedule_display"), "outputs": outputs, "runs": runs,
    }

op = request["op"]
if op == "get":
    result = view(J.get_job(request["id"]))
elif op == "pause":
    J.pause_job(request["id"], reason=request.get("reason") or "Paused by AGOS")
    result = view(J.get_job(request["id"]))
elif op == "slots":
    # A missed run (actions/catch_up.py): each job's latest occurrence after `after`
    # and at or before `now`, by the engine's own schedule math (compute_next_run: its
    # timezone, its cron and interval forms), and the engine's own grace for it.
    from datetime import datetime, timedelta
    now = datetime.fromisoformat(request["now"])
    result = {}
    for item in request["jobs"]:
        sched = item["schedule"]
        at = datetime.fromisoformat(item["after"])
        period = J._schedule_cadence_seconds(sched)
        if period and sched.get("kind") == "interval":
            # Its occurrences are its last run plus whole periods: jump whole ones.
            skip = int((now - at).total_seconds() // period) - 1
            at += timedelta(seconds=period * max(skip, 0))
        elif period:
            at = max(at, now - timedelta(seconds=1.5 * period + 60))
        latest, base = None, at.isoformat()
        for _ in range(2000):
            following = J.compute_next_run(sched, base)
            if not following or datetime.fromisoformat(following) > now:
                break
            latest = base = following
        result[item["id"]] = {"slot": latest, "grace": J._compute_grace_seconds(sched)}
elif op == "check":
    try:
        parsed = J.parse_schedule(request["schedule"])
        result = {"kind": parsed["kind"], "display": parsed.get("display")}
    except ValueError as error:
        result = {"error": str(error).splitlines()[0]}
else:
    raise SystemExit("unknown op")
print("AGOS-JSON " + json.dumps(result))
"""


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class CronError(RuntimeError):
    """Hermes's cron refused or failed; the message is safe to show."""


@dataclass(frozen=True)
class JobSpec:
    name: str
    prompt: str
    schedule: str
    model: str
    provider: str
    reasoning_effort: str | None
    enabled: bool
    # A job with a script runs it and nothing else (Hermes's no-agent job, no tokens).
    script: str | None = None
    # Where Hermes tells a failed run (its own failure notice): the AGOS platform's
    # home chat, the workspace's Co-Founder chat.
    failure_deliver: str | None = FAILURES_TO
    # The skills Hermes loads into each run (the job's own `skills`, cron/jobs.py
    # create_job). Cron leaves `skills.auto_load` out (cron/scheduler.py builds its
    # agent with skip_context_files), so a member's pinned skills ride on its jobs.
    skills: tuple[str, ...] = ()
    # Hermes's monitor mode (cron/monitor.py): this script of the profile runs first,
    # and the agent runs only when its output changed since the last run that woke
    # it (an unchanged tick costs no model call). A status card's job (step 55).
    monitor_script: str | None = None
    # Where Hermes delivers a run's final answer: "local" (kept in the job's output
    # only) for AGOS's jobs, FAILURES_TO for one whose answer is a note to the owner
    # in the Co-Founder chat (the post-hire review, actions/hire_review.py).
    deliver: str = "local"

    def as_dict(self) -> dict[str, Any]:
        return {
            "monitor_script": self.monitor_script,
            "script": self.script,
            "name": self.name,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "model": self.model,
            "provider": self.provider,
            "reasoning_effort": self.reasoning_effort,
            "enabled": self.enabled,
            "failure_deliver": self.failure_deliver,
            "skills": list(self.skills),
            "deliver": self.deliver,
        }


class CronBridge:
    """One call = one short Hermes process in the workspace's profile."""

    def __init__(
        self,
        engine: EngineConfig,
        python: str,
        wall: Callable[[Path], builtins.list[str]] | None = None,
        script_python: builtins.list[str] | None = None,
    ) -> None:
        self.engine = engine
        # The root's Landlock wall (engine/hermes.py walled_for_home): a run now
        # executes the root's own scripts and plugins, which its walled gateway
        # can write, so it runs behind the same wall as the gateway's scheduler.
        self.wall = wall
        self.python = python
        # What runs a script behind the wall: Hermes's own runtime command
        # (engine/models.py hermes_runtime_argv), not AGOS's launcher file, which
        # lives outside what the wall opens.
        self.script_python = list(script_python) if script_python else [python]

    def _call(self, profile_home: Path, request: dict[str, Any], timeout: float = 60) -> Any:
        env = {
            "HOME": str(self.engine.host_home),
            "HERMES_HOME": str(profile_home),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            **self.engine.runtime_env(),
        }
        off_loop("hermes cron bridge")
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell, JSON on stdin
            [self.python, "-c", _BRIDGE],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=env,
            check=False,
            cwd=str(Path(self.python).parent.parent.parent),
        )
        hermes_contract.ran(result)
        lines = [ln for ln in (result.stdout or "").splitlines() if ln.startswith("AGOS-JSON ")]
        if result.returncode != 0 or not lines:
            tail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
            raise CronError(tail[0][:300])
        return json.loads(lines[-1][len("AGOS-JSON ") :])

    def get(self, home: Path, job_id: str) -> dict[str, Any] | None:
        """The job with its executions and outputs (`hermes cron list`/`runs` print
        text only: hermes_cli/subcommands/cron.py has no --json)."""
        found = self._call(home, {"op": "get", "id": job_id})
        return dict(found) if found else None

    def job_states(self, home: Path) -> builtins.list[dict[str, Any]]:
        """The profile's jobs as Hermes saved them (read-only, no Hermes process)."""
        return read_jobs(home)

    def _cli(self, home: Path, *args: str, timeout: float = 120) -> str:
        """`hermes cron ...` in the profile's home; Hermes's refusal is raised."""
        env = {
            "HOME": str(self.engine.host_home),
            "HERMES_HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            **self.engine.runtime_env(),
        }
        try:
            off_loop("hermes cron")
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [self.engine.hermes_bin, "cron", *args],
                capture_output=True,
                text=True,
                timeout=hermes_wait(timeout),
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CronError(str(error)[:300]) from error
        said = _ANSI.sub("", done.stdout or "")
        refused = [ln.strip() for ln in said.splitlines() if ln.strip().startswith("Failed to")]
        if done.returncode != 0 or refused:
            tail = refused or [ln for ln in (done.stderr or said).strip().splitlines()[-1:]]
            raise CronError((tail or ["The scheduler didn't answer"])[0][:300])
        return said

    def create(self, home: Path, spec: JobSpec) -> dict[str, Any]:
        """`hermes cron create`: Hermes's own checks (its prompt scan, the script's
        place, the schedule) and its scheduler registration."""
        args = [f"--name={spec.name}", f"--deliver={spec.deliver}"]
        args += [f"--model={spec.model}"] if spec.model else []
        args += [f"--provider={spec.provider}"] if spec.provider else []
        args += [f"--reasoning-effort={spec.reasoning_effort}"] if spec.reasoning_effort else []
        args += [f"--failure-deliver={spec.failure_deliver}"] if spec.failure_deliver else []
        args += [f"--skill={s}" for s in spec.skills]
        args += [f"--script={spec.script}", "--no-agent"] if spec.script else []
        args += [f"--monitor-script={spec.monitor_script}"] if spec.monitor_script else []
        args += [] if spec.enabled else ["--paused", f"--paused-reason={OFF_REASON}"]
        said = self._cli(
            home, "create", *args, "--", spec.schedule, *([spec.prompt] if spec.prompt else [])
        )
        found = re.search(r"Created job: (\S+)", said)
        if found is None:
            raise CronError("The scheduler made no job")
        return {"id": found.group(1)}

    def update(self, home: Path, job_id: str, spec: JobSpec) -> dict[str, Any] | None:
        """`hermes cron edit` (every field AGOS sets), then on/off: `hermes cron
        resume`, or a pause with AGOS's reason (the CLI's pause takes none)."""
        args = [
            f"--name={spec.name}",
            f"--prompt={spec.prompt}",
            f"--schedule={spec.schedule}",
            f"--model={spec.model}",
            f"--provider={spec.provider}",
            f"--reasoning-effort={spec.reasoning_effort or ''}",
            f"--failure-deliver={spec.failure_deliver or ''}",
            f"--script={spec.script or ''}",
            "--no-agent" if spec.script else "--agent",
        ]
        args += [f"--monitor-script={spec.monitor_script}"] if spec.monitor_script else []
        args += [f"--skill={s}" for s in spec.skills] if spec.skills else ["--clear-skills"]
        self._cli(home, "edit", job_id, *args)
        now = next((j for j in read_jobs(home) if j["id"] == job_id), None)
        if now is None:
            raise CronError(f"The scheduler has no job {job_id}")
        if spec.enabled:
            if not now["enabled"] and now.get("paused_reason") != WORK_HOURS_REASON:
                self.resume(home, job_id)  # off-hours keep it held until check-in
        elif now["enabled"] or now.get("paused_reason") in HELD_REASONS:
            # Turned off by the owner. A job paused by Hermes itself keeps its reason;
            # one AGOS only held for a while (archive, account pause) is now off for good.
            self.pause(home, job_id, OFF_REASON)
        return next((j for j in read_jobs(home) if j["id"] == job_id), None)

    def pause(self, home: Path, job_id: str, reason: str) -> None:
        """Paused with AGOS's reason (why: archived, account pause, off): neither
        `hermes cron pause` nor /api/jobs/{id}/pause takes a reason, so Hermes's own
        cron.jobs.pause_job does it, under the scheduler's lock."""
        self._call(home, {"op": "pause", "id": job_id, "reason": reason})

    def resume(self, home: Path, job_id: str) -> None:
        self._cli(home, "resume", job_id)

    def remove(self, home: Path, job_id: str) -> None:
        self._cli(home, "remove", job_id)

    def run_now(self, home: Path, job_id: str, *, prompt: str | None = None) -> None:
        """Fires on the gateway's next tick: Hermes's API `POST /api/jobs/{id}/run`
        on the root's gateway (a member's job under `/p/<member>/`, the profile's
        own cron store; gateway/platforms/api_server.py _handle_run_job). `prompt`:
        Hermes's one-time context for that run only (cron.jobs.trigger_job
        manual_run_prompt), e.g. the work hours' check-in."""
        import urllib.error
        import urllib.request

        from agos_core.engine.config_file import read_env

        # The root's gateway serves every member; a member's routes take that
        # member's own key (its .env: the profile-scoped API_SERVER_KEY).
        root = home.parent.parent if home.parent.name == "profiles" else home
        port, key = (
            read_env(root).get("API_SERVER_PORT", ""),
            read_env(home).get("API_SERVER_KEY", ""),
        )
        if not port.isdigit() or not key:
            raise CronError("this workspace's engine is not set up yet")
        prefix = f"/p/{home.name}" if root != home else ""
        request = urllib.request.Request(
            f"http://127.0.0.1:{int(port)}{prefix}/api/jobs/{job_id}/run",
            data=json.dumps({"prompt": prompt} if prompt else {}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        off_loop("hermes cron run now")
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:  # noqa: S310
                reply.read()
        except urllib.error.HTTPError as error:
            said = error.read()[:300].decode(errors="replace")
            raise CronError(f"The engine refused the run ({error.code}): {said}") from error
        except OSError as error:
            raise CronError(f"the workspace's gateway didn't answer: {error}") from error

    def _wall(self, home: Path) -> builtins.list[str]:
        return self.wall(home) if self.wall is not None else []

    def run_inline(self, home: Path, job_id: str, timeout: float = 300) -> tuple[bool, str]:
        """Runs the job once now with Hermes's `hermes cron run <id>` (it claims the
        fire, runs it and records the run as the scheduler does: tools/cronjob_tools.py
        _action_run). For a no-agent job: (it succeeded, what its script said)."""
        env = {
            "HOME": str(self.engine.host_home),
            "HERMES_HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            **self.engine.runtime_env(),
        }
        try:
            off_loop("hermes cron run")
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [*self._wall(home), self.engine.hermes_bin, "cron", "run", job_id],
                capture_output=True,
                text=True,
                timeout=hermes_wait(timeout),
                env=env,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CronError(str(error)[:300]) from error
        lines = [ln.strip() for ln in (done.stdout or "").splitlines() if ln.strip()]
        verdict = next((ln for ln in lines if ln.startswith("Ran now:")), "")
        if done.returncode != 0 or not verdict:
            raise CronError((lines[-1:] or [(done.stderr or "no answer").strip()[-300:]])[0][:300])
        return verdict == "Ran now: succeeded.", _last_output(home, job_id).split("\n---\n", 1)[
            -1
        ].strip()

    def slots(
        self, home: Path, jobs: builtins.list[dict[str, Any]], now: str
    ) -> dict[str, dict[str, Any]]:
        """Each job's latest occurrence in (after, now] and Hermes's grace for it, by
        Hermes's own schedule math (cron/jobs.py compute_next_run,
        _compute_grace_seconds), in one Hermes process for the profile. `jobs`:
        {"id", "schedule" (Hermes's dict), "after" (ISO)}."""
        if not jobs:
            return {}
        found = self._call(home, {"op": "slots", "jobs": jobs, "now": now}, timeout=120)
        return dict(found) if isinstance(found, dict) else {}

    def check_schedule(self, home: Path, schedule: str) -> str | None:
        """Why Hermes's own parser refuses the schedule (cron/jobs.py
        parse_schedule: cron, "30m", "every monday 9am", a time), or None. An
        automation repeats: a one-off time is refused too."""
        found = self._call(home, {"op": "check", "schedule": schedule}, timeout=120)
        return schedule_problem(found)

    def describe_schedule(self, home: Path, schedule: str) -> tuple[str | None, str | None]:
        """Hermes's own words for a schedule (parse_schedule's `display`, what it
        saves as the job's schedule_display) and why it refuses it, if it does."""
        found = self._call(home, {"op": "check", "schedule": schedule}, timeout=120)
        problem = schedule_problem(found)
        display = found.get("display") if isinstance(found, dict) else None
        return (str(display) if display and not problem else None), problem

    def run_script(
        self,
        home: Path,
        name: str,
        args: builtins.list[str],
        stdin: str = "",
        timeout: float = 300,
    ) -> tuple[int, str]:
        """Runs one of the profile's scripts once, in Hermes's runtime and home (an
        automation's Run now): its exit code and what it said."""
        script = home / "scripts" / name
        if not script.is_file():
            raise CronError(f"its script {name} is missing; save the automation again")
        env = {
            "HOME": str(self.engine.host_home),
            "HERMES_HOME": str(home),
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            **self.engine.runtime_env(),
        }
        try:
            off_loop("hermes cron script")
            done = subprocess.run(  # noqa: S603 - fixed argv, no shell
                [*self._wall(home), *self.script_python, str(script), *args],
                capture_output=True,
                text=True,
                timeout=hermes_wait(timeout),
                env=env,
                check=False,
                cwd=str(script.parent),
                input=stdin,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise CronError(str(error)[:300]) from error
        said = (done.stdout or "").strip() or (done.stderr or "").strip()
        return done.returncode, said[-2000:]


def schedule_problem(found: Any) -> str | None:
    """Hermes's answer to a schedule check, as AGOS tells it (None: fine)."""
    if not isinstance(found, dict):
        return "The engine didn't answer"
    if found.get("error"):
        return str(found["error"]).rstrip(".")
    if found.get("kind") == "once":
        return "an automation repeats: give a cron, an interval (30m) or a day and time"
    return None


# ---- reading Hermes's jobs (read-only) ---------------------------------------------


def _schedule_text(job: dict[str, Any]) -> str:
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return str(schedule.get("expr") or schedule.get("display") or "")
    return str(schedule or job.get("schedule_display") or "")


def _last_output(home: Path, job_id: str) -> str:
    """The newest output file Hermes saved for the job (its file names are timestamps)."""
    folder = home / "cron" / "output" / job_id
    try:
        files = sorted(folder.glob("*.md")) if folder.is_dir() else []
        return files[-1].read_text(errors="replace")[-20_000:] if files else ""
    except OSError:
        return ""


def job_state(home: Path, job: dict[str, Any]) -> dict[str, Any]:
    """What AGOS shows of a Hermes job: its timing, on/off and last run."""
    job_id = str(job["id"])
    enabled = bool(job.get("enabled", True))
    return {
        "id": job_id,
        "name": job.get("name"),
        "schedule": _schedule_text(job),
        # Hermes's own words for it and its own job state (scheduled / paused /
        # completed / error: cron/jobs.py), shown as they are.
        "schedule_display": str(job.get("schedule_display") or "") or None,
        "state": str(job.get("state") or "") or None,
        "enabled": enabled,
        "paused_reason": None if enabled else job.get("paused_reason"),
        "next_run_at": job.get("next_run_at") if enabled else None,
        "last_run_at": job.get("last_run_at"),
        "last_status": job.get("last_status"),
        "last_error": job.get("last_error"),
        "last_output": _last_output(home, job_id) if job.get("last_run_at") else "",
        "prompt": str(job.get("prompt") or ""),
        "script": str(job.get("script") or ""),
        "skills": job_skills(job),
        # What a missed run is told from (actions/catch_up.py): the schedule as Hermes
        # keeps it, when the job was made, the occurrence its last dispatch was for
        # (cron/jobs.py last_dispatch), a Run now still queued (trigger_job stamps
        # manual_run_at = next_run_at) and a run in flight (its fire claim, heartbeated:
        # older than Hermes's FIRE_CLAIM_TTL_SECONDS it is a dead run's).
        "schedule_spec": job.get("schedule") if isinstance(job.get("schedule"), dict) else None,
        "created_at": job.get("created_at"),
        "dispatched_for": (job.get("last_dispatch") or {}).get("scheduled_at")
        if isinstance(job.get("last_dispatch"), dict)
        else None,
        # ...and when Hermes's scheduler started it (the S4 SLI, actions/slis.py).
        "dispatched_at": (job.get("last_dispatch") or {}).get("dispatched_at")
        if isinstance(job.get("last_dispatch"), dict)
        else None,
        "run_queued": bool(job.get("manual_run_at"))
        and job.get("manual_run_at") == job.get("next_run_at"),
        "claimed_at": (job.get("fire_claim") or {}).get("at")
        if isinstance(job.get("fire_claim"), dict)
        else None,
        # A monitor job's last change Hermes saw (cron/monitor.py monitor_state).
        "monitor_changed_at": (job.get("monitor_state") or {}).get("last_changed_at")
        if isinstance(job.get("monitor_state"), dict)
        else None,
    }


def job_skills(job: dict[str, Any]) -> list[str]:
    """The skills a Hermes job loads (its `skills`, or the old single `skill`),
    as cron/scheduler_prompt.py _job_skill_names reads them."""
    skills = job.get("skills")
    if skills is None:
        skills = [job["skill"]] if job.get("skill") else []
    elif isinstance(skills, str):
        skills = [skills]
    return [str(s).strip() for s in skills if str(s).strip()]


def read_jobs(home: Path) -> list[dict[str, Any]]:
    """The profile's `cron/jobs.json`, read-only. Raises CronError when it can't
    be read (then nothing is known, which is not the same as "no jobs")."""
    path = home / "cron" / "jobs.json"
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8-sig")
        try:
            data = json.loads(raw)
        except ValueError:
            data = json.loads(raw, strict=False)
    except (OSError, ValueError) as error:
        raise CronError(f"The scheduler's jobs can't be read: {error}") from error
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if isinstance(jobs, dict):
        jobs = [{**v, "id": v.get("id") or k} for k, v in jobs.items() if isinstance(v, dict)]
    return [job_state(home, j) for j in jobs or [] if isinstance(j, dict) and j.get("id")]


# ---- a Kanban automation's run: Hermes runs it -------------------------------------

RUN_SCRIPT = Path(__file__).with_name("automation_run.py")


def fire_script_name(automation_id: int) -> str:
    """The script its cron job runs (and Run now)."""
    return f"{JOB_PREFIX}{automation_id}.py"


def hook_script_name(automation_id: int) -> str:
    """The script its webhook route runs for each delivery."""
    return f"agos-hook-{automation_id}.py"


def run_script_text(plan: dict[str, Any]) -> str:
    """The run's code (engine/automation_run.py) with its plan."""
    return (
        RUN_SCRIPT.read_text()
        + "\n\n# ---- written by AGOS ----\n"
        + f"PLAN = json.loads({json.dumps(json.dumps(plan, ensure_ascii=False, sort_keys=True))})\n"
        + 'if __name__ == "__main__":\n'
        + "    sys.exit(main(sys.argv[1:], sys.stdin.read() if PLAN.get('mode') == 'webhook' "
        + "or sys.argv[1:2] == ['manual'] else ''))\n"
    )


def write_run_script(profile_home: Path, name: str, plan: dict[str, Any]) -> bool:
    """Writes the script Hermes runs into the profile's scripts folder (only when
    it changed). True when it was (re)written."""
    scripts = profile_home / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    path = scripts / name
    text = run_script_text(plan)
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


# ---- the prompt ------------------------------------------------------------------


def automation_prompt(instructions: str, tail: str = "") -> str:
    """The Hermes job's own prompt: what to do. Its name is the job's own `name` (the
    one copy of it, shown by Hermes in its outputs and notices); who the agent is and
    the rules for scheduled automations are in its SOUL.md (Hermes's cron reads it).
    `tail`: the variables block (actions/automation_variables.py prompt_tail), which
    instructions_of strips again."""
    return f"{PROMPT_HEAD}{instructions.strip()}{tail}"


PROMPT_HEAD = "This is one of your scheduled automations.\n\n"
# The variables block at the end of a one-agent job's prompt (its defaults).
_PROMPT_VARS = re.compile(
    r"\n\n## Variables\nWhere the text above says \{name\}, use the value below\.\n(?:- .*\n?)*\Z"
)
# The first line automation_prompt writes (and the ones it wrote before: with the
# automation's name, and with the path of the readable copy AGOS kept then).
_PROMPT_HEAD = re.compile(
    r"\A(?:This is one of your scheduled automations\.|This is the scheduled automation "
    r"\*\*.*?\*\*(?: \(its readable copy is `[^`]*`\))?\.)\n\n",
    re.S,
)


def legacy_job_name(automation_id: int) -> str:
    """The name AGOS gave an automation's job before the job held the owner's name
    (found again by it, then renamed by the next sync)."""
    return f"{JOB_PREFIX}{automation_id}"


def instructions_of(prompt: str) -> str:
    """The instructions in a one-agent job's prompt (the prompt as it is, when it
    was changed in Hermes without AGOS's first line)."""
    return _PROMPT_VARS.sub("", _PROMPT_HEAD.sub("", prompt, count=1), count=1).strip()


# ---- reading results ---------------------------------------------------------------


@dataclass(frozen=True)
class FinishedRun:
    id: str
    ok: bool
    source: str
    started_at: str
    finished_at: str | None
    output: str
    error: str | None


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def finished_runs(job: dict[str, Any]) -> list[FinishedRun]:
    """Hermes's finished executions of a job, each with the output file it wrote
    (the first one saved after the run started, not already used), oldest first."""
    outputs = sorted(job.get("outputs") or [], key=lambda o: float(o.get("mtime") or 0))
    used: set[str] = set()
    result = []
    for run in sorted(job.get("runs") or [], key=lambda r: str(r.get("claimed_at") or "")):
        status = str(run.get("status") or "")
        if status not in ("completed", "failed"):
            continue
        start = _epoch(run.get("started_at") or run.get("claimed_at")) or 0.0
        end = _epoch(run.get("finished_at"))
        text = ""
        for out in outputs:
            mtime = float(out.get("mtime") or 0)
            if out["name"] in used or mtime + 2 < start:
                continue
            if end is not None and mtime > end + 120:
                break
            used.add(out["name"])
            text = str(out.get("text") or "")
            break
        result.append(
            FinishedRun(
                id=str(run["id"]),
                ok=status == "completed",
                source=str(run.get("source") or ""),
                started_at=str(run.get("started_at") or run.get("claimed_at") or ""),
                finished_at=run.get("finished_at"),
                output=text,
                error=(str(run["error"])[:500] if run.get("error") else None),
            )
        )
    return result


def report_text(output: str) -> str:
    """The agent's answer from Hermes's saved output file (it adds a header and
    the prompt before the response)."""
    marker = "## Response"
    if marker in output:
        return output.rsplit(marker, 1)[1].strip()
    # A failed run's file: "# Cron Job: …\n\nError: …" — keep the error line.
    lines = [ln for ln in output.strip().splitlines() if not ln.startswith("# Cron Job:")]
    return "\n".join(lines).strip()
