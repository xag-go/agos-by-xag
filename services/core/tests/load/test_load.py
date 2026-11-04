"""Load: N workspaces x M cards x K concurrent chat answers on the real rig (real Hermes
gateways, the fake model), measuring what the owner feels (latency p50/p95 of his
clicks and of an answer), errors, and memory (RSS of the core and the gateways).

    AGOS_LOAD_WORKSPACES  workspaces, each its own Hermes root + gateway  (default 20)
    AGOS_LOAD_CARDS       cards, spread over the workspaces             (default 200)
    AGOS_LOAD_TURNS       chat answers asked at the same time           (default 50)
    AGOS_LOAD_OUT         report folder (report.json, report.md)        (default the rig's logs)
    AGOS_E2E_PORTS        "core,llm,telegram"                           (default 9631,9632,9633)

The report feeds docs/load-limits.md (the hardware minimum). The test fails on any
error or any answer left running; the latency limits are reported, not enforced
(machines differ), except AGOS_LOAD_P95_MS when set.
"""

from __future__ import annotations

import functools
import json
import os
import statistics
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from failure.real_rig import RealRig, add_workspace, real_rig

pytestmark = pytest.mark.hermes


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


class Sampler:
    """RSS of the rig's processes every 2 s; keeps the peak of each group."""

    def __init__(self, rig: RealRig) -> None:
        self.rig = rig
        self.peak: dict[str, float] = {}
        self.peak_total = 0.0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            now = self.rig.rss_mb()
            for k, v in now.items():
                self.peak[k] = max(self.peak.get(k, 0.0), v)
            self.peak_total = max(self.peak_total, sum(now.values()))
            self.stop.wait(2)

    def __enter__(self) -> Sampler:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(10)


def _timed(call: Callable[[], Any]) -> tuple[float, str | None]:
    start = time.perf_counter()
    try:
        call()
    except Exception as error:  # noqa: BLE001 - counted as an error of the phase
        return (time.perf_counter() - start) * 1000, f"{type(error).__name__}: {error}"[:300]
    return (time.perf_counter() - start) * 1000, None


def _stats(samples: list[tuple[float, str | None]]) -> dict[str, Any]:
    ok = sorted(ms for ms, err in samples if err is None)
    errors = [err for _, err in samples if err is not None]

    def pct(p: float) -> float | None:
        if not ok:
            return None
        return round(ok[min(len(ok) - 1, round(p / 100 * (len(ok) - 1)))], 1)

    return {
        "n": len(samples),
        "errors": len(errors),
        "first_errors": errors[:5],
        "p50_ms": pct(50),
        "p95_ms": pct(95),
        "max_ms": round(ok[-1], 1) if ok else None,
        "mean_ms": round(statistics.fmean(ok), 1) if ok else None,
    }


def test_load(tmp_path: Path) -> None:
    n_ws = _env_int("AGOS_LOAD_WORKSPACES", 20)
    n_cards = _env_int("AGOS_LOAD_CARDS", 200)
    n_turns = _env_int("AGOS_LOAD_TURNS", 50)
    report: dict[str, Any] = {
        "asked": {"workspaces": n_ws, "cards": n_cards, "concurrent_turns": n_turns},
        "machine": {"cpus": os.cpu_count(), "mem_total_mb": _mem_total_mb()},
    }
    with real_rig("l6-load", "9631,9632,9633") as rig, Sampler(rig) as sampler:
        out = Path(os.environ.get("AGOS_LOAD_OUT") or rig.E / "logs")
        out.mkdir(parents=True, exist_ok=True)
        idle = rig.rss_mb()
        made: list[tuple[float, str | None]] = []
        workspaces: list[str] = []
        for i in range(n_ws):
            start = time.perf_counter()
            try:
                workspaces.append(add_workspace(rig, f"Load {i + 1:02d}"))
                made.append(((time.perf_counter() - start) * 1000, None))
            except Exception as error:  # noqa: BLE001 - the report counts it
                made.append(((time.perf_counter() - start) * 1000, str(error)[:300]))
        report["workspace_create"] = _stats(made)
        report["rss_after_workspaces_mb"] = {k: round(v) for k, v in rig.rss_mb().items()}
        assert workspaces, "no workspace could be made"

        # Cards: the owner's New card, 8 at a time (a busy morning), spread round-robin.
        def card(i: int) -> tuple[float, str | None]:
            ws = workspaces[i % len(workspaces)]
            body = {"title": f"Load card {i}", "body": "x", "member": "", "triage": False}
            return _timed(lambda: rig.api("POST", f"/workspaces/{ws}/kanban", body))

        with ThreadPoolExecutor(8) as pool:
            report["card_create"] = _stats(list(pool.map(card, range(n_cards))))

        # Concurrent answers: K owner messages at once, each in a workspace's DM.
        dms = {ws: rig.dm(ws) for ws in workspaces}

        def turn(i: int) -> tuple[float, str | None]:
            ws = workspaces[i % len(workspaces)]
            chat = dms[ws]
            words = f"load turn {i} {int(time.time())}"
            start = time.perf_counter()
            try:
                rig.post(ws, chat, words)
                rig.wait(f"answer {i}", lambda: rig.answered_after(ws, chat, words), 600, 2.0)
            except Exception as error:  # noqa: BLE001 - a timed-out wait (AssertionError) counts too
                return (time.perf_counter() - start) * 1000, f"{type(error).__name__}: {error}"[
                    :300
                ]
            return (time.perf_counter() - start) * 1000, None

        # Page reads while the answers run: what the owner's open pages ask for.
        reads: list[tuple[float, str | None]] = []
        reading = threading.Event()

        def reader() -> None:
            paths = ("/kanban", "/inbox", "/log?limit=100", "/workers", "")
            i = 0
            while not reading.is_set():
                ws = workspaces[i % len(workspaces)]
                path = paths[i % len(paths)]
                url = f"/workspaces/{ws}{path}"
                reads.append(_timed(functools.partial(rig.api, "GET", url)))
                i += 1

        readers = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
        for r in readers:
            r.start()
        with ThreadPoolExecutor(n_turns) as pool:
            answers = list(pool.map(turn, range(n_turns)))
        reading.set()
        for r in readers:
            r.join(30)
        report["chat_answer"] = _stats(answers)
        report["page_reads_under_load"] = _stats(reads)
        rig.wait("no live turn left", lambda: not rig.live_turns(), 300, 3)
        report["stuck_turns"] = rig.live_turns()
        report["rss_idle_mb"] = {k: round(v) for k, v in idle.items()}
        report["rss_peak_mb"] = {k: round(v) for k, v in sampler.peak.items()}
        report["rss_peak_total_mb"] = round(sampler.peak_total)
        report["rss_per_workspace_mb"] = round(
            (sampler.peak.get("gateway", 0.0) + sampler.peak.get("hermes-other", 0.0))
            / max(1, len(workspaces))
        )
        (out / "report.json").write_text(json.dumps(report, indent=1))
        (out / "report.md").write_text(_markdown(report))
        print(_markdown(report))
    errors = sum(
        report[k]["errors"]
        for k in ("workspace_create", "card_create", "chat_answer", "page_reads_under_load")
    )
    assert errors == 0, json.dumps(report, indent=1)[:3000]
    limit = os.environ.get("AGOS_LOAD_P95_MS")
    if limit:
        assert (report["chat_answer"]["p95_ms"] or 0) <= float(limit), report["chat_answer"]


def _mem_total_mb() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) // 1024
    return 0


def _markdown(r: dict[str, Any]) -> str:
    rows = ["| phase | n | errors | p50 ms | p95 ms | max ms |", "|---|---|---|---|---|---|"]
    for key in ("workspace_create", "card_create", "chat_answer", "page_reads_under_load"):
        s = r[key]
        rows.append(
            f"| {key} | {s['n']} | {s['errors']} | {s['p50_ms']} | {s['p95_ms']} | {s['max_ms']} |"
        )
    return "\n".join(
        [
            f"Load: {r['asked']} on {r['machine']}",
            "",
            *rows,
            "",
            f"RSS idle (MB): {r['rss_idle_mb']}",
            f"RSS after the workspaces (MB): {r['rss_after_workspaces_mb']}",
            f"RSS peak (MB): {r['rss_peak_mb']} total {r['rss_peak_total_mb']}",
            f"RSS per workspace (gateway + Hermes workers, MB): {r['rss_per_workspace_mb']}",
            "",
        ]
    )
