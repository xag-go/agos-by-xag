"""Hermes's own gateway as a workspace's channel: the connection row, the bridge file
and key in the profile, the profile's .env, the Telegram bot's on/off, token and
reactions, and the gateway restart.

Owns: what AGOS writes into a workspace's Hermes profile to serve a channel.
Must not: know about chats, turns or messages (that is chat_turns / gateway_mirror).

Part of the Channel service (moved out of actions/hermes_channel.py, which re-exports
every name for old callers)."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.db import app_settings, chat_turns
from agos_core.db import channel_connections as connections_repo
from agos_core.db import chats as chats_repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.domain.secrets import same_secret
from agos_core.hermes_gateway import cli as hermes_cli

__all__ = [
    "AGOS_OWNER",
    "BOT_SWITCH",
    "BRIDGE_FILE",
    "ENGINE_HERMES",
    "ENV_PREFIX",
    "MOVE_OFF",
    "REACTIONS",
    "STALE_AFTER_S",
    "TOKEN_LINE",
    "TURN_WAIT_S",
    "bot_on",
    "bot_token",
    "bridge_key",
    "cofounder_chat",
    "connection",
    "inside_turn",
    "key_ok",
    "move_old_switches",
    "prepare_profile",
    "profile_env",
    "reactions_on",
    "refresh_bridge",
    "restart_gateway",
    "set_bot_on",
    "set_reactions",
    "token_held_by",
    "write_token",
]

log = logging.getLogger("agos.hermes_channel")


ENGINE_HERMES = "hermes"
BRIDGE_FILE = "agos-bridge.json"
# The .env lines AGOS writes (TELEGRAM_ALLOWED_USERS is Hermes's own: its allowlist,
# changed by its pairing and `hermes config set`, actions/telegram_people.py).
ENV_PREFIX = ("TELEGRAM_BOT_TOKEN=", "TELEGRAM_REACTIONS=", "AGOS_PLATFORM_", "WEBHOOK_")
# Hermes turns that never reported their end (gateway restarted mid-answer, …).
STALE_AFTER_S = 3 * 3600
AGOS_OWNER = "owner"  # who writes in AGOS (its own sign-in decides who that is)


def connection(core: Core, workspace_id: str) -> sqlite3.Row | None:
    """The workspace's Telegram bot run by Hermes, if any."""
    return connections_repo.hermes_telegram(core.db, workspace_id, ENGINE_HERMES, only_on=True)


def bridge_key(core: Core, workspace_id: str) -> str:
    digest = hmac.new(
        core.internal_token.encode(), f"hermes-bridge:{workspace_id}".encode(), hashlib.sha256
    )
    return digest.hexdigest()


def key_ok(core: Core, workspace_id: str, given: str) -> bool:
    return same_secret(given, bridge_key(core, workspace_id))


def cofounder_chat(core: Core, workspace_id: str) -> int | None:
    """The workspace's Co-Founder chat (the agos platform's home chat)."""
    return chats_repo.cofounder_chat_id(core.db, workspace_id)


def profile_env(core: Core, workspace_id: str) -> dict[str, str]:
    """TELEGRAM_* lines of the profile's .env: the bot token (who may talk to it is
    Hermes's own allowlist and pairing); AGOS_PLATFORM_* (its AGOS conversations);
    WEBHOOK_* (its webhook routes)."""
    from agos_core.actions import hooks

    env: dict[str, str] = hooks.hook_env(core, workspace_id)  # webhooks reach Hermes first
    # Every workspace's AGOS chats are its Hermes's conversations (the agos platform).
    env |= {"AGOS_PLATFORM_ENABLED": "true", "AGOS_PLATFORM_ALLOWED_USERS": AGOS_OWNER}
    cofounder = cofounder_chat(core, workspace_id)
    if cofounder is not None:  # where Hermes delivers its own notices (cron results…)
        env["AGOS_PLATFORM_HOME_CHANNEL"] = str(cofounder)
    # The token stays while the bot is off: its on/off is Hermes's own switch
    # (platforms.telegram.enabled, bot_on), never the token's presence.
    row = connections_repo.hermes_telegram(core.db, workspace_id, ENGINE_HERMES, only_on=False)
    if row is None:
        return env
    token = bot_token(core, workspace_id)
    if not token:
        return env
    # Hermes's 👀 / ✅ / ❌ is its own `telegram.reactions` (shown and switched on the
    # bot's card, reactions_on); AGOS no longer forces it in .env.
    return env | {"TELEGRAM_BOT_TOKEN": token}


TOKEN_LINE = "TELEGRAM_BOT_TOKEN="  # noqa: S105 - the .env key, not a secret
REACTIONS = "telegram.reactions"  # Hermes's 👀 / ✅ / ❌ while it works (default off)
_OLD_REACTIONS = "TELEGRAM_REACTIONS="  # what AGOS used to force in .env (it wins over YAML)
BOT_SWITCH = "platforms.telegram.enabled"  # Hermes's own on/off of its Telegram bot
MOVE_OFF = "telegram.off.move."  # + workspace id: an old AGOS "off", put into Hermes once


# Each workspace's bot on/off as last read, per database connection: (stamp, on).
# It is read on every outbox / reaction poll and per row by agos_bot_on(); asking
# app_settings and copying Hermes's whole config each time was the cost.
_bot_seen: weakref.WeakKeyDictionary[Any, dict[str, tuple[tuple[Any, ...], bool]]] = (
    weakref.WeakKeyDictionary()
)


def bot_on(core: Core, workspace_id: str) -> bool:
    """The owner's on/off of the workspace's bot: Hermes's `platforms.telegram.enabled`
    in its root profile (an explicit false wins over the token in .env,
    gateway/config_env.py _enable_from_env); unset = on (Hermes starts a bot it has a
    token for). An old AGOS "off" not yet in Hermes counts until it is.

    Read again only when Hermes's config.yaml changed (its mtime and size) or AGOS
    wrote anything to its database since (`total_changes`: the old "off" is
    AGOS's own row), so the answer is always the files' and rows' current one."""
    from agos_core.engine import config_file

    home = core.engine.profile_home(workspace_id) if core.engine is not None else None
    stamp = (core.db.total_changes, config_file.stamp(home) if home is not None else None)
    try:
        seen = _bot_seen.setdefault(core.db, {})
    except TypeError:  # a plain test connection can't be weakly referenced: no memory
        seen = {}
    found = seen.get(workspace_id)
    if found is not None and found[0] == stamp:
        return found[1]
    on = _bot_on_now(core, workspace_id, home)
    seen[workspace_id] = (stamp, on)
    return on


def _bot_on_now(core: Core, workspace_id: str, home: Path | None) -> bool:
    from agos_core.db.app_settings import get_setting

    if get_setting(core.db, MOVE_OFF + workspace_id, None) is not None:
        return False
    if home is None:
        return True
    from agos_core.engine import config_file

    found = config_file.value(home, BOT_SWITCH)
    return str(found).strip().lower() not in ("false", "0", "no", "off")


def set_bot_on(core: Core, workspace_id: str, on: bool) -> None:
    """Turns the bot on or off in Hermes (its own switch; the token stays in .env)."""
    if core.engine is None:
        raise ValueError("No engine to turn the bot on or off.")
    hermes_cli.cli(
        core.engine, workspace_id, "config", "set", BOT_SWITCH, "true" if on else "false"
    )
    app_settings.delete_setting(core.db, MOVE_OFF + workspace_id)


# Set while a Co-Founder action runs (actions/cofounder_more.do): the action is a tool
# call INSIDE a turn of the very gateway a restart would stop.
_IN_TURN: contextvars.ContextVar[bool] = contextvars.ContextVar("agos_in_turn", default=False)
TURN_WAIT_S = 600.0  # the longest a restart waits for the workspace's chat answers


@contextlib.contextmanager
def inside_turn() -> Iterator[None]:
    token = _IN_TURN.set(True)
    try:
        yield
    finally:
        _IN_TURN.reset(token)


def _answers_running(core: Core, workspace_id: str) -> bool:
    root = core.engine.split(workspace_id)[0] if core.engine is not None else workspace_id
    return chat_turns.workspace_busy(core.db, root)


def restart_gateway(core: Core, workspace_id: str, *, wait: bool = False) -> None:
    """Hermes reads its platform switches when its gateway starts: a running one is
    restarted off the request (Hermes's own stop drains running answers first).
    `wait` restarts it before returning (a new bot is "saved" once it truly runs).

    From a Co-Founder action (`inside_turn`) the restart never waits and starts only
    once the workspace's chat answers ended: a stop while its own turn waits on this
    tool call drained for 60 s and then cut that turn off."""
    engine = core.engine
    if engine is None:
        return
    after_turn = _IN_TURN.get()

    def run() -> None:
        if after_turn:
            deadline = time.monotonic() + TURN_WAIT_S
            time.sleep(1.0)
            while time.monotonic() < deadline and _answers_running(core, workspace_id):
                time.sleep(2.0)
        try:
            if engine.is_running(workspace_id):
                engine.stop(workspace_id)
                engine.start(workspace_id)
        except Exception as error:  # noqa: BLE001 — Hermes's service keeps it up afterwards
            log.warning("gateway of %s not restarted: %s", workspace_id, error)

    if wait and not after_turn:
        run()
        return
    threading.Thread(target=run, name=f"bot-switch-{workspace_id}", daemon=True).start()


def reactions_on(core: Core, workspace_id: str) -> bool:
    """Hermes's `telegram.reactions` in the root profile (a TELEGRAM_REACTIONS line in
    .env wins over it: plugins/platforms/telegram/adapter.py _reactions_enabled)."""
    if core.engine is None:
        return False
    from agos_core.engine import config_file

    home = core.engine.profile_home(workspace_id)
    env = config_file.read_env(home).get("TELEGRAM_REACTIONS")
    value = env if env is not None else config_file.get(config_file.read(home), REACTIONS)
    return str(value).strip().lower() in ("true", "1", "yes", "on")


def set_reactions(core: Core, workspace_id: str, on: bool) -> None:
    """The owner's choice, in Hermes's own key."""
    if core.engine is None:
        raise ValueError("No engine to change the bot's reactions.")
    hermes_cli.cli(core.engine, workspace_id, "config", "set", REACTIONS, "true" if on else "false")


def _move_old_reactions(core: Core, workspace_id: str, home: Path) -> bool:
    """AGOS used to force TELEGRAM_REACTIONS=true into .env (no card): the owner kept
    those reactions, so they go into Hermes's own key once; the .env line then goes.
    False when Hermes didn't take it (the line stays until it does)."""
    try:
        lines = (home / ".env").read_text().splitlines()
    except OSError:
        return True
    if not any(line.startswith(_OLD_REACTIONS) for line in lines):
        return True
    try:
        set_reactions(core, workspace_id, True)
    except Exception as error:  # noqa: BLE001 — tried again at the next apply
        log.warning("reactions of %s not moved into Hermes: %s", workspace_id, error)
        return False
    return True


def move_old_switches(core: Core) -> int:
    """Bots AGOS had turned off itself (the dropped channel_connections.enabled): their
    off goes into Hermes once, then AGOS's mark goes."""
    moved = 0
    for key, _value in app_settings.with_prefix(core.db, MOVE_OFF):
        workspace_id = key[len(MOVE_OFF) :]
        try:
            set_bot_on(core, workspace_id, False)
            moved += 1
        except Exception as error:  # noqa: BLE001 — tried again at the next start
            log.warning("bot switch of %s not moved into Hermes: %s", workspace_id, error)
    return moved


def bot_token(core: Core, workspace_id: str) -> str:
    """The workspace's bot token: only in its Hermes's .env (Hermes's own place for
    it, carried by its backups); AGOS keeps no copy."""
    if core.engine is None:
        return ""
    env_file = core.engine.profile_home(workspace_id) / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith(TOKEN_LINE):
            return line[len(TOKEN_LINE) :].strip()
    return ""


def write_token(core: Core, workspace_id: str, token: str) -> None:
    """Puts the bot token into the workspace's Hermes (.env), replacing the old one."""
    if core.engine is None:
        raise ValueError("No engine to keep the bot's token.")
    if "\n" in token or "\r" in token:
        raise ValueError("A bot token can't contain line breaks.")
    from agos_core.engine import envfile

    held = token_held_by(core, workspace_id, token)
    if held is not None:
        from agos_core.actions.errors import ActionError

        raise ActionError(
            f"That bot is already the bot of the workspace “{held}”. One bot can't serve "
            "two workspaces: make another one with @BotFather.",
            409,
        )
    home = core.engine.profile_home(workspace_id)
    home.mkdir(parents=True, exist_ok=True)
    envfile.rewrite(home / ".env", (TOKEN_LINE,), [f"{TOKEN_LINE}{token}"])


def token_held_by(core: Core, workspace_id: str, token: str) -> str | None:
    """The name of ANOTHER workspace whose Hermes already holds this bot token.
    Each root's gateway keeps its locks in its own folder (engine/hermes.py
    lock_dir, Hermes's HERMES_GATEWAY_LOCK_DIR), so Hermes's machine-wide token
    lock (gateway/status.py acquire_scoped_lock) can no longer see two roots on one
    bot: AGOS refuses it where the token is written."""
    if core.engine is None or not token.strip():
        return None
    from agos_core.actions.engine import workspace_name

    for other in workspaces_repo.other_ids(core.db, workspace_id):
        if bot_token(core, other) == token.strip():
            return workspace_name(core, other) or other
    return None


def prepare_profile(core: Core, workspace_id: str, home: Path, core_url: str) -> str:
    """Writes the TELEGRAM_* lines and the plugin's bridge file. Returns a digest of
    the lines, so a change restarts the gateway (and nothing else does)."""
    from agos_core.actions.services.channel import owner_needs

    # The Co-Founder's chat, made now if the workspace has none yet: Hermes's home
    # channel, and where its Kanban notifier tells the owner (the bridge file).
    owner_needs.ensure_cofounder_chat(core, workspace_id)
    env = profile_env(core, workspace_id)
    if not _move_old_reactions(core, workspace_id, home):
        env["TELEGRAM_REACTIONS"] = "true"  # kept until Hermes's own key holds it
    from agos_core.engine import envfile

    if any("\n" in v or "\r" in v for v in env.values()):
        raise ValueError("A channel setting can't contain line breaks.")
    envfile.rewrite(home / ".env", ENV_PREFIX, [f"{n}={v}" for n, v in sorted(env.items())])
    if env:
        _write_bridge(core, workspace_id, home, core_url)
    else:
        (home / BRIDGE_FILE).unlink(missing_ok=True)
    return hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()


def _write_bridge(core: Core, workspace_id: str, home: Path, core_url: str) -> None:
    from agos_core.actions.services.channel import owner_needs

    content: dict[str, Any] = {
        "core": core_url,
        "workspace": workspace_id,
        "key": bridge_key(core, workspace_id),
    }
    notify = owner_needs.kanban_notify_target(core, workspace_id)
    if notify is not None:
        content["notify"] = notify  # Hermes's Kanban notifier: the Co-Founder's chat
    body = json.dumps(content, sort_keys=True)
    bridge = home / BRIDGE_FILE
    if bridge.is_file() and bridge.read_text() == body:
        return
    tmp = bridge.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(body)
    tmp.replace(bridge)


def refresh_bridge(core: Core, workspace_id: str) -> None:
    """The Co-Founder's chat moved (linked to his Telegram, say): the plugin's bridge
    file follows at once (it reads it again when it changes)."""
    if core.engine is None:
        return
    home = core.engine.profile_home(workspace_id)
    if not (home / BRIDGE_FILE).is_file():
        return
    from agos_core.actions import apps

    _write_bridge(core, workspace_id, home, apps.core_url())
