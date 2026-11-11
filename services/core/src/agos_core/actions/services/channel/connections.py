"""A workspace's bot connections: their records and views, add, change, delete, check,
and the bot's live state (its @name as Hermes tells it, its lamp read from Hermes).
Must not: send a message or queue one (outbox does).

Split out of agos_core.actions.channels (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
from typing import Any, Literal

from agos_core.actions import telegram_people
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.channel import gateway_platform
from agos_core.actions.telegram_people import PairingRequest, Person
from agos_core.context import Core
from agos_core.db import channel_connections as connections_repo
from agos_core.db import workspaces as workspaces_repo
from agos_core.db.connection import transaction
from agos_core.db.records import Record
from agos_core.db.rows import now
from agos_core.engine import hermes_time
from agos_core.engine.hermes import EngineError

__all__ = [
    "TELEGRAM_LIMIT",
    "AddressView",
    "ClaimView",
    "ConnectionView",
    "Kind",
    "add_connection",
    "bot_is",
    "channel_ok_at",
    "channel_since",
    "channel_state",
    "check_one",
    "delete_connection",
    "list_connections",
    "read_ahead",
    "retry",
    "telegram_state",
    "update_connection",
    "workspace_bots",
]

log = logging.getLogger("agos.channels")

Kind = Literal["telegram"]
TELEGRAM_LIMIT = 4096  # one Telegram message; a longer card is cut (Hermes splits replies)


class ConnectionView(Record):
    id: int
    kind: Kind
    name: str
    secret: str  # ••••last4
    # Who the bot listens to, and who asked: Hermes's allowlist and DM pairing.
    allowed: list[str]
    people: list[Person]
    pending: list[PairingRequest]
    enabled: bool  # Hermes's own platforms.telegram.enabled (hermes_channel.bot_on)
    reactions: bool = False  # Hermes's own telegram.reactions (👀 / ✅ / ❌ while it works)
    status: Literal["connecting", "connected", "error"]
    status_reason: str
    identity: str
    last_ok_at: str | None
    workspace_id: str | None = None  # a bot made for one workspace (its Co-Founder chat)


class ClaimView(Record):
    """The bot's own link: writing to it there asks Hermes for a pairing code."""

    link: str
    expires_in: int  # seconds Hermes keeps the request


class AddressView(Record):
    id: int
    connection_id: int
    connection_name: str
    kind: Kind
    address: str
    label: str
    notify: bool
    status: Literal["connecting", "connected", "error"]
    status_reason: str


# ---- connections ------------------------------------------------------------------------

SETUP_LOCK = threading.Lock()


def _view(core: Core, row: Any) -> ConnectionView:
    from agos_core.actions import hermes_channel

    ws = str(row["workspace_id"] or "")
    who = telegram_people.people(core, ws) if ws else []
    # The lamp is Hermes's own state of the bot, read live (gateway_state.json).
    status, reason = channel_state(core, row)
    return ConnectionView(
        id=row["id"],
        kind=row["kind"],
        name=row["name"],
        # The token's end, read from its one home: the workspace's Hermes .env.
        secret=f"••••{hermes_channel.bot_token(core, ws)[-4:] if ws else ''}",
        allowed=[p.id for p in who],
        people=who,
        pending=telegram_people.pending(core, ws) if ws else [],
        enabled=hermes_channel.bot_on(core, ws) if ws else True,
        reactions=hermes_channel.reactions_on(core, ws) if ws else False,
        status=status,  # type: ignore[arg-type]
        status_reason=reason,
        identity=row["identity"],
        last_ok_at=channel_ok_at(core, row),
        workspace_id=row["workspace_id"],
    )


def list_connections(core: Core) -> list[ConnectionView]:
    rows = connections_repo.all_bots(core.db)
    return [_view(core, r) for r in rows]


def read_ahead(core: Core) -> None:
    """After the core starts (engine/read_ahead.py): every bot's state as its
    Hermes gateway has it (Settings → Channels and each workspace's bots read the
    same views)."""
    list_connections(core)


def _clean_allowed(allowed: list[str]) -> list[str]:
    out = []
    for a in allowed:
        a = a.strip().lstrip("@")
        if a and re.fullmatch(r"[A-Za-z0-9_:.-]{1,100}", a):
            out.append(a)
    return sorted(set(out))[:50]


def add_connection(
    core: Core,
    *,
    kind: Kind,
    name: str,
    secret: str,
    allowed: list[str],
    workspace_id: str | None = None,
    identity: str = "",
) -> int:
    secret = secret.strip()
    allowed_clean = _clean_allowed(allowed)
    if kind == "telegram" and workspace_id is None:
        # Like Hermes: each workspace has its own channels, run by its own gateway.
        raise ActionError(
            "A Telegram bot belongs to a workspace: add it in that workspace's settings."
        )
    if not allowed_clean and workspace_id is None:
        raise ActionError("Add at least one allowed person (your own account); others are ignored.")
    _not_the_bot(kind, secret, allowed_clean)
    if workspace_id is not None:
        if kind != "telegram":
            raise ActionError("Only a Telegram bot can be a workspace's own bot.")
        live_workspace(core, workspace_id)
    _token_shape(kind, secret)
    # The bot's @name: from its setup, or told by the workspace's Hermes once it connects.
    identity = f"@{identity.lstrip('@')}" if re.fullmatch(r"@?[A-Za-z0-9_]{3,40}", identity) else ""
    at = now()
    with transaction(core.db):
        cid = connections_repo.add(
            core.db, kind, name.strip() or kind.title(), identity, at, workspace_id
        )
        if workspace_id is not None:
            # The token's one home: the workspace's Hermes (AGOS keeps only its end).
            from agos_core.actions import hermes_channel

            hermes_channel.write_token(core, workspace_id, secret)
            # Who it starts with (the account that made it): Hermes's allowlist.
            telegram_people.allow(core, workspace_id, allowed_clean)
        if kind == "telegram":
            # Received by the workspace's own Hermes gateway.
            connections_repo.run_by(core.db, cid, "hermes")
    if kind == "telegram" and workspace_id is not None:
        from agos_core.actions import hermes_channel, library

        # A new bot is on, with Hermes's 👀 / ✅ / ❌ (the owner switches them on its
        # card): both are Hermes's own keys, set now in its root profile.
        with contextlib.suppress(EngineError, ValueError):
            if not hermes_channel.bot_on(core, workspace_id):
                hermes_channel.set_bot_on(core, workspace_id, True)
            hermes_channel.set_reactions(core, workspace_id, True)
        library.apply_workspace(core, workspace_id)  # its profile gets the bot now
        # Hermes reads TELEGRAM_BOT_TOKEN only when its gateway starts: one already
        # running (started before this bot existed) goes once more, or the bot
        # stays silent until something else restarts it. A no-op when it's down.
        hermes_channel.restart_gateway(core, workspace_id, wait=True)
    return cid


def _token_shape(kind: str, secret: str) -> None:
    """A bot token looks like 123456789:AA…; whether it works is Hermes's to say."""
    if kind == "telegram" and not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", secret):
        raise ActionError("That isn't a bot token (it looks like 123456789:AA…, from @BotFather).")


def _not_the_bot(kind: str, secret: str, allowed: list[str]) -> None:
    """The number before ":" in a bot token is the bot's own id, not a person."""
    bot_id = secret.split(":", 1)[0]
    if kind == "telegram" and bot_id in allowed:
        raise ActionError(
            f"{bot_id} is the bot's own id (the start of its token), not your account. "
            "Leave it out and use “Link my Telegram account” instead."
        )


def live_workspace(core: Core, workspace_id: str) -> None:
    if not workspaces_repo.is_live(core.db, workspace_id):
        raise NotFoundError("This workspace")


def update_connection(
    core: Core,
    connection_id: int,
    *,
    name: str,
    enabled: bool,
    secret: str | None,
    reactions: bool | None = None,
) -> None:
    """Its name is AGOS's; on/off and the reactions are Hermes's own switches."""
    row = connection_row(core, connection_id)
    if secret and row["workspace_id"]:
        _not_the_bot(
            row["kind"], secret.strip(), telegram_people.ids(core, str(row["workspace_id"]))
        )
    if secret:
        _token_shape(row["kind"], secret.strip())
        if row["workspace_id"]:
            from agos_core.actions import hermes_channel

            hermes_channel.write_token(core, str(row["workspace_id"]), secret.strip())
    connections_repo.set_name(core.db, connection_id, name.strip() or row["name"])
    if not row["workspace_id"]:
        return
    from agos_core.actions import hermes_channel

    workspace_id = str(row["workspace_id"])
    changed = bool(secret)  # a new token is read only when the gateway starts
    try:
        if enabled != hermes_channel.bot_on(core, workspace_id):
            hermes_channel.set_bot_on(core, workspace_id, enabled)
            changed = True
        if reactions is not None and reactions != hermes_channel.reactions_on(core, workspace_id):
            hermes_channel.set_reactions(core, workspace_id, reactions)
            changed = True
    except (EngineError, ValueError) as error:
        raise ActionError("The engine didn't take the change. Try again.", 503) from error
    if changed:
        hermes_channel.restart_gateway(core, workspace_id)


def delete_connection(core: Core, connection_id: int) -> None:
    connection_row(core, connection_id)
    connections_repo.delete(core.db, connection_id)


def retry(core: Core, connection_id: int) -> ConnectionView:
    connection_row(core, connection_id)
    check_one(core, connection_id)
    return _view(core, connection_row(core, connection_id))


def connection_row(core: Core, connection_id: int) -> Any:
    row = connections_repo.get(core.db, connection_id)
    if row is None:
        raise NotFoundError("This connection")
    return row


def check_one(core: Core, connection_id: int) -> None:
    """The workspace's Hermes gateway, started if down (its lamp is read live)."""
    row = connection_row(core, connection_id)
    if not row["workspace_id"]:
        return
    workspace_id = str(row["workspace_id"])
    if core.engine is not None and not core.engine.is_running(workspace_id):
        with contextlib.suppress(Exception):  # Hermes's service keeps it up afterwards
            core.engine.start(workspace_id)


def workspace_bots(core: Core, workspace_id: str) -> list[ConnectionView]:
    rows = connections_repo.of_workspace(core.db, workspace_id)
    return [_view(core, r) for r in rows]


# ---- the bot's live state (Hermes's gateway_state.json) -------------------------------


def bot_is(core: Core, workspace_id: str, name: str) -> None:
    """The bot's @name, told by the workspace's Hermes once its Telegram connected.
    AGOS keeps it: Hermes holds it only in its running adapter (H:
    plugins/platforms/telegram/adapter.py `_note_bot_username`), not in
    gateway_state.json."""
    name = name.strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,40}", name):
        return
    row = gateway_platform.connection(core, workspace_id)
    if row is not None:
        connections_repo.set_identity(core.db, int(row["id"]), f"@{name}")


def _telegram(core: Core, workspace_id: str) -> tuple[str, str, str | None]:
    """The bot as the workspace's Hermes gateway sees it, read live with Hermes's
    own status functions (engine.gateway_status: H: gateway/status.py
    read_runtime_status, runtime_status_pid_is_live, runtime_status_is_stale):
    ("connected" | "error" | "connecting", Hermes's reason, when Hermes set that
    state). A crashed or wedged gateway's last snapshot never shows a green lamp.
    AGOS keeps no copy of it."""
    if core.engine is None:
        return "connecting", "", None
    # A page's lamp: Hermes is asked again when the gateway's files say something new.
    gateway = core.engine.gateway_shown(core.engine.profile_home(workspace_id))
    state = gateway.get("record")
    if not isinstance(state, dict):
        return "connecting", "", None
    if state.get("gateway_state") == "startup_failed":
        why = str(state.get("exit_reason") or "The workspace didn't start.")
        return "error", why, None
    if not gateway.get("live") or gateway.get("stale"):
        return "connecting", "The workspace isn't running right now.", None
    if state.get("gateway_state") not in ("running", "degraded", None):
        return "connecting", "", None
    tg = (state.get("platforms") or {}).get("telegram") or {}
    if not isinstance(tg, dict):
        return "connecting", "", None
    status = str(tg.get("state") or "")
    reason = str(tg.get("error_message") or tg.get("error_code") or "")
    at = hermes_time.iso_utc(str(tg.get("updated_at") or ""))
    if status == "connected":
        return "connected", "", at
    if status in ("error", "fatal", "failed", "disconnected") or tg.get("needs_attention"):
        return "error", reason or "The engine can't reach this bot.", at
    return "connecting", reason, at


def telegram_state(core: Core, workspace_id: str) -> tuple[str, str]:
    """The bot as the workspace's Hermes gateway sees it: (lamp, Hermes's reason)."""
    status, reason, _at = _telegram(core, workspace_id)
    return status, reason


def channel_state(core: Core, row: Any) -> tuple[str, str]:
    """A connection's lamp read live from Hermes (its gateway_state.json): a bot runs
    only on its workspace's Hermes gateway, so one with no workspace isn't up."""
    if row["workspace_id"] and str(row["engine"]) == gateway_platform.ENGINE_HERMES:
        return telegram_state(core, str(row["workspace_id"]))
    return "connecting", ""


def channel_since(core: Core, row: Any) -> tuple[str, str | None]:
    """A connection's lamp and when Hermes set it (its gateway_state.json)."""
    if row["workspace_id"] and str(row["engine"]) == gateway_platform.ENGINE_HERMES:
        status, _reason, at = _telegram(core, str(row["workspace_id"]))
        return status, at
    return "connecting", None


def channel_ok_at(core: Core, row: Any) -> str | None:
    """When Hermes last marked the bot connected, if it is now."""
    status, at = channel_since(core, row)
    return at if status == "connected" else None
