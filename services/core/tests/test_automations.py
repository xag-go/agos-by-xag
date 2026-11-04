"""Automations run by the workspace's Hermes cron (fake bridge; live test apart)."""

import builtins
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_engine_sync import FakeRunner

from agos_core.actions import automations as actions
from agos_core.api.app import create_app
from agos_core.config import EngineConfig, Settings
from agos_core.engine.cron import JobSpec, finished_runs, report_text
from agos_core.engine.cron import automation_prompt as cron_prompt

MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "high"}


class FakeCron:
    """Hermes's cron in every profile home (each job is in one home's cron)."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.fired: list[str] = []
        self.ran_inline: list[str] = []  # `hermes cron run` (Run now of a team automation)
        self.down = False
        self.n = 0
        self.runner: Any = None  # the fake Hermes (its Kanban) the scripts run against

    def _check(self) -> None:
        if self.down:
            from agos_core.engine.cron import CronError

            raise CronError("scheduler unreachable")

    def _in(self, home: Path, job_id: str) -> dict[str, Any]:
        """The job, only from that home's cron (Hermes's cron is per profile)."""
        job = self.jobs.get(job_id)
        if job is None or job["home"] != str(home):
            from agos_core.engine.cron import CronError

            raise CronError(f"no job {job_id} in {home}")
        return job

    def job_states(self, home: Path) -> list[dict[str, Any]]:
        """What CronBridge.jobs reads from jobs.json (job_state's shape)."""
        self._check()
        out = []
        for j in self.jobs.values():
            if j["home"] != str(home):
                continue
            runs = j["runs"]
            last = runs[-1] if runs else None
            out.append(
                {
                    "id": j["id"],
                    "name": j["spec"].name,
                    "schedule": j["spec"].schedule,
                    "enabled": j["enabled"],
                    "paused_reason": None if j["enabled"] else j.get("paused_reason"),
                    "next_run_at": j["next_run_at"] if j["enabled"] else None,
                    "last_run_at": last["claimed_at"] if last else None,
                    "last_status": (
                        None if not last else "ok" if last["status"] == "completed" else "error"
                    ),
                    "last_error": last["error"] if last else None,
                    "last_output": j["outputs"][-1]["text"] if j["outputs"] else "",
                    "model": j["spec"].model,
                    "provider": j["spec"].provider,
                    "reasoning_effort": j["spec"].reasoning_effort,
                    "prompt": j["spec"].prompt,
                    "script": j["spec"].script or "",
                    "skills": list(j["spec"].skills),
                }
            )
        return out

    def list(self, home: Path) -> list[dict[str, Any]]:
        self._check()
        return [j for j in self.jobs.values() if j["home"] == str(home)]

    def get(self, home: Path, job_id: str) -> dict[str, Any] | None:
        self._check()
        job = self.jobs.get(job_id)
        return job if job is not None and job["home"] == str(home) else None

    def create(self, home: Path, spec: JobSpec) -> dict[str, Any]:
        self._check()
        self.n += 1
        job: dict[str, Any] = {
            "id": f"job{self.n}",
            "spec": spec,
            "enabled": spec.enabled,
            "paused_reason": None if spec.enabled else "Turned off in AGOS",
            "home": str(home),
            "next_run_at": "2026-09-28T09:00:00+00:00",
            "runs": [],
            "outputs": [],
        }
        self.jobs[job["id"]] = job
        return job

    def update(self, home: Path, job_id: str, spec: JobSpec) -> dict[str, Any]:
        self._check()
        job = self._in(home, job_id)
        held = ("Workspace archived in AGOS", "Account pause in AGOS")
        if spec.enabled:
            job.update(enabled=True, paused_reason=None)
        elif job["enabled"] or job.get("paused_reason") in held:
            job.update(enabled=False, paused_reason="Turned off in AGOS")
        job.update(spec=spec)
        return job

    def check_schedule(self, home: Path, schedule: str) -> str | None:
        """Hermes's parse_schedule, as far as these tests need it (the real one is
        checked in test_cron_schedule_is_checked_by_hermess_own_parser)."""
        self._check()
        text = schedule.strip()
        fields = text.split()
        if len(fields) == 5 and all(re.fullmatch(r"[\d*,/-]+", f) for f in fields):
            return None
        if re.fullmatch(r"(every )?\d+[mhd]|every \w+ \d{1,2}(am|pm)", text):
            return None
        return f"Invalid schedule '{text}'"

    def pause(self, home: Path, job_id: str, reason: str) -> None:
        self._in(home, job_id).update(enabled=False, paused_reason=reason)

    def resume(self, home: Path, job_id: str) -> None:
        self._in(home, job_id).update(enabled=True, paused_reason=None)

    def run_now(self, home: Path, job_id: str) -> None:
        self._check()
        self._in(home, job_id)
        self.fired.append(job_id)

    def remove(self, home: Path, job_id: str) -> None:
        if self.get(home, job_id) is not None:
            self.jobs.pop(job_id)

    def run_script(
        self, home: Path, name: str, args: "builtins.list[str]", stdin: str = ""
    ) -> tuple[int, str]:
        """Hermes runs one of the profile's scripts (an automation's run)."""
        import hermes_script

        self._check()
        return hermes_script.run(home / "scripts" / name, self.runner, args, stdin)

    def run_inline(self, home: Path, job_id: str) -> tuple[bool, str]:
        """`hermes cron run <id>`: Hermes runs the job once now and records it (its
        no-agent script; a paused job is refused)."""
        import hermes_script

        from agos_core.engine.cron import CronError

        self._check()
        job = self._in(home, job_id)
        if not job["enabled"]:
            raise CronError("Job is paused/disabled; resume it before running.")
        self.ran_inline.append(job_id)
        code, said = hermes_script.run(home / "scripts" / str(job["spec"].script), self.runner, [])
        return code == 0, said

    def fire(self, home: Path, name: str) -> tuple[int, str]:
        """The job's time came: Hermes's scheduler runs its script (no agent)."""
        import hermes_script

        return hermes_script.run(home / "scripts" / name, self.runner, [])

    def finish(self, job_id: str, run_id: str, ok: bool, text: str, at: float) -> None:
        from datetime import datetime

        claimed = f"2026-09-25T10:00:{int(at) % 60:02d}+00:00"
        mtime = datetime.fromisoformat(claimed).timestamp() + 5
        self.jobs[job_id]["runs"].append(
            {
                "id": run_id,
                "status": "completed" if ok else "failed",
                "source": "scheduler",
                "claimed_at": claimed,
                "started_at": None,
                "finished_at": None,
                "error": None if ok else "model refused",
            }
        )
        self.jobs[job_id]["outputs"].append({"name": f"{run_id}.md", "mtime": mtime, "text": text})


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[TestClient, Any, FakeCron, str]]:
    hermes_home = tmp_path / "home" / ".hermes"
    hermes_home.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
        engine=EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=hermes_home,
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path / "home",
            roots_dir=tmp_path / "data" / "hermes",
        ),
    )
    app = create_app(settings, background=False)
    with TestClient(app) as client:
        core = app.state.core
        core.engine.runner = FakeRunner(hermes_home)
        started: list[str] = []
        core.engine.start = lambda workspace_id, **_: started.append(workspace_id)
        core.engine.is_running = lambda workspace_id: False
        core.engine.stop = lambda workspace_id, **_: None
        cron = FakeCron()
        cron.runner = core.engine.runner
        core.engine.cron_bridge = cron
        core.engine.started = started
        client.headers["x-agos-internal"] = settings.internal_token_file.read_text()
        ws = client.post("/workspaces", json={"name": "Argan", "defaultModel": MODEL}).json()["id"]
        yield client, core, cron, ws


def new(client: TestClient, ws: str, **extra: Any) -> int:
    body = {
        "name": "Daily brief",
        "instructions": "Summarize new files.",
        "schedule": "0 9 * * *",
        "model": MODEL,
        "on": True,
        **extra,
    }
    r = client.post(f"/workspaces/{ws}/automations", json=body)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_saving_creates_a_hermes_job_with_model_effort_and_schedule(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    (job,) = cron.jobs.values()
    spec: JobSpec = job["spec"]
    # The owner's name is the job's own name (the one copy: AGOS's row lets it go).
    assert spec.name == "Daily brief" and spec.schedule == "0 9 * * *"
    row = core.db.execute("SELECT name FROM automations WHERE id = ?", (aid,)).fetchone()
    assert row["name"] == ""
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["name"] == "Daily brief"
    assert "Daily brief" not in spec.prompt
    assert spec.model == "claude-sonnet-5" and spec.provider == "anthropic"
    assert spec.reasoning_effort == "high" and spec.enabled
    assert "Summarize new files." in spec.prompt
    # The rules for automations are in SOUL.md (Hermes's cron reads it), not the job.
    from agos_core.engine.identity import RULES

    assert "Never start" not in spec.prompt and "Never start" in RULES
    assert job["home"].endswith(f"hermes/agos-{ws}")
    # Hermes's systemd service keeps the gateway (the scheduler) up: AGOS's sync
    # never starts one, so a gateway stopped on purpose stays stopped.
    assert core.engine.started == []
    listed = client.get(f"/workspaces/{ws}/automations").json()[0]
    assert listed["problem"] is None


def test_sync_never_starts_a_gateway_under_systemd_only_under_spawn(env: Any) -> None:
    import dataclasses

    from agos_core.actions import automations

    client, core, _cron, ws = env
    assert core.engine.settings.gateway_supervisor == "systemd"
    aid = new(client, ws)
    automations.sync_job(core, ws, aid)  # the background keep_in_step pass
    assert core.engine.started == []
    core.engine.settings = dataclasses.replace(core.engine.settings, gateway_supervisor="spawn")
    automations.sync_job(core, ws, aid)
    assert core.engine.started == [ws]  # test-only spawn: nothing else restarts it


def test_edit_toggle_and_delete_follow_in_hermes(env: Any) -> None:
    client, _core, cron, ws = env
    aid = new(client, ws)
    body = {
        "name": "Weekly",
        "instructions": "Review.",
        "schedule": "0 9 * * 1",
        "model": MODEL | {"effort": "none"},
        "on": True,
    }
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code == 200
    (job,) = cron.jobs.values()
    assert job["spec"].schedule == "0 9 * * 1" and job["spec"].reasoning_effort == "none"
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    assert job["enabled"] is False and job["spec"].enabled is False
    assert client.delete(f"/workspaces/{ws}/automations/{aid}").status_code == 200
    assert cron.jobs == {}


def test_a_scheduler_problem_is_shown_never_silent(env: Any) -> None:
    client, _core, cron, ws = env
    cron.down = True
    aid = new(client, ws)
    listed = client.get(f"/workspaces/{ws}/automations").json()[0]
    assert listed["problem"].startswith("Not scheduled: scheduler unreachable")
    r = client.post(f"/workspaces/{ws}/automations/{aid}/run")
    assert r.status_code == 409
    cron.down = False
    assert client.post(f"/workspaces/{ws}/automations/{aid}/run").status_code == 202
    assert cron.fired == ["job1"]
    assert client.get(f"/workspaces/{ws}/automations").json()[0]["problem"] is None


def test_runs_are_read_live_from_hermes_and_agos_keeps_no_index(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    text = "# Cron Job: x\n\n## Prompt\n\nignored\n\n## Response\n\nTwo new invoices."
    cron.finish("job1", "run-a", True, text, 1)
    cron.finish("job1", "run-b", False, "# Cron Job: x\n\nError: model refused\n", 2)
    # Hermes no longer tells AGOS when a run ends: there is nothing to collect.
    from agos_core.actions import hermes_channel as channel

    good = {"authorization": f"Bearer {channel.bridge_key(core, ws)}"}
    assert client.post(f"/hermes-bridge/{ws}/cron-run", json={}, headers=good).status_code == 404
    runs = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    by_result = {r["result"]: r for r in runs}
    ok, failed = by_result["ok"], by_result["failed"]
    assert ok["report"] == "Two new invoices." and ok["source"] == "schedule"
    assert failed["error"] == "model refused"
    tables = {r[0] for r in core.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {"automation_runs", "automation_proposals", "automation_events"}
    listed = client.get(f"/workspaces/{ws}/automations").json()[0]
    assert listed["lastRun"]["result"] in ("ok", "failed")
    assert listed["nextRunAt"] == "2026-09-28T09:00:00+00:00"
    # A failed run: Hermes tells the Co-Founder chat itself (its failure notice).
    assert cron.jobs["job1"]["spec"].failure_deliver == "agos"


def test_archive_pauses_jobs_and_restore_resyncs(env: Any) -> None:
    client, _core, cron, ws = env
    new(client, ws)
    assert client.post(f"/workspaces/{ws}/archive").status_code < 300
    assert cron.jobs["job1"]["enabled"] is False
    assert client.post(f"/workspaces/{ws}/unarchive").status_code < 300
    assert cron.jobs["job1"]["enabled"] is True


def test_matching_outputs_to_runs() -> None:
    job = {
        "runs": [
            {
                "id": "b",
                "status": "completed",
                "claimed_at": "2026-09-25T10:05:00+00:00",
                "started_at": "2026-09-25T10:05:00+00:00",
                "finished_at": "2026-09-25T10:06:00+00:00",
            },
            {
                "id": "a",
                "status": "completed",
                "claimed_at": "2026-09-25T10:00:00+00:00",
                "started_at": "2026-09-25T10:00:00+00:00",
                "finished_at": "2026-09-25T10:01:00+00:00",
            },
            {"id": "c", "status": "running", "claimed_at": "2026-09-25T10:10:00+00:00"},
        ],
        "outputs": [
            {"name": "2.md", "mtime": 1790330730.0, "text": "## Response\n\nsecond"},
            {"name": "1.md", "mtime": 1790330430.0, "text": "## Response\n\nfirst"},
        ],
    }
    got = [(r.id, report_text(r.output)) for r in finished_runs(job)]
    assert got == [("a", "first"), ("b", "second")]
    assert report_text("# Cron Job: n\n\nError: boom\n") == "Error: boom"


# ---- Hermes's cron is the one place for the timing; the file for the instructions ----


def _row(core: Any, aid: int) -> Any:
    return core.db.execute("SELECT * FROM automations WHERE id = ?", (aid,)).fetchone()


def test_timing_is_read_live_from_hermes_and_agos_keeps_no_copy(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    row = _row(core, aid)
    # Hermes has the job: AGOS keeps no copy of its schedule, model or instructions.
    assert row["schedule"] == "" and row["model"] is None
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["model"]["model"] == MODEL["model"] and got["model"]["effort"] == "high"
    # The owner picks another model: it goes into the job, and AGOS forgets it again.
    body = {
        "name": got["name"],
        "instructions": got["instructions"],
        "schedule": got["schedule"],
        "model": {**MODEL, "model": "claude-opus-5", "effort": "low"},
        "on": got["on"],
    }
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code < 300
    job_spec = next(iter(cron.jobs.values()))["spec"]
    assert (job_spec.model, job_spec.reasoning_effort) == ("claude-opus-5", "low")
    assert _row(core, aid)["model"] is None
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["model"]["model"] == (
        "claude-opus-5"
    )
    assert "instructions" not in row.keys()  # noqa: SIM118 - the file holds them
    assert "next_run_at" not in row.keys()  # noqa: SIM118 - a Row's `in` checks values
    job = cron.jobs["job1"]
    # Changed in Hermes (its CLI, say): AGOS shows Hermes's values.
    job["spec"] = JobSpec(**{**job["spec"].as_dict(), "schedule": "30 7 * * 1"})
    job["next_run_at"] = "2026-10-12T07:30:00+00:00"
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["schedule"] == "30 7 * * 1" and got["nextRunAt"] == "2026-10-12T07:30:00+00:00"
    assert got["instructions"] == "Summarize new files." and got["on"] is True
    # Paused by Hermes itself: off, and the owner is told why.
    job.update(enabled=False, paused_reason="Auto-paused by scheduler: no model")
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["on"] is False and got["nextRunAt"] is None
    assert got["problem"] == "Paused by Hermes: Auto-paused by scheduler: no model"
    actions.keep_in_step(core)  # AGOS doesn't overwrite Hermes's reason
    assert job["paused_reason"] == "Auto-paused by scheduler: no model"
    # The last run is Hermes's.
    job.update(enabled=True, paused_reason=None)
    cron.finish("job1", "r1", True, "## Response\n\nAll quiet.\nNothing new.", 1)
    last = client.get(f"/workspaces/{ws}/automations").json()[0]["lastRun"]
    assert last["result"] == "ok" and last["summary"] == "All quiet."


def test_toggle_writes_only_into_hermes(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    job = cron.jobs["job1"]
    assert job["enabled"] is False and job["paused_reason"] == "Turned off in AGOS"
    assert job["spec"].schedule == "0 9 * * *"  # the schedule came from Hermes's job
    assert _row(core, aid)["schedule"] == ""
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["on"] is False and got["schedule"] == "0 9 * * *" and got["problem"] is None
    client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": True})
    assert job["enabled"] is True


def test_a_job_missing_in_hermes_asks_for_a_resave_and_is_never_guessed(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    cron.jobs.clear()  # removed in Hermes behind AGOS's back
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["problem"] == actions.MISSING and got["nextRunAt"] is None
    r = client.post(f"/workspaces/{ws}/automations/{aid}/toggle", json={"on": False})
    assert r.status_code == 409
    actions.keep_in_step(core)
    actions.resync_workspace(core, ws)
    assert cron.jobs == {} and _row(core, aid)["hermes_job_id"] == "job1"  # link kept
    # Saving it again schedules it again.
    body = {"name": "Daily brief", "instructions": "x", "schedule": "0 8 * * *", "model": MODEL}
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code == 200
    assert [j["spec"].schedule for j in cron.jobs.values()] == ["0 8 * * *"]
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["problem"] is None


def test_hermes_unreachable_keeps_the_request_until_hermes_takes_it(env: Any) -> None:
    client, core, cron, ws = env
    cron.down = True
    aid = new(client, ws)
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["schedule"] == "0 9 * * *" and got["problem"].startswith("Not scheduled")
    assert _row(core, aid)["schedule"] == "0 9 * * *"  # the request, until Hermes has it
    cron.down = False
    actions.keep_in_step(core)  # tried again
    assert [j["spec"].schedule for j in cron.jobs.values()] == ["0 9 * * *"]
    assert _row(core, aid)["schedule"] == ""
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["problem"] is None


def test_hermess_job_prompt_is_the_one_copy_of_the_instructions(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    assert not path.exists()  # Hermes's job holds them: AGOS keeps no file
    job = cron.jobs["job1"]
    assert job["spec"].prompt == cron_prompt("Summarize new files.")
    # Changed in Hermes (`hermes cron edit --prompt`, or the agent's cronjob tool):
    # that is the change. AGOS shows it and never writes it back.
    job["spec"] = JobSpec(**{**job["spec"].as_dict(), "prompt": "Summarize new mails."})
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["instructions"] == "Summarize new mails."
    calls = []
    cron.update = lambda *a: calls.append(a)
    actions.keep_in_step(core)
    assert calls == [] and not path.exists()
    # The owner edits them: into the job's prompt, still no file.
    del cron.update
    body = {
        "name": "Daily brief",
        "instructions": "Summarize new files and mails.",
        "schedule": "0 9 * * *",
        "model": MODEL,
        "on": True,
    }
    assert client.put(f"/workspaces/{ws}/automations/{aid}", json=body).status_code == 200
    assert job["spec"].prompt.endswith("\n\nSummarize new files and mails.")
    assert not path.exists()


def test_unchanged_instructions_hermes_holds_are_never_written_again(env: Any) -> None:
    """Hermes's prompt holds the instructions: a save that changes something else
    (and that Hermes refuses) leaves no second copy in a file."""
    client, core, cron, ws = env
    aid = new(client, ws)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    assert not path.exists()
    from agos_core.engine.cron import CronError

    def refused(*_: Any) -> None:
        raise CronError("Hermes refused it")

    cron.update = refused
    body = {"name": "Daily brief", "instructions": "Summarize new files.", "schedule": "0 8 * * *"}
    r = client.put(f"/workspaces/{ws}/automations/{aid}", json=body | {"model": MODEL})
    assert r.status_code == 200
    assert not path.exists()
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["instructions"] == "Summarize new files." and got["problem"]


def test_instructions_hermes_refused_wait_in_the_file_until_hermes_takes_them(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    cron.down = True
    body = {"name": "Daily brief", "instructions": "New text.", "schedule": "0 9 * * *"}
    r = client.put(f"/workspaces/{ws}/automations/{aid}", json=body | {"model": MODEL})
    assert r.status_code == 200
    assert "New text." in path.read_text()  # the owner's request, shown with the problem
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["instructions"] == "New text." and got["problem"].startswith("Not scheduled")
    cron.down = False
    actions.keep_in_step(core)  # tried again: Hermes has them, the file goes
    assert cron.jobs["job1"]["spec"].prompt.endswith("\n\nNew text.") and not path.exists()


def test_a_file_kept_before_moves_into_hermess_prompt_once(env: Any) -> None:
    """Live data from before: the file was the master and the job's prompt had the
    old first line (with the file's path). The next round puts the file's text
    into the prompt, the file goes; then nothing more happens."""
    client, core, cron, ws = env
    aid = new(client, ws)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    job = cron.jobs["job1"]
    old = (
        "This is the scheduled automation **Daily brief** (its readable copy is "
        "`/workspace/automations/daily-brief.md`).\n\nSummarize new files."
    )
    job["spec"] = JobSpec(**{**job["spec"].as_dict(), "prompt": old})
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["instructions"] == (
        "Summarize new files."
    )
    path.write_text('---\nname: "Daily brief"\n---\n\nSummarize new files and mails.\n')
    actions.keep_in_step(core)
    assert job["spec"].prompt == cron_prompt("Summarize new files and mails.")
    assert not path.exists()
    calls = []
    cron.update = lambda *a: calls.append(a)
    actions.keep_in_step(core)
    assert calls == []
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["instructions"] == "Summarize new files and mails."


def test_a_save_during_a_sync_is_never_lost(env: Any) -> None:
    """The owner saves new instructions while a background sync writes the job:
    that sync doesn't remove his newer file; the next round puts it into Hermes."""
    client, core, cron, ws = env
    aid = new(client, ws)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    path.write_text('---\nname: "Daily brief"\n---\n\nOld text.\n')  # live data
    real = cron.update

    def update(home: Path, job_id: str, spec: JobSpec) -> dict[str, Any]:
        path.write_text('---\nname: "Daily brief"\n---\n\nNewer text.\n')  # his save
        return dict(real(home, job_id, spec))

    cron.update = update
    actions.keep_in_step(core)
    assert cron.jobs["job1"]["spec"].prompt.endswith("Old text.") and path.exists()
    cron.update = real
    actions.keep_in_step(core)
    assert cron.jobs["job1"]["spec"].prompt.endswith("Newer text.") and not path.exists()
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["instructions"] == (
        "Newer text."
    )


def test_a_sync_pass_with_nothing_changed_runs_no_hermes_process(env: Any) -> None:
    """keep_in_step runs every 20 s: when nothing changed it only reads Hermes's
    jobs.json and routes; it starts no Hermes process (no cron write, no CLI)."""
    client, core, cron, ws = env
    new(client, ws)
    new(client, ws, name="Team one", check_first=True)
    actions.keep_in_step(core)  # settles whatever the saves left
    calls: list[str] = []
    for op in ("create", "update", "remove", "pause", "resume", "run_now", "check_schedule"):
        setattr(cron, op, lambda *a, _op=op, **k: calls.append(_op))
    real_run = core.engine.runner.run

    def run(args: Any, **k: Any) -> Any:
        calls.append(" ".join(args[:3]))
        return real_run(args, **k)

    core.engine.runner.run = run
    for _ in range(3):
        actions.keep_in_step(core)
    assert calls == []


def test_a_kanban_automations_file_stays_its_instructions(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws, check_first=True)
    path = core.layout.workspaces / ws / "automations" / "daily-brief.md"
    assert "Summarize new files." in path.read_text()
    assert cron.jobs["job1"]["spec"].prompt == ""  # its job runs a script, no prompt
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["instructions"] == "Summarize new files."


def test_a_hermes_runs_report_stays_in_hermes(env: Any) -> None:
    client, core, cron, ws = env
    aid = new(client, ws)
    cron.finish("job1", "run-a", True, "## Response\n\nTwo new invoices.", 1)
    tables = {r[0] for r in core.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & {"automation_runs", "automation_proposals", "automation_events"}
    (run,) = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    assert run["report"] == "Two new invoices." and run["result"] == "ok"


def test_archive_keeps_an_automation_that_was_off_off(env: Any) -> None:
    client, _core, cron, ws = env
    new(client, ws)
    off = new(client, ws, name="Off one")
    client.post(f"/workspaces/{ws}/automations/{off}/toggle", json={"on": False})
    assert client.post(f"/workspaces/{ws}/archive").status_code < 300
    assert all(j["enabled"] is False for j in cron.jobs.values())
    assert client.post(f"/workspaces/{ws}/unarchive").status_code < 300
    by_name = {j["spec"].name: j["enabled"] for j in cron.jobs.values()}
    assert by_name == {"Daily brief": True, "Off one": False}


def test_old_copies_go_once_hermes_and_the_file_have_them(env: Any) -> None:
    client, core, _cron, ws = env
    aid = new(client, ws)
    # A row saved before: AGOS kept the schedule and the model too.
    core.db.execute(
        "UPDATE automations SET schedule = '0 9 * * *', model = ? WHERE id = ?",
        (json.dumps(MODEL), aid),
    )
    got = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert got["nextRunAt"] == "2026-09-28T09:00:00+00:00" and got["lastRun"] is None
    actions.keep_in_step(core)
    row = _row(core, aid)
    assert (row["schedule"], row["model"]) == ("", None)
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["instructions"] == (
        "Summarize new files."
    )


def _guard() -> Any:
    from agos_core.hermes_plugin import agos_guard

    hooks: dict[str, Any] = {}

    class Ctx:
        def register_hook(self, name: str, fn: Any) -> None:
            hooks.setdefault(name, fn)  # the guard's own comes first

        def __getattr__(self, _: str) -> Any:
            return lambda *a, **k: None

    agos_guard.register(Ctx())
    return hooks["pre_tool_call"]


def test_a_run_proposes_cards_with_hermess_kanban_create_and_they_wait_for_the_owner(
    env: Any,
) -> None:
    """An automation's run proposes cards with Hermes's own kanban_create: the guard
    has them made blocked (they wait on the board for the owner) and keeps the rest
    of the board read only in a cron run. The run shows them."""
    import datetime as dt
    import sqlite3

    client, core, cron, ws = env
    check = _guard()
    cron_session = "cron_job1_20261015_090000"
    made = check(tool_name="kanban_create", args={"title": "x"}, session_id=cron_session)
    assert made == {"action": "modify", "args": {"initial_status": "blocked", "triage": False}}
    blocked = {"title": "x", "initial_status": "blocked"}
    assert check(tool_name="kanban_create", args=blocked, session_id=cron_session) is None
    moved = check(tool_name="kanban_complete", args={"task_id": "t1"}, session_id=cron_session)
    assert moved and moved["action"] == "block" and "read only" in moved["message"]
    assert check(tool_name="kanban_list", args={}, session_id=cron_session) is None
    assert check(tool_name="kanban_create", args={"title": "x"}, session_id="chat-1") is None
    # How a run proposes cards is in the agents' SOUL.md (Hermes's), not in each prompt.
    from agos_core.engine import identity

    rules = identity.RULES[identity.RULES.index("## Scheduled automations") :]
    assert "kanban_create" in rules.split("## How you talk")[0]
    assert "kanban_create" not in cron_prompt("B")

    aid = new(client, ws)
    cron.finish("job1", "run-a", True, "## Response\n\nTwo cards proposed.", 1)
    run = cron.jobs["job1"]["runs"][-1]
    started = dt.datetime.fromisoformat(run["claimed_at"]).timestamp()
    from agos_core.actions import agent_profiles

    board = agent_profiles.board_db(core, ws)
    board.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(board) as db:
        db.executescript(
            """CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, status TEXT,
                 result TEXT, idempotency_key TEXT, session_id TEXT, created_at INTEGER,
                 completed_at INTEGER, assignee TEXT, block_kind TEXT);
               CREATE TABLE task_links (parent_id TEXT, child_id TEXT);
               CREATE TABLE task_events (id INTEGER PRIMARY KEY, task_id TEXT, kind TEXT,
                 payload TEXT);"""
        )
        db.executemany(
            "INSERT INTO tasks (id, title, body, status, session_id, created_at) "
            "VALUES (?, ?, 'why', ?, ?, ?)",
            [
                ("t_a", "Call the supplier", "blocked", cron_session, int(started) + 30),
                ("t_b", "Post a poll", "archived", cron_session, int(started) + 31),
                ("t_c", "Not this job's", "blocked", "cron_other_1", int(started) + 32),
            ],
        )
    (shown,) = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    assert [(p["title"], p["kanbanCard"]) for p in shown["proposals"]] == [
        ("Call the supplier", "t_a"),
        ("Post a poll", "t_b"),
    ]
