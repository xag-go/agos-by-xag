"""deploy/agos rollback and the watch after an update, on the fake machine of
test_agos_cli: what the independent review of eng/ops found.

- a second rollback never puts an older database over today's (H1);
- a rollback on a full disk changes nothing (H2), and a full disk alone is never
  a rollback trigger;
- every rollback keeps today's data in its own rolled-from-<time> folder, never
  rotated away (M2), next to the snapshots in AGOS's data folder, not the backup
  folder (M7);
- the watch is not fooled by a hand stop, a restore or an archived workspace (M1);
- cron run state survives a rollback (M5); a broken roots tar never deletes the
  live plugins (Low).
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import stat
import subprocess
import tarfile
import time
from pathlib import Path

from test_agos_cli import AGOS, Machine, _git, machine  # noqa: F401 - fixture
from test_agos_cli import pytestmark as pytestmark


def _fake(m: Machine) -> Path:
    return Path(m.env["FAKE"])


def _watch(m: Machine, snap: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full = {**m.env, "AGOS_WATCH_FAILS": "1", "AGOS_WATCH_SECONDS": "3", **env}
    return subprocess.run(  # noqa: S603
        ["bash", str(AGOS), "update-watch", snap.name],  # noqa: S607
        env=full, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip


def _head(m: Machine) -> str:
    return _git(m.app, "rev-parse", "HEAD")


def _db(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        return str(conn.execute("SELECT v FROM t").fetchone()[0])
    finally:
        conn.close()


# ---- H1: a second rollback ------------------------------------------------------


def test_a_second_rollback_is_refused_and_keeps_todays_data(machine: Machine) -> None:  # noqa: F811
    old = _head(machine)
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    machine.agos("rollback", "--yes")
    assert _head(machine) == old and machine.db_value() == "before"
    machine.set_db_value("written after the rollback")
    done = machine.agos("rollback", "--yes", check=False)
    assert done.returncode == 1
    assert "rolled back already" in done.stderr and "Nothing changed" in done.stderr
    assert machine.db_value() == "written after the rollback"


def test_a_forced_rollback_keeps_each_days_data_in_its_own_folder(machine: Machine) -> None:  # noqa: F811
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    machine.agos("rollback", "--yes")
    machine.set_db_value("later")
    time.sleep(1.1)  # its own stamp
    machine.agos("rollback", "--yes", "--force")
    assert machine.db_value() == "before"
    kept = machine.rolled_from()
    assert [_db(k / "agos.db") for k in kept] == ["after", "later"]


def test_a_rollback_after_a_later_update_is_refused(machine: Machine) -> None:  # noqa: F811
    machine.release("Second release")
    machine.agos("update", "--yes")
    first = machine.snapshots()[0]
    third = machine.release("Third release")
    machine.agos("update", "--yes")
    done = machine.agos("rollback", "--yes", "--to", first.name, check=False)
    assert done.returncode == 1 and "moved since" in done.stderr
    assert _head(machine) == third


def test_an_update_that_fails_before_changing_anything_leaves_no_snapshot(
    machine: Machine,  # noqa: F811
) -> None:
    """VM run: a failed backup left an empty update-<time> folder; the next
    `agos rollback` picked it (the newest) and refused, though the update before it
    was complete."""
    old = _head(machine)
    good = machine.release("Second release")
    machine.agos("update", "--yes")
    [complete] = machine.snapshots()
    machine.release("Third release")
    time.sleep(1.1)  # its own stamp
    (_fake(machine) / "backup-fails").touch()
    done = machine.agos("update", "--yes", check=False)
    assert done.returncode == 1 and _head(machine) == good
    assert machine.snapshots() == [complete]
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state["phase"] == "failed" and "Hermes said no" in state["error"]
    (_fake(machine) / "backup-fails").unlink()
    machine.agos("rollback", "--yes")
    assert _head(machine) == old


def test_rollback_skips_an_incomplete_snapshot(machine: Machine) -> None:  # noqa: F811
    old = _head(machine)
    machine.release("Second release")
    machine.agos("update", "--yes")
    # An older AGOS's failed update (or a crash mid-snapshot) left a newer, empty one.
    (machine.snaps / "update-29990101T000000Z").mkdir(mode=0o700)
    machine.agos("rollback", "--yes")
    assert _head(machine) == old


def test_a_crash_mid_snapshot_never_becomes_the_rollback_point(machine: Machine) -> None:  # noqa: F811
    """Review L1: agos.sha and agos.db were all a "complete" snapshot needed, and
    both exist before roots.tar and the gateways list. A crash in between left the
    newest folder looking complete; rollback picked it and refused ("moved since")."""
    old = _head(machine)
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.release("Third release")
    time.sleep(1.1)  # its own stamp
    (_fake(machine) / "die-mid-snapshot").touch()
    assert machine.agos("update", "--yes", check=False).returncode != 0
    (_fake(machine) / "die-mid-snapshot").unlink()
    machine.agos("rollback", "--yes")
    assert _head(machine) == old


def test_rotation_counts_only_complete_snapshots(machine: Machine) -> None:  # noqa: F811
    """Review L2: the rotation kept the three newest update-* folders of any kind,
    so crash leftovers (or an older AGOS's empty folders) could push every complete
    snapshot out. Only complete ones count; leftovers go."""
    machine.release("Release 0")
    machine.agos("update", "--yes")
    junk = [
        machine.snaps / "update-29990101T000000Z",  # empty
        machine.snaps / "update-29990102T000000Z",  # agos.sha only
        machine.snaps / "update-20000101T000000Z.partial",
        machine.snaps / "update-29990103T000000Z.partial",
    ]
    for folder in junk:
        folder.mkdir(mode=0o700)
    (junk[1] / "agos.sha").write_text("x\n")
    for name in ("agos.sha", "agos.db"):
        (junk[2] / name).write_text("x\n")
    for n in range(1, 4):
        machine.release(f"Release {n}")
        time.sleep(1.1)
        machine.agos("update", "--yes")
    kept = machine.snapshots()
    assert len(kept) == 3, kept
    assert all((k / "agos.db").is_file() and (k / "gateways").is_file() for k in kept)
    assert not any(k.name.endswith(".partial") for k in machine.snaps.iterdir())
    machine.agos("rollback", "--yes")


def test_rollback_to_needs_a_value(machine: Machine) -> None:  # noqa: F811
    done = machine.agos("rollback", "--to", check=False)
    assert done.returncode == 1 and "usage" in done.stderr


# ---- H2: a full disk --------------------------------------------------------------


def test_a_rollback_without_room_changes_nothing(machine: Machine) -> None:  # noqa: F811
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    (_fake(machine) / "no-room").touch()
    calls = _fake(machine) / "calls"
    calls.write_text("")
    done = machine.agos("rollback", "--yes", check=False)
    assert done.returncode == 1 and "Not enough free disk" in done.stderr
    assert _head(machine) == new and machine.db_value() == "after"
    assert "systemctl stop agos-web" not in calls.read_text()  # AGOS never stopped


def test_a_rollback_that_cannot_keep_todays_copy_changes_nothing(machine: Machine) -> None:  # noqa: F811
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    (_fake(machine) / "no-copy").touch()  # today's database can't be copied (disk full)
    calls = _fake(machine) / "calls"
    calls.write_text("")
    done = machine.agos("rollback", "--yes", check=False)
    assert done.returncode == 1 and "could not be kept aside" in done.stderr
    assert _head(machine) == new and machine.db_value() == "after"
    assert machine.rolled_from() == []  # no half copy left
    lines = calls.read_text().splitlines()
    stop = next(i for i, c in enumerate(lines) if "systemctl stop agos-web" in c)
    assert any("systemctl start agos-core" in c for c in lines[stop:])  # started again


def test_a_snapshot_database_that_cannot_be_copied_changes_nothing(machine: Machine) -> None:  # noqa: F811
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    [snap] = machine.snapshots()
    (snap / "agos.db").chmod(0)
    try:
        done = machine.agos("rollback", "--yes", check=False)
    finally:
        (snap / "agos.db").chmod(0o600)
    assert done.returncode == 1
    assert _head(machine) == new and machine.db_value() == "after"
    assert not (machine.data / "system" / "agos.db.rollback-tmp").exists()


def test_a_full_disk_alone_does_not_roll_the_update_back(machine: Machine) -> None:  # noqa: F811
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    (_fake(machine) / "disk-full").touch()
    done = _watch(machine, snap, AGOS_WATCH_EVERY_S="1")
    assert done.returncode == 0, done.stderr
    assert _head(machine) == new


# ---- M2 / M7: where the copies live -----------------------------------------------


def test_snapshots_live_in_the_data_folder_not_the_backup_folder(machine: Machine) -> None:  # noqa: F811
    legacy = machine.backups / "update-20260101T000000Z"
    legacy.mkdir(parents=True)
    for name in ("agos.sha", "agos.db", "hermes.pin"):
        (legacy / name).write_text("x\n")
    machine.release("Second release")
    machine.agos("update", "--yes")
    assert not list(machine.backups.glob("update-*"))  # keys never sit with the backups
    assert stat.S_IMODE(machine.snaps.stat().st_mode) == 0o700
    assert (machine.snaps / legacy.name).is_dir()  # an older snapshot moved in
    assert any(s.name != legacy.name for s in machine.snapshots())


def test_rolled_from_copies_survive_the_snapshot_rotation(machine: Machine) -> None:  # noqa: F811
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.set_db_value("after")
    machine.agos("rollback", "--yes")
    for n in range(4):
        machine.release(f"Release {n}")
        time.sleep(1.1)
        machine.agos("update", "--yes")
    assert len(machine.snapshots()) == 3
    [kept] = machine.rolled_from()
    assert _db(kept / "agos.db") == "after"


# ---- M1: the watch ----------------------------------------------------------------


def test_the_watch_ends_when_agos_was_stopped_by_hand(machine: Machine) -> None:  # noqa: F811
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    (_fake(machine) / "down").touch()
    (_fake(machine) / "core-inactive").touch()
    done = _watch(machine, snap)
    assert done.returncode == 0 and "stopped by hand" in done.stderr
    assert _head(machine) == new
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state["watch"] == "stopped"


def _two_gateways(m: Machine) -> None:
    fake = _fake(m)
    names = ["hermes-gateway-agos-ws1.service", "hermes-gateway-agos-ws2.service"]
    (fake / "gateways").write_text("\n".join(names) + "\n")
    for unit, ws in zip(names, ("ws1", "ws2"), strict=True):
        (fake / f"unit-{unit}").write_text(f"Environment=HERMES_HOME={m.data}/hermes/agos-{ws}\n")


def test_an_update_keeps_every_gateway_whose_unit_comes_in_two_writes(
    machine: Machine,  # noqa: F811
) -> None:
    """`systemctl cat | grep -q` under pipefail: systemctl dies of SIGPIPE writing
    the drop-in after grep's first match, and the gateway was left out of the
    update's list (not stopped, not in the snapshot)."""
    _two_gateways(machine)
    fake = _fake(machine)
    for ws in ("ws1", "ws2"):
        unit = fake / f"unit-hermes-gateway-agos-{ws}.service"
        unit.write_text(unit.read_text() + ("# " + "x" * 200 + "\n") * 2000)
    (fake / "slow-cat").touch()
    machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    assert (snap / "gateways").read_text().split() == [
        "hermes-gateway-agos-ws1.service",
        "hermes-gateway-agos-ws2.service",
    ]


def test_the_watch_skips_the_gateway_of_a_workspace_archived_since(machine: Machine) -> None:  # noqa: F811
    _two_gateways(machine)
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    assert "agos-ws2" in (snap / "gateways").read_text()
    (_fake(machine) / "workspaces").write_text('[{"id": "ws1"}]')  # ws2 archived since
    (_fake(machine) / "down-hermes-gateway-agos-ws2.service").touch()
    done = _watch(machine, snap, AGOS_WATCH_EVERY_S="1")
    assert done.returncode == 0, done.stderr
    assert _head(machine) == new


def test_the_watch_still_rolls_back_when_an_active_workspaces_gateway_died(
    machine: Machine,  # noqa: F811
) -> None:
    _two_gateways(machine)
    old = _head(machine)
    machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    (_fake(machine) / "workspaces").write_text('[{"id": "ws1"}, {"id": "ws2"}]')
    (_fake(machine) / "down-hermes-gateway-agos-ws2.service").touch()
    done = _watch(machine, snap)
    assert "gateway hermes-gateway-agos-ws2.service" in done.stderr
    assert _head(machine) == old


def test_stop_restart_and_restore_stop_the_watch(machine: Machine) -> None:  # noqa: F811
    calls = _fake(machine) / "calls"
    for cmd in ("stop", "restart"):
        calls.write_text("")
        machine.agos(cmd)
        lines = calls.read_text().splitlines()
        watch = next(i for i, c in enumerate(lines) if "--user stop agos-update-watch" in c)
        services = next(i for i, c in enumerate(lines) if f"systemctl {cmd} agos-" in c)
        assert watch < services, cmd
    calls.write_text("")
    backup = machine.root / "b.agosb"
    backup.write_bytes(b"x")
    done = machine.agos("restore", str(backup), check=False, AGOS_BACKUP_PASSWORD="p")
    assert "--user stop agos-update-watch" in calls.read_text()
    assert "kept 14 days" in done.stdout


def test_the_fallback_watch_can_be_stopped(machine: Machine) -> None:  # noqa: F811
    machine.release("Second release")
    (_fake(machine) / "no-systemd-run").touch()
    machine.agos("update", "--yes", AGOS_WATCH_EVERY_S="1")
    pid_file = machine.data / "system" / "agos-update-watch.pid"
    for _ in range(50):
        if pid_file.is_file():
            break
        time.sleep(0.1)
    pid = int(pid_file.read_text())
    try:
        assert Path(f"/proc/{pid}").exists()
        machine.agos("stop")
        for _ in range(100):
            if not Path(f"/proc/{pid}").exists() or "zombie" in _proc_state(pid):
                break
            time.sleep(0.1)
        assert not Path(f"/proc/{pid}").exists() or "zombie" in _proc_state(pid)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)


def _proc_state(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/status").read_text().split("State:", 1)[1].split("\n", 1)[0]
    except (OSError, IndexError):
        return "zombie"


def test_the_scripts_copies_are_removed_when_they_end(machine: Machine) -> None:  # noqa: F811
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.agos("rollback", "--yes")
    assert not list(machine.root.glob("agos-copy.*"))


# ---- M5 / Low: what goes back into the roots --------------------------------------


def test_a_rollback_keeps_the_cron_jobs_run_state(machine: Machine) -> None:  # noqa: F811
    jobs = machine.data / "hermes" / "agos-ws1" / "profiles" / "a-writer" / "cron" / "jobs.json"
    job = {"id": "j1", "prompt": "old", "next_run_at": "2026-11-01T09:00:00Z", "last_run_at": None}
    jobs.write_text(json.dumps({"jobs": [job], "updated_at": "x"}))
    machine.release("Second release")
    machine.agos("update", "--yes")
    # The new release rewrote the prompt; then the job ran (Hermes moved its state).
    ran = {
        **job,
        "prompt": "new",
        "next_run_at": "2026-11-02T09:00:00Z",
        "last_run_at": "2026-11-01T09:00:03Z",
        "last_status": "ok",
    }
    jobs.write_text(json.dumps({"jobs": [ran], "updated_at": "y"}))
    machine.agos("rollback", "--yes")
    [back] = json.loads(jobs.read_text())["jobs"]
    assert back["prompt"] == "old"  # the definition is the snapshot's
    assert back["next_run_at"] == "2026-11-02T09:00:00Z"  # it does not run twice
    assert back["last_run_at"] == "2026-11-01T09:00:03Z" and back["last_status"] == "ok"


def test_a_broken_roots_tar_never_deletes_the_live_plugins(machine: Machine) -> None:  # noqa: F811
    plugin = machine.data / "hermes" / "agos-ws1" / "plugins" / "agos_guard"
    plugin.mkdir(parents=True)
    body = os.urandom(200_000)
    (plugin / "big.bin").write_bytes(body)
    machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    tar = snap / "roots.tar"
    with tarfile.open(tar) as t:
        assert any(n.endswith("plugins/agos_guard/big.bin") for n in t.getnames())
    with tar.open("r+b") as f:
        f.truncate(tar.stat().st_size - 120_000)  # the plugin's data cut half-way
    done = machine.agos("rollback", "--yes", check=False)
    assert "could not be put back" in done.stderr
    assert (plugin / "big.bin").read_bytes() == body
