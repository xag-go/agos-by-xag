from typing import Any

from agos_core.engine.step_levels import done_by, step_levels

WATCHER: list[dict[str, Any]] = [
    {"key": "s1", "agent": "media-intake-specialist", "waits_on": []},
    {"key": "s2", "agent": "brand-voice-developer", "waits_on": ["s1"]},
    {"key": "s4", "agent": "video-editor", "waits_on": ["s1"]},
    {"key": "s3", "waits_on": ["s2", "s4"]},
]


def test_inspiration_watcher_runs_in_three_levels() -> None:
    assert [[s["key"] for s in lv] for lv in step_levels(WATCHER)] == [["s1"], ["s2", "s4"], ["s3"]]
    assert done_by(WATCHER) == (
        "@media-intake-specialist → (@brand-voice-developer + @video-editor) → Co-Founder"
    )


def test_straight_chain_reads_as_before() -> None:
    chain: list[dict[str, Any]] = [
        {"key": "a", "agent": "r"},
        {"key": "b", "agent": "i", "waits_on": ["a"]},
        {"key": "c", "agent": "i", "waits_on": ["b"]},
        {"key": "d", "kind": "approval", "waits_on": ["c"]},
    ]
    assert done_by(chain) == "@r → @i → you"


def test_no_waits_not_first_starts_with_first_level_and_unknown_ignored() -> None:
    steps: list[dict[str, Any]] = [
        {"key": "a", "agent": "x"},
        {"key": "b", "agent": "y", "waits_on": ["zz"]},
    ]
    assert [len(lv) for lv in step_levels(steps)] == [2]


def test_cycle_ends() -> None:
    steps: list[dict[str, Any]] = [
        {"key": "a"},
        {"key": "b", "waits_on": ["c"]},
        {"key": "c", "waits_on": ["b"]},
    ]
    assert [[s["key"] for s in lv] for lv in step_levels(steps)] == [["a"], ["b", "c"]]
