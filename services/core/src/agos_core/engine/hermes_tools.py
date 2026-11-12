"""Hermes's tools as AGOS shows them: the list comes from Hermes itself.

Every toolset Hermes offers (its `hermes tools` list) appears in Settings → Tools
and in each workspace's Capabilities, with Hermes's own words and, for the ones
that need an outside service, Hermes's list of services. When Hermes adds a
toolset or a service, it shows up by itself: AGOS reads the list from Hermes's
runtime (engine.HermesEngine.tools_catalog) at start and every few hours. AGOS
keeps no copy of it: the list lives in this process's memory only (no saved
setting), so a restart asks Hermes again (until it answers: what AGOS knew).

AGOS only adds its rules on top:
- always on: Hermes's core (files, terminal, web, memory, skills, past
  conversations, plans, questions, cron, Kanban): no switch;
- locked: what reaches outside accounts or another app's platform;
- everything else: on in every workspace unless the owner turns it off.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Hashable
from typing import Any

log = logging.getLogger("agos.hermes_tools")

REFRESH_SECONDS = 6 * 3600

ALWAYS: dict[str, str] = {
    "web": "Search the web and read pages.",
    "terminal": "Run commands in the workspace's sandbox.",
    "file": "Read and write the workspace's files.",
    "skills": "Use, make and improve its skills (it learns how you work).",
    "memory": "Remember what it learns about the project and about you.",
    "session_search": "Look back through your past conversations.",
    "todo": "Keep a plan while it works.",
    "clarify": "Ask you a question and wait for your answer.",
    "cronjob": "Schedule its own follow-ups.",
    "kanban": "Work the team's board.",
    "stt": "Transcribe your voice notes.",
}
LOCKED: dict[str, str] = {
    "connections": "Locked: authorizes outside accounts outside AGOS's vault.",
    "homeassistant": "Locked: controls smart-home devices outside the workspace.",
    "spotify": "Locked: controls a Spotify account outside the workspace.",
    "discord": "Locked: only for a Discord bot (AGOS's channels are its own).",
    "discord_admin": "Locked: only for a Discord bot (AGOS's channels are its own).",
    "yuanbao": "Locked: only for the Yuanbao app.",
}
# AGOS's own words where the sandbox matters (Hermes's are used for the rest).
WORDS: dict[str, str] = {
    "code_execution": "Run Python in the workspace's sandbox.",
    "delegation": "Split work between helper agents in the same sandbox.",
    "image_gen": "Create images with a picture service set up in the engine.",
    "tts": "Turn text into speech.",
    "vision": "Look at pictures in the workspace (read inside its sandbox only).",
    "video": "Watch videos in the workspace (read inside its sandbox only).",
    "browser": "Browse websites in the workspace's own browser (inside its sandbox, public internet only).",
    "computer_use": "Use the workspace's own virtual desktop: mouse, keyboard, apps (inside its sandbox).",
    "x_search": "Search posts and threads on X (Twitter). Needs an xAI sign-in or key.",
    "video_gen": "Make videos from text or a picture, with a video service.",
    "context_engine": "Extra tools of the context engine, when one is set up.",
}


def _plain(text: str) -> str:
    """Hermes's words without its own setup hints (here, setup is done in AGOS)."""
    import re

    text = re.sub(r"[^.]*`hermes [^`]*`[^.]*\.?", "", text)
    return " ".join(text.split()).strip()


# Before Hermes has been asked (or without it, in tests): what AGOS knew.
FALLBACK: list[dict[str, Any]] = [
    {"key": k, "label": k.replace("_", " ").capitalize(), "about": v, "providers": []}
    for k, v in {**ALWAYS, **WORDS, **LOCKED}.items()
]

# The list, when it was read (monotonic) and the installed Hermes it was read from.
_current: dict[str, Any] = {"list": FALLBACK}


def current() -> list[dict[str, Any]]:
    return list(_current["list"])


def names() -> list[str]:
    return [str(t["key"]) for t in current()]


def optional() -> list[str]:
    """The toolsets a workspace may turn on or off (on by default)."""
    return [k for k in names() if k not in ALWAYS and k not in LOCKED]


def about(key: str) -> str:
    for t in current():
        if t["key"] == key:
            found = WORDS.get(key) or ALWAYS.get(key) or LOCKED.get(key)
            return found or _plain(str(t.get("about") or ""))
    return WORDS.get(key, "")


def title(key: str) -> str:
    for t in current():
        if t["key"] == key and t.get("label"):
            return str(t["label"])
    return key.replace("_", " ").capitalize()


def providers(key: str) -> list[dict[str, Any]]:
    """Hermes's services for a toolset, each with the sign-in it needs (`signIn`,
    engine/provider_login.py sign_in_for), so the web keeps no map of its own."""
    from agos_core.engine.provider_login import sign_in_for

    for t in current():
        if t["key"] == key:
            return [{**p, "signIn": sign_in_for(p)} for p in t.get("providers") or []]
    return []


def installed(core: Any) -> Hashable:
    """The installed Hermes as its files are now, without starting it: its checkout's
    HEAD and pyproject.toml (`hermes update` moves them)."""
    from agos_core.engine import hermes_update, read_cache

    src = hermes_update.source_dir(core.engine)
    return read_cache.file_stamp(src / ".git" / "HEAD", src / "pyproject.toml")


def due(core: Any) -> bool:
    """Whether Hermes's list is asked again: not read yet in this process, read
    REFRESH_SECONDS ago, or the installed Hermes changed since (what the start read
    was for: a new Hermes's new tools)."""
    at = _current.get("at")
    if at is None or core.engine is None:
        return core.engine is not None
    if time.monotonic() - at >= REFRESH_SECONDS:
        return True
    return bool(installed(core) != _current.get("installed"))


def refresh(core: Any) -> bool:
    """Asks Hermes for its list now. True when it answered."""
    if core.engine is None:
        return False
    was = installed(core)  # before the read: a change during it is read next time
    try:
        found = core.engine.tools_catalog()
    except Exception as error:  # noqa: BLE001 - the last list stays
        log.info("Hermes's tools not read: %s", error)
        return False
    if not found:
        return False
    _current.update(list=found, at=time.monotonic(), installed=was)
    return True
