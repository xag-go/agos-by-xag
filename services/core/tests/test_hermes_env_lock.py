"""AGOS and Hermes write the same .env at the same time, and no line is lost.

Hermes's writers (pairing approval, dashboard, `hermes tools`) use
hermes_cli.config.save_env_value, under Hermes's .env lock (an flock on
`<.env>.lock`, hermes_cli/config.py:2578). AGOS's only .env writer
(engine/envfile.py rewrite) takes the same lock.
"""

import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agos_core.engine import envfile

ROUNDS = 40


def _agos_writer(env_file: str, tag: str) -> None:
    for i in range(ROUNDS):
        envfile.rewrite(Path(env_file), (f"AGOS_{tag}_{i}=",), [f"AGOS_{tag}_{i}=v{i}"])


def _names(env_file: Path) -> set[str]:
    return {line.split("=", 1)[0] for line in env_file.read_text().splitlines() if "=" in line}


def test_agos_writers_in_several_processes_keep_every_line(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TELEGRAM_ALLOWED_USERS=1\n")
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_agos_writer, args=(str(env_file), f"P{n}")) for n in range(3)]
    for p in procs:
        p.start()
    threads = [
        threading.Thread(target=_agos_writer, args=(str(env_file), f"T{n}")) for n in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    want = {f"AGOS_{tag}_{i}" for tag in ("P0", "P1", "P2", "T0", "T1") for i in range(ROUNDS)}
    assert want | {"TELEGRAM_ALLOWED_USERS"} == _names(env_file)
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"


def test_rewrite_waits_for_hermess_lock(tmp_path: Path) -> None:
    """While Hermes holds its .env lock, AGOS's write waits (and gives up after
    the time Hermes itself waits)."""
    env_file = tmp_path / ".env"
    with envfile.hermes_env_lock(env_file):  # stands for Hermes holding it
        done = threading.Event()

        def write() -> None:
            envfile.rewrite(env_file, ("A=",), ["A=1"])
            done.set()

        worker = threading.Thread(target=write)
        worker.start()
        assert not done.wait(0.3)
    worker.join(5)
    assert done.is_set() and env_file.read_text() == "A=1\n"
    with (
        envfile.hermes_env_lock(env_file),
        pytest.raises(TimeoutError),
        envfile.hermes_env_lock(env_file, timeout=0.2),
    ):
        pass


def test_export_lines_are_replaced_too(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("export TELEGRAM_BOT_TOKEN=old\nOTHER=1\n")
    envfile.rewrite(env_file, ("TELEGRAM_BOT_TOKEN=",), ["TELEGRAM_BOT_TOKEN=new"])
    assert env_file.read_text() == "OTHER=1\nTELEGRAM_BOT_TOKEN=new\n"


# Hermes's own writer, as its pairing approval runs it (gateway/pairing.py
# _write_allowlist_env -> save_env_value), in Hermes's runtime.
_HERMES_WRITER = r"""
import sys
from hermes_cli.config import save_env_value
for i in range(int(sys.argv[1])):  # each one a whole read, change and write
    save_env_value(f"HERMES_PAIRED_{i}", str(i))
save_env_value("TELEGRAM_ALLOWED_USERS", "1,2,3")
print("HERMES-DONE")
"""


def _hermes_python() -> str | None:
    """Hermes's runtime Python (AGOS's launcher for it), or None without Hermes."""
    hermes = shutil.which("hermes")
    if not hermes:
        return None
    from agos_core.engine.models import hermes_python

    try:
        return hermes_python(cast(Any, SimpleNamespace(hermes_bin=hermes)))
    except Exception:  # noqa: BLE001 - no usable Hermes: the test is skipped
        return None


def test_hermes_save_env_value_and_agos_rewrite_at_once_lose_nothing(tmp_path: Path) -> None:
    """The real Hermes save_env_value (what a pairing approval calls) and AGOS's
    rewrite, at the same moment on one .env: every line of both survives."""
    python = _hermes_python()
    if python is None:
        pytest.skip("no Hermes install on this machine")
    home = tmp_path / "home"
    home.mkdir()
    env_file = home / ".env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=x\n")
    (home / "config.yaml").write_text("{}\n")
    keep = ("PATH", "HOME", "USER", "LANG")
    env = {k: v for k, v in os.environ.items() if k in keep}
    env["HERMES_HOME"] = str(home)
    tools = Path.home() / ".hermes" / "tools"
    if tools.is_dir():
        env["HERMES_RUNTIME_DIR"] = str(tools)  # never a runtime of its own
    hermes = subprocess.Popen(  # noqa: S603 - Hermes's own runtime
        [python, "-c", _HERMES_WRITER, str(ROUNDS * 5)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # AGOS writes for as long as Hermes does (and some more): they overlap.
    agos = 0
    while hermes.poll() is None or agos < ROUNDS:
        envfile.rewrite(env_file, (f"AGOS_MCP_K{agos}=",), [f"AGOS_MCP_K{agos}=v{agos}"])
        agos += 1
        time.sleep(0.002)
    out, err = hermes.communicate(timeout=120)
    assert hermes.returncode == 0 and "HERMES-DONE" in out, err[-2000:]
    names = _names(env_file)
    lost = (
        {f"HERMES_PAIRED_{i}" for i in range(ROUNDS * 5)}
        | {f"AGOS_MCP_K{i}" for i in range(agos)}
        | {"TELEGRAM_ALLOWED_USERS", "TELEGRAM_BOT_TOKEN"}
    ) - names
    assert not lost, sorted(lost)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(pytest.main([__file__, "-q"]))
