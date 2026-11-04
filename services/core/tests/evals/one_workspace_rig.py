"""One throwaway workspace on real Hermes, for the agent evals and the speed budgets.

    AGOS_E2E=<dir> AGOS_E2E_PORTS=core,llm,telegram python tests/evals/run.py ...

Built on the e2e rig (tests/e2e/rooms_e2e.py: its spawn / api / wait / fake_model /
down), lighter than its `setup` (one workspace, no members, no Telegram): the AGOS core,
a scripted model (`llm`: a fake_llm.py-style server, the evals' own by default) and the
workspace's Hermes root with its gateway. Everything lives under $AGOS_E2E; `down`
ends every process of it and removes the folder.

Owns: starting, setting up and ending that rig.
Must not: score anything (run.py) or measure anything (tests/perf/budgets.py).
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

__all__ = ["HERE", "Rig", "e2e"]

HERE = Path(__file__).resolve().parent
E2E_DIR = HERE.parent / "e2e"


def e2e() -> ModuleType:
    """tests/e2e/rooms_e2e.py, read with this run's AGOS_E2E / AGOS_E2E_PORTS."""
    if str(E2E_DIR) not in sys.path:
        sys.path.insert(0, str(E2E_DIR))
    import rooms_e2e

    return rooms_e2e


class Rig:
    """The rig of one run: `up()`, `workspace()`, `down()`."""

    def __init__(self, llm_script: Path | None = None) -> None:
        self.e = e2e()
        self.dir: Path = self.e.E
        self.llm_script = llm_script or HERE / "eval_llm.py"

    # ---- processes ---------------------------------------------------------------------

    def up(self) -> None:
        e = self.e
        if e.STATE.exists():
            raise SystemExit(f"{e.STATE} exists: run `down` first")
        for port in (e.CORE_PORT, e.LLM_PORT):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    raise SystemExit(f"port {port} is in use: another rig is up")
        for d in ("home/.hermes", "data", "roots", "logs"):
            (self.dir / d).mkdir(parents=True, exist_ok=True)
        py = sys.executable
        e.spawn(
            "llm",
            [py, str(self.llm_script), str(e.LLM_PORT), str(self.dir / "logs" / "llm.jsonl")],
        )
        self.start_core()

    def start_core(self) -> float:
        """Starts the core; seconds until it answered its first request."""
        started = time.monotonic()
        self.e.start_core()
        self.e.wait("AGOS core", lambda: self.e.api("GET", "/workspaces") is not None, 120, 0.05)
        return time.monotonic() - started

    def stop_core(self) -> None:
        pid = int(self.e.state().get("pids", {}).get("core") or 0)
        if pid and not self.e.gone(pid):
            os.kill(pid, 15)
            self.e.wait("core gone", lambda: self.e.gone(pid), 60, 0.1)

    def core_pid(self) -> int:
        return int(self.e.state().get("pids", {}).get("core") or 0)

    def down(self, *, keep: bool = False) -> None:
        argv = sys.argv
        sys.argv = [argv[0], "down", *(["--keep"] if keep else [])]
        try:
            self.e.down()
        finally:
            sys.argv = argv

    # ---- the workspace -----------------------------------------------------------------

    def workspace(self, name: str = "Evals") -> str:
        """A workspace on the scripted model (its Co-Founder's gateway restarted on it)."""
        e = self.e
        made = dict(e.state().get("ws") or {})
        if name in made:
            return str(made[name])
        ws = str(e.api("POST", "/workspaces", {"name": name, "defaultModel": e.MODEL})["id"])
        root = e.root_of(ws)
        e.wait(f"{ws} root", lambda: (root / "agos-bridge.json").is_file(), 300, 2)
        e.fake_model(root)
        e.restart_gateway(root)
        made[name] = ws
        e.save(ws=made)
        return ws

    def cofounder_dm(self, ws: str) -> int:
        dms = self.e.api("GET", f"/workspaces/{ws}/workers")["dms"]
        return int(next(c["id"] for c in dms if not c["agent"]))

    def llm_log(self) -> list[dict[str, Any]]:
        log = self.dir / "logs" / "llm.jsonl"
        if not log.is_file():
            return []
        return [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
