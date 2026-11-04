"""deploy/verify-server.sh on a fake machine: an uncaged gateway is a failure unless
the owner turned the cage off (AGOS_SANDBOXD=off in agos-core's environment).
Review M1: it reported every uncaged gateway as ok, so a check after an update
missed gateways that had lost their cage."""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"
pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="verify-server.sh needs jq")

SHIMS = {
    # Only `systemctl show -p Environment --value agos-core` answers: the core's env.
    "systemctl": '#!/usr/bin/env bash\n[[ "$*" == *"show"*"Environment"* ]] && cat "$FAKE/core-env" 2>/dev/null\nexit 1\n',
    "docker": "#!/usr/bin/env bash\nexit 1\n",
    "curl": "#!/usr/bin/env bash\nexit 1\n",
    "loginctl": "#!/usr/bin/env bash\nexit 1\n",
    "sudo": "#!/usr/bin/env bash\nexit 1\n",
    "ss": "#!/usr/bin/env bash\nexit 0\n",
}
CAGED = 'ExecStart="bwrap" "--" "/usr/bin/python3" "wall.py" "--" hermes gateway run\nKillMode=control-group\n'
UNCAGED = 'ExecStart="/usr/bin/python3" "wall.py" "--" hermes gateway run\n'


def _check(tmp_path: Path, dropin: str, core_env: str) -> str:
    fake = tmp_path / "fake"
    fake.mkdir()
    for name, body in SHIMS.items():
        (fake / name).write_text(body)
        (fake / name).chmod(stat.S_IRWXU)
    (fake / "core-env").write_text(core_env + "\n")
    conf = tmp_path / "home" / ".config" / "systemd" / "user" / "hermes-gateway-a.service.d"
    conf.mkdir(parents=True)
    (conf / "agos-runtime.conf").write_text(dropin + "MemoryMax=1G\nTasksMax=64\n")
    done = subprocess.run(  # noqa: S603
        ["bash", str(DEPLOY / "verify-server.sh"), "--no-agent-run"],  # noqa: S607
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake}:/usr/bin:/bin",
            "FAKE": str(fake),
            "AGOS_DATA_DIR": str(tmp_path / "data"),
        },
        capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    return done.stdout


def test_an_uncaged_gateway_fails_the_check(tmp_path: Path) -> None:
    out = _check(tmp_path, UNCAGED, "AGOS_ENGINE=hermes AGOS_DATA_DIR=/x")
    assert "[FAIL] hermes-gateway-a.service: NOT caged" in out, out


def test_an_uncaged_gateway_is_ok_when_the_owner_turned_the_cage_off(tmp_path: Path) -> None:
    out = _check(tmp_path, UNCAGED, "AGOS_ENGINE=hermes AGOS_SANDBOXD=off")
    assert "[ok]   hermes-gateway-a.service: not caged (AGOS_SANDBOXD=off" in out, out


def test_a_caged_gateway_is_ok(tmp_path: Path) -> None:
    out = _check(tmp_path, CAGED, "AGOS_ENGINE=hermes")
    assert "[ok]   hermes-gateway-a.service: caged" in out, out
    assert "hermes-gateway-a.service: NOT caged" not in out
