"""Restart one service of a running e2e setup (after a code change).

python tests/e2e/restart.py llm|core
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rooms_e2e as r

which = sys.argv[1]
pid = r.state()["pids"][which]
with contextlib.suppress(ProcessLookupError):
    os.kill(pid, 15)
deadline = time.monotonic() + 30
while time.monotonic() < deadline and Path(f"/proc/{pid}").exists():
    time.sleep(0.5)
if which == "llm":
    r.spawn(
        "llm",
        [
            sys.executable,
            str(r.HERE / "fake_llm.py"),
            str(r.LLM_PORT),
            str(r.E / "logs" / "llm.jsonl"),
        ],
    )
    r.wait("llm", lambda: socket.create_connection(("127.0.0.1", r.LLM_PORT), 1), 20)
else:
    r.start_core()
    r.wait("AGOS core", lambda: r.api("GET", "/workspaces") is not None, 120)
r.say("restarted", which)
