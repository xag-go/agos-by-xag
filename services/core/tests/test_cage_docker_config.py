"""The caged docker CLI's default is the workspace's filtered socket (engine/cage.py
write_docker_config + argv docker_config), not only DOCKER_HOST.

Hermes runs its sandboxed browser with `docker exec` and an env of PATH and HOME only
(tools/browser_tool_session `_sandbox_wrap`): DOCKER_HOST is gone, so the CLI fell
back to /var/run/docker.sock, which the cage blanks ("Cannot connect to the Docker
daemon"). A docker config folder bound over the gateway's ~/.docker names a context
whose endpoint is the workspace's own broker socket, so any child that loses
DOCKER_HOST still lands on the filter, and the real socket stays dead."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from test_cage import _dropin, _restricted
from test_wall import _Runner

from agos_core.engine import cage, sandboxd


def _meta(folder: Path) -> dict[str, object]:
    digest = hashlib.sha256(b"agos").hexdigest()
    found = json.loads((folder / "contexts" / "meta" / digest / "meta.json").read_text())
    assert isinstance(found, dict)
    return found


def test_the_config_names_the_own_socket_and_keeps_the_hosts_settings(tmp_path: Path) -> None:
    host = tmp_path / "home" / ".docker" / "config.json"
    host.parent.mkdir(parents=True)
    host.write_text(
        json.dumps({"credsStore": "pass", "auths": {"x.io": {}}, "currentContext": "o"})
    )
    sock = tmp_path / "run" / "agos-alpha" / "docker.sock"
    folder = cage.write_docker_config(tmp_path / "cfg" / "agos-alpha", sock, host)
    config = json.loads((folder / "config.json").read_text())
    assert config == {"auths": {"x.io": {}}, "credsStore": "pass", "currentContext": "agos"}
    assert _meta(folder)["Name"] == "agos"
    assert _meta(folder)["Endpoints"] == {
        "docker": {"Host": f"unix://{sock}", "SkipTLSVerify": False}
    }
    # Unchanged content is not rewritten (a gateway restart touches nothing).
    stamp = (folder / "config.json").stat().st_mtime_ns
    time.sleep(0.01)
    cage.write_docker_config(folder, sock, host)
    assert (folder / "config.json").stat().st_mtime_ns == stamp
    # No host config at all (live today): only the context.
    bare = cage.write_docker_config(tmp_path / "bare", sock, tmp_path / "none.json")
    assert json.loads((bare / "config.json").read_text()) == {"currentContext": "agos"}


def test_the_cage_binds_the_config_folder_over_home_docker(tmp_path: Path) -> None:
    base = tmp_path / "sockets"
    own = base / "agos-alpha"
    own.mkdir(parents=True)
    config, home = tmp_path / "cfg", tmp_path / "home" / ".docker"
    argv = cage.argv(
        socket_dir=own, runtime_dir=tmp_path, family=base, docker_config=(config, home)
    )
    text = " ".join(argv)
    assert f"--ro-bind {config} {home}" in text
    # After the family tmpfs (bwrap applies in order), and DOCKER_HOST stays.
    assert text.index(f"--tmpfs {base}") < text.index(f"--ro-bind {config}")
    assert f"--setenv DOCKER_HOST unix://{own / 'docker.sock'}" in text
    assert str(config) not in " ".join(cage.argv(socket_dir=own, runtime_dir=tmp_path, family=base))


def test_the_dropin_binds_each_workspaces_own_docker_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cage, "available", lambda: True)
    body = _dropin(tmp_path, "auto", _Runner())
    exec_line = next(ln for ln in body.splitlines() if ln.startswith("ExecStart=") and len(ln) > 11)
    folder = tmp_path / "data" / "sandboxd" / "docker-config" / "agos-alpha"
    assert f'"--ro-bind" "{folder}" "{tmp_path / ".docker"}"' in exec_line
    sock = tmp_path / "run" / "agos-sandboxd" / "agos-alpha" / "docker.sock"
    assert _meta(folder)["Endpoints"] == {
        "docker": {"Host": f"unix://{sock}", "SkipTLSVerify": False}
    }
    assert json.loads((folder / "config.json").read_text())["currentContext"] == "agos"


def _short_dir() -> Path:
    # Unix socket paths are capped at ~108 bytes: a short base, not tmp_path.
    cache = Path.home() / ".cache"
    cache.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="agos-cage-", dir=cache))


def _behind_broker(
    short: Path,
    tmp_path: Path,
    run: Callable[[], object],
    labels: dict[str, dict[str, str] | None] | None = None,
) -> object:
    """`run()` (in a thread) while agos-alpha's broker socket serves a fake daemon
    whose containers carry `labels`."""
    from sandboxd_rig import FakeDocker, _policy

    async def scenario() -> object:
        fake = FakeDocker(labels=labels or {})
        real = short / "real.sock"
        server = await asyncio.start_unix_server(fake.handle, path=str(real))
        (short / "p").mkdir()
        _policy(tmp_path)
        (short / "p" / "agos-alpha.policy.json").write_text((tmp_path / "pol.json").read_text())
        daemon = sandboxd.Sandboxd(
            sockets_dir=short / "sockets",
            policies_dir=short / "p",
            docker_socket=real,
            events_file=short / "events.jsonl",
        )
        await daemon.rescan()
        try:
            return await asyncio.get_running_loop().run_in_executor(None, run)
        finally:
            daemon.close()
            server.close()
            await asyncio.sleep(0)

    return asyncio.run(scenario())


@pytest.mark.skipif(
    _restricted or shutil.which("docker") is None, reason="needs bwrap and the docker CLI"
)
def test_a_caged_docker_cli_without_docker_host_reaches_the_own_socket(tmp_path: Path) -> None:
    """Hermes's browser path for real: PATH and HOME only, DOCKER_HOST removed
    inside the cage; `docker version` answers through the workspace's broker."""
    short = _short_dir()
    own = short / "sockets" / "agos-alpha"
    own.mkdir(parents=True)
    home = tmp_path / "home"
    (home / ".docker").mkdir(parents=True)
    config = cage.write_docker_config(
        short / "cfg", own / "docker.sock", home / ".docker" / "c.json"
    )
    prefix = cage.argv(
        socket_dir=own,
        runtime_dir=short,
        family=short / "sockets",
        docker_config=(config, home / ".docker"),
    )
    docker = shutil.which("docker") or "docker"

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - bwrap + docker CLI, fixed argv
            [*prefix, "/usr/bin/env", "-u", "DOCKER_HOST", docker, *args],
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin", "HOME": str(home)},  # _sandbox_wrap's host env
            check=False,
        )

    def both() -> tuple[subprocess.CompletedProcess[str], ...]:
        version = cli("version", "--format", "{{.Server.APIVersion}}")
        real = [
            cli("-H", f"unix://{s}", "version") for s in cage.DOCKER_SOCKETS if Path(s).exists()
        ]
        return (version, *real)

    try:
        done = _behind_broker(short, tmp_path, both)
    finally:
        shutil.rmtree(short, ignore_errors=True)
    assert isinstance(done, tuple)
    version, *real = done
    assert version.returncode == 0, version.stderr
    assert "1.51" in version.stdout
    # The real socket is still a dead file inside the cage.
    for refused in real:
        assert refused.returncode != 0 and "Server:" not in refused.stdout, refused.stdout


@pytest.mark.skipif(_restricted, reason="needs a working bwrap")
def test_a_config_rewritten_after_the_cage_started_shows_inside(tmp_path: Path) -> None:
    """A folder bind, never a file bind: AGOS rewriting the context (os.replace makes a
    new inode) is seen by a gateway that started before."""
    base = tmp_path / "sockets"
    own = base / "agos-alpha"
    own.mkdir(parents=True)
    home = tmp_path / "home" / ".docker"
    home.mkdir(parents=True)
    config = cage.write_docker_config(tmp_path / "cfg", own / "old.sock", tmp_path / "none")
    digest = hashlib.sha256(b"agos").hexdigest()
    inside = home / "contexts" / "meta" / digest / "meta.json"
    go = tmp_path / "go"
    probe = (
        "import os,sys,time\n"
        f"first=open({str(inside)!r}).read()\n"
        "print('ready',flush=True)\n"
        f"while not os.path.exists({str(go)!r}): time.sleep(0.05)\n"
        f"print(first.count('old.sock'), open({str(inside)!r}).read().count('docker.sock'))\n"
    )
    proc = subprocess.Popen(  # noqa: S603 - bwrap + the system python, fixed argv
        [
            *cage.argv(
                socket_dir=own, runtime_dir=tmp_path, family=base, docker_config=(config, home)
            ),
            "/usr/bin/python3",
            "-I",
            "-c",
            probe,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "ready"
        cage.write_docker_config(config, own / "docker.sock", tmp_path / "none")
        go.touch()
        out, err = proc.communicate(timeout=30)
    finally:
        proc.kill()
    assert out.split() == ["1", "1"], err
    # The host's own ~/.docker was never written (the bind is read-only, AGOS-made).
    assert list(home.iterdir()) == []
    assert os.access(config / "config.json", os.R_OK)
