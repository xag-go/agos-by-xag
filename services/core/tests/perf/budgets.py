"""Speed and RAM budgets of the core on an e2e-style rig (real Hermes, scripted model).

    cd services/core
    uv run python tests/perf/budgets.py [--report perf-report.json] [--update] [--keep] [--reuse]

Brings up one throwaway workspace (tests/evals/one_workspace_rig.py) under $AGOS_E2E
(default ~/.hermes/cache/scratch/agos-perf, ports 28966/28995/28997), gives it a board
and a chat to read (cards, a few Co-Founder answers), then measures:

- `core.start_s`: the core's start, from its process to its first answer, with this
  data and the workspace's gateway running (median of 3 restarts);
- `api.<page>.p50_ms`: the reads behind the owner's main pages once warm (median of
  15 calls after 3 warm-up calls): overview, board, chats (list and one chat),
  settings (the workspace and its Hermes settings), the workspace list;
- `core.rss_mb`: the core's resident memory after all of that.

The numbers are checked against tests/perf/baseline.json with
scripts/ci/budget_ratchet.py (more than 20% worse fails; --update records better
numbers only). The baseline was measured on the self-hosted runner's machine: run it
there (the nightly does), not on a laptop or GitHub's runners.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BASELINE = HERE / "baseline.json"
sys.path.insert(0, str(HERE.parent / "evals"))

from one_workspace_rig import Rig  # noqa: E402 - beside the evals

__all__ = ["main", "p50_ms", "pages", "rss_mb"]


def _ratchet(args: list[str]) -> int:
    """scripts/ci/budget_ratchet.py's command (a standard-library script beside CI's)."""
    spec = importlib.util.spec_from_file_location(
        "budget_ratchet", REPO / "scripts" / "ci" / "budget_ratchet.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclass looks its module up
    spec.loader.exec_module(module)
    done: int = module.main(args)
    return done


WARM = 3
CALLS = 15
STARTS = 3
CARDS = 12
CHAT_TURNS = 3


def p50_ms(call: Callable[[], Any], *, warm: int = WARM, calls: int = CALLS) -> float:
    """The median of `calls` timed calls, after `warm` untimed ones (milliseconds)."""
    for _ in range(warm):
        call()
    times = []
    for _ in range(calls):
        started = time.perf_counter()
        call()
        times.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(times), 1)


def rss_mb(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return round(int(line.split()[1]) / 1024, 1)
    raise RuntimeError(f"no VmRSS for {pid}")


def pages(ws: str, chat: int) -> dict[str, str]:
    """The reads behind the owner's main pages: page -> GET path."""
    return {
        "overview": f"/workspaces/{ws}/overview",
        "board": f"/workspaces/{ws}/kanban",
        "chats": f"/workspaces/{ws}/chats",
        "chat": f"/workspaces/{ws}/chats/{chat}",
        "settings": f"/workspaces/{ws}",
        "hermes_settings": f"/workspaces/{ws}/hermes-settings",
        "workspaces": "/workspaces",
    }


def _content(rig: Rig, ws: str, chat: int) -> None:
    """Something to read: cards on the board (unassigned: no worker runs) and a chat."""
    have = len(rig.e.api("GET", f"/workspaces/{ws}/kanban").get("cards") or [])
    for n in range(have, CARDS):
        rig.e.api(
            "POST", f"/workspaces/{ws}/kanban", {"title": f"Perf card {n}", "body": "x" * 200}
        )
    for n in range(CHAT_TURNS):
        before = len(rig.e.api("GET", f"/workspaces/{ws}/chats/{chat}")["messages"])
        rig.e.api(
            "POST",
            f"/workspaces/{ws}/chats/{chat}/messages",
            {"body": f"perf hello {n}", "attachments": []},
        )

        def answered(before: int = before) -> bool:
            got = rig.e.api("GET", f"/workspaces/{ws}/chats/{chat}")
            return bool(len(got["messages"]) >= before + 2 and not got.get("working"))

        rig.e.wait("the chat's answer", answered, 180, 1)


def measure(rig: Rig) -> dict[str, dict[str, Any]]:
    ws = rig.workspace("Perf")
    chat = rig.cofounder_dm(ws)
    _content(rig, ws, chat)
    metrics: dict[str, dict[str, Any]] = {}
    starts = []
    for _ in range(STARTS):
        rig.stop_core()
        starts.append(rig.start_core())
        time.sleep(2)
    metrics["core.start_s"] = {"value": round(statistics.median(starts), 2), "unit": "s"}
    # Let the start's read-ahead from Hermes end (the e2e rig's ends within ~45 s).
    time.sleep(45)
    for page, path in pages(ws, chat).items():
        metrics[f"api.{page}.p50_ms"] = {
            "value": p50_ms(functools.partial(rig.e.api, "GET", path)),
            "unit": "ms",
        }
    metrics["core.rss_mb"] = {"value": rss_mb(rig.core_pid()), "unit": "MB"}
    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Core speed and RAM budgets on a real-Hermes rig.")
    parser.add_argument("--report", type=Path, default=Path("perf-report.json"))
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update", action="store_true", help="record better numbers")
    parser.add_argument("--keep", action="store_true", help="leave the rig up")
    parser.add_argument("--reuse", action="store_true", help="use a rig left up by --keep")
    args = parser.parse_args(argv)
    # Read when the rig is made (tests/e2e/rooms_e2e.py reads them at its import).
    os.environ.setdefault(
        "AGOS_E2E", str(Path.home() / ".hermes" / "cache" / "scratch" / "agos-perf")
    )
    os.environ.setdefault("AGOS_E2E_PORTS", "28966,28995,28997")
    rig = Rig()
    if not args.reuse:
        rig.up()
    try:
        metrics = measure(rig)
    finally:
        if not args.keep:
            rig.down()
    args.report.write_text(
        json.dumps({"at": time.time(), "host": os.uname().nodename, "metrics": metrics}, indent=1)
        + "\n"
    )
    ratchet = [str(args.report), "--baseline", str(args.baseline)]
    return _ratchet([*ratchet, *(["--update"] if args.update else [])])


if __name__ == "__main__":
    sys.exit(main())
