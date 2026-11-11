"""The cage around each workspace's gateway (engine/cage.py + the sandbox broker
wiring in engine/hermes.py): bwrap hides the real Docker socket and the user bus,
DOCKER_HOST points at the workspace's own filtered socket, the drop-in survives
bwrap's missing SIGTERM forwarding (KillMode=control-group), and AGOS_SANDBOXD=off
restores today's behaviour exactly."""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from test_wall import HERMES_UNIT, _Runner, _volumes

from agos_core.config import (
    ConfigError,
    EngineConfig,
    _sandboxd,
    _sandboxd_run_dir,
    _sandboxd_unit,
)
from agos_core.engine import cage, root_unit, sandbox_broker, sandboxd, wall
from agos_core.engine.hermes import HermesEngine


# ---- the bwrap prefix -------------------------------------------------------------
def test_the_cage_masks_docker_the_bus_and_every_other_workspaces_socket(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "systemd").mkdir(parents=True)
    (run_dir / "bus").touch()
    base = tmp_path / "sockets"
    own = base / "agos-alpha"
    own.mkdir(parents=True)
    (base / "agos-beta").mkdir()
    token = tmp_path / "system" / "internal.token"
    token.parent.mkdir()
    token.write_text("secret")
    argv = cage.argv(
        socket_dir=own,
        runtime_dir=run_dir,
        family=base,
        hidden_files=(token,),
        hidden_dirs=(token.parent,),
    )
    assert argv[0] == cage.BWRAP and argv[-1] == "--"
    text = " ".join(argv)
    assert f"--ro-bind /dev/null {run_dir / 'bus'}" in text
    assert f"--tmpfs {run_dir / 'systemd'}" in text
    # AGOS's own secrets: the token file is dead, the system folder is empty.
    assert f"--ro-bind /dev/null {token}" in text
    assert f"--tmpfs {token.parent}" in text
    # The container runtimes' other sockets (containerd's API, dockerd's own
    # folders) and the system D-Bus are closed wherever they exist on this machine.
    dirs_real = {str(Path(d).resolve()) for d in cage.RUNTIME_SOCKET_DIRS if Path(d).is_dir()}
    for folder in dirs_real:
        assert f"--tmpfs {folder}" in text, folder
    # Aliases (/var/run is a symlink to /run) are masked once, by one path.
    bus_real = {str(Path(b).resolve()) for b in cage.SYSTEM_BUS if Path(b).exists()}
    bus_masked = [b for b in cage.SYSTEM_BUS if f"--ro-bind /dev/null {b}" in text]
    assert len(bus_masked) == len(bus_real)
    # The sockets base is a tmpfs (siblings gone); only its own folder is bound back.
    assert f"--tmpfs {base} --bind {own} {own}" in text
    assert "--unsetenv INVOCATION_ID" in text
    assert f"--setenv DOCKER_HOST unix://{own / 'docker.sock'}" in text
    # The real Docker socket is masked once per real file (aliases like
    # /var/run/docker.sock resolve to the same file as /run/docker.sock).
    import os

    resolved = {os.path.realpath(s) for s in cage.DOCKER_SOCKETS if Path(s).exists()}
    masked = [s for s in cage.DOCKER_SOCKETS if f"--ro-bind /dev/null {s}" in text]
    assert len(masked) == len(resolved)


def test_staging_and_live_cages_hide_the_whole_broker_family(tmp_path: Path) -> None:
    """Review H1: staging's sockets sat beside live's (/run/user/<uid>/agos-stg-sandboxd),
    and the tmpfs covered only the caller's own run folder, so a staging gateway
    reached live's broker as any live workspace (and the reverse). Both instances
    now nest under one family folder, the tmpfs always covers that family, and only
    the caller's own socket folder is bound back."""
    family = tmp_path / "agos-sandboxd"
    live = family / "agos-ws1"
    stg = family / "stg" / "stg-ws1"
    for folder in (live, stg):
        folder.mkdir(parents=True)
    for own in (stg, live):
        argv = cage.argv(socket_dir=own, runtime_dir=tmp_path / "rt", family=family)
        text = " ".join(argv)
        assert f"--tmpfs {family} --bind {own} {own}" in text
        bound = [
            argv[i + 1] for i, a in enumerate(argv) if a in ("--bind", "--ro-bind", "--dev-bind")
        ]
        under = [b for b in bound if Path(b).is_relative_to(family)]
        assert under == [str(own)], under
    with pytest.raises(ValueError, match="family"):
        cage.argv(socket_dir=tmp_path / "elsewhere", runtime_dir=tmp_path / "rt", family=family)


def test_the_policy_lists_only_this_workspaces_folders(tmp_path: Path) -> None:
    root = tmp_path / "data" / "hermes" / "agos-alpha"
    other_root = tmp_path / "data" / "hermes" / "agos-beta"
    files = tmp_path / "data" / "workspaces" / "alpha" / "files"
    granted = tmp_path / "Projects"
    temp = tmp_path / ".agos-tmp" / "alpha"
    for folder in (root, other_root, files, granted, temp):
        folder.mkdir(parents=True)
    config = {
        "terminal": {"docker_volumes": [f"{files}:/workspace", f"{granted}:/shared/projects:ro"]},
        "skills": {"external_dirs": [str(tmp_path / "skills"), str(other_root / "skills")]},
    }
    policy = cage.policy(
        labels=["agos-alpha", "agos-alpha--a-writer"],
        images=["agos-sandbox:1", "agos-sandbox:desktop"],
        networks=["agos-net-agos-alpha"],
        root=root,
        temp_dir=temp,
        configs=[config],
        host_home=tmp_path,
        workspace_mount="/workspace",
    )
    assert policy["labels"] == ["agos-alpha", "agos-alpha--a-writer"]
    assert policy["images"] == ["agos-sandbox:1", "agos-sandbox:desktop"]
    assert set(policy["networks"]) == {"agos-net-agos-alpha", "none"}
    assert str(files) in policy["binds_rw"] and str(root) in policy["binds_rw"]
    assert str(granted) in policy["binds_ro"]
    assert str(tmp_path / "skills") in policy["binds_ro"]
    # Another workspace's folders are never bindable, whatever a config names.
    everything = json.dumps(policy)
    assert str(other_root) not in everything
    target = cage.write_policy(tmp_path / "pol", "agos-alpha", policy)
    stamp = target.stat().st_mtime_ns
    assert sandboxd.load_policy(target).labels == frozenset(policy["labels"])
    cage.write_policy(tmp_path / "pol", "agos-alpha", policy)  # unchanged: not rewritten
    assert target.stat().st_mtime_ns == stamp


def test_the_broker_unit_runs_the_stdlib_daemon_outside_the_cages(tmp_path: Path) -> None:
    text = cage.unit_text(
        script=tmp_path / "sandboxd.py",
        sockets_dir=tmp_path / "run",
        policies_dir=tmp_path / "pol",
    )
    assert "ExecStart=" in text and str(tmp_path / "sandboxd.py") in text
    assert "--sockets" in text and "--policies" in text and "--events" in text
    assert "Restart=always" in text and "MemoryMax=" in text and "TasksMax=" in text
    assert "NoNewPrivileges=yes" in text
    assert "bwrap" not in text and "wall.py" not in text


# ---- the config switch ------------------------------------------------------------
def test_agos_sandboxd_reads_required_off_and_nothing_else() -> None:
    """Audit F9: unset, the old "auto" and "on" all mean required."""
    assert _sandboxd({}) == "required"
    assert _sandboxd({"AGOS_SANDBOXD": "off"}) == "off"
    assert _sandboxd({"AGOS_SANDBOXD": " ON "}) == "required"
    assert _sandboxd({"AGOS_SANDBOXD": "auto"}) == "required"
    with pytest.raises(ConfigError):
        _sandboxd({"AGOS_SANDBOXD": "maybe"})
    assert _sandboxd_run_dir({}) is None
    with pytest.raises(ConfigError):
        _sandboxd_run_dir({"AGOS_SANDBOXD_RUN_DIR": "relative/x"})


def test_a_broker_run_dir_must_sit_inside_the_agos_sandboxd_family() -> None:
    """Review H1: the cage hides /run/user/<uid>/agos-sandboxd as a whole, so a run
    dir anywhere else would sit beside it, unhidden from the other AGOS's cages."""
    import os

    family = Path(f"/run/user/{os.getuid()}/agos-sandboxd")
    for ok in (family, family / "stg", family / "stg" / ""):
        assert _sandboxd_run_dir({"AGOS_SANDBOXD_RUN_DIR": str(ok)}) == Path(os.path.normpath(ok))
    for wrong in (
        f"/run/user/{os.getuid()}/agos-stg-sandboxd",
        f"/run/user/{os.getuid()}/agos-sandboxd-stg",
        f"{family}/../agos-stg-sandboxd",
        f"/run/user/{os.getuid() + 1}/agos-sandboxd/stg",
        "/var/agos-sandboxd",
    ):
        with pytest.raises(ConfigError, match="agos-sandboxd"):
            _sandboxd_run_dir({"AGOS_SANDBOXD_RUN_DIR": wrong})


# ---- the drop-in ------------------------------------------------------------------
def _caged_engine(tmp_path: Path, mode: str, runner: Any) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="agos-sandbox:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "data" / "hermes",
            runtime_dir=tmp_path / ".hermes" / "tools",
            gateway_supervisor="systemd",
            sandboxd=mode,
            sandboxd_run_dir=tmp_path / "run" / "agos-sandboxd",
        ),
        runner=runner,
    )


def _dropin(tmp_path: Path, mode: str, runner: _Runner) -> str:
    engine = _caged_engine(tmp_path, mode, runner)
    _volumes(
        engine.root("alpha"),
        [f"{tmp_path / 'data' / 'workspaces' / 'alpha' / 'files'}:/workspace"],
    )
    root_unit.remember(engine.root("alpha"), "hermes-gw-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(HERMES_UNIT)
    engine.refresh_dropin("alpha")
    return (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()


def test_the_dropin_cages_the_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage, "available", lambda: True)
    runner = _Runner()
    body = _dropin(tmp_path, "auto", runner)
    exec_line = next(ln for ln in body.splitlines() if ln.startswith("ExecStart=") and len(ln) > 11)
    # bwrap first, then the wall's launcher, then Hermes's own command.
    assert '"bwrap"' in exec_line
    assert exec_line.index('"bwrap"') < exec_line.index("wall.py")
    assert exec_line.index("wall.py") < exec_line.index("gateway")
    assert "DOCKER_HOST" in exec_line and "agos-sandboxd" in exec_line
    # bwrap does not forward SIGTERM: systemd signals the whole cgroup, and reload
    # reads the gateway's own JSON pid record.
    assert "KillMode=control-group" in body
    assert "ExecReload=" in body and "SIGUSR1" in body and "gateway.pid" in body
    # The broker itself was set up: policy written, unit written, systemctl asked.
    policies = tmp_path / "data" / "sandboxd"
    policy = json.loads((policies / "agos-alpha.policy.json").read_text())
    assert "agos-sandbox:1" in policy["images"]
    assert any("agos-alpha" in label for label in policy["labels"])
    unit_file = tmp_path / ".config" / "systemd" / "user" / cage.SERVICE
    assert unit_file.is_file() and "sandboxd" in unit_file.read_text()
    flat = [" ".join(call) for call in runner.calls]
    assert any("daemon-reload" in c for c in flat)
    assert any(f"enable --now {cage.SERVICE}" in c for c in flat)


def test_sandboxd_off_keeps_todays_dropin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cage, "available", lambda: True)
    body = _dropin(tmp_path, "off", _Runner())
    assert '"bwrap"' not in body and "KillMode" not in body and "DOCKER_HOST" not in body
    assert "wall.py" in body  # the wall stays
    assert not (tmp_path / ".config" / "systemd" / "user" / cage.SERVICE).exists()


def test_without_bwrap_every_mode_but_off_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Audit F9: no bwrap used to start every gateway uncaged under "auto". Now the
    drop-in is never written without the cage, and the refusal is a Problem the
    owner sees: an ERROR on an agos.* logger (actions/system_log.py)."""
    monkeypatch.setattr(cage, "available", lambda: False)
    monkeypatch.setattr(cage, "_told_missing", [])
    monkeypatch.setattr(cage, "_told_at", {})
    with caplog.at_level(logging.ERROR, logger="agos"), pytest.raises(FileNotFoundError):
        _dropin(tmp_path, "required", _Runner())  # refused: no drop-in written
    missing = [r for r in caplog.records if "bubblewrap" in r.getMessage()]
    assert missing and missing[0].levelno == logging.ERROR
    assert missing[0].name.startswith("agos.")
    for mode in ("required", "auto", "on"):
        with pytest.raises(Exception, match="cage_refused"):
            _caged_engine(tmp_path, mode, _Runner()).sandboxd_on()


def test_a_second_agos_on_this_user_runs_its_own_broker_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Staging beside live: one agos-sandboxd.service for both let staging's core
    replace live's broker. AGOS_SANDBOXD_UNIT names this AGOS's own."""
    monkeypatch.setattr(cage, "available", lambda: True)
    assert _sandboxd_unit({}) == "agos-sandboxd.service"
    assert _sandboxd_unit({"AGOS_SANDBOXD_UNIT": "agos-stg-sandboxd.service"}) == (
        "agos-stg-sandboxd.service"
    )
    for wrong in (
        "../x.service",
        "agos-sandboxd",
        "hermes-gateway-1.service",
        "agos-a b.service",
        # Review L4: another AGOS unit (ensure() would overwrite it).
        "agos-update-watch.service",
        "agos-core.service",
        "agos-sandboxd-x.service",
    ):
        with pytest.raises(ConfigError):
            _sandboxd_unit({"AGOS_SANDBOXD_UNIT": wrong})
    runner = _Runner()
    engine = _caged_engine(tmp_path, "auto", runner)
    engine.settings = dataclasses.replace(
        engine.settings, sandboxd_unit="agos-stg-sandboxd.service"
    )
    engine.root("alpha").mkdir(parents=True)
    sandbox_broker.ensure(engine, "alpha")
    units = tmp_path / ".config" / "systemd" / "user"
    assert (units / "agos-stg-sandboxd.service").is_file()
    assert not (units / cage.SERVICE).exists()
    flat = [" ".join(call) for call in runner.calls if call[:1] == ["systemctl"]]
    assert flat and all("agos-stg-sandboxd.service" in c or "daemon-reload" in c for c in flat)


def test_a_staging_gateways_cage_hides_lives_sockets_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review H1, engine side: staging's run dir is <family>/stg; its gateways'
    tmpfs covers the family (live's folders included), not only <family>/stg."""
    monkeypatch.setattr(cage, "available", lambda: True)
    engine = _caged_engine(tmp_path, "auto", _Runner())
    family = tmp_path / "run" / "agos-sandboxd"
    engine.settings = dataclasses.replace(engine.settings, sandboxd_run_dir=family / "stg")
    (family / "agos-live1").mkdir(parents=True)
    argv = sandbox_broker.cage_argv(engine, "alpha")
    own = family / "stg" / engine.profile("alpha")
    assert f"--tmpfs {family} --bind {own} {own}" in " ".join(argv)
    # A run dir outside any agos-sandboxd folder can't be hidden: refuse, never uncage.
    engine.settings = dataclasses.replace(engine.settings, sandboxd_run_dir=tmp_path / "loose")
    with pytest.raises(Exception, match="agos-sandboxd"):
        sandbox_broker.cage_argv(engine, "alpha")


def test_a_bwrap_that_cannot_run_here_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ops VM, Ubuntu 24.04: bwrap is installed but the kernel's user-namespace
    restriction stops it ("setting up uid map: Permission denied"). Caged anyway,
    every gateway died at start; uncaged (the old "auto"), it held the real Docker
    socket. The engine probes bwrap itself and refuses with cage_refused."""
    from agos_core.hermes_gateway.errors import HermesFailed

    class NoUserns(_Runner):
        def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
            if list(args)[:1] == [cage.BWRAP]:
                self.calls.append(list(args))
                raise HermesFailed("bwrap failed", exit_code=1, reason="uid map")
            return super().run(args, timeout=timeout, env=env)

    monkeypatch.setattr(cage, "available", lambda: True)
    monkeypatch.setattr(cage, "_told_at", {})
    runner = NoUserns()
    engine = _caged_engine(tmp_path, "required", runner)
    with caplog.at_level(logging.ERROR, logger="agos"):
        for _ in range(3):
            with pytest.raises(Exception, match="can't run here"):
                engine.sandboxd_on()
    told = [r for r in caplog.records if "can't run" in r.getMessage()]
    assert len(told) == 1 and told[0].name.startswith("agos.")  # once a minute at most
    probes = [c for c in runner.calls if c[:1] == [cage.BWRAP]]
    assert len(probes) == 1  # asked once per backoff, not per call


def test_walled_commands_are_caged_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Hermes process AGOS starts for a root (plugin CLI, cron, scripts) runs
    behind the same cage: uncaged, a planted script would reach the real socket."""
    monkeypatch.setattr(cage, "available", lambda: True)
    engine = _caged_engine(tmp_path, "auto", _Runner())
    engine.root("alpha").mkdir(parents=True)
    argv = engine.walled("alpha", ["/bin/hermes", "cron", "run", "j1"])
    assert argv[0] == cage.BWRAP
    cut = argv.index("--")
    assert "DOCKER_HOST" in argv[:cut]
    assert argv[cut + 1 :][0].endswith("python3") or argv[cut + 1 :][0] == wall.python()
    off = _caged_engine(tmp_path, "off", _Runner())
    assert off.walled("alpha", ["/bin/hermes"])[0] != cage.BWRAP


# ---- the real cage (bwrap on this machine, no Docker daemon needed) ---------------
_restricted = (
    shutil.which(cage.BWRAP) is None
    or subprocess.run(  # noqa: S603 - fixed probe
        [cage.BWRAP, "--dev-bind", "/", "/", "--", "/bin/true"], capture_output=True, check=False
    ).returncode
    != 0
)


@pytest.mark.skipif(_restricted, reason="needs a working bwrap")
def test_the_real_cage_hides_the_socket_and_the_siblings(tmp_path: Path) -> None:
    run_dir = tmp_path / "rt"
    (run_dir / "systemd").mkdir(parents=True)
    (run_dir / "bus").touch()
    base = tmp_path / "sockets"
    own = base / "agos-alpha"
    own.mkdir(parents=True)
    (own / "docker.sock").touch()
    sibling = base / "agos-beta"
    sibling.mkdir()
    (sibling / "docker.sock").touch()
    token = tmp_path / "system" / "internal.token"
    token.parent.mkdir()
    token.write_text("secret")
    (token.parent / "agos.db").write_text("db")
    runtime_dirs = [d for d in cage.RUNTIME_SOCKET_DIRS if Path(d).is_dir()]
    buses = [b for b in cage.SYSTEM_BUS if Path(b).exists()]
    probe = f"""
import json, os
from pathlib import Path
real = [s for s in {list(cage.DOCKER_SOCKETS)!r} if Path(s).exists()]
print(json.dumps({{
    "docker_masked": all(Path(s).stat().st_size == 0 and not Path(s).is_socket() for s in real),
    "own": sorted(p.name for p in Path({str(base)!r}).iterdir()),
    "own_sock": Path({str(own / "docker.sock")!r}).exists(),
    "docker_host": os.environ.get("DOCKER_HOST", ""),
    "invocation": "INVOCATION_ID" in os.environ,
    "token": Path({str(token)!r}).read_text() if Path({str(token)!r}).exists() else "",
    "system": sorted(p.name for p in Path({str(token.parent)!r}).iterdir()),
    "user_bus": Path({str(run_dir / "bus")!r}).stat().st_size,
    "manager": sorted(p.name for p in Path({str(run_dir / "systemd")!r}).iterdir()),
    "runtime_dirs": {{d: sorted(p.name for p in Path(d).iterdir()) for d in {runtime_dirs!r}}},
    "buses": {{b: Path(b).is_socket() for b in {buses!r}}},
}}))
"""
    env = {"PATH": "/usr/bin:/bin", "INVOCATION_ID": "deadbeef"}
    done = subprocess.run(  # noqa: S603 - bwrap + the system python, fixed argv
        [
            *cage.argv(
                socket_dir=own,
                runtime_dir=run_dir,
                family=base,
                hidden_files=(token,),
                hidden_dirs=(token.parent,),
            ),
            wall.python(),
            "-I",
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got["docker_masked"] is True
    assert got["own"] == ["agos-alpha"]  # the sibling's folder is gone
    assert got["own_sock"] is True
    assert got["docker_host"] == f"unix://{own / 'docker.sock'}"
    assert got["invocation"] is False
    # AGOS's own secrets: the token reads empty, the system folder (agos.db) is empty.
    assert got["token"] == "" and got["system"] == []
    # The user bus and the user manager's control sockets are dead inside.
    assert got["user_bus"] == 0 and got["manager"] == []
    # containerd's/dockerd's socket folders are empty; the system D-Bus is not a socket.
    assert all(names == [] for names in got["runtime_dirs"].values()), got["runtime_dirs"]
    assert all(is_sock is False for is_sock in got["buses"].values()), got["buses"]


@pytest.mark.skipif(_restricted, reason="needs a working bwrap")
def test_the_real_cages_block_the_other_instances_sockets_even_new_ones() -> None:
    """Review H1 with real bwrap and real sockets: a staging cage can't reach live's
    socket, a live cage can't reach staging's, nor a staging socket created after
    the live cage started (the tmpfs hides later entries too); each reaches its own."""
    import socket
    import tempfile
    import threading

    # Unix socket paths are capped at ~108 bytes: a short base, never a long TMPDIR.
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    short = Path(tempfile.mkdtemp(prefix="agos-cage-", dir=cache))
    family = short / "agos-sandboxd"
    live = family / "agos-ws1"
    stg = family / "stg" / "stg-ws1"
    late = family / "stg" / "stg-late"
    servers: list[socket.socket] = []

    def serve(folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(str(folder / "docker.sock"))
        srv.listen(5)
        servers.append(srv)

        def accept() -> None:
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                conn.sendall(folder.name.encode())
                conn.close()

        threading.Thread(target=accept, daemon=True).start()

    probe = (
        "import os, socket, sys, time\n"
        "go = sys.argv[1]\n"
        "while not os.path.exists(go): time.sleep(0.05)\n"
        "for p in sys.argv[2:]:\n"
        "    s = socket.socket(socket.AF_UNIX)\n"
        "    try:\n"
        "        s.connect(p); print(s.recv(64).decode())\n"
        "    except OSError:\n"
        "        print('blocked')\n"
    )

    def caged(own: Path, go: Path, *targets: Path) -> subprocess.Popen[str]:
        argv = cage.argv(socket_dir=own, runtime_dir=short / "rt", family=family)
        return subprocess.Popen(  # noqa: S603 - bwrap + the system python, fixed argv
            [
                *argv,
                wall.python(),
                "-I",
                "-c",
                probe,
                str(go),
                *(str(t / "docker.sock") for t in targets),
            ],
            stdout=subprocess.PIPE,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        )

    try:
        serve(live)
        serve(stg)
        staging = caged(stg, short / "go", live, stg)
        lived = caged(live, short / "go", live, stg, late)
        time.sleep(0.5)  # both cages are up
        serve(late)  # a sibling made after the live cage started
        (short / "go").touch()
        got_staging = staging.communicate(timeout=30)[0].split()
        got_live = lived.communicate(timeout=30)[0].split()
    finally:
        for srv in servers:
            srv.close()
        shutil.rmtree(short, ignore_errors=True)
    assert got_staging == ["blocked", "stg-ws1"]
    assert got_live == ["agos-ws1", "blocked", "blocked"]


@pytest.mark.skipif(_restricted, reason="needs a working bwrap")
def test_bwrap_does_not_forward_sigterm_hence_killmode_control_group(tmp_path: Path) -> None:
    """The fact the drop-in's KillMode=control-group exists for: SIGTERM to bwrap
    alone never reaches the child; a TERM to the child itself (what control-group
    does) drains it."""
    mark = tmp_path / "drained"
    child = tmp_path / "child.py"
    child.write_text(
        "import signal, sys, time, os\n"
        f"open({str(tmp_path / 'pid')!r}, 'w').write(str(os.getpid()))\n"
        f"signal.signal(signal.SIGTERM, lambda *a: (open({str(mark)!r}, 'w').write('x'), sys.exit(0)))\n"
        "time.sleep(20)\n"
    )
    argv = [cage.BWRAP, "--dev-bind", "/", "/", "--die-with-parent", "--",
            wall.python(), "-I", str(child)]  # fmt: skip
    proc = subprocess.Popen(argv, env={"PATH": "/usr/bin:/bin"})  # noqa: S603
    try:
        deadline = 50
        while not (tmp_path / "pid").exists() and deadline:
            deadline -= 1
            __import__("time").sleep(0.1)
        assert (tmp_path / "pid").exists(), "the caged child never started"
        proc.terminate()  # TERM to bwrap only: not forwarded
        __import__("time").sleep(0.5)
        assert not mark.exists(), "bwrap forwarded SIGTERM: drop the KillMode override"
        __import__("os").kill(int((tmp_path / "pid").read_text()), 15)
        deadline = 50
        while not mark.exists() and deadline:
            deadline -= 1
            __import__("time").sleep(0.1)
        assert mark.exists(), "a TERM to the child itself must drain it"
    finally:
        proc.kill()


@pytest.mark.skipif(
    _restricted or shutil.which("docker") is None, reason="needs bwrap and the docker CLI"
)
def test_the_caged_docker_cli_reaches_only_the_filtered_socket(tmp_path: Path) -> None:
    """End to end without a real daemon: a caged `docker version` resolves
    DOCKER_HOST to the workspace socket (the broker's fake behind it), and the
    real socket path is a dead file."""
    import asyncio
    import tempfile

    from sandboxd_rig import FakeDocker, _policy

    # Unix socket paths are capped at ~108 bytes: a short base, not tmp_path.
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    short = Path(tempfile.mkdtemp(prefix="agos-cage-", dir=cache))
    run_dir = short / "rt"
    (run_dir / "systemd").mkdir(parents=True)
    base = short / "sockets"
    own = base / "agos-alpha"
    own.mkdir(parents=True)

    async def scenario() -> subprocess.CompletedProcess[str]:
        fake = FakeDocker(labels={})
        docker_sock = short / "real.sock"
        server = await asyncio.start_unix_server(fake.handle, path=str(docker_sock))
        daemon = sandboxd.Sandboxd(
            sockets_dir=base,
            policies_dir=short / "p",
            docker_socket=docker_sock,
            events_file=short / "events.jsonl",
        )
        (short / "p").mkdir()
        _policy(tmp_path)
        (short / "p" / "agos-alpha.policy.json").write_text((tmp_path / "pol.json").read_text())
        await daemon.rescan()
        try:

            def cli() -> subprocess.CompletedProcess[str]:
                argv = [
                    *cage.argv(socket_dir=own, runtime_dir=run_dir, family=base),
                    shutil.which("docker") or "docker",
                    "version",
                    "--format",
                    "{{.Server.APIVersion}}",
                ]
                return subprocess.run(  # noqa: S603 - bwrap + docker CLI, fixed argv
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
                    check=False,
                )

            return await asyncio.get_running_loop().run_in_executor(None, cli)
        finally:
            daemon.close()
            server.close()
            await asyncio.sleep(0)

    try:
        done = asyncio.run(scenario())
    finally:
        shutil.rmtree(short, ignore_errors=True)
    assert done.returncode == 0, done.stderr
    assert "1.51" in done.stdout


def test_every_members_own_network_is_in_its_workspaces_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live 2026-11-04..08: each member's sandbox runs on its own internal network
    (`agos-net-<ws>--<member>`, engine/network.sandbox_settings), but the policy
    listed only the root's, so the broker refused every member sandbox (`docker run`
    exit 125) and workers had no terminal. The policy must name the exact network
    each profile's own config asks for, and never another workspace's."""
    from agos_core.engine import network as net

    monkeypatch.setattr(cage, "available", lambda: True)
    engine = _caged_engine(tmp_path, "auto", _Runner())
    for ws, member in (("alpha", "a-writer"), ("alpha", "a-scout"), ("beta", "a-spy")):
        home = engine.root(ws) / "profiles" / member
        home.mkdir(parents=True)
        (home / "config.yaml").write_text("{}\n")
    target = cage.write_policy(
        tmp_path / "pol", engine.profile("alpha"), sandbox_broker.policy(engine, "alpha")
    )
    allowed = sandboxd.load_policy(target).networks
    for key in ("alpha", "alpha--a-writer", "alpha--a-scout"):
        extra = json.loads(net.sandbox_settings(engine.profile(key))["terminal.docker_extra_args"])
        asked = {a.split("=", 1)[1] for a in extra if a.startswith("--network=")}
        assert asked and asked <= allowed, (key, asked, allowed)
    assert net.network_name(engine.profile("beta")) not in allowed
    assert net.network_name(engine.profile("beta--a-spy")) not in allowed
    assert allowed == {
        "none",
        *(
            net.network_name(engine.profile(k))
            for k in ("alpha", "alpha--a-writer", "alpha--a-scout")
        ),
    }
