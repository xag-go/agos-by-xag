"""A member's DM linked to a Telegram topic is Hermes's own routed conversation.

Hermes routes a chat or forum topic of the workspace's one bot to a member's
profile with `gateway.profile_routes` in the root's config (H:
gateway/profile_routing.py; stamped on the message in gateway/platforms/base.py
`build_source`, honoured in gateway/run.py `_profile_name_for_source`). The member
then answers in the topic itself, as its own profile (its SOUL, memory, skills,
`.env`, voice notes, `gateway.message_timestamps`), Hermes sends the answer from
the shared bot into the same topic, and Hermes's own /commands typed there run on
that member's session. AGOS keeps nothing of it: the web chat reads the member's
own session (db/hermes_chats.py), and what he writes in AGOS goes into that same
session (the agos-guard plugin's inbox).

AGOS only says which topic is which member: it writes the routes into the root's
config with Hermes's `config set` (under the workspace's config lock), keeping any
route the owner wrote himself, and restarts the root's gateway, which reads its
routes once when it starts (H: gateway/run.py `GatewayRunner.__init__`, the config
is loaded once; there is no hot reload of routes).

The member's conversation from before (on the agos platform) goes on in the topic:
Hermes's own session store points the topic's session key at it
(`SessionStore.switch_session`, what Hermes's /resume and /handoff call: H:
gateway/slash_commands_session.py `_handle_resume_command`, gateway/run_startup.py
`_process_handoff`), done once by the plugin inside the gateway (a "bind" inbox
item). /resume itself refuses it: the old session is an agos-platform one, and a
cross-platform resume needs `/resume <id> --all` by an explicitly configured
admin (H: gateway/slash_commands_session.py `_resume_target_allowed`,
`_persisted_row_proves_owner`), which turns on slash-command gating for every
group sender (H: gateway/slash_access.py) and needs a restart. Hermes's `sessions`
CLI has no command that binds a session to a chat.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from agos_core.context import Core
from agos_core.db import channel_connections, chat_addresses, hermes_inbox
from agos_core.db.app_settings import delete_setting
from agos_core.engine import doorbell

log = logging.getLogger("agos.member_topics")

ROUTE_PREFIX = "agos-topic-"  # AGOS's own routes; any other route is the owner's
ROUTES_KEY = "gateway.profile_routes"
BIND = "bind"  # the inbox item that points the topic's session at the old one
# The start mark of AGOS's own relay of member answers (before Hermes routed the
# topics): dropped at core start.
OLD_RELAY_MARK = "channels.hermes_replies_since"

_restart_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _restart_lock(workspace_id: str) -> threading.Lock:
    with _guard:
        return _restart_locks.setdefault(workspace_id, threading.Lock())


def linked(core: Core, workspace_id: str) -> list[dict[str, Any]]:
    """The workspace's member DMs linked to a place of its Hermes bot, whose member
    has its own profile: {chat_id, agent, address}."""
    from agos_core.actions import agent_profiles

    out = []
    for r in chat_addresses.member_dm_places(core.db, workspace_id):
        agent = str(r["agent"])
        if agent_profiles.ready(core, workspace_id, agent):
            out.append({"chat_id": int(r["id"]), "agent": agent, "address": str(r["address"])})
    return out


def _hermes_profile(core: Core, workspace_id: str, agent: str) -> str:
    """The member's profile as Hermes names it in the root ("a-writer")."""
    from agos_core.actions import agent_profiles

    assert core.engine is not None
    return core.engine.hermes_name(agent_profiles.key(workspace_id, agent))


def wanted_routes(core: Core, workspace_id: str) -> list[dict[str, str]]:
    """Hermes's routes for the workspace's member topics, one per linked place: the
    chat and its topic (a topic route outranks a chat one: H:
    gateway/profile_routing.py `specificity`). A group's General (address `:0`) is
    the whole group only when nothing else of AGOS lives in that group; otherwise
    Hermes's General thread ("1")."""
    if core.engine is None:
        return []
    links = linked(core, workspace_id)
    every = chat_addresses.visible_addresses(core.db, workspace_id)
    routes = []
    for link in links:
        chat, _, thread = link["address"].partition(":")
        route = {
            "name": f"{ROUTE_PREFIX}{chat}-{thread or '0'}",
            "platform": "telegram",
            "chat_id": chat,
            "profile": _hermes_profile(core, workspace_id, link["agent"]),
        }
        if thread not in ("", "0"):
            route["thread_id"] = thread
        elif chat.startswith("-") and any(
            a.partition(":")[0] == chat and a != link["address"] for a in every
        ):
            route["thread_id"] = "1"  # the forum's General only
        routes.append(route)
    return sorted(routes, key=lambda r: r["name"])


def _current(core: Core, workspace_id: str) -> list[Any]:
    from agos_core.engine import config_file

    assert core.engine is not None
    found = config_file.get(config_file.read(core.engine.profile_home(workspace_id)), ROUTES_KEY)
    return list(found) if isinstance(found, list) else []


def _ours(route: Any) -> bool:
    return isinstance(route, dict) and str(route.get("name") or "").startswith(ROUTE_PREFIX)


def _same(a: list[Any], b: list[Any]) -> bool:
    def norm(routes: list[Any]) -> str:
        return json.dumps(
            [{k: str(v) for k, v in r.items()} if isinstance(r, dict) else r for r in routes],
            sort_keys=True,
        )

    return norm(a) == norm(b)


def write_routes(core: Core, workspace_id: str) -> bool:
    """The root's `gateway.profile_routes` say which topic is which member (Hermes's
    own `config set`; the owner's own routes are kept). True when it changed."""
    engine = core.engine
    if engine is None:
        return False
    if not (engine.profile_home(workspace_id) / "config.yaml").is_file():
        return False
    from agos_core.actions.library import workspace_lock

    with workspace_lock(workspace_id):
        have = _current(core, workspace_id)
        wanted = [r for r in have if not _ours(r)] + wanted_routes(core, workspace_id)
        if _same(have, wanted):
            return False
        engine.set_setting(workspace_id, ROUTES_KEY, json.dumps(wanted))
    log.info("%s: member topics routed by Hermes: %d route(s)", workspace_id, len(wanted))
    return True


def sync(core: Core, workspace_id: str, *, restart: bool = True) -> bool:
    """The routes as AGOS's links say, the root's gateway restarted when they
    changed (it reads them when it starts), then each linked topic's earlier
    conversation bound to it. Safe to repeat. True when the routes changed."""
    engine = core.engine
    if engine is None:
        return False
    with _restart_lock(workspace_id):
        changed = write_routes(core, workspace_id)
        if changed and restart and engine.is_running(workspace_id):
            # Hermes's own stop drains running answers first (agent.restart_drain_timeout).
            engine.stop(workspace_id)
            engine.start(workspace_id)
    queue_binds(core, workspace_id)
    return changed


def follow(core: Core, workspace_id: str) -> None:
    """A link changed (in a request): the routes follow, off the request."""

    def run() -> None:
        try:
            sync(core, workspace_id)
        except Exception:
            log.exception("%s: member topics not routed", workspace_id)

    threading.Thread(target=run, name=f"member-topics-{workspace_id}", daemon=True).start()


def queue_binds(core: Core, workspace_id: str) -> int:
    """Each linked topic with no Hermes conversation of its own yet continues the
    member's conversation from before (its newest agos-platform session for that
    chat): a "bind" item for the plugin. Never twice: none while one waits, none
    once the topic has its own Telegram session in the member's profile."""
    from agos_core.actions import agent_profiles
    from agos_core.db import hermes_chats as hc

    store = hc.store()
    if store is None or core.engine is None:
        return 0
    queued = 0
    for link in linked(core, workspace_id):
        chat, _, thread = link["address"].partition(":")
        profile = store.profile_of(agent_profiles.key(workspace_id, link["agent"]))
        thread_ids = ["", "0", "1"] if thread in ("", "0") else [thread]
        own = store.query(
            profile,
            f"""SELECT 1 FROM sessions WHERE source = 'telegram' AND chat_id = ?
                  AND COALESCE(thread_id, '') IN ({",".join("?" * len(thread_ids))}) LIMIT 1""",
            [chat, *thread_ids],
        )
        if own:
            continue
        before = store.query(
            profile,
            """SELECT id FROM sessions WHERE source = 'agos' AND chat_id = ?
                 ORDER BY started_at DESC LIMIT 1""",
            [str(link["chat_id"])],
        )
        if not before:
            continue
        if hermes_inbox.waits_of_kind(core.db, workspace_id, link["address"], BIND):
            continue
        body = {
            "session": str(before[0]["id"]),
            "profile": _hermes_profile(core, workspace_id, link["agent"]),
        }
        hermes_inbox.put(core.db, workspace_id, link["address"], json.dumps(body), BIND)
        doorbell.ring(doorbell.INBOX, workspace_id)
        queued += 1
    return queued


def sync_all(core: Core) -> int:
    """Core start: every workspace with a Hermes bot gets its member topics routed by
    Hermes (the live migration from AGOS's own relay; safe to run again). The old
    relay's start mark goes."""
    delete_setting(core.db, OLD_RELAY_MARK)
    changed = 0
    for ws in channel_connections.hermes_telegram_workspaces(core.db):
        try:
            changed += int(sync(core, ws))
        except Exception:
            log.exception("%s: member topics not routed", ws)
    return changed
