"""deploy/agos-staging.sh against the fake machine of test_agos_cli: the copy gets
live's newest backup under its own names, paths, ports and units, and never
touches live's data, roots or Hermes's shared home."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

from test_agos_cli import Machine, _exe, machine  # noqa: F401 - fixture
from test_agos_cli import pytestmark as pytestmark

STAGING = Path(__file__).resolve().parents[3] / "deploy" / "agos-staging.sh"
OWN = STAGING.parent / "staging-own-paths.py"

RESTORE = """#!/usr/bin/env bash
# The fake uv: `uv run ... restore_and_verify.py <backup> <target>` makes a restore.
for a in "$@"; do last1="$a"; done
if [[ "$*" == *restore_and_verify.py* ]]; then
  t="$last1"
  [[ -d "$t" ]] && stat -c %a "$t" > "$FAKE/restore-mode"
  mkdir -p "$t/agos-data/system" "$t/hermes/roots"
  sqlite3 "$t/agos-data/system/agos.db" "CREATE TABLE t (v TEXT); INSERT INTO t VALUES ('from-backup')"
  echo zip > "$t/hermes/roots/agos-ws1.zip"
  echo zip > "$t/hermes/hermes-backup.zip"
fi
exit 0
"""

HERMES = """#!/usr/bin/env bash
# The fake hermes: `import --force <zip>` into $HERMES_HOME (a root), with the live
# install's paths in it, as a real root's settings, member profiles, cron jobs and
# Kanban board would have. `config set` is logged.
echo "${HERMES_HOME:-} $*" >> "$FAKE/hermes-calls"
if [[ "${1:-}" == import ]]; then
  if [[ -z "${HERMES_HOME:-}" ]]; then touch "$FAKE/shared-home-imported"; exit 0; fi
  [[ -f "$FAKE/import-fails" ]] && exit 1
  cat > "$HERMES_HOME/config.yaml" <<EOF
terminal:
  docker_volumes: ['$FAKE_DATA/workspaces/ws1/files:/workspace']
  docker_extra_args: ['--network=agos-net-agos-ws1']
  docker_env: {HTTP_PROXY: 'http://agos-egress:8888'}
EOF
  p="$HERMES_HOME/profiles/a-writer"
  mkdir -p "$p/cron"
  echo "model: x" > "$p/config.yaml"
  echo "home: $FAKE_DATA/hermes/agos-ws1/profiles/a-writer" > "$p/profile.yaml"
  echo '{"jobs": [{"id": "j1", "workdir": "'"$FAKE_DATA"'/workspaces/ws1/files"}]}' > "$p/cron/jobs.json"
  sqlite3 "$HERMES_HOME/kanban.db" "CREATE TABLE tasks (id INTEGER, workspace_path TEXT);
    INSERT INTO tasks VALUES (1, '$FAKE_DATA/workspaces/ws1/files/cards/1')"
  exit 0
fi
echo 'Hermes v0 (aaaa)'
"""

DOCKER = """#!/usr/bin/env bash
echo "docker $*" >> "$FAKE/calls"
if [[ "$1 $2" == "ps -a" && "$*" == *hermes-agent=1* ]]; then
  printf 'c-stg stg-ws1-0123456789ab\\nc-live agos-ws1-0123456789ab\\n'
fi
exit 0
"""


def _run(m: Machine, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    base = m.root / "home" / "agos-staging"
    full = {
        **m.env,
        "AGOS_UNIT_DIR": str(m.root / "units"),
        "AGOS_STAGING_CONF": str(m.root / "staging.conf"),
        "AGOS_STAGING_NO_BUILD": "1",
        "AGOS_STAGING_NO_START": "1",
        "AGOS_BACKUP_PASSWORD": "not-used-by-the-fake",
        "AGOS_STAGING_DIR": str(base),
        **env,
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(STAGING), *args],  # noqa: S607
        env=full, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip


def _setup(m: Machine) -> Path:
    home = m.root / "home"
    _exe(home / ".local" / "bin" / "uv", RESTORE)
    _exe(home / ".local" / "bin" / "hermes", HERMES)
    m.backups.mkdir(exist_ok=True)
    (m.backups / "agos-backup-20261101-000000.agosb").write_bytes(b"x")
    return home / "agos-staging"


def test_status_without_a_copy_says_so(machine: Machine) -> None:  # noqa: F811
    done = _run(machine, "status")
    assert done.returncode == 0 and "No staging copy" in done.stdout


def test_up_makes_a_quiet_copy_under_its_own_names(machine: Machine) -> None:  # noqa: F811
    base = _setup(machine)
    live_root = machine.root_config.read_text()
    done = _run(machine, "up")
    assert done.returncode == 0, done.stdout + done.stderr
    data = base / "data"
    # The data is the backup's; live's database and roots are untouched.
    conn = sqlite3.connect(data / "system" / "agos.db")
    assert conn.execute("SELECT v FROM t").fetchone()[0] == "from-backup"
    conn.close()
    assert machine.db_value() == "before"
    assert machine.root_config.read_text() == live_root
    # The root under staging's prefix, with staging's own paths, network and proxy.
    config = (data / "hermes" / "stg-ws1" / "config.yaml").read_text()
    assert not (data / "hermes" / "agos-ws1").exists()
    assert str(machine.data) + "/" not in config
    assert f"{data}/workspaces/ws1/files" in config
    assert "agos-net-stg-ws1" in config and "http://agos-stg-egress:" in config
    # Hermes's shared home (live's ~/.hermes) is never imported.
    assert not (Path(machine.env["FAKE"]) / "shared-home-imported").exists()
    # Its own units, ports and quiet switches; its Update button refuses.
    core = (machine.root / "units" / "agos-staging-core.service").read_text()
    for line in (
        "--port 8866",
        "Environment=AGOS_STAGING=1",
        "Environment=AGOS_PROFILE_PREFIX=stg-",
        "Environment=AGOS_EGRESS_NAME=agos-stg-egress",
        "Environment=AGOS_HOOKS_PORT=8867",
        f"Environment=AGOS_DATA_DIR={data}",
    ):
        assert line in core
    assert "[Install]" not in core  # never started at boot
    web = (machine.root / "units" / "agos-staging-web.service").read_text()
    assert "-p 3100" in web and "AGOS_CORE_URL=http://127.0.0.1:8866" in web
    # Live's limits (install-server.sh): a runaway staging copy can't take the machine.
    hooks = (machine.root / "units" / "agos-staging-hooks.service").read_text()
    for unit, tasks in ((core, 512), (hooks, 64), (web, 256)):
        assert "\nMemoryMax=" in unit and f"\nTasksMax={tasks}\n" in unit
    assert "\nMemoryHigh=" in core
    assert f"AGOS_LOCAL_REPO={base / 'app'}" in (machine.root / "staging.conf").read_text()
    # The checkout is a worktree at live's release.
    head = subprocess.run(  # noqa: S603
        ["git", "-C", str(base / "app"), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    live = subprocess.run(  # noqa: S603
        ["git", "-C", str(machine.app), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert head == live


def test_refresh_replaces_only_stagings_data(machine: Machine) -> None:  # noqa: F811
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    (base / "data" / "stale.txt").write_text("old staging file")
    done = _run(machine, "refresh")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (base / "data" / "stale.txt").exists()
    assert (base / "data" / "hermes" / "stg-ws1" / "config.yaml").is_file()
    assert machine.db_value() == "before"


def test_refresh_needs_a_backup(machine: Machine) -> None:  # noqa: F811
    _setup(machine)
    assert _run(machine, "up").returncode == 0
    for f in machine.backups.glob("*.agosb"):
        f.unlink()
    done = _run(machine, "refresh")
    assert done.returncode == 1 and "agos backup first" in done.stderr


def test_down_purge_removes_the_copy_and_its_units_only(machine: Machine) -> None:  # noqa: F811
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    done = _run(machine, "down", "--purge")
    assert done.returncode == 0, done.stderr
    assert not base.exists()
    assert not list((machine.root / "units").glob("agos-staging-*"))
    assert machine.root_config.is_file() and machine.db_value() == "before"


# ---- the independent review of eng/ops -------------------------------------------


def test_refresh_gives_every_root_file_stagings_own_paths(machine: Machine) -> None:  # noqa: F811
    """M3: settings, member profiles, cron jobs and the Kanban board, not only
    config.yaml; and the copy's check finds no live path left."""
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    root = base / "data" / "hermes" / "stg-ws1"
    live = str(machine.data)
    member = root / "profiles" / "a-writer"
    for f in (root / "config.yaml", member / "profile.yaml", member / "cron" / "jobs.json"):
        assert live + "/" not in f.read_text(), f
    assert f"{base}/data/hermes/stg-ws1/profiles/a-writer" in (member / "profile.yaml").read_text()
    conn = sqlite3.connect(root / "kanban.db")
    [(path,)] = conn.execute("SELECT workspace_path FROM tasks").fetchall()
    conn.close()
    assert path == f"{base}/data/workspaces/ws1/files/cards/1"
    check = subprocess.run(  # noqa: S603
        ["python3", str(OWN), "check", str(base / "data" / "hermes"), live],  # noqa: S607
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert check.returncode == 0, check.stdout


def test_refresh_turns_hermes_kanban_dispatcher_off_in_every_home(machine: Machine) -> None:  # noqa: F811
    """M3: copied cards would be worked with the provider logins staging shares."""
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    calls = (Path(machine.env["FAKE"]) / "hermes-calls").read_text().splitlines()
    off = {c.split(" ", 1)[0] for c in calls if "config set kanban.dispatch_in_gateway false" in c}
    root = base / "data" / "hermes" / "stg-ws1"
    assert off == {str(root), str(root / "profiles" / "a-writer")}


def test_down_turns_stagings_gateways_off_for_good(machine: Machine) -> None:  # noqa: F811
    """M4: a stopped staging copy does not come back at the next boot."""
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    fake = Path(machine.env["FAKE"])
    unit = "hermes-gateway-stg-ws1.service"
    (fake / "gateways").write_text(unit + "\n")
    (fake / f"unit-{unit}").write_text(f"Environment=HERMES_HOME={base}/data/hermes/stg-ws1\n")
    (fake / f"enabled-{unit}").touch()
    done = _run(machine, "down")
    assert done.returncode == 0, done.stderr
    assert f"--user disable --now {unit}" in (fake / "calls").read_text()
    assert not (fake / f"enabled-{unit}").exists()
    assert (base / "data").is_dir()  # down without --purge keeps the data


def test_down_finds_a_gateway_whose_unit_comes_in_two_writes(machine: Machine) -> None:  # noqa: F811
    """Ops VM: `systemctl cat | grep -q` under pipefail: grep stops at the first
    match, cat dies of SIGPIPE (141) and the pipeline reads as no match, so a
    caged gateway's long unit was missed now and then (left enabled at boot)."""
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    fake = Path(machine.env["FAKE"])
    unit = "hermes-gateway-stg-ws1.service"
    (fake / "gateways").write_text(unit + "\n")
    drop_in = "# " + "x" * 200 + "\n"
    (fake / f"unit-{unit}").write_text(
        f"Environment=HERMES_HOME={base}/data/hermes/stg-ws1\n" + drop_in * 2000
    )
    (fake / "slow-cat").touch()
    (fake / f"enabled-{unit}").touch()
    assert _run(machine, "down").returncode == 0
    assert f"--user disable --now {unit}" in (fake / "calls").read_text()


def test_staging_runs_its_own_sandbox_broker_and_never_touches_lives(
    machine: Machine,  # noqa: F811
) -> None:
    """Ops VM: both cores wrote the one agos-sandboxd.service; staging's took over
    (its policies, its checkout), live's gateways lost their Docker socket, and the
    purge deleted the checkout the broker ran from. Staging gets its own broker
    unit and socket folder; down stops it, --purge removes it, live's stays."""
    base = _setup(machine)
    assert _run(machine, "up").returncode == 0
    core = (machine.root / "units" / "agos-staging-core.service").read_text()
    assert "Environment=AGOS_SANDBOXD_UNIT=agos-stg-sandboxd.service" in core
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S607
    # Inside live's family folder: every cage hides the whole family (review H1).
    assert f"Environment=AGOS_SANDBOXD_RUN_DIR=/run/user/{uid}/agos-sandboxd/stg" in core
    units = machine.root / "home" / ".config" / "systemd" / "user"
    units.mkdir(parents=True, exist_ok=True)
    (units / "agos-stg-sandboxd.service").write_text("[Service]\n")
    (units / "agos-sandboxd.service").write_text("[Service]\n")  # live's
    assert _run(machine, "down").returncode == 0
    calls = (Path(machine.env["FAKE"]) / "calls").read_text()
    assert "--user disable --now agos-stg-sandboxd.service" in calls
    assert (units / "agos-stg-sandboxd.service").is_file()  # down keeps it
    assert _run(machine, "down", "--purge").returncode == 0
    assert not (units / "agos-stg-sandboxd.service").exists()
    assert (units / "agos-sandboxd.service").is_file()
    assert not base.exists()
    calls = (Path(machine.env["FAKE"]) / "calls").read_text()
    assert " agos-sandboxd.service" not in calls


def test_purge_removes_stagings_sandboxes_before_its_networks(machine: Machine) -> None:  # noqa: F811
    """M4: a staging sandbox holds its network: rm -f it first, never a live one."""
    _setup(machine)
    _exe(Path(machine.env["FAKE"]) / "bin" / "docker", DOCKER)
    assert _run(machine, "up").returncode == 0
    assert _run(machine, "down", "--purge").returncode == 0
    lines = (Path(machine.env["FAKE"]) / "calls").read_text().splitlines()
    rm = next(i for i, c in enumerate(lines) if c.startswith("docker rm -f") and "c-stg" in c)
    net = next(i for i, c in enumerate(lines) if c.startswith("docker network ls"))
    assert rm < net
    assert not [c for c in lines if c.startswith("docker rm") and "c-live" in c]


def test_refresh_refuses_when_stagings_data_would_be_lives(machine: Machine) -> None:  # noqa: F811
    """The guard was always true (DATA is BASE/data by construction): it now compares
    with live's data folder itself."""
    _setup(machine)
    live = machine.root / "home" / "data"
    machine.data.rename(live)
    conf = Path(machine.env["FAKE"]) / "agos.conf"
    conf.write_text(conf.read_text().replace(str(machine.data), str(live)))
    home = str(machine.root / "home")
    assert _run(machine, "up", AGOS_STAGING_DIR=home).returncode == 0  # live's db: no refresh
    done = _run(machine, "refresh", AGOS_STAGING_DIR=home)
    assert done.returncode == 1 and "refusing" in done.stderr
    assert (live / "system" / "agos.db").is_file()


def test_a_failed_refresh_leaves_no_decrypted_copy(machine: Machine) -> None:  # noqa: F811
    base = _setup(machine)
    (Path(machine.env["FAKE"]) / "import-fails").touch()
    done = _run(machine, "up")
    assert done.returncode == 1
    assert not list(base.glob("restore-*"))
    assert (Path(machine.env["FAKE"]) / "restore-mode").read_text().strip() == "700"


def test_sudo_keeps_the_backup_password(machine: Machine) -> None:  # noqa: F811
    fake = Path(machine.env["FAKE"])
    _exe(fake / "bin" / "sudo", '#!/usr/bin/env bash\necho "sudo $*" >> "$FAKE/calls"\n')
    _run(machine, "up", AGOS_UNIT_DIR="/etc/systemd/system")
    assert "sudo --preserve-env=AGOS_BACKUP_PASSWORD -- bash" in (fake / "calls").read_text()


def test_own_paths_are_literal_text(tmp_path: Path) -> None:
    """Paths holding sed's special characters, and a sibling folder that only starts
    like live's, are handled as plain text."""
    live, stg = "/srv/a#b&c.d/agos-data", "/srv/stg&x/data"
    root = tmp_path / "hermes" / "stg-ws1"
    root.mkdir(parents=True)
    (root / "config.yaml").write_text(
        f"a: {live}/workspaces/ws1/files\nb: {live}2/other\nc: {live}/hermes/agos-ws1/x\n"
    )
    done = subprocess.run(  # noqa: S603
        ["python3", str(OWN), "fix", str(tmp_path / "hermes"), live, stg, "agos-", "stg-", "eg"],  # noqa: S607
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    text = (root / "config.yaml").read_text()
    assert f"a: {stg}/workspaces/ws1/files" in text
    assert f"b: {live}2/other" in text  # not live's folder
    assert f"c: {stg}/hermes/stg-ws1/x" in text


def test_the_script_passes_shellcheck() -> None:
    import shutil

    if shutil.which("shellcheck") is None:
        return
    done = subprocess.run(  # noqa: S603
        ["shellcheck", "-x", "-S", "warning", str(STAGING)],  # noqa: S607
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout
