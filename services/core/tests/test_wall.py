"""The wall around each workspace's Hermes gateway (engine/wall.py): Landlock, set by
a stdlib launcher in front of Hermes's own command, on the systemd path (AGOS's
drop-in wraps the unit's ExecStart) and on the test-only spawn path. A walled
process of workspace A runs Hermes in its own root, and can't read or write
workspace B, AGOS's system folder nor the shared Hermes home."""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agos_core.config import EngineConfig
from agos_core.engine import root_unit, wall
from agos_core.engine.hermes import HermesEngine

HERMES = Path.home() / ".hermes" / "hermes-agent"
LAUNCHER = shutil.which("hermes")
real = pytest.mark.skipif(
    wall.abi() < 1 or not HERMES.is_dir() or LAUNCHER is None,
    reason="needs Landlock and an installed Hermes",
)

HERMES_UNIT = """[Unit]
Description=Hermes gateway

[Service]
Type=simple
ExecStart="/opt/h/.hermes/bin/hermes" "gateway" "run"
WorkingDirectory=/x
Environment="HERMES_HOME=/x"
Restart=always
ExecStop=-"/opt/h/.hermes/bin/hermes" "--run-module" "gateway.systemd_stop_mark"
"""


class _Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.spawned: list[list[str]] = []

    def run(self, args: Any, *, timeout: float, env: Any = None) -> str:
        self.calls.append(list(args))
        return ""

    def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
        self.spawned.append(list(args))


def _engine(tmp_path: Path, supervisor: str, runner: Any) -> HermesEngine:
    return HermesEngine(
        EngineConfig(
            hermes_bin="/bin/hermes",
            docker_bin="/bin/docker",
            hermes_home=tmp_path / ".hermes",
            profile_prefix="agos-",
            sandbox_image="img:1",
            host_home=tmp_path,
            roots_dir=tmp_path / "data" / "hermes",
            runtime_dir=tmp_path / ".hermes" / "tools",
            gateway_supervisor=supervisor,
        ),
        runner=runner,
    )


def _volumes(home: Path, specs: list[str]) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("terminal:\n  docker_volumes: " + json.dumps(specs) + "\n")


def _lists(tmp_path: Path) -> tuple[HermesEngine, wall.Lists]:
    engine = _engine(tmp_path, "systemd", _Runner())
    files = tmp_path / "data" / "workspaces" / "alpha" / "files"
    _volumes(
        engine.root("alpha"),
        [
            f"{files}:/workspace",
            f"{files}/playbooks/agents:/workspace/playbooks/agents:ro",
            f"{tmp_path}/Projects:/shared/projects",
        ],
    )
    _volumes(engine.root("alpha") / "profiles" / "a-writer", [f"{files}:/workspace:ro"])
    return engine, engine.wall_lists("alpha--a-writer")


def test_the_allow_list_opens_only_this_workspace(tmp_path: Path) -> None:
    engine, lists = _lists(tmp_path)
    files = str(tmp_path / "data" / "workspaces" / "alpha" / "files")
    root = str(engine.root("alpha"))
    assert root in lists.rw and files in lists.rw and "/tmp" in lists.rw  # noqa: S108
    # Hermes's per-OS-user lock folder is shared by every workspace: closed. Each
    # root has its own (HERMES_GATEWAY_LOCK_DIR, inside its own temp folder).
    assert not any(".local" in p for p in lists.rw + lists.ro)
    assert str(engine.temp_dir("alpha")) in lists.rw
    # The owner's extra folder: read-only; the playbooks are inside the files folder.
    assert f"{tmp_path}/Projects" in lists.ro and f"{tmp_path}/Projects" not in lists.rw
    assert not any("playbooks" in p for p in lists.rw + lists.ro)
    # The Hermes install (code, runtime, its install state) and the managed scope: read-only.
    for path in ("hermes-agent", "tools", "installs"):
        assert str(tmp_path / ".hermes" / path) in lists.ro
    assert str(engine.settings.managed_home) in lists.ro
    assert lists.locks == [str(tmp_path / ".hermes" / "installs")]
    # Never open: the shared Hermes home itself, other roots, AGOS's data and home.
    every = lists.rw + lists.ro
    for closed in (
        tmp_path / ".hermes",
        tmp_path / "data",
        tmp_path / "data" / "hermes",
        tmp_path / "data" / "system",
        tmp_path,
    ):
        assert str(closed) not in every
    assert not any(p.startswith(str(engine.root("beta"))) for p in every)


def test_the_systemd_drop_in_wraps_hermess_own_command(tmp_path: Path) -> None:
    runner = _Runner()
    engine, _lists_before = _lists(tmp_path)
    engine.runner = runner
    root_unit.remember(engine.root("alpha"), "hermes-gateway-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True)
    unit.write_text(HERMES_UNIT)
    engine.refresh_dropin("alpha")
    body = (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()
    lines = body.splitlines()
    assert "ExecStart=" in lines  # replaces Hermes's, systemd's own way
    start = next(ln for ln in lines if ln.startswith("ExecStart=") and ln != "ExecStart=")
    assert start.endswith(' "--" "/opt/h/.hermes/bin/hermes" "gateway" "run"')
    assert f'"{Path(wall.__file__).resolve()}"' in start
    assert f'"--rw" "{engine.root("alpha")}"' in start
    assert f'"--ro" "{tmp_path}/Projects"' in start
    assert runner.calls[-1][:3] == ["systemctl", "--user", "daemon-reload"]
    # A grant changes: the drop-in follows (the gateway's next start opens it).
    files = tmp_path / "data" / "workspaces" / "alpha" / "files"
    _volumes(engine.root("alpha"), [f"{files}:/workspace", f"{tmp_path}/Music:/shared/music:ro"])
    before = len(runner.calls)
    engine.refresh_dropin("alpha")
    body = (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()
    assert f'"--ro" "{tmp_path}/Music"' in body and "Projects" not in body
    assert len(runner.calls) == before + 1  # reloaded once
    engine.refresh_dropin("alpha")
    assert len(runner.calls) == before + 1  # unchanged: no reload


def test_the_spawn_gateway_starts_walled(tmp_path: Path) -> None:
    runner = _Runner()
    engine = _engine(tmp_path, "spawn", runner)
    engine.is_running = lambda _ws: bool(runner.spawned)  # type: ignore[method-assign,assignment]
    engine.start("alpha")
    argv = runner.spawned[0]
    assert argv[1:3] == ["-I", str(Path(wall.__file__).resolve())]
    assert argv[argv.index("--") :] == ["--", "/bin/hermes", "gateway", "run", "--replace"]
    assert str(engine.root("alpha")) in argv


# ---- a real wall, a real Hermes ---------------------------------------------


@pytest.fixture
def layout() -> Iterator[Path]:
    """Not under /tmp (open to every walled gateway): beside the home's caches, at one
    fixed place so Hermes's per-root environments survive between tests."""
    from conftest import kept_layout

    with kept_layout("agos-wall-test") as folder:
        yield folder


def _real_lists(base: Path) -> tuple[Path, Path, wall.Lists]:
    data = base / "data"
    root_a, root_b = data / "hermes" / "agos-alpha", data / "hermes" / "agos-beta"
    files_a = data / "workspaces" / "alpha" / "files"
    files_b = data / "workspaces" / "beta" / "files"
    for folder in (root_a, root_b, files_a, files_b, data / "system", data / "hermes-managed"):
        folder.mkdir(parents=True, exist_ok=True)
    (root_b / ".env").write_text("OPENROUTER_API_KEY=beta-secret\n")
    (files_b / "notes.txt").write_text("beta's file\n")
    (data / "system" / "internal.token").write_text("token\n")
    from conftest import hermes_warm

    hermes_warm(root_a)  # first run of the kept layout: Hermes syncs its environment once
    install = Path.home() / ".hermes"
    lists = wall.allow_list(
        root=root_a,
        configs=[{"terminal": {"docker_volumes": [f"{files_a}:/workspace"]}}],
        host_home=Path.home(),
        install_home=install,
        runtime_dir=install / "tools",
        managed_home=data / "hermes-managed",
        hermes_bin=str(LAUNCHER),
        temp_dir=None,
        workspace_mount="/workspace",
    )
    return root_a, data, lists


def _env(root: Path, data: Path) -> dict[str, str]:
    keep = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("HERMES", "_HERMES", "AGOS_", "PYTEST"))
    }
    return {
        **keep,
        "HERMES_HOME": str(root),
        "HERMES_MANAGED_DIR": str(data / "hermes-managed"),
        "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
        "NO_COLOR": "1",
    }


def _walled(
    lists: wall.Lists, command: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the launcher and a fixed command
        wall.argv(wall.python(), lists, command),
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        check=False,
    )


@real
def test_a_walled_hermes_runs_in_its_own_root(layout: Path) -> None:
    root_a, data, lists = _real_lists(layout)
    env = _env(root_a, data)
    subprocess.run(  # noqa: S603 - unwalled: AGOS's own write
        [str(LAUNCHER), "config", "set", "model.provider", "openrouter"],
        env=env, capture_output=True, timeout=180, check=True,
    )  # fmt: skip
    got = _walled(lists, [str(LAUNCHER), "config", "get", "model.provider"], env)
    assert got.returncode == 0, got.stderr
    assert "openrouter" in got.stdout
    # The install's own dependency state is read (never a runtime of its own in the root).
    assert "Preparing the isolated Hermes runtime" not in got.stdout + got.stderr
    listed = _walled(lists, [str(LAUNCHER), "plugins", "list"], env)
    assert listed.returncode == 0, listed.stderr
    assert "not writable" not in listed.stderr  # Hermes's install leases and locks


@real
def test_a_walled_process_cant_reach_another_workspace(layout: Path) -> None:
    root_a, data, lists = _real_lists(layout)
    probe = f"""
import pathlib
def tried(fn):
    try:
        fn()
        return "open"
    except PermissionError:
        return "denied"
data = pathlib.Path({str(data)!r})
print(tried(lambda: (data / "hermes" / "agos-beta" / ".env").read_text()))
print(tried(lambda: (data / "workspaces" / "beta" / "files" / "notes.txt").read_text()))
print(tried(lambda: (data / "hermes" / "agos-beta" / "planted").write_text("x")))
print(tried(lambda: (data / "system" / "internal.token").read_text()))
print(tried(lambda: list((pathlib.Path.home() / ".hermes").iterdir())))
print(tried(lambda: (data / "hermes-managed" / "x").write_text("x")))
print(tried(lambda: (data / "hermes" / "agos-alpha" / "own").write_text("x")))
print(tried(lambda: (data / "workspaces" / "alpha" / "files" / "own").write_text("x")))
"""
    done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root_a, data))
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == [
        "denied",  # B's root
        "denied",  # B's files
        "denied",  # writing into B
        "denied",  # AGOS's system folder
        "denied",  # the shared Hermes home
        "denied",  # the managed scope is read-only
        "open",  # its own root
        "open",  # its own files
    ]
    assert not (data / "hermes" / "agos-beta" / "planted").exists()


@real
def test_the_launcher_refuses_to_run_unwalled(tmp_path: Path) -> None:
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-I", str(Path(wall.__file__).resolve()), "--rw", str(tmp_path)],
        capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip
    assert done.returncode != 0 and "usage" in done.stderr


@pytest.mark.skipif(wall.abi() < 1, reason="this kernel has no Landlock")
def test_a_writable_folder_that_isnt_there_yet_is_made_before_the_wall(tmp_path: Path) -> None:
    """A fresh home has no ~/.local/state yet: once walled, Hermes could never make
    its ~/.local/state/hermes (gateway lock, Telegram lock), so the launcher makes
    every writable folder first (the e2e's gateways died on exactly this)."""
    state = tmp_path / "home" / ".local" / "state" / "hermes"
    lists = wall.Lists(rw=[str(state)], ro=list(wall.SYSTEM_RO), locks=[])
    got = _walled(
        lists,
        ["/usr/bin/python3", "-I", "-c", f"open({str(state / 'gateway.lock')!r}, 'w').write('x')"],
        dict(os.environ),
    )
    assert got.returncode == 0, got.stderr
    assert (state / "gateway.lock").read_text() == "x"


def test_the_wall_opens_the_logins_and_shared_skills_the_profiles_point_at(tmp_path: Path) -> None:
    """A root's mcp-tokens is a link into AGOS's connectors folder (Hermes must
    read and refresh the app logins there), and skills.external_dirs names the
    shared skill folders: a wall without them silently lost every app login and
    the library/Brain skills."""
    root = tmp_path / "hermes" / "agos-x"
    tokens = tmp_path / "system" / "connectors" / "w" / "x" / "mcp-tokens"
    tokens.mkdir(parents=True)
    root.mkdir(parents=True)
    (root / "mcp-tokens").symlink_to(tokens)
    skills = tmp_path / "agos-skills"
    lists = wall.allow_list(
        root=root,
        configs=[{"skills": {"external_dirs": [str(skills), "~/nowhere-x"]}}],
        host_home=tmp_path / "home",
        install_home=tmp_path / "home" / ".hermes",
        runtime_dir=None,
        managed_home=tmp_path / "managed",
        hermes_bin="/bin/true",
        temp_dir=None,
        workspace_mount="/workspace",
    )
    assert str(tokens) in lists.rw
    assert str(skills) in lists.ro
    assert str(tmp_path / "home" / "nowhere-x") in lists.ro
    assert str(tmp_path / "system") not in lists.rw + lists.ro  # only the link's target


def test_each_root_has_its_own_gateway_lock_folder(tmp_path: Path) -> None:
    """Hermes's machine-wide lock folder (~/.local/state/hermes: every gateway's
    token locks, the host records, a serve token) was writable by every walled
    gateway. Hermes's own HERMES_GATEWAY_LOCK_DIR (H: gateway/status.py:319-330)
    gives each root its own, on the systemd path, the spawn path and every Hermes
    command AGOS runs for that root."""
    runner = _Runner()
    engine, _lists_before = _lists(tmp_path)
    engine.runner = runner
    own = engine.lock_dir("alpha")
    assert own == engine.temp_dir("alpha") / "gateway-locks"
    assert own != engine.lock_dir("beta")
    assert engine.lock_dir("alpha--a-writer") == own  # a member: its root's
    assert engine.hermes_env("alpha--a-writer")["HERMES_GATEWAY_LOCK_DIR"] == str(own)
    root_unit.remember(engine.root("alpha"), "hermes-gateway-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True)
    unit.write_text(HERMES_UNIT)
    engine.refresh_dropin("alpha")
    body = (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()
    assert f'Environment="HERMES_GATEWAY_LOCK_DIR={own}"' in body.splitlines()
    spawned: list[dict[str, str]] = []

    class Spawn(_Runner):
        def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
            super().spawn(args, log_file=log_file, env=env)
            spawned.append(dict(env or {}))

    spawner = Spawn()
    other = _engine(tmp_path / "s", "spawn", spawner)
    other.is_running = lambda _ws: bool(spawner.spawned)  # type: ignore[method-assign,assignment]
    other.start("alpha")
    assert spawned[0]["HERMES_GATEWAY_LOCK_DIR"] == str(other.lock_dir("alpha"))


def test_each_root_has_its_own_browser_folder(tmp_path: Path) -> None:
    """Hermes's browser engine (browser-harness) keeps its daemons, spawn locks and
    logs under BH_HOME, else the shared ~/.config/browser-harness: one "default"
    daemon for every workspace, and a folder the wall closes (a walled browser_exec
    failed its first call). Each root gets its own, inside its own temp folder (open
    in the wall), on the systemd path, the spawn path and every Hermes command."""
    runner = _Runner()
    engine, _lists_before = _lists(tmp_path)
    engine.runner = runner
    own = engine.browser_dir("alpha")
    assert own == engine.temp_dir("alpha") / "browser-harness"
    assert own != engine.browser_dir("beta")
    assert engine.browser_dir("alpha--a-writer") == own  # a member: its root's
    assert engine.hermes_env("alpha--a-writer")["BH_HOME"] == str(own)
    assert any(own.is_relative_to(Path(p)) for p in engine.wall_lists("alpha").rw)
    # Every root's wall opens /tmp itself (test above); the test's tmp_path may sit
    # under it (a CI runner's /tmp/pytest-of-runner), live roots never do.
    beta_rw = [p for p in engine.wall_lists("beta").rw if p != "/tmp"]  # noqa: S108
    assert not any(own.is_relative_to(Path(p)) for p in beta_rw)
    root_unit.remember(engine.root("alpha"), "hermes-gateway-a.service")
    unit = engine.service_unit("alpha")
    unit.parent.mkdir(parents=True)
    unit.write_text(HERMES_UNIT)
    engine.refresh_dropin("alpha")
    body = (unit.with_name(unit.name + ".d") / "agos-runtime.conf").read_text()
    assert f'Environment="BH_HOME={own}"' in body.splitlines()
    spawned: list[dict[str, str]] = []

    class Spawn(_Runner):
        def spawn(self, args: Any, *, log_file: Path, env: Any = None) -> None:
            super().spawn(args, log_file=log_file, env=env)
            spawned.append(dict(env or {}))

    spawner = Spawn()
    other = _engine(tmp_path / "s", "spawn", spawner)
    other.is_running = lambda _ws: bool(spawner.spawned)  # type: ignore[method-assign,assignment]
    other.start("alpha")
    assert spawned[0]["BH_HOME"] == str(other.browser_dir("alpha"))


@real
def test_a_walled_gateway_locks_in_its_own_folder_not_the_shared_one(layout: Path) -> None:
    """Real wall, real Hermes: the token lock lands in the root's own folder, and
    Hermes's per-user folder (another workspace's locks) can't be read or written.
    On a fresh home (a new install, the nightly's runner account) that folder isn't
    there yet: the walled gateway then can't make it either."""
    root_a, data, lists = _real_lists(layout)
    own = layout / "tmp-a" / "gateway-locks"
    shared = Path.home() / ".local" / "state" / "hermes"
    existed = shared.is_dir()
    lists = wall.Lists([*lists.rw, str(own.parent)], lists.ro, lists.locks)
    python = sorted((Path.home() / ".hermes" / "tools").glob("python-3.*/bin/python3"))
    if not python:
        pytest.skip("no Hermes runtime python")
    probe = f"""
import sys, pathlib
sys.path.insert(0, {str(HERMES)!r})
import hermes_bootstrap
from gateway.status import acquire_scoped_lock, _get_lock_dir
ok, _ = acquire_scoped_lock("telegram-bot-token", "123:abc")
print("lock", ok, _get_lock_dir())
def tried(fn):
    try:
        fn()
        return "open"
    except PermissionError:
        return "denied"
    except FileNotFoundError:
        return "absent"
    except FileExistsError:
        return "exists"
shared = pathlib.Path({str(shared)!r})
print("shared-read", tried(lambda: list(shared.iterdir())))
print("shared-write", tried(lambda: (shared / "agos-planted").write_text("x")))
print("shared-make", tried(lambda: shared.mkdir(parents=True)))
"""
    env = {**_env(root_a, data), "HERMES_GATEWAY_LOCK_DIR": str(own)}
    try:
        done = _walled(lists, [str(python[-1]), "-I", "-c", probe], env)
    finally:
        planted = shared / "agos-planted"
        leaked = planted.exists()
        planted.unlink(missing_ok=True)  # only what this probe itself may have written
    assert not leaked
    assert done.returncode == 0, done.stderr[-800:]
    lines = dict(ln.split(" ", 1) for ln in done.stdout.splitlines() if " " in ln)
    assert lines["lock"] == f"True {own}"
    assert any(own.glob("telegram-bot-token-*.lock"))
    if existed:
        assert lines["shared-read"] == "denied"
        assert lines["shared-write"] == "denied"
        assert lines["shared-make"] == "exists"
    else:
        assert lines["shared-read"] == lines["shared-write"] == "absent"
        assert lines["shared-make"] == "denied"
        assert not shared.exists()


@real
def test_a_walled_process_reads_the_shared_skills_and_its_logins(layout: Path) -> None:
    """The b7ef1a8 fix, under a real wall: the shared skill folder can be listed and
    read (not written), and a token behind the root's mcp-tokens link read and
    refreshed."""
    data = layout / "data"
    root = data / "hermes" / "agos-alpha"
    tokens = data / "system" / "connectors" / "w" / "alpha" / "mcp-tokens"
    skills = data / "brain" / "skills" / "agos-brain-x"
    for folder in (root, tokens, skills):
        folder.mkdir(parents=True, exist_ok=True)
    (tokens / "app.json").write_text("{}")
    (root / "mcp-tokens").symlink_to(tokens)
    (skills / "SKILL.md").write_text("---\nname: agos-brain-x\n---\nx\n")
    lists = wall.allow_list(
        root=root,
        configs=[{"skills": {"external_dirs": [str(skills.parent)]}}],
        host_home=Path.home(),
        install_home=Path.home() / ".hermes",
        runtime_dir=None,
        managed_home=data / "managed",
        hermes_bin=str(LAUNCHER),
        temp_dir=None,
        workspace_mount="/workspace",
    )
    probe = f"""
import pathlib
def tried(fn):
    try:
        fn()
        return "open"
    except PermissionError:
        return "denied"
skills = pathlib.Path({str(skills.parent)!r})
root = pathlib.Path({str(root)!r})
print(tried(lambda: list(skills.iterdir())))
print(tried(lambda: (skills / "agos-brain-x" / "SKILL.md").read_text()))
print(tried(lambda: (skills / "agos-brain-x" / "SKILL.md").write_text("x")))
print(tried(lambda: (root / "mcp-tokens" / "app.json").read_text()))
print(tried(lambda: (root / "mcp-tokens" / "app.json").write_text("{{}}")))
"""
    done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root, data))
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["open", "open", "denied", "open", "open"]


def test_a_member_reads_its_workspace_skills_and_never_another_roots(tmp_path: Path) -> None:
    """A member's skills.external_dirs names its workspace's skill folder (inside its
    root: open with it); a config naming another root's folder opens nothing of it."""
    roots = tmp_path / "data" / "hermes"
    root, other = roots / "agos-a", roots / "agos-b"
    own = root / "skills" / "agos-library"
    theirs = other / "skills" / "agos-library"
    for folder in (own, theirs, root / "profiles" / "a-writer"):
        folder.mkdir(parents=True)
    brain = tmp_path / "data" / "brain" / "skills"
    lists = wall.allow_list(
        root=root,
        configs=[
            {"skills": {"external_dirs": [str(brain)]}},
            {"skills": {"external_dirs": [str(brain), str(own), str(theirs), str(roots)]}},
        ],
        host_home=tmp_path / "home",
        install_home=tmp_path / "home" / ".hermes",
        runtime_dir=None,
        managed_home=tmp_path / "managed",
        hermes_bin="/bin/true",
        temp_dir=None,
        workspace_mount="/workspace",
    )
    opened = lists.rw + lists.ro
    assert str(root) in lists.rw  # its own skill folder is inside: readable
    assert str(brain) in lists.ro
    assert not [p for p in opened if p == str(roots) or p.startswith(str(other))]
    assert str(own) not in lists.rw  # nothing extra is opened for writing


@real
def test_a_walled_member_reads_its_workspace_skills_not_another_workspaces(layout: Path) -> None:
    """Under a real wall: the root's gateway (its members' runs too) reads the
    workspace's skill folder, never another root's, even when a config names it."""
    data = layout / "data"
    root, other = data / "hermes" / "agos-alpha", data / "hermes" / "agos-beta"
    mine = root / "skills" / "agos-library" / "writing"
    theirs = other / "skills" / "agos-library" / "writing"
    for folder in (mine, theirs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text("---\nname: writing\n---\nx\n")
    lists = wall.allow_list(
        root=root,
        configs=[{"skills": {"external_dirs": [str(mine.parent), str(theirs.parent)]}}],
        host_home=Path.home(),
        install_home=Path.home() / ".hermes",
        runtime_dir=None,
        managed_home=data / "managed",
        hermes_bin=str(LAUNCHER),
        temp_dir=None,
        workspace_mount="/workspace",
    )
    probe = f"""
import pathlib
def tried(fn):
    try:
        fn()
        return "open"
    except PermissionError:
        return "denied"
print(tried(lambda: pathlib.Path({str(mine / "SKILL.md")!r}).read_text()))
print(tried(lambda: pathlib.Path({str(theirs / "SKILL.md")!r}).read_text()))
"""
    done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root, data))
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["open", "denied"]


# ---- what the wall closes beyond paths (docs/adr/0025) ------------------------


@real
def test_a_walled_process_reads_proc_but_cant_write_another_processes_proc(
    layout: Path,
) -> None:
    """/proc is read-only behind the wall: a hijacked gateway could rename any
    same-uid process (its `comm`) or poke its settings. Reading stays open
    (Hermes checks pid start times in /proc)."""
    root_a, data, lists = _real_lists(layout)
    outside = os.getpid()  # this pytest process: same uid, outside the wall
    probe = f"""
import pathlib
def tried(fn):
    try:
        fn()
        return "open"
    except PermissionError:
        return "denied"
print(tried(lambda: pathlib.Path("/proc/self/status").read_text()))
print(tried(lambda: pathlib.Path("/proc/{outside}/stat").read_text()))
print(tried(lambda: open("/proc/{outside}/comm", "w")))
"""
    done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root_a, data))
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["open", "open", "denied"]


@real
@pytest.mark.skipif(wall.abi() < 6, reason="abstract-socket scoping needs Landlock ABI 6")
def test_a_walled_process_cant_connect_an_outside_abstract_socket(layout: Path) -> None:
    """An abstract unix socket has no path, so the filesystem rules never see it;
    ABI 6's scope closes it (another gateway's or the desktop's endpoints)."""
    import socket

    root_a, data, lists = _real_lists(layout)
    name = f"\0agos-wall-test-{os.getpid()}"
    server = socket.socket(socket.AF_UNIX)
    server.bind(name)
    server.listen()
    try:
        probe = (
            "import socket\n"
            "s = socket.socket(socket.AF_UNIX)\n"
            f"s.connect('\\0agos-wall-test-{os.getpid()}')\n"
            "print('connected')\n"
        )
        done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root_a, data))
        assert done.returncode != 0 and "connected" not in done.stdout
        assert "PermissionError" in done.stderr or "ConnectionRefused" in done.stderr
    finally:
        server.close()


@real
def test_a_walled_gateway_keeps_its_powers(layout: Path) -> None:
    """The owner's rule: hardening removes nothing the Co-Founder has. Behind the
    wall it still writes a skill in its own root (Hermes's skill tools write
    there), its profiles, and the workspace's files folder (/workspace in the
    sandbox, read-write)."""
    root_a, data, lists = _real_lists(layout)
    skill = root_a / "skills" / "made-behind-the-wall" / "SKILL.md"
    member = root_a / "profiles" / "a-writer" / "config.yaml"
    script = data / "workspaces" / "alpha" / "files" / "made.py"
    probe = f"""
import pathlib
for path, text in (
    ({str(skill)!r}, "---\\nname: made-behind-the-wall\\n---\\n"),
    ({str(member)!r}, "model: {{}}\\n"),
    ({str(script)!r}, "print('ran in /workspace')"),
):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
import subprocess, sys
print(subprocess.run([sys.executable, "-I", {str(script)!r}], capture_output=True, text=True).stdout.strip())
"""
    done = _walled(lists, [wall.python(), "-I", "-c", probe], _env(root_a, data))
    assert done.returncode == 0, done.stderr
    assert "ran in /workspace" in done.stdout
    assert skill.read_text().startswith("---")
