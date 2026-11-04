"""Why General Settings' provider keys stay `.env` copies (area1 P4), proven
against the installed Hermes: its `secrets.command` source (one helper printing
KEY=VALUE, H: agent/secret_sources/command.py) runs once per process and home
(H: hermes_cli/env_loader.py:61-66 `_APPLIED_HOMES`; docs user-guide/secrets/
command.md "runs the helper ONCE"), while a profile's `.env` is read again on every
gateway turn and cron fire (env_loader.py:67-72). A key the owner changes reaches a
running gateway at its next turn through `.env`; through secrets.command only after
a restart of every workspace's gateway. When this test fails, Hermes re-reads its
secret sources and the move can be made."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SRC = Path.home() / ".hermes" / "hermes-agent"
PROBE = """
import os, sys, json
sys.path.insert(0, sys.argv[2])
import hermes_bootstrap
from pathlib import Path
from hermes_cli.env_loader import load_hermes_dotenv
home = Path(os.environ["HERMES_HOME"])
load_hermes_dotenv(hermes_home=home)
first = [os.environ.get("FAKE_PROVIDER_API_KEY"), os.environ.get("OWN_DOTENV_KEY")]
(Path(sys.argv[1]) / "keys.env").write_text("FAKE_PROVIDER_API_KEY=second\\n")
(home / ".env").write_text("OWN_DOTENV_KEY=b\\n")
load_hermes_dotenv(hermes_home=home)
second = [os.environ.get("FAKE_PROVIDER_API_KEY"), os.environ.get("OWN_DOTENV_KEY")]
print("AGOS-SEC " + json.dumps({"first": first, "second": second}))
"""


def test_hermes_reads_secrets_command_once_and_dotenv_every_time() -> None:
    python = sorted((Path.home() / ".hermes" / "tools").glob("python-3.*/bin/python3"))
    if not python or not (SRC / "agent" / "secret_sources" / "command.py").is_file():
        pytest.skip("no Hermes install on this machine")
    base = Path(tempfile.mkdtemp(dir=Path.home() / ".hermes" / "cache"))
    try:
        home = base / "home"
        home.mkdir()
        (base / "keys.env").write_text("FAKE_PROVIDER_API_KEY=first\n")
        (home / ".env").write_text("OWN_DOTENV_KEY=a\n")
        (home / "config.yaml").write_text(
            f'secrets:\n  command:\n    enabled: true\n    command: "cat {base / "keys.env"}"\n'
        )
        done = subprocess.run(  # noqa: S603 - Hermes's own interpreter
            [str(python[-1]), "-I", "-c", PROBE, str(base), str(SRC)],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                "HOME": str(Path.home()),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HERMES_HOME": str(home),
                "HERMES_RUNTIME_DIR": str(Path.home() / ".hermes" / "tools"),
            },
            check=False,
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)
    line = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-SEC ")]
    assert line, done.stderr[-500:]
    found = json.loads(line[-1][len("AGOS-SEC ") :])
    assert found["first"] == ["first", "a"]
    assert found["second"] == ["first", "b"]  # .env read again; the helper's value is not
