"""A small real rig for the failure and load tests: AGOS's core, real Hermes gateways
on throwaway roots, the scripted fake model (tests/e2e/fake_llm.py) and fake Telegram,
driven through tests/e2e/rooms_e2e.py (ADR 0020). One workspace (or N for the load
test), each a Co-Founder, optionally a member.

    AGOS_E2E        the rig's folder (default ~/agos-roots-test/e2e-<name>)
    AGOS_E2E_PORTS  "core,llm,telegram" (default 9621,9622,9623 for failure, 9631,... for load)

Everything the rig starts is stopped by `down()` (rooms_e2e's own: every process whose
HERMES_HOME or argv is under AGOS_E2E), also when a test fails.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import signal
import socket
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

E2E_DIR = Path(__file__).resolve().parents[1] / "e2e"
LIVE = ("starting", "running", "stopping")


def load_rooms_e2e(folder: Path, ports: str) -> ModuleType:
    """rooms_e2e reads its folder and ports when imported: set them first."""
    os.environ["AGOS_E2E"] = str(folder)
    os.environ["AGOS_E2E_PORTS"] = ports
    os.environ.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    if str(E2E_DIR) not in sys.path:
        sys.path.insert(0, str(E2E_DIR))
    module = importlib.import_module("rooms_e2e")
    if Path(module.E) != folder:  # imported earlier with other settings
        module = importlib.reload(module)
    return module


class RealRig:
    """The running rig and what the tests do with it."""

    def __init__(self, rig: ModuleType) -> None:
        self.rig = rig
        self.E = Path(rig.E)
        self.workspaces: dict[str, str] = {}

    # ---- the core's API and database ----------------------------------------------------

    def api(self, method: str, path: str, body: Any = None, timeout: float = 120) -> Any:
        return self.rig.api(method, path, body, timeout)

    def db(self) -> sqlite3.Connection:
        """AGOS's database, read-only (the core is its only writer)."""
        con = sqlite3.connect(
            f"file:{self.E / 'data' / 'system' / 'agos.db'}?mode=ro", uri=True, timeout=30
        )
        con.row_factory = sqlite3.Row
        return con

    def turns(self, chat: int) -> list[dict[str, Any]]:
        with contextlib.closing(self.db()) as con:
            rows = con.execute(
                "SELECT id, status, error, started_at, ended_at FROM chat_turns WHERE chat_id = ? ORDER BY id",
                (chat,),
            ).fetchall()
        return [dict(r) for r in rows]

    def live_turns(self) -> list[dict[str, Any]]:
        with contextlib.closing(self.db()) as con:
            rows = con.execute(
                f"SELECT id, chat_id, status FROM chat_turns WHERE status IN {LIVE!r}"
            ).fetchall()
        return [dict(r) for r in rows]

    def messages(self, ws: str, chat: int) -> list[dict[str, Any]]:
        return list(self.api("GET", f"/workspaces/{ws}/chats/{chat}")["messages"])

    def post(self, ws: str, chat: int, text: str) -> Any:
        return self.api(
            "POST", f"/workspaces/{ws}/chats/{chat}/messages", {"body": text, "attachments": []}
        )

    def dm(self, ws: str) -> int:
        """The Co-Founder's DM chat of the workspace."""
        dms = self.api("GET", f"/workspaces/{ws}/workers")["dms"]
        return int(next(c["id"] for c in dms if not c["agent"]))

    def problems(self, ws: str) -> list[dict[str, Any]]:
        return list(self.api("GET", f"/workspaces/{ws}/log?level=problems&limit=200")["entries"])

    def wait(self, what: str, check: Callable[[], Any], timeout: float, every: float = 1.0) -> Any:
        deadline = time.monotonic() + timeout
        last: Any = None
        while time.monotonic() < deadline:
            try:
                last = check()
            except Exception as error:  # noqa: BLE001 - polled again
                last = error
            if last and not isinstance(last, Exception):
                return last
            time.sleep(every)
        raise AssertionError(f"timed out after {timeout:.0f} s waiting for {what} (last: {last!r})")

    def answered(self, ws: str, chat: int, words: str) -> list[dict[str, Any]]:
        """The agent's answers that carry `words` (the fake model echoes what he
        wrote: "DM answer: [time] <his words>")."""
        return [
            m
            for m in self.messages(ws, chat)
            if m["from"] == "agent" and "DM answer" in str(m["body"]) and words in str(m["body"])
        ]

    def answered_after(self, ws: str, chat: int, words: str) -> bool:
        """An answer came after his message carrying `words` (Hermes batches messages
        sent one after another into one; the fake model may echo a note Hermes put
        after them instead of his words)."""
        shown = self.messages(ws, chat)
        mine = [i for i, m in enumerate(shown) if m["from"] == "owner" and words in str(m["body"])]
        return bool(mine) and any(
            m["from"] == "agent" and "DM answer" in str(m["body"]) for m in shown[mine[0] + 1 :]
        )

    def said(self, ws: str, chat: int, words: str) -> int:
        """How many times his message `words` is in the chat."""
        return sum(
            1 for m in self.messages(ws, chat) if m["from"] == "owner" and str(m["body"]) == words
        )

    # ---- processes ----------------------------------------------------------------------

    def root(self, ws: str) -> Path:
        return Path(self.rig.root_of(ws))

    def gateway_pid(self, home: Path) -> int:
        record = json.loads((home / "gateway_state.json").read_text())
        return int(record["pid"])

    def kill(self, pid: int, sig: int = signal.SIGKILL) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)

    def pid(self, name: str) -> int:
        return int(self.rig.state()["pids"][name])

    def stop_core(self, sig: int = signal.SIGKILL) -> None:
        pid = self.pid("core")
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(pid), sig)
        self.wait("core gone", lambda: self.rig.gone(pid), 30, 0.2)

    def start_core(self) -> None:
        self.rig.start_core()
        self.wait("core back", lambda: self.api("GET", "/workspaces", timeout=5) is not None, 90)

    def stop_llm(self) -> None:
        pid = self.pid("llm")
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        self.wait("fake model gone", lambda: self.rig.gone(pid), 30, 0.2)

    def start_llm(self) -> None:
        port = self.rig.LLM_PORT
        self.rig.spawn(
            "llm",
            [
                sys.executable,
                str(E2E_DIR / "fake_llm.py"),
                str(port),
                str(self.E / "logs" / "llm.jsonl"),
            ],
        )
        self.wait("fake model back", lambda: _listening(port), 30, 0.2)

    def rss_mb(self) -> dict[str, float]:
        """Resident memory of every rig process, grouped (core, gateways, workers, fakes)."""
        groups: dict[str, float] = {}
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                env = (proc / "environ").read_bytes().decode(errors="replace")
                argv = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                status = (proc / "status").read_text()
            except OSError:
                continue
            if str(self.E) not in env and str(self.E) not in argv:
                continue
            rss = next(
                (int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")),
                0,
            )
            kind = (
                "core"
                if "agos_core.api.app" in argv
                else "gateway"
                if "gateway run" in argv
                else "fakes"
                if "fake_llm.py" in argv or "fake_bot_api.py" in argv
                else "hermes-other"
            )
            groups[kind] = groups.get(kind, 0.0) + rss / 1024
        return groups


def _listening(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


MODEL = {"provider": "claude", "mode": "cli", "model": "claude-sonnet-5", "effort": "medium"}


def add_workspace(real: RealRig, name: str, members: tuple[str, ...] = ()) -> str:
    """A workspace on the fake model; members' profiles too. Its gateway restarts once
    so it reads the fake model (Hermes reads the model when it starts)."""
    rig = real.rig
    ws = str(
        real.api("POST", "/workspaces", {"name": name, "defaultModel": MODEL}, timeout=1200)["id"]
    )
    for agent in members:
        body = {
            "name": agent,
            "title": agent.title(),
            "definition": {"instructions": f"You are {agent}."},
        }

        def hire(body: dict[str, Any] = body) -> bool:
            try:
                real.api("POST", f"/workspaces/{ws}/agents", body, timeout=600)
            except RuntimeError as error:  # the Co-Founder's own setup may still run
                if "isn't set up yet" not in str(error):
                    raise
                return False
            return True

        real.wait(f"{ws}: {agent} added", hire, 600, 5)
    root = real.root(ws)
    homes = [root, *(root / "profiles" / f"a-{m}" for m in members)]
    real.wait(
        f"{ws} root + members",
        lambda: all((h / "agos-bridge.json").is_file() for h in homes),
        600,
        2,
    )
    for home in homes:
        rig.fake_model(home)
    rig.restart_gateway(root)
    real.workspaces[name] = ws
    return ws


@contextlib.contextmanager
def real_rig(name: str, ports: str) -> Iterator[RealRig]:
    folder = Path(os.environ.get("AGOS_E2E") or Path.home() / "agos-roots-test" / f"e2e-{name}")
    rig = load_rooms_e2e(folder, os.environ.get("AGOS_E2E_PORTS") or ports)
    if Path(rig.STATE).exists():  # a run that died without its down
        rig.down()
    real = RealRig(rig)
    try:
        rig.up()
        yield real
    finally:
        keep = os.environ.get("AGOS_E2E_KEEP", "") not in ("", "0")
        if keep:
            sys.argv.append("--keep")
        try:
            rig.down()
        finally:
            if keep:
                sys.argv.remove("--keep")
