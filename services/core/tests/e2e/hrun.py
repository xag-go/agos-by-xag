"""Run Python code inside a Hermes home's own runtime (tests and ops scripts).

    python hrun.py <hermes home> <script.py | -> [args…]

HERMES_RUNTIME_DIR must be set (never let a throwaway root rewrite the shared
launcher). Uses Hermes's documented `--print-runtime-command` launcher.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def runtime_argv(hermes_bin: str = "") -> list[str]:
    hermes_bin = hermes_bin or os.environ.get("AGOS_E2E_HERMES") or "hermes"
    out = subprocess.run(  # noqa: S603 - fixed argv
        [hermes_bin, "--print-runtime-command", "--module", "agos_goal_judge"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    argv: list[str] = json.loads(out)
    argv[-1] = argv[-1].replace(
        "runpy.run_module('agos_goal_judge', run_name='__main__', alter_sys=True)",
        "exec(compile(sys.stdin.read(), 'agos-script', 'exec'))",
    )
    return argv


def run(home: str, code: str, args: list[str] | None = None, timeout: float = 120) -> str:
    if not os.environ.get("HERMES_RUNTIME_DIR"):
        raise SystemExit("HERMES_RUNTIME_DIR is not set")
    env = {**os.environ, "HERMES_HOME": home}
    done = subprocess.run(  # noqa: S603 - Hermes's own launcher
        [*runtime_argv(), *(args or [])],
        input=code,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-2000:])
    return done.stdout


if __name__ == "__main__":
    home, script = sys.argv[1], sys.argv[2]
    code = sys.stdin.read() if script == "-" else Path(script).read_text()
    sys.stdout.write(run(home, code, sys.argv[3:]))
