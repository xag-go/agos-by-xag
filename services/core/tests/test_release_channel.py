"""The release tag grammar and order of each channel (ADR 0028)."""

import pytest

from agos_core.actions import release_channel as rc

TAGS = [
    "v0.1.0",
    "v0.1.1",
    "v0.10.0-beta.1",
    "v0.2.0-beta.2",
    "v0.2.0-rc.1",
    "v0.9.9",
    "va",
    "v1.0",
]


def test_stable_takes_the_newest_plain_release_in_semver_order() -> None:
    assert rc.newest(TAGS, "stable") == "v0.9.9"  # 0.9.9 < 0.10.0, numbers not letters


def test_beta_counts_betas_and_release_candidates() -> None:
    assert rc.newest(TAGS, "beta") == "v0.10.0-beta.1"
    assert rc.newest(["v0.2.0-beta.2", "v0.2.0-rc.1"], "beta") == "v0.2.0-rc.1"
    assert rc.newest(["v0.2.0-rc.1", "v0.2.0"], "beta") == "v0.2.0"  # the release wins


def test_main_and_nothing_have_no_tag() -> None:
    assert rc.newest(TAGS, "main") is None
    assert rc.newest([], "stable") is None
    assert rc.newest(["v0.2.0-beta.1"], "stable") is None


@pytest.mark.parametrize(
    ("conf", "channel"),
    [({}, "stable"), ({"AGOS_CHANNEL": "beta"}, "beta"), ({"AGOS_CHANNEL": "nightly"}, "stable")],
)
def test_the_channel_in_agos_conf(conf: dict[str, str], channel: str) -> None:
    assert rc.channel_of(conf) == channel
