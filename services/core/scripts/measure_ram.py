"""Measure RAM with N throwaway workspaces (gateway + sandbox each), then remove
them. Usage: AGOS_DATA_DIR=... uv run python scripts/measure_ram.py 5
Prints per-process RSS for the Hermes gateways and `docker stats` for sandboxes.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CORE = os.environ.get("AGOS_CORE_URL", "http://127.0.0.1:8766")
DATA = Path(os.environ["AGOS_DATA_DIR"])
HERMES = Path.home() / ".hermes"
PY = HERMES / "hermes-agent" / "venv" / "bin" / "python"
PS = shutil.which("ps") or "/bin/ps"
DOCKER = shutil.which("docker") or "/usr/local/bin/docker"
MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "low"}
PROBE = (
    "from tools.terminal_tool import terminal_tool\n"
    "print(terminal_tool(command='echo up', task_id='agos-ram'))\n"
)


def call(method: str, path: str, body: object = None) -> object:
    token = (DATA / "system" / "internal.token").read_text().strip()
    req = urllib.request.Request(  # noqa: S310 - local core
        CORE + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"x-agos-internal": token, "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
        raw = r.read()
        return json.loads(raw) if raw else None


def rss_mb(pattern: str) -> list[float]:
    ps_cmd = [PS, "-axo", "rss=,command="]
    out = subprocess.run(ps_cmd, capture_output=True, text=True, check=False).stdout  # noqa: S603
    return [
        int(line.split(None, 1)[0]) / 1024
        for line in out.splitlines()
        if pattern in line and "grep" not in line
    ]


def main(n: int) -> None:
    tag = secrets.token_hex(3)
    made: list[str] = []
    try:
        for i in range(n):
            ws = call("POST", "/workspaces", {"name": f"zz-ram-{tag}-{i}", "defaultModel": MODEL})[
                "id"
            ]  # type: ignore[index]
            made.append(str(ws))
        for ws in made:
            home = HERMES / "profiles" / f"agos-{ws}"
            subprocess.run(  # noqa: S603
                [str(PY), "-c", PROBE],
                env={
                    "HOME": str(Path.home()),
                    "HERMES_HOME": str(home),
                    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                    "HERMES_STATE_DB_GUARD_BYPASS": "1",
                },
                cwd=str(HERMES / "hermes-agent"),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        # Start each gateway exactly as AGOS does before a run (no model call).
        from agos_core.config import load_settings
        from agos_core.engine.hermes import HermesEngine

        settings = load_settings()
        assert settings.engine is not None
        engine = HermesEngine(settings.engine)
        for ws in made:
            engine.start(ws)
        time.sleep(10)
        gateways = rss_mb("gateway run --replace --force")
        docker_cmd = [DOCKER, "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"]
        stats = subprocess.run(  # noqa: S603
            docker_cmd,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        core = rss_mb("agos_core.api.app")
        print(
            json.dumps(
                {
                    "workspaces": n,
                    "gateways_running": len(gateways),
                    "gateway_rss_mb_each": [round(g) for g in gateways],
                    "gateways_total_mb": round(sum(gateways)),
                    "core_rss_mb": [round(c) for c in core],
                    "docker": stats.strip().splitlines(),
                },
                indent=1,
            )
        )
    finally:
        for ws in made:
            try:
                call("POST", f"/workspaces/{ws}/delete", {"confirm": ws})
                call("DELETE", f"/trash/{ws}")
            except Exception as error:  # noqa: BLE001
                print("cleanup", ws, error)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
