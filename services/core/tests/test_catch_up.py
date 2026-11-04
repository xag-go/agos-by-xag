"""A run missed while the server was off runs once when AGOS is back, or is skipped
(actions/catch_up.py), on a fake clock and a fake Hermes cron; the real Hermes's
schedule math and its `cron.catch_up_missed` switch are checked at the end."""

import builtins
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_automations import MODEL, FakeCron, env, new  # noqa: F401  (fixture)

from agos_core.actions import catch_up, cofounder_more
from agos_core.engine.cron import WORK_HOURS_REASON, CronError

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class Cron(FakeCron):
    """FakeCron plus the job fields a missed run is told from and Hermes's slots."""

    def __init__(self, base: FakeCron) -> None:
        self.__dict__.update(base.__dict__)
        self.gateway_down = False
        self.asked: list[tuple[str, str]] = []

    def job_states(self, home: Path) -> builtins.list[dict[str, Any]]:
        out = super().job_states(home)
        for item in out:
            item.update(self.jobs[item["id"]].get("hermes", {}))
        return out

    def run_now(self, home: Path, job_id: str) -> None:
        if self.gateway_down:
            raise CronError("the workspace's gateway didn't answer: refused")
        super().run_now(home, job_id)

    def slots(
        self, home: Path, jobs: builtins.list[dict[str, Any]], now: str
    ) -> dict[str, dict[str, Any]]:
        """Hermes's compute_next_run for the two forms used here: an interval, and
        "0 9 * * *" (09:00 UTC daily)."""
        self.asked.append((str(home), now))
        at_now = datetime.fromisoformat(now)
        out: dict[str, dict[str, Any]] = {}
        for item in jobs:
            sched, after = item["schedule"], datetime.fromisoformat(item["after"])
            if sched["kind"] == "interval":
                step = timedelta(minutes=int(sched["minutes"]))
            else:
                step = timedelta(days=1)
                after_9 = after.replace(hour=9, minute=0, second=0, microsecond=0)
                after = after_9 - step if after_9 > after else after_9
            latest, t = None, after + step
            while t <= at_now:
                latest, t = t, t + step
            grace = max(120, min(int(step.total_seconds()) // 2, 7200))
            out[item["id"]] = {"slot": latest.isoformat() if latest else None, "grace": grace}
        return out


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
def rig(env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    client, core, base, ws = env
    cron = Cron(base)
    core.engine.cron_bridge = cron
    clock = {"now": NOW}
    monkeypatch.setattr(catch_up, "_now", lambda: clock["now"])
    catch_up.forget()
    return client, core, cron, ws, clock


def _automation(
    client: Any, cron: Cron, ws: str, *, schedule: dict[str, Any], last_run: datetime, **extra: Any
) -> tuple[int, str]:
    aid = new(client, ws, **extra)
    (job_id,) = [j for j in cron.jobs if cron.jobs[j]["spec"].name == "Daily brief"][-1:]
    cron.jobs[job_id]["hermes"] = {
        "schedule_spec": schedule,
        "created_at": _iso(last_run - timedelta(days=30)),
        "last_run_at": _iso(last_run),
        "dispatched_for": _iso(last_run),
        "run_queued": False,
        "claimed_at": None,
    }
    return aid, job_id


def _pass(core: Any) -> None:
    catch_up.forget()  # each pass looks again (as a new core would)
    catch_up.keep(core)


def _log(core: Any, ws: str) -> builtins.list[str]:
    return [
        str(r["text"])
        for r in core.db.execute(
            "SELECT text FROM activity WHERE workspace_id = ? AND kind LIKE 'automation.catch_up%'",
            (ws,),
        )
    ]


DAILY = {"kind": "cron", "expr": "0 9 * * *"}
HOURLY = {"kind": "interval", "minutes": 60}


def test_a_run_missed_once_runs_once_with_its_log_line_and_runs_label(rig: Any) -> None:
    client, core, cron, ws, _clock = rig
    # Ran yesterday 09:00, today's 09:00 passed while the server was off (now 12:00:
    # 3 h late, beyond Hermes's 2 h grace for a daily job).
    aid, job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    _pass(core)
    assert cron.fired == [job]
    (line,) = _log(core, ws)
    assert line.startswith("Catch-up run (missed at Mon 02 Nov 09:00") and "Daily brief" in line
    # Hermes ran it: its execution shows as the catch-up run, the card has the chip.
    cron.jobs[job]["runs"].append(
        {
            "id": "r1",
            "status": "completed",
            "error": None,
            "source": "manual",
            "claimed_at": _iso(NOW + timedelta(seconds=40)),
            "started_at": _iso(NOW + timedelta(seconds=40)),
            "finished_at": _iso(NOW + timedelta(minutes=2)),
        }
    )
    cron.jobs[job]["outputs"].append(
        {
            "name": "a.md",
            "mtime": (NOW + timedelta(minutes=2)).timestamp(),
            "text": "## Response\nok",
        }
    )
    cron.jobs[job]["hermes"]["last_run_at"] = _iso(NOW + timedelta(seconds=40))
    runs = client.get(f"/workspaces/{ws}/automations/{aid}/runs").json()
    assert runs[0]["caughtUp"] == _iso(NOW.replace(hour=9))
    shown = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    assert shown["caughtUp"] == _iso(NOW.replace(hour=9)) and shown["catchUp"] == "once"
    _pass(core)
    assert cron.fired == [job]  # it ran: nothing more


def test_ten_missed_runs_make_one_run(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    # Hourly, last run 10 h 40 min ago: 10 slots missed, the latest 40 min ago (beyond
    # Hermes's 30 min grace).
    last = NOW - timedelta(hours=10, minutes=40)
    _aid, job = _automation(client, cron, ws, schedule=HOURLY, last_run=last)
    for _ in range(4):
        _pass(core)
        clock["now"] += timedelta(seconds=20)
    assert cron.fired == [job]
    assert len(_log(core, ws)) == 1


def test_skip_never_runs_it_and_says_so_once(rig: Any) -> None:
    client, core, cron, ws, _clock = rig
    _aid, _job = _automation(
        client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27), catchUp="skip"
    )
    _pass(core)
    _pass(core)
    assert cron.fired == []
    (line,) = _log(core, ws)
    assert line.startswith("Missed run skipped")


def test_an_automation_that_is_off_never_catches_up(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    _aid, job = _automation(
        client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27), on=False
    )
    _pass(core)
    assert cron.fired == []
    # Off over the slot, then turned back on: the slot it missed while off never runs
    # (Hermes's resume keeps it due; its catch_up_missed: false skips it).
    clock["now"] += timedelta(hours=1)
    cron.jobs[job].update(enabled=True, paused_reason=None)
    _pass(core)
    clock["now"] += timedelta(minutes=5)
    _pass(core)
    assert cron.fired == [] and _log(core, ws) == []


def test_a_run_missed_more_than_the_limit_ago_never_runs(rig: Any) -> None:
    client, core, cron, ws, _clock = rig
    every_ten_days = {"kind": "interval", "minutes": 10 * 24 * 60}
    _aid, _job = _automation(
        client, cron, ws, schedule=every_ten_days, last_run=NOW - timedelta(days=18)
    )
    _pass(core)  # its slot was 8 days ago (limit: 7)
    assert cron.fired == []


def test_within_hermess_grace_hermes_runs_it_itself(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    clock["now"] = NOW.replace(hour=10)  # 1 h late: Hermes's daily grace is 2 h
    _aid, _job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    _pass(core)
    assert cron.fired == []


def test_a_core_restart_never_runs_it_twice_and_a_gateway_not_up_yet_waits(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    _aid, job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    cron.gateway_down = True
    _pass(core)
    assert cron.fired == [] and _log(core, ws) == []
    (state,) = core.db.execute(
        "SELECT state FROM cron_catch_up WHERE job_id = ?", (job,)
    ).fetchone()
    assert state == "waiting"
    cron.gateway_down = False  # the gateway is up
    clock["now"] += timedelta(seconds=20)
    _pass(core)
    assert cron.fired == [job]
    # A new core (nothing in memory) while Hermes hasn't run it yet: no second ask.
    clock["now"] += timedelta(seconds=20)
    _pass(core)
    assert cron.fired == [job] and len(_log(core, ws)) == 1


def test_a_queued_run_now_or_a_live_run_is_never_doubled(rig: Any) -> None:
    client, core, cron, ws, _clock = rig
    _aid, job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    cron.jobs[job]["hermes"]["run_queued"] = True
    _pass(core)
    cron.jobs[job]["hermes"].update(run_queued=False, claimed_at=_iso(NOW - timedelta(seconds=30)))
    _pass(core)
    assert cron.fired == []
    cron.jobs[job]["hermes"]["claimed_at"] = _iso(NOW - timedelta(hours=2))  # a dead run's claim
    _pass(core)
    assert cron.fired == [job]


def test_off_hours_wait_for_the_check_in_then_run_once(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    _aid, job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    cron.jobs[job].update(enabled=False, paused_reason=WORK_HOURS_REASON)
    _pass(core)
    assert cron.fired == []  # never run off-hours
    clock["now"] += timedelta(hours=1)
    cron.jobs[job].update(enabled=True, paused_reason=None)  # check-in
    _pass(core)
    assert cron.fired == [job]


def test_the_choice_is_saved_and_the_cofounder_changes_it_with_undo(rig: Any) -> None:
    client, core, cron, ws, _clock = rig
    aid, _job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW)
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["catchUp"] == "once"
    done = cofounder_more.DOES["set_automation_catch_up"](
        core, ws, {"automation": "Daily brief", "catch_up": "skip"}
    )
    assert catch_up.choice(core, ws, aid) == "skip"
    cofounder_more.UNDOES["set_automation_catch_up"](core, ws, done)
    assert catch_up.choice(core, ws, aid) == "once"
    body = client.get(f"/workspaces/{ws}/automations/{aid}").json()
    r = client.put(
        f"/workspaces/{ws}/automations/{aid}",
        json={
            "name": body["name"],
            "instructions": "Summarize new files.",
            "schedule": "0 9 * * *",
            "model": MODEL,
            "catchUp": "skip",
        },
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/workspaces/{ws}/automations/{aid}").json()["catchUp"] == "skip"
    bad = client.put(
        f"/workspaces/{ws}/automations/{aid}",
        json={
            "name": body["name"],
            "instructions": "x",
            "schedule": "0 9 * * *",
            "model": MODEL,
            "catchUp": "twice",
        },
    )
    assert bad.status_code == 422


def test_hermess_switch_is_pinned_off_in_its_managed_scope(rig: Any) -> None:
    _client, core, _cron, _ws, _clock = rig
    wrote: list[Any] = []
    core.engine.managed_write = lambda sets, unsets: wrote.append((sets, unsets))
    assert catch_up.pin_hermes(core) is True
    assert wrote == [([("cron.catch_up_missed", "false")], [])]


# ---- the real Hermes ---------------------------------------------------------------


def _real(tmp_path: Path) -> Any:
    from test_cron_schedule import _bridge

    found = _bridge(tmp_path)
    if found is None:
        pytest.skip("no Hermes install on this machine")
    return found


def test_hermess_own_schedule_math_finds_the_missed_slot_and_its_grace(tmp_path: Path) -> None:
    bridge, home = _real(tmp_path)
    found = bridge.slots(
        home,
        [
            {"id": "d", "schedule": DAILY, "after": "2026-11-01T09:00:00+00:00"},
            {"id": "h", "schedule": HOURLY, "after": "2026-11-02T01:30:00+00:00"},
            {"id": "x", "schedule": DAILY, "after": "2026-11-02T09:00:00+00:00"},
        ],
        "2026-11-02T12:00:00+00:00",
    )
    assert datetime.fromisoformat(found["d"]["slot"]) == NOW.replace(hour=9)
    assert found["d"]["grace"] == 7200  # half a day, clamped to 2 h
    assert datetime.fromisoformat(found["h"]["slot"]) == NOW.replace(hour=11, minute=30)
    assert found["h"]["grace"] == 1800
    assert found["x"]["slot"] is None  # nothing since


def _due_scan(bridge: Any, home: Path, config: str) -> dict[str, Any]:
    """Hermes's own due scan (cron/jobs.py get_due_jobs) on a daily job whose last
    occurrence passed 3+ h ago, with the home's config.yaml as given."""
    (home / "config.yaml").write_text(config)
    (home / "cron").mkdir(exist_ok=True)
    now = datetime.now(UTC).replace(microsecond=0)
    due = now.replace(hour=9, minute=0, second=0)  # an occurrence of "0 9 * * *"
    if now - due < timedelta(hours=3):
        due -= timedelta(days=1)  # at least 3 h late: beyond Hermes's 2 h grace
    job = {
        "id": "missed1",
        "name": "probe",
        "prompt": "hi",
        "enabled": True,
        "state": "scheduled",
        "schedule": DAILY,
        "schedule_display": "0 9 * * *",
        "created_at": (now - timedelta(days=5)).isoformat(),
        "last_run_at": (due - timedelta(days=1)).isoformat(),
        "next_run_at": due.isoformat(),
        "repeat": {"times": None, "completed": 3},
    }
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [job]}))
    code = (
        "import json\nfrom cron import jobs as J\n"
        "due = [j['id'] for j in J.get_due_jobs()]\n"
        "print('AGOS-JSON ' + json.dumps({'due': due, 'next': J.get_job('missed1')['next_run_at']}))"
    )
    run_env = {
        "HOME": str(bridge.engine.host_home),
        "HERMES_HOME": str(home),
        "PATH": "/usr/bin:/bin",
        **bridge.engine.runtime_env(),
    }
    run_env.pop("HERMES_MANAGED_DIR", None)
    done = subprocess.run(  # noqa: S603 - fixed argv
        [bridge.python, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        env=run_env,
        check=False,
        cwd=str(Path(bridge.python).parent.parent.parent),
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")]
    assert lines, done.stderr[-2000:]
    found: dict[str, Any] = json.loads(lines[-1][len("AGOS-JSON ") :])
    found["now"] = now
    return found


@pytest.mark.skipif(os.environ.get("AGOS_SKIP_HERMES_SCAN") == "1", reason="asked to skip")
def test_real_hermes_skips_a_missed_run_only_with_the_switch_off(tmp_path: Path) -> None:
    bridge, home = _real(tmp_path)
    native = _due_scan(bridge, home, "{}\n")
    assert native["due"] == ["missed1"]  # Hermes's default: runs it once by itself
    off = _due_scan(bridge, home, "cron:\n  catch_up_missed: false\n")
    assert off["due"] == []  # the switch AGOS pins: Hermes skips it...
    assert datetime.fromisoformat(off["next"]) > off["now"]  # ...and re-anchors, once


def test_a_pass_with_nothing_changed_asks_hermes_nothing(rig: Any) -> None:
    client, core, cron, ws, clock = rig
    clock["now"] = NOW.replace(hour=10)  # within Hermes's grace: nothing to catch up
    _aid, job = _automation(client, cron, ws, schedule=DAILY, last_run=NOW - timedelta(hours=27))
    catch_up.keep(core)
    catch_up.keep(core)
    assert len(cron.asked) == 1  # one Hermes process, not one per pass
    # Hermes's tick skipped the slot (its catch_up_missed: false): jobs.json moved.
    clock["now"] = NOW
    cron.jobs[job]["next_run_at"] = _iso(NOW.replace(hour=9) + timedelta(days=1))
    jobs = core.engine.profile_home(ws) / "cron" / "jobs.json"
    jobs.parent.mkdir(parents=True, exist_ok=True)
    jobs.write_text("{}")
    catch_up.keep(core)
    assert len(cron.asked) == 2 and cron.fired == [job]
