"""Runs one of the scripts AGOS writes for Hermes (an automation's run,
engine/automation_run.py) the way Hermes would, against the fake Hermes of the
tests (FakeRunner): its Kanban CLI calls go to the fake's `hermes kanban`, its
read of the board reads the fake's cards."""

import contextlib
import io
import json
from pathlib import Path
from typing import Any

from test_engine_sync import _agos_name


def run(path: Path, runner: Any, args: list[str] | None = None, stdin: str = "") -> tuple[int, str]:
    """(exit code, what it printed)."""
    namespace: dict[str, Any] = {"__name__": "hermes_script"}
    exec(compile(path.read_text(), str(path), "exec"), namespace)  # noqa: S102 - AGOS's own script
    plan = namespace["PLAN"]
    profile = _agos_name(str(plan["env"]["HERMES_HOME"]))

    def cli(cli_args: list[str]) -> str:
        return str(runner.run([plan["hermes"], "kanban", *cli_args], timeout=60, env=plan["env"]))

    def board(prefix: str = "") -> list[dict[str, Any]]:
        prefix = prefix or f"agos-automation:{plan['automation']}:"
        return [
            {
                "id": c["id"],
                "status": str(c["status"]),
                "key": str(c.get("key") or ""),
                "parents": list(c.get("parents") or []),
            }
            for c in runner.kanban.get(profile, {}).values()
            if str(c.get("key") or "").startswith(prefix)
        ]

    namespace["_cli"], namespace["_board"] = cli, board
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = int(namespace["main"](list(args or []), stdin))
    return code, out.getvalue().strip()


def cards_made(said: str) -> list[str] | None:
    """The cards a run's output names (None: it didn't start)."""
    if not said.startswith("On the Kanban: "):
        return None
    return said.removeprefix("On the Kanban: ").split(" (")[0].split(", ")


def payload_text(payload: Any) -> str:
    return payload if isinstance(payload, str) else json.dumps(payload)
