"""The bot's Telegram places: groups and their names (kept in Hermes's directory),
the team group, a chat's topic, and AGOS's own buttons pressed there.

Owns: group/topic names and the team group setting.
Must not: deliver messages or open turns.

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import logging
import re
from typing import Any

from agos_core.actions.services.channel import gateway_platform, hermes_addresses
from agos_core.context import Core
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.connection import transaction

__all__ = [
    "GROUPS_KEY",
    "TEAM_GROUP_KEY",
    "callback",
    "move_group_names",
    "place_names",
    "places",
    "set_team_group",
    "team_groups",
    "topic_for",
]

log = logging.getLogger("agos.hermes_channel")


GROUPS_KEY = "telegram.groups."  # + workspace id: AGOS's old note, moved into Hermes once
TEAM_GROUP_KEY = "telegram.team_group."
# The groups and topics are Hermes's own channel directory with its own aliases
# (engine/hermes_directory: channel_directory.json + channel_aliases.json). A group
# the bot stays quiet in (AGOS consumed his message there: Hermes made no session, so
# its directory never lists it) and a topic's name Hermes doesn't know are written
# into the root profile's channel_aliases.json, which Hermes lays over its directory
# (an id it hasn't seen yet becomes an entry there, addressable by name).


def _hermes_groups(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    from agos_core.engine import hermes_directory

    engine = core.engine
    if engine is None:
        return {}
    homes = [h for p in engine.own_profiles(workspace_id) if (h := engine.home_of(p))]
    return hermes_directory.telegram_groups(homes)


def _alias_names(
    group: str, group_name: str, topics: dict[str, str], known: dict[str, Any] | None
) -> dict[str, str]:
    """channel_aliases.json entries for what Hermes's directory lacks or names
    otherwise than Telegram just did: the group's name (its id when none is known, so
    it is listed) and each topic's "<group> / <topic>" (Hermes's own form, "/ topic
    <n>" when unnamed)."""
    from agos_core.engine.hermes_directory import general

    listed = known is not None
    known = known or {"name": "", "topics": {}}
    out: dict[str, str] = {}
    shown = group_name or known["name"] or group
    if (group_name and group_name != known["name"]) or not listed:
        out[group] = group_name or group  # its id when no name is known: still listed
    for thread, topic in topics.items():
        thread = general(thread)
        if thread == "0":
            continue
        have = known["topics"].get(thread)
        if (topic and have != topic) or (not topic and thread not in known["topics"]):
            out[f"{group}:{thread}"] = f"{shown} / {topic or f'topic {thread}'}"
    return out


def _write_names(core: Core, workspace_id: str, names: dict[str, str]) -> None:
    if not names or core.engine is None:
        return
    from agos_core.engine import hermes_directory

    home = core.engine.profile_home(workspace_id)
    if home.is_dir():
        hermes_directory.write_aliases(home, names)


def move_group_names(core: Core) -> None:
    """Every workspace's old group-name note into its root's channel_aliases.json,
    at start (it used to wait for the Channels page to be opened; a workspace whose
    root doesn't exist yet keeps its note until it does)."""
    for workspace_id in workspaces_repo.live_ids(core.db):
        _move_old_names(core, workspace_id)


def _move_old_names(core: Core, workspace_id: str) -> None:
    """AGOS's old note of names Hermes lacked (telegram.groups.<ws>) goes into the
    root's channel_aliases.json once, then the note goes."""
    from agos_core.db.app_settings import delete_setting, get_setting

    raw = get_setting(core.db, GROUPS_KEY + workspace_id, None)
    if raw is None or core.engine is None:
        return
    if not core.engine.profile_home(workspace_id).is_dir():
        return  # kept until the workspace's Hermes exists
    hermes = _hermes_groups(core, workspace_id)
    names: dict[str, str] = {}
    for group, v in raw.items() if isinstance(raw, dict) else []:
        entry: dict[str, Any] = v if isinstance(v, dict) else {"name": str(v)}
        topics = entry.get("topics")
        names |= _alias_names(
            str(group),
            str(entry.get("name") or ""),
            {str(t): str(n or "") for t, n in topics.items()} if isinstance(topics, dict) else {},
            hermes.get(str(group)),
        )
    _write_names(core, workspace_id, names)
    delete_setting(core.db, GROUPS_KEY + workspace_id)


def _groups(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    """{group id: {"name", "topics": {topic id: name}}}: Hermes's directory and aliases."""
    from agos_core.engine.hermes_directory import general

    _move_old_names(core, workspace_id)
    hermes = _hermes_groups(core, workspace_id)
    out: dict[str, dict[str, Any]] = {}
    for group, known in hermes.items():
        topics: dict[str, str] = {}
        for thread in known["topics"]:
            thread = general(thread)
            topics[thread] = known["topics"].get(thread) or (
                "General" if thread == "0" else f"Topic {thread}"
            )
        out[group] = {"name": known["name"] or group, "topics": topics}
    return out


def _seen_group(
    core: Core, workspace_id: str, group: str, name: str, thread: str = "", topic: str = ""
) -> None:
    """He wrote in a group: what Hermes's directory lacks goes into its aliases."""
    names = _alias_names(
        group,
        name[:120],
        {thread: topic[:120]} if thread else {},
        _hermes_groups(core, workspace_id).get(group),
    )
    _write_names(core, workspace_id, names)


def place_names(core: Core, workspace_id: str) -> dict[str, str]:
    """{"<group>:<topic>": "<group name> · <topic name>"}: the names of the
    workspace's Telegram places as Hermes's channel directory (and its aliases) has
    them now (H: gateway/channel_directory.py:65), so a rename shows at once. {} when
    they can't be read."""
    try:
        groups = _groups(core, workspace_id)
    except (OSError, ValueError) as error:
        log.info("Telegram place names of %s not read: %s", workspace_id, error)
        return {}
    out: dict[str, str] = {}
    for group, entry in groups.items():
        for thread, topic in dict(entry.get("topics") or {}).items():
            out[f"{group}:{thread}"] = f"{entry['name']} · {topic}"
    return out


def team_groups(core: Core, workspace_id: str) -> dict[str, Any]:
    """Telegram groups the workspace's bot is in (seen when he wrote there), and the
    one chosen as the team group (each chat gets its own topic there)."""
    from agos_core.db.app_settings import get_setting

    chosen = str(get_setting(core.db, TEAM_GROUP_KEY + workspace_id, "") or "")
    return {
        "groups": [{"id": k, "name": v["name"]} for k, v in _groups(core, workspace_id).items()],
        "teamGroup": chosen,
    }


def places(core: Core, workspace_id: str) -> dict[str, Any]:
    """Every place in the workspace's Telegram a chat can be linked to: the private
    chat with the bot, each group's General and each topic seen (or made by AGOS),
    with the chat each is linked to now."""

    row = gateway_platform.connection(core, workspace_id)
    if row is None:
        return {"connectionId": None, "places": []}
    from agos_core.db import chats as repo

    linked = {
        str(r["address"]): repo.chat_title(core.db, r)
        for r in addresses_repo.linked_chats(core.db, int(row["id"]))
    }
    out: list[dict[str, Any]] = []
    from agos_core.actions import telegram_people

    owner = telegram_people.owner_id(core, workspace_id)
    if owner:
        address = f"{owner}:0"
        out.append(
            {
                "address": address,
                "label": "Private chat with the bot",
                "group": "",
                "linkedTo": linked.get(address),
            }
        )
    groups = _groups(core, workspace_id)
    for address in linked:  # topics AGOS made (or linked by hand) count too
        group, _, thread = address.partition(":")
        if group.startswith("-"):
            entry = groups.setdefault(group, {"name": group, "topics": {}})
            entry.setdefault("topics", {}).setdefault(
                thread or "0", "General" if thread in ("", "0") else linked[address]
            )
    for group, entry in groups.items():
        topics = dict(entry.get("topics") or {})
        topics.setdefault("0", "General")
        for thread, topic in sorted(topics.items(), key=lambda t: (t[0] != "0", t[1].lower())):
            address = f"{group}:{thread}"
            out.append(
                {
                    "address": address,
                    "label": topic,
                    "group": entry["name"],
                    "linkedTo": linked.get(address),
                }
            )
    return {"connectionId": int(row["id"]), "places": out}


def set_team_group(core: Core, workspace_id: str, group: str) -> None:
    from agos_core.actions.errors import ActionError
    from agos_core.db.app_settings import set_setting

    if group and not re.fullmatch(r"-\d{5,20}", group):
        raise ActionError("A Telegram group id looks like -1001234567890.")
    set_setting(core.db, TEAM_GROUP_KEY + workspace_id, group)


def topic_for(core: Core, workspace_id: str, chat_id: int) -> int:
    """The chat gets its own topic in the team group (named after it), linked both
    ways: what is said in the topic is that chat, in AGOS too."""
    from agos_core.actions import channels
    from agos_core.actions.errors import ActionError
    from agos_core.db.app_settings import get_setting

    row = gateway_platform.connection(core, workspace_id)
    if row is None:
        raise ActionError("Connect this workspace's Telegram bot first (Settings → Channels).")
    group = str(get_setting(core.db, TEAM_GROUP_KEY + workspace_id, "") or "")
    if not group:
        raise ActionError("Choose the team group first (Settings → Channels → Team group).")
    return channels.add_address(
        core,
        workspace_id,
        chat_id,
        connection_id=int(row["id"]),
        address=None,
        create_topic=group,
        notify=False,
    )


def callback(
    core: Core,
    workspace_id: str,
    address: str,
    data: str,
    message_id: str,
) -> tuple[str, str]:
    """A button of AGOS's pressed in Telegram (Hermes's gateway already checked who
    pressed it): (what happened, what to show him)."""
    row = gateway_platform.connection(core, workspace_id)
    if row is None:
        return "ignored: no Hermes channel", ""
    from agos_core.actions import channels

    with channels._WORK, transaction(core.db):
        outcome, shown = channels.button(core, row, hermes_addresses.address_of(address), data)
    log.info("hermes channel %s: %s", row["id"], outcome)
    if shown and not shown.startswith("Already"):
        # The plugin shows the answer on the card itself (like Hermes's own buttons).
        channels.mark_card_closed(core, int(row["id"]), message_id)
    return outcome, shown
