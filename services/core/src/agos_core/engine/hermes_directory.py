"""The Telegram groups and topics a workspace's Hermes knows, read from its own
channel directory (H: gateway/channel_directory.py `build_channel_directory`, saved
to `<home>/channel_directory.json`, rebuilt from its sessions at gateway start and
every 5 minutes, `_build_from_sessions_db`). AGOS keeps no copy of it.

An entry is `{"id": "<chat>" | "<chat>:<thread>", "name": ..., "type": ...,
"thread_id": ...}`; a topic's name is `"<group> / <topic>"`, and `"<group> / topic
<n>"` when Hermes doesn't know the topic's name (H: `_session_entry_name`; its
Telegram knows only a DM topic's or a configured topic's name, H:
plugins/platforms/telegram/adapter.py `_resolve_topic_binding`).
"""

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FILE = "channel_directory.json"
# Hermes's own names by chat id, laid over its directory (H: gateway/channel_directory.py
# `_apply_channel_aliases`, on every rebuild and every read; "an aliased id not yet
# discovered gets a placeholder entry so a freshly-created group is addressable by name
# before its first message"). Per profile, in Hermes's backups and profile copies
# (H: hermes_cli/backup.py:1063, hermes_cli/profile_channels.py:397). Hermes has no
# writer for it (no CLI): AGOS writes its Telegram entries here, atomically, keeping
# every other entry, and reads them back with the directory.
ALIASES = "channel_aliases.json"


def read_aliases(home: Path) -> dict[str, Any]:
    try:
        data = json.loads((home / ALIASES).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_aliases(home: Path, names: dict[str, str]) -> bool:
    """Puts Telegram names into the profile's channel_aliases.json ({chat id or
    "<chat>:<thread>": name}); every other entry is kept. False: nothing changed."""
    data = read_aliases(home)
    telegram = data.get("telegram")
    telegram = dict(telegram) if isinstance(telegram, dict) else {}
    merged = {**telegram, **{k: v for k, v in names.items() if k and v.strip()}}
    if merged == telegram:
        return False
    data["telegram"] = merged
    fd, tmp = tempfile.mkstemp(dir=home, prefix=f".{ALIASES}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        Path(tmp).replace(home / ALIASES)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def _with_aliases(home: Path, entries: list[Any]) -> list[Any]:
    """The directory's Telegram entries as Hermes reads them: its aliases laid over
    (the same rule as _apply_channel_aliases), so a name shows before the next rebuild."""
    aliases = read_aliases(home).get("telegram")
    if not isinstance(aliases, dict):
        return entries
    out = [dict(e) if isinstance(e, dict) else e for e in entries]
    for chat_id, friendly in aliases.items():
        if not isinstance(friendly, str) or not friendly.strip():
            continue
        matches = [e for e in out if isinstance(e, dict) and e.get("id") == str(chat_id)]
        for e in matches:
            e["name"] = friendly.strip()
        if not matches:
            out.append({"id": str(chat_id), "name": friendly.strip(), "thread_id": None})
    return out


def general(thread: str) -> str:
    """Telegram's General topic: no thread, or thread 1 (Hermes names it so)."""
    return "0" if thread in ("", "0", "1", "None") else thread


def telegram_groups(homes: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """{group id: {"name": str, "topics": {thread: name | None}}} over the profiles'
    directories. A topic's name is None when Hermes knows the topic but not its
    name; a group's name is "" when Hermes has none for it."""
    out: dict[str, dict[str, Any]] = {}
    for home in homes:
        try:
            data = json.loads((home / FILE).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        platforms = data.get("platforms") if isinstance(data, dict) else None
        entries = platforms.get("telegram") if isinstance(platforms, dict) else None
        entries = _with_aliases(home, entries if isinstance(entries, list) else [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw = str(entry.get("id") or "")
            group, _, thread = raw.partition(":")
            if not group.startswith("-"):
                continue  # a private chat, not a group
            thread = general(str(entry.get("thread_id") or thread or ""))
            name = str(entry.get("name") or "")
            place = out.setdefault(group, {"name": "", "topics": {}})
            if thread == "0" and ":" not in raw:
                place["name"] = place["name"] or name
                place["topics"].setdefault("0", None)
                continue
            base, topic = _split(name, thread, str(entry.get("thread_id") or thread))
            place["name"] = place["name"] or base
            if topic is not None or thread not in place["topics"]:
                place["topics"][thread] = None if thread == "0" else topic
    for group, place in out.items():
        if place["name"] == group:  # Hermes had only the id
            place["name"] = ""
    return out


def _split(name: str, thread: str, raw_thread: str) -> tuple[str, str | None]:
    """("<group>", "<topic>" | None) of a topic entry's name."""
    unnamed = f" / topic {raw_thread}"
    if name.endswith(unnamed):
        return name[: -len(unnamed)], None
    base, sep, topic = name.partition(" / ")
    return (base, topic or None) if sep else (name, None)
