"""Release channels (ADR 0028): which release tag a channel follows.

Owns: the tag grammar (vX.Y.Z stable, vX.Y.Z-beta.N / -rc.N beta), their SemVer order
and the channel names. Must not: run git or read files (actions/agos_update.py does);
deploy/agos holds the same rules in bash for `agos update` (tests keep the two equal).
"""

from __future__ import annotations

import re

__all__ = ["CHANNELS", "DEFAULT", "channel_of", "newest", "version_key"]

CHANNELS = ("stable", "beta", "main")
DEFAULT = "stable"  # an install made before channels has none in agos.conf
_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-(beta|rc)\.(\d+))?$")
_PRE_RANK = {"beta": 0, "rc": 1}


def channel_of(conf: dict[str, str]) -> str:
    """The channel in the installer's agos.conf (AGOS_CHANNEL), stable when unset or odd."""
    found = (conf.get("AGOS_CHANNEL") or DEFAULT).strip()
    return found if found in CHANNELS else DEFAULT


def version_key(tag: str) -> tuple[int, int, int, int, int, int] | None:
    """SemVer order of a release tag (a beta or rc before its release); None if not one."""
    match = _TAG.match(tag.strip())
    if not match:
        return None
    major, minor, patch, pre, n = match.groups()
    final = 1 if pre is None else 0
    return (int(major), int(minor), int(patch), final, _PRE_RANK.get(pre or "", 0), int(n or 0))


def newest(tags: list[str], channel: str) -> str | None:
    """The channel's newest release tag: stable counts only vX.Y.Z, beta also its betas
    and release candidates. None when there is none (or the channel is main)."""
    if channel == "main":
        return None
    best: tuple[tuple[int, int, int, int, int, int], str] | None = None
    for tag in tags:
        key = version_key(tag)
        if key is None or (channel == "stable" and key[3] == 0):
            continue
        if best is None or key > best[0]:
            best = (key, tag.strip())
    return best[1] if best else None
