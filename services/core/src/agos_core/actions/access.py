"""Who says yes to a command an agent wants to run: Hermes's own approvals.

AGOS keeps no copy of the owner's switches; they are Hermes's settings and state:

- The workspace's switch is its Co-Founder profile's `approvals.mode` (the root's
  config.yaml). Full access = `off` on every profile of its root (the Co-Founder and
  each member): nothing is asked anywhere in it (its chats, its automations, its
  cards). Still only inside the workspace's sandbox; Hermes's hard blocks (wiping
  the disk...) and `approvals.deny` always apply. Ask me first = `manual` (Hermes's
  own "smart" mode would let its model approve some). A member's profile follows
  its Co-Founder's (`follow_cofounder`).
- A chat's own switch is Hermes's per-conversation YOLO (what `/yolo` turns on):
  the gateway's session routing entry of that conversation keeps it (`yolo`,
  gateway/session.py SessionEntry), and Hermes clears it at a conversation boundary
  (/new, an idle reset). AGOS sends Hermes's own `/yolo` command into that
  conversation (H: gateway/slash_commands.py `_handle_yolo_command`: it makes the
  routing entry when there is none, toggles, and persists). `/yolo` only toggles,
  so AGOS reads the state first and sends it only when the switch differs; it
  reads it back from the gateway's routing index.
- An automation's run is allowed (`approvals.cron_mode: approve`, written with the
  switch); one that is "Check with me first" waits for his Start on the Kanban.

The owner's Autonomy rule "Ask me" is not a command approval: Full access never
answers it (the agos-guard plugin still asks him; a cron run, with nobody to ask,
is refused).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db import hermes_inbox
from agos_core.engine import doorbell
from agos_core.engine.owner_asks import ASK_RULE_MARK as ASK_RULE_MARK
from agos_core.engine.owner_asks import owner_rule as owner_rule
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.access")

MODES = ("off", "manual", "smart")
# An automation's run has nobody to ask: it runs (the owner's rule).
CRON_MODE = "approve"


def mode(core: Core, workspace_id: str) -> str:
    """The Co-Founder profile's `approvals.mode` as Hermes has it ("" = not set)."""
    if core.engine is None:
        return ""
    from agos_core.engine import config_file

    found = config_file.get(
        config_file.read(core.engine.profile_home(workspace_id)), "approvals.mode"
    )
    if found is False:  # YAML reads a bare `off` as false
        return "off"
    return str(found or "").strip().lower()


def workspace_full(core: Core, workspace_id: str) -> bool:
    return mode(core, workspace_id) == "off"


def set_workspace(core: Core, workspace_id: str, full: bool) -> None:
    """The owner's switch into Hermes: the Co-Founder's profile first, then each
    member follows it. No restart: the Co-Founder's next command reads it, and the
    root's gateway takes a member's changed config at its next profile re-scan
    (Hermes multiplexing, within 30 s)."""
    engine = core.engine
    if engine is None:
        return
    if (engine.profile_home(workspace_id) / "config.yaml").is_file():
        hermes_cli.cli(
            engine, workspace_id, "config", "set", "approvals.mode", "off" if full else "manual"
        )
        _cron_mode(engine, workspace_id, workspace_id)
    from agos_core.actions import agent_profiles

    members = [
        agent_profiles.key(ws, agent) for ws, agent in agent_profiles.existing(core, workspace_id)
    ]
    if not members:
        return
    # The members side by side, up to 4 at once (each under its own lock).
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(4, len(members))) as pool:
        list(pool.map(lambda key: follow_cofounder(engine, workspace_id, key), members))


def follow_cofounder(engine: Any, workspace_id: str, key: str) -> None:
    """A member's approvals = its Co-Founder's (the root's profile). Read and written
    under the member profile's lock: a member being made in the background never
    ends with an older switch than the owner's last one."""
    if not (engine.profile_home(key) / "config.yaml").is_file():
        return
    with engine._locks.hold(engine.profile(key)):
        value = _cofounder_mode(engine, workspace_id)
        # Hermes's own writer, which skips it when the member holds it already (a
        # re-sync of the team rewrote it every time).
        hermes_cli.config_writes(
            engine,
            key,
            [("config", "set", "approvals.mode", value if value in MODES else "manual")],
        )
        _cron_mode(engine, workspace_id, key)
        _follow_lists(engine, workspace_id, key)


def _cofounder_mode(engine: Any, workspace_id: str) -> str:
    """The Co-Founder's `approvals.mode`, read from the root's config.yaml the way
    Hermes reads it (parsed again only when the file changed): asking Hermes's CLI
    was one Hermes start (~0.65 s) per member, on every re-sync of the team. When
    the file holds none of the modes (no such line: Hermes fills in its default;
    another value; a file that can't be read), Hermes's own `config get` says."""
    from agos_core.engine import config_file

    found = config_file.value(engine.profile_home(workspace_id), "approvals.mode")
    if found is False:  # YAML reads a bare `off` as false
        return "off"
    if found in MODES:
        return str(found)
    value = (
        hermes_cli.cli(engine, workspace_id, "config", "get", "approvals.mode").strip().strip("\"'")
    )
    return "off" if value.lower() == "false" else value


def _cron_mode(engine: Any, workspace_id: str, key: str) -> None:
    """`approvals.cron_mode`: AGOS's recommendation (engine/owner_choices.py) only
    where the profile has none; a member starts on its Co-Founder's value. Afterwards
    the owner's (Settings → Hermes settings)."""
    from agos_core.engine import config_file
    from agos_core.engine.owner_choices import keep_owner

    pairs = keep_owner(
        {"approvals.cron_mode": CRON_MODE},
        config_file.read(engine.profile_home(key)),
        config_file.read(engine.profile_home(workspace_id)),
    )
    for value in pairs.values():
        hermes_cli.cli(engine, key, "config", "set", "approvals.cron_mode", value)


# ---- Hermes's own deny and allow rules (the Access card) -------------------------------

# Hermes's keys: `approvals.deny` (case-insensitive fnmatch globs; a match blocks a
# command even under Full access / mode off: tools/approval_floors.py :31) and
# `command_allowlist` (commands or dangerous-pattern keys allowed without asking;
# Hermes adds to it itself on "Always allow": tools/approval.py _persist_choice,
# globs matched in approval_floors.py _command_matches_permanent_allowlist).
LISTS: dict[str, str] = {"deny": "approvals.deny", "allow": "command_allowlist"}


def _list_of(config: dict[str, Any], key: str) -> list[str]:
    from agos_core.engine import config_file

    found = config_file.get(config, key)
    if isinstance(found, str):  # an old scalar list (Hermes recovers it the same way)
        try:
            found = json.loads(found)
        except ValueError:
            found = [found] if found.strip() else []
    return [str(x) for x in found if isinstance(x, str)] if isinstance(found, list) else []


def lists(core: Core, workspace_id: str) -> dict[str, list[str]]:
    """The workspace's deny and allow rules as its Co-Founder's Hermes has them."""
    if core.engine is None:
        return {name: [] for name in LISTS}
    from agos_core.engine import config_file

    config = config_file.read(core.engine.profile_home(workspace_id))
    return {name: _list_of(config, key) for name, key in LISTS.items()}


def _clean(entries: Any) -> list[str]:
    if not isinstance(entries, list) or any(not isinstance(e, str) for e in entries):
        raise ActionError("Use a list of commands or patterns.")
    return list(dict.fromkeys(e.strip() for e in entries if e.strip()))


def set_lists(core: Core, workspace_id: str, deny: Any, allow: Any) -> dict[str, list[str]]:
    """The owner's deny and allow rules into Hermes: the Co-Founder's profile, then each
    member (members keep entries only they have, e.g. their own "Always allow",
    unless the owner just removed that entry from the Co-Founder's list)."""
    engine = core.engine
    if engine is None:
        raise ActionError("Hermes isn't available.", status=503)
    wanted = {"deny": _clean(deny), "allow": _clean(allow)}
    from agos_core.engine import config_file

    root = engine.profile_home(workspace_id)
    if not (root / "config.yaml").is_file():
        raise ActionError("This workspace's Hermes isn't set up yet.", status=409)
    before = lists(core, workspace_id)
    for name, key in LISTS.items():
        if before[name] != wanted[name]:
            hermes_cli.cli(engine, workspace_id, "config", "set", key, json.dumps(wanted[name]))
    from agos_core.actions import agent_profiles

    for ws, agent in agent_profiles.existing(core, workspace_id):
        member = agent_profiles.key(ws, agent)
        home = engine.profile_home(member)
        if not (home / "config.yaml").is_file():
            continue
        config = config_file.read(home)
        for name, key in LISTS.items():
            have = _list_of(config, key)
            own = [e for e in have if e not in before[name] and e not in wanted[name]]
            merged = [*wanted[name], *own]
            if merged != have:
                hermes_cli.cli(engine, member, "config", "set", key, json.dumps(merged))
    return lists(core, workspace_id)


def _follow_lists(engine: Any, workspace_id: str, key: str) -> None:
    """A member starts with its Co-Founder's deny and allow rules (keeping its own)."""
    from agos_core.engine import config_file

    cofounder = config_file.read(engine.profile_home(workspace_id))
    mine = config_file.read(engine.profile_home(key))
    for name in LISTS.values():
        wanted = _list_of(cofounder, name)
        have = _list_of(mine, name)
        merged = [*wanted, *(e for e in have if e not in wanted)]
        if merged != have:
            hermes_cli.cli(engine, key, "config", "set", name, json.dumps(merged))


# ---- a chat's own switch: Hermes's per-conversation /yolo ------------------------------


def _same_chat(lane: dict[str, Any], address: str) -> bool:
    """A routing entry of this AGOS conversation or Telegram chat (topic), by the
    origin Hermes recorded on it (no AGOS-built key)."""
    if address.startswith("agos:"):
        return lane.get("platform") == "agos" and lane.get("chat_id") == address[5:]
    chat, _, thread = address.partition(":")
    if lane.get("platform") != "telegram" or lane.get("chat_id") != chat:
        return False
    return (lane.get("thread_id") or "0") == (thread or "0")


def chat_full(core: Core, workspace_id: str, chat_id: int) -> bool:
    """The chat's own Full access: its Hermes conversation has /yolo on (Hermes's
    routing index, read by Hermes: engine.hermes_lanes)."""
    if core.engine is None:
        return False
    from agos_core.actions import hermes_channel
    from agos_core.engine.hermes import EngineError

    where = hermes_channel.chat_on_hermes(core, chat_id)
    if where is None:
        return False
    address = str(where["address"])
    root, homes = lane_homes(core, workspace_id)
    try:
        lanes = core.engine.hermes_lanes(root, homes)
    except (EngineError, OSError, ValueError) as error:
        log.info("Hermes's session index of %s not read: %s", workspace_id, error)
        return False
    found = [
        (str(lane.get("updated_at") or ""), lane.get("yolo") is True)
        for home_lanes in lanes.values()
        for lane in home_lanes
        if _same_chat(lane, address)
    ]
    return max(found)[1] if found else False


def lane_homes(core: Core, workspace_id: str) -> tuple[Path, list[Path]]:
    """The homes whose routing index says a chat's /yolo: the root and its members."""
    assert core.engine is not None
    root = core.engine.profile_home(workspace_id)
    return root, [root, *sorted(p for p in (root / "profiles").glob("*") if p.is_dir())]


def read_ahead(core: Core) -> None:
    """engine/read_ahead.py: each workspace's routing index (every chat's Full access),
    asked from Hermes once after a start, so the first chat opened doesn't wait."""
    from agos_core.db import workspaces as workspaces_repo
    from agos_core.engine.hermes import EngineError

    if core.engine is None:
        return
    for ws in workspaces_repo.list_workspaces(core.db):
        if not (core.engine.profile_home(ws.id) / "config.yaml").is_file():
            continue  # no Hermes root yet: nothing to ask
        try:
            core.engine.hermes_lanes(*lane_homes(core, ws.id))
        except (EngineError, OSError, ValueError) as error:
            log.info("Hermes's session index of %s not read ahead: %s", ws.id, error)


YOLO_WAIT_S = 20.0
YOLO = "/yolo"  # Hermes's own command: toggles the conversation's YOLO


def set_chat(core: Core, workspace_id: str, chat_id: int, full: bool) -> None:
    """The owner's switch for one chat: Hermes's own /yolo in its conversation,
    sent only when Hermes's state differs (it is a toggle). Answers once Hermes's
    routing entry says what he asked. Only a chat of this workspace (NotFoundError)."""
    from agos_core.actions import hermes_channel
    from agos_core.actions.services.chat.chat_records import require_chat

    require_chat(core, workspace_id, chat_id)
    where = hermes_channel.chat_on_hermes(core, chat_id)
    if where is None:
        raise ActionError("This chat has no Hermes conversation to switch.")
    if chat_full(core, workspace_id, chat_id) == full:
        return
    item = hermes_inbox.put(core.db, workspace_id, str(where["address"]), YOLO, "command")
    doorbell.ring(doorbell.INBOX, workspace_id)
    hermes_channel.mark_own_command(core, str(where["address"]))
    deadline = time.monotonic() + YOLO_WAIT_S
    while time.monotonic() < deadline:
        there, done = hermes_inbox.done_mark(core.db, workspace_id, item)
        taken = not there or done
        if taken and chat_full(core, workspace_id, chat_id) == full:
            return
        time.sleep(0.2)
    hermes_inbox.drop_unfinished(core.db, workspace_id, item)
    raise ActionError("The workspace's Hermes didn't take it. Try again in a moment.", 503)
