"""deploy/agos against a fake machine: a real git release, a real SQLite database,
real Hermes-root files, and shims for systemctl / sudo / curl / pnpm / uv / hermes.

Covers what a release can break after it shipped: the update's snapshot of the
Hermes roots, its automatic rollback (now with the roots), `agos rollback`, the
watch after an update, and `agos doctor --bundle`."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not all(shutil.which(c) for c in ("git", "sqlite3", "jq", "flock", "tar")),
    reason="deploy/agos needs git, sqlite3, jq, flock and tar",
)

AGOS = Path(__file__).resolve().parents[3] / "deploy" / "agos"

SHIMS = {
    "sudo": """#!/usr/bin/env bash
while [[ "${1:-}" == -* ]]; do [[ "$1" == -p ]] && shift; shift; done
[[ "${1:-}" == -- ]] && shift
[[ "${1:-}" == /usr/bin/systemctl ]] && { shift; exec systemctl "$@"; }
exec "$@"
""",
    "systemctl": """#!/usr/bin/env bash
echo "systemctl $*" >> "$FAKE/calls"
unit="${@: -1}"
case "$*" in
  *is-active*hermes-gateway*) [[ -f "$FAKE/down-$unit" ]] && { echo inactive; exit 3; }; echo active ;;
  *is-active*agos-core*) [[ -f "$FAKE/core-inactive" ]] && { echo inactive; exit 3; }; echo active ;;
  *is-active*) echo active ;;
  *is-enabled*) [[ -f "$FAKE/enabled-$unit" ]] || exit 1 ;;
  *disable*) for u in "$@"; do rm -f "$FAKE/enabled-$u"; done ;;
  *list-units*|*list-unit-files*) [[ -f "$FAKE/gateways" ]] && cat "$FAKE/gateways" ;;
  *" cat "*) if [[ -f "$FAKE/unit-$unit" ]]; then
               # Like systemctl: the unit, then its drop-ins in a later write (a reader
               # gone by then kills it with SIGPIPE: exit 141).
               head -n 1 "$FAKE/unit-$unit"; [[ -f "$FAKE/slow-cat" ]] && sleep 0.3
               exec tail -n +2 "$FAKE/unit-$unit"
             else echo "Environment=HERMES_HOME=$FAKE_DATA/hermes/agos-ws1"; fi ;;
esac
exit 0
""",
    "curl": """#!/usr/bin/env bash
echo "curl $*" >> "$FAKE/calls"
url="${@: -1}"
[[ -f "$FAKE/down" ]] && exit 7
if [[ "$url" == *"/health?deep=1" && -f "$FAKE/disk-full" ]]; then  # a 503 with its answer
  [[ " $* " == *" -f"* ]] && exit 22
  [[ " $* " == *" -o /dev/null "* ]] || echo '{"ok": false, "database": true, "disk": false, "loops": true}'
  exit 0
fi
[[ " $* " == *" -o /dev/null "* ]] && exit 0
case "$url" in
  *"/health?deep=1") echo '{"ok": true, "database": true, "disk": true, "loops": true}' ;;
  */health*) echo '{"ok": true}' ;;
  */workspaces) if [[ -f "$FAKE/workspaces" ]]; then cat "$FAKE/workspaces"; else echo '[{"id": "ws1"}]'; fi ;;
  */backups) if [[ -f "$FAKE/backup-fails" ]]; then echo '{"hasPassword": true, "lastError": "Hermes said no"}'
             else echo '{"hasPassword": false}'; fi ;;
  */backups/run) [[ -f "$FAKE/backup-fails" ]] && exit 22 ;;
  */diagnostics) echo '{"madeAt": "2026-11-02T00:00:00Z", "text": "## AGOS diagnostics\\nok"}' ;;
  *) [[ "$*" == *http_code* ]] && printf 200 ;;
esac
exit 0
""",
    "pnpm": """#!/usr/bin/env bash
echo "pnpm $*" >> "$FAKE/calls"
[[ -x "$FAKE/on-build" && "$*" == *build* ]] && "$FAKE/on-build"
exit 0
""",
    "systemd-run": """#!/usr/bin/env bash
echo "systemd-run $*" >> "$FAKE/calls"
[[ -f "$FAKE/no-systemd-run" ]] && exit 1
exit 0
""",
    # `sqlite3`: fails on a rolled-from copy when $FAKE/no-copy exists; with
    # $FAKE/die-mid-snapshot, copies an update snapshot's database, then kills the
    # update (a crash before roots.tar and the gateways list).
    "sqlite3": """#!/usr/bin/env bash
[[ -f "$FAKE/no-copy" && "$*" == *rolled-from* ]] && exit 1
if [[ -f "$FAKE/die-mid-snapshot" && "$*" == *update-* ]]; then /usr/bin/sqlite3 "$@"; kill -9 "$PPID"; exit 1; fi
exec /usr/bin/sqlite3 "$@"
""",
    # `df`: a nearly full disk when $FAKE/no-room exists, else the real one.
    "df": """#!/usr/bin/env bash
if [[ -f "$FAKE/no-room" ]]; then
  printf 'Filesystem 1-blocks Used Available Capacity Mounted on\\nfake 100000000 99990000 10000 100%% /\\n'
  exit 0
fi
exec /usr/bin/df "$@"
""",
    "uv": """#!/usr/bin/env bash
exit 0
""",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(cwd), *args],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


def _exe(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@dataclass
class Machine:
    root: Path
    app: Path
    data: Path
    backups: Path
    origin: Path
    env: dict[str, str]

    def agos(self, *args: str, check: bool = True, **env: str) -> subprocess.CompletedProcess[str]:
        done = subprocess.run(  # noqa: S603
            ["bash", str(AGOS), *args],  # noqa: S607
            env={**self.env, **env}, capture_output=True, text=True, timeout=120, check=False,
        )  # fmt: skip
        if check and done.returncode != 0:
            raise AssertionError(f"agos {args} rc={done.returncode}\n{done.stdout}\n{done.stderr}")
        return done

    def release(self, message: str, pin: str = "aaaa") -> str:
        src = self.root / "src"
        (src / "deploy" / "hermes.pin").write_text(pin + "\n")
        (src / "notes.txt").write_text(message + "\n")
        _git(src, "add", ".")
        _git(src, "commit", "-q", "-m", message)
        _git(src, "push", "-q", "origin", "main")
        return _git(src, "rev-parse", "HEAD")

    def db_value(self) -> str:
        conn = sqlite3.connect(self.data / "system" / "agos.db")
        try:
            return str(conn.execute("SELECT v FROM t").fetchone()[0])
        finally:
            conn.close()

    def set_db_value(self, value: str) -> None:
        conn = sqlite3.connect(self.data / "system" / "agos.db")
        conn.execute("UPDATE t SET v = ?", (value,))
        conn.commit()
        conn.close()

    @property
    def root_config(self) -> Path:
        return self.data / "hermes" / "agos-ws1" / "config.yaml"

    @property
    def snaps(self) -> Path:
        """Update snapshots hold keys: in AGOS's data folder, never the backup folder."""
        return self.data / "system" / "update-snapshots"

    def snapshots(self) -> list[Path]:
        return sorted(self.snaps.glob("update-*"))

    def rolled_from(self) -> list[Path]:
        return sorted(self.snaps.glob("rolled-from-*"))


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    src, origin, app = tmp_path / "src", tmp_path / "origin.git", tmp_path / "home" / "agos"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "T")
    (src / "deploy").mkdir()
    (src / "deploy" / "hermes.pin").write_text("aaaa\n")
    (src / "VERSION").write_text("0.1.0\n")
    (src / "services" / "core").mkdir(parents=True)
    (src / "services" / "core" / "pyproject.toml").write_text("")
    _git(src, "add", ".")
    _git(src, "commit", "-q", "-m", "First release")
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(origin)], check=True)  # noqa: S603,S607
    _git(src, "remote", "add", "origin", str(origin))
    subprocess.run(["git", "clone", "-q", str(origin), str(app)], check=True)  # noqa: S603,S607
    home = tmp_path / "home"
    data, backups = home / "agos-data", home / "agos-backups"
    (data / "system").mkdir(parents=True)
    (data / "system" / "internal.token").write_text("tok")
    conn = sqlite3.connect(data / "system" / "agos.db")
    conn.execute("CREATE TABLE t (v TEXT)")
    conn.execute("INSERT INTO t VALUES ('before')")
    conn.commit()
    conn.close()
    root = data / "hermes" / "agos-ws1"
    (root / "profiles" / "a-writer" / "cron").mkdir(parents=True)
    (root / "sessions").mkdir()
    (root / "config.yaml").write_text("model: old\n")
    (root / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
    (root / "sessions" / "s1.json").write_text("{}")
    (root / "profiles" / "a-writer" / "config.yaml").write_text("member: old\n")
    (root / "profiles" / "a-writer" / "cron" / "jobs.json").write_text('{"jobs": []}')
    (data / "hermes-managed").mkdir()
    (data / "hermes-managed" / "config.yaml").write_text("managed: old\n")
    fake = tmp_path / "fake"
    bin_dir = fake / "bin"
    for name, text in SHIMS.items():
        _exe(bin_dir / name, text)
    _exe(home / ".local" / "bin" / "hermes", "#!/usr/bin/env bash\necho 'Hermes v0 (aaaa)'\n")
    _exe(home / ".local" / "bin" / "uv", "#!/usr/bin/env bash\nexit 0\n")
    user = subprocess.run(["id", "-un"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S607
    conf = fake / "agos.conf"
    conf.write_text(
        f"AGOS_USER={user}\nAGOS_HOME={home}\nAGOS_APP={app}\nAGOS_DATA_DIR={data}\n"
        f"AGOS_BACKUP_DIR={backups}\nAGOS_REF=main\nAGOS_CHANNEL=main\nAGOS_REPO_URL={origin}\n"
    )
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "AGOS_CONF": str(conf),
        "AGOS_WAIT_TRIES": "2",
        "AGOS_WAIT_SLEEP": "0",
        "AGOS_WATCH_EVERY_S": "0",
        "FAKE": str(fake),
        "FAKE_DATA": str(data),
        "TMPDIR": str(tmp_path),
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }
    return Machine(tmp_path, app, data, backups, origin, env)


def test_an_update_snapshots_the_hermes_roots_config_but_not_their_sessions(
    machine: Machine,
) -> None:
    machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    tar = snap / "roots.tar"
    assert stat.S_IMODE(tar.stat().st_mode) == 0o600
    names = subprocess.run(  # noqa: S603
        ["tar", "-tf", str(tar)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert "hermes/agos-ws1/config.yaml" in names
    assert "hermes/agos-ws1/.env" in names
    assert "hermes/agos-ws1/profiles/a-writer/config.yaml" in names
    assert "hermes/agos-ws1/profiles/a-writer/cron/jobs.json" in names
    assert "hermes-managed/config.yaml" in names
    assert not [n for n in names if "sessions" in n]


def test_a_failed_update_puts_the_roots_files_back_too(machine: Machine) -> None:
    old = _git(machine.app, "rev-parse", "HEAD")
    machine.release("A release that rewrites root config and then fails")
    # The new release's build rewrites a root's config, then the core never answers.
    _exe(
        Path(machine.env["FAKE"]) / "on-build",
        f"#!/usr/bin/env bash\necho 'model: new' > {machine.root_config}\n"
        f"[[ -f {machine.env['FAKE']}/built-once ]] || {{ touch {machine.env['FAKE']}/built-once;"
        f" touch {machine.env['FAKE']}/down; }}\n",
    )
    done = machine.agos("update", "--yes", check=False)
    assert done.returncode == 1
    Path(machine.env["FAKE"], "down").unlink(missing_ok=True)
    assert _git(machine.app, "rev-parse", "HEAD") == old
    # The old release's rebuild ran the hook again (no "down" then): the roots tar
    # is put back AFTER the rebuild, so the file is the old one.
    assert machine.root_config.read_text() == "model: old\n"
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state["rolled_back"] is True and state["phase"] == "failed"


def test_agos_rollback_goes_back_to_the_last_update_and_keeps_the_newer_data_aside(
    machine: Machine,
) -> None:
    old = _git(machine.app, "rev-parse", "HEAD")
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    assert _git(machine.app, "rev-parse", "HEAD") == new
    machine.set_db_value("after")
    machine.root_config.write_text("model: new\n")
    machine.agos("rollback", "--yes")
    assert _git(machine.app, "rev-parse", "HEAD") == old
    assert machine.db_value() == "before"
    assert machine.root_config.read_text() == "model: old\n"
    [kept_dir] = machine.rolled_from()
    kept = sqlite3.connect(kept_dir / "agos.db")
    assert kept.execute("SELECT v FROM t").fetchone()[0] == "after"
    kept.close()
    assert (kept_dir / "roots.tar").is_file()
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state["rolled_back"] is True


def test_agos_rollback_without_an_update_says_so(machine: Machine) -> None:
    done = machine.agos("rollback", "--yes", check=False)
    assert done.returncode == 1
    assert "No update to roll back" in done.stderr


def test_a_good_update_starts_the_watch(machine: Machine) -> None:
    machine.release("Second release")
    machine.agos("update", "--yes")
    calls = (Path(machine.env["FAKE"]) / "calls").read_text()
    assert "systemd-run --user --unit=agos-update-watch" in calls
    assert "update-watch" in calls


def test_the_watch_rolls_back_after_three_failed_checks(machine: Machine) -> None:
    old = _git(machine.app, "rev-parse", "HEAD")
    machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    Path(machine.env["FAKE"], "down").touch()
    env = {**machine.env, "AGOS_WATCH_MINUTES": "1", "AGOS_WATCH_FAILS": "3"}
    done = subprocess.run(  # noqa: S603
        ["bash", str(AGOS), "update-watch", snap.name],  # noqa: S607
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    Path(machine.env["FAKE"], "down").unlink()
    assert "rolling back" in (done.stdout + done.stderr).lower()
    assert _git(machine.app, "rev-parse", "HEAD") == old
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state["rolled_back"] is True and "health" in state["error"]


def test_an_update_stops_the_last_updates_watch(machine: Machine) -> None:
    machine.release("Second release")
    machine.agos("update", "--yes")
    machine.release("Third release")
    calls = Path(machine.env["FAKE"], "calls")
    calls.write_text("")
    machine.agos("update", "--yes")
    lines = calls.read_text().splitlines()
    stop = next(i for i, c in enumerate(lines) if "--user stop agos-update-watch" in c)
    build = next(i for i, c in enumerate(lines) if c.startswith("pnpm"))
    assert stop < build


def test_an_update_keeps_a_hermes_that_is_on_the_pin_even_when_it_says_much(
    machine: Machine,
) -> None:
    """`hermes --version | grep -q <pin>` under pipefail: grep stops at the first
    line, Hermes gets SIGPIPE writing the rest, the check reads as 'not on the pin'
    and the update reinstalls Hermes from the network."""
    lines = "".join(f"line {n} " + "y" * 200 + "\n" for n in range(2000))
    (machine.root / "home" / ".local" / "bin" / "hermes").write_text(
        f"#!/usr/bin/env bash\necho 'Hermes v0 (bbbb)'\ncat <<'EOF'\n{lines}EOF\n"
    )
    machine.release("Second release, Hermes already on its new pin", pin="bbbb")
    machine.agos("update", "--yes")
    calls = (Path(machine.env["FAKE"]) / "calls").read_text()
    assert "install.sh" not in calls


def test_agos_version_shows_hermess_first_line_only(machine: Machine) -> None:
    """`hermes --version | head -1 || echo "not found"`: head's early exit SIGPIPEd
    Hermes, so a working Hermes printed its line AND 'not found'."""
    lines = "".join(f"line {n} " + "y" * 200 + "\n" for n in range(2000))
    (machine.root / "home" / ".local" / "bin" / "hermes").write_text(
        f"#!/usr/bin/env bash\necho 'Hermes v0 (aaaa)'\ncat <<'EOF'\n{lines}EOF\n"
    )
    out = machine.agos("version").stdout
    assert "Hermes Hermes v0 (aaaa) — pin aaaa" in out
    assert "not found" not in out


def _watch_pid_file(machine: Machine) -> Path:
    return machine.data / "system" / "agos-update-watch.pid"


def test_stopping_with_a_gone_watch_pid_says_nothing(machine: Machine) -> None:
    """The last watch ended long ago: its pid file names a process that is gone.
    `tr < /proc/<pid>/cmdline 2>/dev/null` opened the file before hiding errors, so
    every stop printed '/proc/<pid>/cmdline: No such file or directory'."""
    gone = subprocess.Popen(["true"])  # noqa: S607
    gone.wait()
    _watch_pid_file(machine).write_text(f"{gone.pid}\n")
    done = machine.agos("stop")
    assert "No such file" not in done.stderr, done.stderr
    assert "cmdline" not in done.stderr, done.stderr


def test_stopping_kills_a_running_nohup_watch_only(machine: Machine) -> None:
    """The nohup fallback's watch is found by its command line (read whole, no
    `| grep -q` under pipefail: an early grep exit SIGPIPEs tr and the check fails)."""
    watch = subprocess.Popen(  # noqa: S603
        # Lines (grep reads whole lines) and far more than a pipe holds after the match.
        [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            "update-watch\n",
            *["x\n" * 50_000] * 10,
        ],
    )
    other = subprocess.Popen(["sleep", "60"])  # noqa: S607
    try:
        _watch_pid_file(machine).write_text(f"{watch.pid}\n")
        machine.agos("stop")
        try:
            ended = watch.wait(timeout=10) != 0
        except subprocess.TimeoutExpired:
            ended = False
        assert ended, "the nohup watch was not stopped"
        _watch_pid_file(machine).write_text(f"{other.pid}\n")
        machine.agos("stop")
        assert other.poll() is None  # not a watch: left alone
    finally:
        for proc in (watch, other):
            proc.kill()
            proc.wait()


def test_a_watch_never_rolls_back_a_later_release(machine: Machine) -> None:
    machine.release("Second release")
    machine.agos("update", "--yes")
    first = machine.snapshots()[0]
    third = machine.release("Third release")
    machine.agos("update", "--yes")
    Path(machine.env["FAKE"], "down").touch()
    env = {**machine.env, "AGOS_WATCH_MINUTES": "1", "AGOS_WATCH_FAILS": "1"}
    done = subprocess.run(  # noqa: S603
        ["bash", str(AGOS), "update-watch", first.name],  # noqa: S607
        env=env, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    Path(machine.env["FAKE"], "down").unlink()
    assert "not rolling back" in done.stderr
    assert _git(machine.app, "rev-parse", "HEAD") == third


def test_the_watch_ends_quietly_when_all_is_well(machine: Machine) -> None:
    new = machine.release("Second release")
    machine.agos("update", "--yes")
    [snap] = machine.snapshots()
    env = {**machine.env, "AGOS_WATCH_MINUTES": "0"}
    done = subprocess.run(  # noqa: S603
        ["bash", str(AGOS), "update-watch", snap.name],  # noqa: S607
        env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert _git(machine.app, "rev-parse", "HEAD") == new
    state = json.loads((machine.data / "system" / "agos-update.json").read_text())
    assert state.get("watch") == "ok"


def test_doctor_bundle_writes_the_report_to_a_private_file(machine: Machine) -> None:
    out = machine.root / "report.md"
    machine.agos("doctor", "--bundle", str(out))
    assert out.read_text().startswith("## AGOS diagnostics")
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_an_update_across_many_releases_runs(machine: Machine) -> None:
    """Ops VM: an update across 93 commits ended silently right after its list of
    changes: `git log | head -20` under pipefail, git got SIGPIPE once head had its
    20 lines, and set -e stopped the update. Long subjects (more than the pipe holds
    after head's 20 lines) make git always still be writing when head closes it."""
    last = ""
    for n in range(40):
        last = machine.release(f"Release {n} " + "x" * 8000)
    check = machine.agos("update", "--check")
    assert "New AGOS release" in check.stdout
    machine.agos("update", "--yes")
    assert _git(machine.app, "rev-parse", "HEAD") == last


def test_the_script_passes_shellcheck() -> None:
    if not any(os.access(Path(p) / "shellcheck", os.X_OK) for p in os.environ["PATH"].split(":")):
        pytest.skip("shellcheck not installed")
    done = subprocess.run(  # noqa: S603
        ["shellcheck", "-x", "-S", "warning", str(AGOS)],  # noqa: S607
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout


def _plugin_release(machine: Machine, message: str) -> str:
    """A release that changes the agos-guard plugin and keeps the Hermes pin."""
    src = machine.root / "src"
    plugin = src / "services" / "core" / "src" / "agos_core" / "hermes_plugin" / "agos_guard"
    plugin.mkdir(parents=True, exist_ok=True)
    (plugin / "__init__.py").write_text(f"# {message}\n")
    return machine.release(message)


@pytest.mark.parametrize("plugin_changed", [True, False])
def test_gateways_restart_when_the_plugin_changes_even_on_the_same_hermes(
    machine: Machine, plugin_changed: bool
) -> None:
    """Running gateways keep the agos-guard plugin they loaded: an update that changes
    it restarts them after AGOS is up (the upgrade VM test found an old plugin still
    answering after an update from a pre-public build). Same Hermes, no plugin change: they keep running."""
    fake = Path(machine.env["FAKE"])
    (fake / "gateways").write_text("hermes-gateway-agos-ws1.service\n")
    if plugin_changed:
        _plugin_release(machine, "Plugin fix")
    else:
        machine.release("Core-only release")
    machine.agos("update", "--yes")
    calls = (fake / "calls").read_text().splitlines()
    stops = [c for c in calls if " stop hermes-gateway-agos-ws1.service" in c]
    starts = [c for c in calls if " start hermes-gateway-agos-ws1.service" in c]
    assert (len(stops), len(starts)) == ((1, 1) if plugin_changed else (0, 0)), calls
    if plugin_changed:  # started again only once AGOS (which installs the plugin) is up
        assert calls.index(starts[0]) > max(
            i for i, c in enumerate(calls) if "start agos-core" in c or "restart agos-core" in c
        )
