"""An automation's schedule is checked by Hermes's own parser (cron/jobs.py
parse_schedule), in core; AGOS has no cron validator of its own."""

import shutil
from pathlib import Path
from typing import Any

import pytest
from test_automations import MODEL, env  # noqa: F401  (fixture)

from agos_core.config import EngineConfig
from agos_core.engine.cron import CronBridge, schedule_problem


def test_hermess_answer_is_what_the_owner_is_told() -> None:
    assert schedule_problem({"kind": "cron"}) is None
    assert schedule_problem({"kind": "interval"}) is None
    assert schedule_problem({"error": "Invalid cron expression '61 * * * *': bad."}) == (
        "Invalid cron expression '61 * * * *': bad"
    )
    assert "repeats" in str(schedule_problem({"kind": "once"}))
    assert schedule_problem(None) is not None


def test_a_schedule_hermes_refuses_is_never_saved(env: Any) -> None:  # noqa: F811
    client, _core, cron, ws = env
    body = {"name": "x", "instructions": "y", "schedule": "every monday", "model": MODEL}
    r = client.post(f"/workspaces/{ws}/automations", json=body)
    assert r.status_code == 400 and "Schedule: Invalid schedule" in r.text
    assert cron.jobs == {}
    ok = client.post(f"/workspaces/{ws}/automations", json=body | {"schedule": "30m"})
    assert ok.status_code == 201  # Hermes's interval form


def _bridge(tmp_path: Path) -> tuple[CronBridge, Path] | None:
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    from agos_core.engine.models import hermes_python

    tools = Path.home() / ".hermes" / "tools"
    engine = EngineConfig(
        hermes_bin=hermes,
        docker_bin="docker",
        hermes_home=tmp_path / "hermes",
        profile_prefix="agos-",
        sandbox_image="x",
        host_home=Path.home(),
        roots_dir=tmp_path / "roots",
        runtime_dir=tools if tools.is_dir() else None,
    )
    try:
        python = hermes_python(engine)
    except Exception:  # noqa: BLE001 - no usable Hermes here
        return None
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("{}\n")
    return CronBridge(engine, python), home


def test_cron_schedule_is_checked_by_hermess_own_parser(tmp_path: Path) -> None:
    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    bridge, home = found
    for ok in ("0 9 * * 1", "*/15 * * * *", "0 8 * * MON", "every monday 9am", "30m"):
        assert bridge.check_schedule(home, ok) is None, ok
    for bad in ("61 * * * *", "every monday", "soon", "0 8 * *"):
        assert bridge.check_schedule(home, bad), bad
    assert "repeats" in str(bridge.check_schedule(home, "2030-01-01T09:00:00"))
    assert not (home / "cron" / "jobs.json").exists()  # a check writes nothing


def test_a_six_field_cron_hermes_takes_is_taken(tmp_path: Path) -> None:
    """Hermes's parser takes 5-6 cron fields (cron/jobs.py parse_schedule); the web
    leaves the check to it (packages/core/src/cron.ts)."""
    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    bridge, home = found
    assert bridge.check_schedule(home, "0 9 * * 1 30") is None  # croniter: 6th = seconds


def test_a_jobs_own_skills_are_written_into_hermess_cron(tmp_path: Path) -> None:
    """The member's pinned skills go on its job (cron/jobs.py create_job skills),
    and Hermes's cron loads them into the run's prompt (cron/scheduler_prompt.py)."""
    import json
    import subprocess

    from agos_core.engine.cron import JobSpec, read_jobs

    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    bridge, home = found
    skill = home / "skills" / "copywriting"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: copywriting\ndescription: Short punchy copy.\n---\n\nWRITE-PUNCHY-COPY\n"
    )
    spec = JobSpec("agos-automation-1", "Write.", "0 9 * * *", "", "", None, False)
    job = bridge.create(home, spec.__class__(**{**spec.__dict__, "skills": ("copywriting",)}))
    (saved,) = read_jobs(home)
    assert saved["skills"] == ["copywriting"] and saved["id"] == job["id"]
    bridge.update(home, str(job["id"]), spec)
    assert read_jobs(home)[0]["skills"] == []
    bridge.update(
        home, str(job["id"]), spec.__class__(**{**spec.__dict__, "skills": ("copywriting",)})
    )
    code = (
        "import json,sys\nfrom cron.jobs import get_job\n"
        "from cron.scheduler_prompt import _build_job_prompt\n"
        f"print(_build_job_prompt(get_job({json.dumps(str(job['id']))})))\n"
    )
    done = subprocess.run(  # noqa: S603 - fixed argv
        [bridge.python, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **bridge.engine.runtime_env(),
            "HERMES_HOME": str(home),
            "HOME": str(Path.home()),
            "PATH": "/usr/bin:/bin",
        },
        cwd=str(Path(bridge.python).parent.parent.parent),
        check=False,
    )
    assert "WRITE-PUNCHY-COPY" in done.stdout, done.stderr[-2000:]


def test_run_now_of_a_team_job_is_hermess_cron_run(tmp_path: Path) -> None:
    """`hermes cron run <id>`: Hermes runs the no-agent job once and records the
    run (last_run_at, its output); a paused job is refused by Hermes."""
    from agos_core.engine.cron import CronError, JobSpec, read_jobs

    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    bridge, home = found
    (home / "scripts").mkdir()
    (home / "scripts" / "agos-automation-7.py").write_text(
        'print("Didn\'t start: its last run (card t1) is still going.")\n'
    )
    spec = JobSpec(
        "agos-automation-7", "", "0 9 * * *", "", "", None, True, script="agos-automation-7.py"
    )
    job = str(bridge.create(home, spec)["id"])
    ok, said = bridge.run_inline(home, job)
    assert ok and said.startswith("Didn't start:"), said
    (saved,) = read_jobs(home)
    assert saved["last_run_at"] and saved["last_status"] == "ok"
    bridge.pause(home, job, "Turned off in AGOS")
    with pytest.raises(CronError):
        bridge.run_inline(home, job)


def test_run_now_is_hermess_own_run_never_agos_own() -> None:
    """A one-agent Run now is Hermes's API `POST /api/jobs/{id}/run`; a scheduled
    team automation's is `hermes cron run`. The bridge no longer triggers jobs."""
    from agos_core.engine import cron

    assert "trigger_job" not in cron._BRIDGE and '"run"' not in cron._BRIDGE
    actions = Path(cron.__file__).parent.parent / "actions"
    src = (actions / "services" / "automation" / "owner.py").read_text()
    body = src[src.index("def _run_on_board(") :]
    assert "bridge.run_inline(" in body and body.index("run_inline") < body.index("run_script")


def test_cron_writes_are_hermess_own_cli(tmp_path: Path) -> None:
    """Create, edit, resume and remove are `hermes cron create|edit|resume|remove`;
    only a pause with AGOS's reason (no CLI or API takes one) is cron.jobs."""
    from agos_core.engine import cron
    from agos_core.engine.cron import ARCHIVED_REASON, OFF_REASON, JobSpec, read_jobs

    for op in ('"create"', '"update"', '"resume"', '"remove"', '"list"'):
        assert f"op == {op}" not in cron._BRIDGE, op
    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    bridge, home = found
    spec = JobSpec("agos-automation-3", "- starts with a dash", "0 9 * * *", "", "", "high", True)
    job = str(bridge.create(home, spec)["id"])
    (saved,) = read_jobs(home)
    assert saved["prompt"] == "- starts with a dash" and saved["enabled"]
    off = JobSpec(**{**spec.__dict__, "enabled": False, "prompt": "Now this."})
    bridge.update(home, job, off)
    (saved,) = read_jobs(home)
    assert saved["prompt"] == "Now this." and saved["paused_reason"] == OFF_REASON
    bridge.update(home, job, spec)
    assert read_jobs(home)[0]["enabled"]
    bridge.pause(home, job, ARCHIVED_REASON)
    bridge.update(home, job, off)  # held by AGOS for a while, now off for good
    assert read_jobs(home)[0]["paused_reason"] == OFF_REASON
    bridge.remove(home, job)
    assert read_jobs(home) == []


def test_run_now_of_a_member_job_takes_the_members_own_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The root's gateway serves the member under /p/<member>/ and checks that
    member's own API_SERVER_KEY (api_server.py _expected_api_key), never the root's."""
    import urllib.request

    root = tmp_path / "agos-alpha"
    member = root / "profiles" / "a-editor"
    member.mkdir(parents=True)
    (root / ".env").write_text("API_SERVER_PORT=4321\nAPI_SERVER_KEY=root-key\n")
    (member / ".env").write_text("API_SERVER_PORT=9999\nAPI_SERVER_KEY=member-key\n")
    sent: list[urllib.request.Request] = []

    class Reply:
        def __enter__(self) -> "Reply":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def urlopen(request: urllib.request.Request, timeout: float = 0) -> Reply:
        sent.append(request)
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    bridge = CronBridge.__new__(CronBridge)
    bridge.run_now(member, "j1")
    bridge.run_now(root, "j2")
    assert [r.full_url for r in sent] == [
        "http://127.0.0.1:4321/p/a-editor/api/jobs/j1/run",
        "http://127.0.0.1:4321/api/jobs/j2/run",
    ]
    assert [r.get_header("Authorization") for r in sent] == [
        "Bearer member-key",
        "Bearer root-key",
    ]
