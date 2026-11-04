"""Setting up a bot and claiming it: the set-up flow, a person's claim, removing a person.
Must not: decide Hermes's allowlist itself (Hermes's CLI does, via actions/telegram_people.py).

Split out of agos_core.actions.channels (which re-exports it); behaviour unchanged.
"""

from __future__ import annotations

import re
from typing import Literal

from agos_core.actions import telegram_people
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.channel.bot_addresses import link_cofounder_chat
from agos_core.actions.services.channel.connections import (
    SETUP_LOCK,
    ClaimView,
    add_connection,
    connection_row,
    live_workspace,
)
from agos_core.context import Core
from agos_core.db import chat_addresses as addresses_repo
from agos_core.db.records import Record
from agos_core.engine import telegram_setup

__all__ = [
    "BotSetupView",
    "bot_setup_status",
    "remove_person",
    "start_bot_setup",
    "start_claim",
]

# ---- a new Telegram bot from a QR code ------------------------------------------------------


class BotSetupView(Record):
    id: str
    status: Literal["waiting", "ready", "saved", "error", "expired"]
    link: str
    error: str
    bot_username: str
    connection_id: int | None


def _setup_view(p: telegram_setup.Pairing) -> BotSetupView:
    return BotSetupView(
        id=p.id,
        status=p.status,
        link=p.link,
        error=p.error,
        bot_username=p.bot_username,
        connection_id=p.connection_id,
    )


def start_bot_setup(core: Core, workspace_id: str | None, bot_name: str) -> BotSetupView:
    if workspace_id is not None:
        live_workspace(core, workspace_id)
    if core.engine is None:
        raise ActionError("Hermes isn't available.", 503)
    try:
        pairing = telegram_setup.start(
            core.engine.settings, bot_name.strip()[:60] or "AGOS", workspace_id
        )
    except telegram_setup.PairingError as error:
        raise ActionError(str(error), 502) from error
    return _setup_view(pairing)


def bot_setup_status(core: Core, setup_id: str) -> BotSetupView:
    """Polled by the web while the QR is on screen; saves the bot once it's ready."""
    pairing = telegram_setup.get(setup_id)
    if pairing is None:
        raise NotFoundError("This QR code")
    with SETUP_LOCK:
        if core.engine is not None:
            telegram_setup.poll(core.engine.settings, pairing)
        if pairing.status == "ready":
            try:
                cid = add_connection(
                    core,
                    kind="telegram",
                    name=pairing.bot_name,
                    secret=pairing.token,
                    allowed=[pairing.owner_id],
                    workspace_id=pairing.workspace_id,
                    identity=pairing.bot_username,
                )
            except (ActionError, NotFoundError) as error:
                pairing.status, pairing.error = "error", str(error)
            else:
                pairing.status, pairing.connection_id = "saved", cid
                # His private chat with a bot has his own user id as its id.
                link_cofounder_chat(core, cid, f"{pairing.owner_id}:0")
            finally:
                telegram_setup.forget_token(pairing)
    return _setup_view(pairing)


# ---- who may write to the bot: Hermes's DM pairing ---------------------------------


def start_claim(core: Core, connection_id: int) -> ClaimView:
    """The bot's own link: he opens it and writes (Start); Hermes answers with its
    pairing code and his request shows here, for the owner to approve."""
    row = connection_row(core, connection_id)
    if row["kind"] != "telegram" or not row["workspace_id"]:
        raise ActionError("Only a workspace's own Telegram bot links this way.")
    username = str(row["identity"] or "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,64}", username):
        raise ActionError("The bot isn't reachable yet; try again when its lamp is green.")
    return ClaimView(link=f"https://t.me/{username}", expires_in=telegram_people.CODE_TTL_S)


def remove_person(core: Core, connection_id: int, user_id: str) -> None:
    """The bot stops listening to him (Hermes's pairing and allowlist); his private
    chat stops being a place of the Co-Founder's chat."""
    row = connection_row(core, connection_id)
    workspace_id = str(row["workspace_id"] or "")
    if not workspace_id:
        raise ActionError("Only a workspace's own Telegram bot has people.")
    telegram_people.remove(core, workspace_id, user_id)
    addresses_repo.remove_place(core.db, connection_id, f"{user_id}:0")
    from agos_core.actions import hermes_channel

    hermes_channel.refresh_bridge(core, workspace_id)
