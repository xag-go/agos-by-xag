"""Live: from a workspace's real sandbox, nothing but the public internet is
reachable (step 6b). AGOS_LIVE_NETWORK=1 against a running core (real engine).

Uses Hermes's own terminal tool in the throwaway profile (no model), so the
sandbox is created exactly as an agent's command would create it.
"""

import json
import os
import secrets
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from agos_core.engine.hermes import sandbox_label_of

pytestmark = pytest.mark.skipif(
    os.environ.get("AGOS_LIVE_NETWORK") != "1", reason="live test (AGOS_LIVE_NETWORK=1)"
)

CORE = os.environ.get("AGOS_CORE_URL", "http://127.0.0.1:8766")
if not CORE.startswith(("http://", "https://")):
    raise ValueError("AGOS_CORE_URL must be http(s)")
DATA = Path(os.environ.get("AGOS_DATA_DIR", "agos-data"))
HERMES_ROOT = Path.home() / ".hermes"
PY = HERMES_ROOT / "hermes-agent" / "venv" / "bin" / "python"
DOCKER = shutil.which("docker") or "/usr/local/bin/docker"
MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "low"}

PROBE = r"""
import json, sys
from tools.terminal_tool import terminal_tool
out = terminal_tool(command=sys.argv[1], task_id="agos-net-probe")
print("AGOS-JSON " + json.dumps(out if isinstance(out, str) else str(out)))
"""


def call(method: str, path: str, body: Any = None) -> Any:
    token = (DATA / "system" / "internal.token").read_text().strip()
    req = urllib.request.Request(  # noqa: S310 - http(s) only, checked above
        CORE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-agos-internal": token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
        raw = r.read()
        return json.loads(raw) if raw else None


def in_sandbox(profile: str, command: str) -> str:
    env = {
        "HOME": str(Path.home()),
        "HERMES_HOME": str(DATA / "hermes" / profile),  # the workspace's own root
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HERMES_STATE_DB_GUARD_BYPASS": "1",
    }
    done = subprocess.run(  # noqa: S603 - fixed argv
        [str(PY), "-c", PROBE, command],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=str(HERMES_ROOT / "hermes-agent"),
        check=False,
    )
    lines = [ln for ln in done.stdout.splitlines() if ln.startswith("AGOS-JSON ")]
    assert lines, done.stderr[-800:]
    return str(json.loads(lines[-1][len("AGOS-JSON ") :]))


def test_sandbox_reaches_only_the_public_internet() -> None:
    tag = secrets.token_hex(3)
    ws = call("POST", "/workspaces", {"name": f"zz-live-{tag}-net", "defaultModel": MODEL})["id"]
    profile = f"agos-{ws}"
    try:
        checks = {
            "internet": "curl -s -m 12 -o /dev/null -w '%{http_code}' https://example.com/",
            "agos core via host": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://host.docker.internal:8766/health",
            "agos web via host": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://host.docker.internal:3001/",
            "host gateway": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://172.17.0.1:8766/health",
            "lan": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://192.168.1.1/",
            "tailscale": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://100.100.100.100/",
            "metadata": "curl -s -m 6 -o /dev/null -w '%{http_code}' http://169.254.169.254/",
            "direct, no proxy": "curl -s -m 6 --noproxy '*' -o /dev/null -w '%{http_code}' https://example.com/",
            "raw tcp to host": "timeout 5 bash -c 'echo > /dev/tcp/host.docker.internal/8766' && echo OPEN || echo CLOSED",
        }
        results = {name: in_sandbox(profile, cmd) for name, cmd in checks.items()}
        tools = in_sandbox(
            profile,
            "git --version && node --version && uv --version && gh --version | head -1 "
            "&& ffmpeg -version | head -1 && cd /workspace && git init -q probe && echo GIT-OK",
        )
        print("tools:", tools[:400])
        if os.environ.get("AGOS_SANDBOX_IMAGE", "").startswith("agos-sandbox"):
            assert "GIT-OK" in tools and "uv " in tools and "gh version" in tools
        for name, out in results.items():
            print(f"{name}: {out[:160]!r}")
        assert '"200"' in results["internet"] or "200" in results["internet"]
        for name in checks:
            if name == "internet":
                continue
            out = results[name]
            assert "OPEN" not in out and "200" not in out.replace("000", ""), (name, out)
        containers = subprocess.run(  # noqa: S603
            [DOCKER, "ps", "-q", "--filter", f"label=hermes-profile={sandbox_label_of(profile)}"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split()
        assert containers, "the probe should have created the sandbox"
        mode = subprocess.run(  # noqa: S603
            [DOCKER, "inspect", "-f", "{{.HostConfig.NetworkMode}}", containers[0]],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        assert mode == f"agos-net-{profile}", mode
    finally:
        try:
            call("POST", f"/workspaces/{ws}/delete", {"confirm": ws})
            call("DELETE", f"/trash/{ws}")
        except urllib.error.HTTPError as error:
            print("cleanup", ws, error.code, error.read()[:200])
        time.sleep(2)
