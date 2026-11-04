"""The core's speed / RAM measurement (tests/perf/budgets.py), without a rig: what it
times and how (the rig run itself is nightly, on the machine of its baseline)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import budgets

BASELINE = Path(budgets.__file__).with_name("baseline.json")


def test_a_page_read_is_the_median_after_warm_up_calls() -> None:
    seen: list[int] = []
    slow_first = iter([0.2, 0.2, 0.2, *([0.001] * 14), 0.5])

    def call() -> None:
        seen.append(1)
        time.sleep(next(slow_first))

    value = budgets.p50_ms(call, warm=3, calls=15)
    assert len(seen) == 18  # 3 untimed warm-up calls, then 15 timed
    assert value < 100  # the slow first calls and one outlier don't count


def test_the_owners_main_pages_are_measured() -> None:
    assert set(budgets.pages("ws1", 7)) >= {"overview", "board", "chats", "chat", "settings"}
    assert budgets.pages("ws1", 7)["board"] == "/workspaces/ws1/kanban"


def test_rss_reads_this_process() -> None:
    assert 1 < budgets.rss_mb(os.getpid()) < 100_000


def test_the_recorded_baseline_covers_every_measurement() -> None:
    names = {f"api.{p}.p50_ms" for p in budgets.pages("w", 1)} | {"core.start_s", "core.rss_mb"}
    recorded = json.loads(BASELINE.read_text())["metrics"]
    assert set(recorded) == names
    assert all(v["value"] > 0 for v in recorded.values())
