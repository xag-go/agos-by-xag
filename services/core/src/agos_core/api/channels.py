"""Each workspace's channels (its Telegram bot) and each chat's "Where"."""

import asyncio
from typing import Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import channels as actions
from agos_core.actions.channels import AddressView, BotSetupView, ClaimView, ConnectionView
from agos_core.actions.services.chat import chat_records
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body, Created

router = APIRouter(tags=["channels"])


class NewConnection(Body):
    kind: Literal["telegram"] = "telegram"
    name: str = Field(default="")
    secret: str = Field(min_length=10, max_length=200)
    allowed: list[str] = Field(default_factory=list, max_length=50)
    workspace_id: str | None = Field(default=None, max_length=100)


class NewBot(Body):
    name: str = Field(default="")
    workspace_id: str | None = Field(default=None, max_length=100)


class ConnectionUpdate(Body):
    name: str = Field(default="")
    enabled: bool = True  # Hermes's platforms.telegram.enabled
    secret: str | None = Field(default=None, max_length=200)
    reactions: bool | None = None  # Hermes's telegram.reactions (None: leave it)


class NewAddress(Body):
    connection_id: int
    address: str | None = Field(default=None, max_length=100)
    # Telegram: the forum group's id; AGOS creates a topic named after the chat.
    create_topic_in: str | None = Field(default=None, max_length=100)
    notify: bool = False


@router.get("/channels")
async def list_connections(core: CoreDep) -> list[ConnectionView]:
    return await asyncio.to_thread(actions.list_connections, core)


@router.post("/channels", status_code=201)
async def add_connection(core: CoreDep, body: NewConnection) -> Created:
    return Created(
        id=await asyncio.to_thread(
            actions.add_connection,
            core,
            kind=body.kind,
            name=body.name,
            secret=body.secret,
            allowed=body.allowed,
            workspace_id=body.workspace_id,
        )
    )


@router.post("/channels/telegram/setup", status_code=201)
async def start_bot_setup(core: CoreDep, body: NewBot) -> BotSetupView:
    """A new Telegram bot from a QR code (Hermes's setup service)."""
    return await asyncio.to_thread(actions.start_bot_setup, core, body.workspace_id, body.name)


@router.get("/channels/telegram/setup/{setup_id}")
async def bot_setup_status(core: CoreDep, setup_id: str) -> BotSetupView:
    return await asyncio.to_thread(actions.bot_setup_status, core, setup_id)


@router.post("/channels/{connection_id}/claim")
async def start_claim(core: CoreDep, connection_id: int) -> ClaimView:
    """The bot's link: writing to it asks Hermes for a pairing code (approved here)."""
    return actions.start_claim(core, connection_id)


@router.post("/channels/{connection_id}/pairing/{request_id}", status_code=204)
async def approve_person(core: CoreDep, connection_id: int, request_id: str) -> None:
    """Yes to someone who wrote to the bot: Hermes's own pairing approval."""
    await asyncio.to_thread(actions.approve_person, core, connection_id, request_id[:64])


@router.delete("/channels/{connection_id}/people/{user_id}", status_code=204)
async def remove_person(core: CoreDep, connection_id: int, user_id: str) -> None:
    """The bot stops listening to him (Hermes's pairing and allowlist)."""
    await asyncio.to_thread(actions.remove_person, core, connection_id, user_id[:100])


@router.get("/workspaces/{workspace_id}/bots")
async def workspace_bots(core: CoreDep, workspace_id: str) -> list[ConnectionView]:
    return await asyncio.to_thread(actions.workspace_bots, core, workspace_id)


@router.put("/channels/{connection_id}", status_code=204)
async def update_connection(core: CoreDep, connection_id: int, body: ConnectionUpdate) -> None:
    await asyncio.to_thread(
        actions.update_connection,
        core,
        connection_id,
        name=body.name,
        enabled=body.enabled,
        secret=body.secret,
        reactions=body.reactions,
    )


@router.delete("/channels/{connection_id}", status_code=204)
def delete_connection(core: CoreDep, connection_id: int) -> None:
    actions.delete_connection(core, connection_id)


@router.post("/channels/{connection_id}/retry")
async def retry(core: CoreDep, connection_id: int) -> ConnectionView:
    return await asyncio.to_thread(actions.retry, core, connection_id)


@router.get("/workspaces/{workspace_id}/chats/{chat_id}/addresses")
def addresses(core: CoreDep, workspace_id: str, chat_id: int) -> list[AddressView]:
    return actions.addresses_of(core, chat_id)


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/addresses", status_code=201)
async def add_address(core: CoreDep, workspace_id: str, chat_id: int, body: NewAddress) -> Created:
    return Created(
        id=await asyncio.to_thread(
            actions.add_address,
            core,
            workspace_id,
            chat_id,
            connection_id=body.connection_id,
            address=body.address,
            create_topic=body.create_topic_in,
            notify=body.notify,
        )
    )


@router.delete("/workspaces/{workspace_id}/chats/{chat_id}/addresses/{address_id}", status_code=204)
def remove_address(core: CoreDep, workspace_id: str, chat_id: int, address_id: int) -> None:
    actions.remove_address(core, workspace_id, chat_id, address_id)


class HermesCommand(Body):
    command: str
    description: str


@router.get("/workspaces/{workspace_id}/chats/{chat_id}/hermes-commands")
def hermes_commands(core: CoreDep, workspace_id: str, chat_id: int) -> list[HermesCommand]:
    """Hermes's command menu (the same list Telegram shows), for a chat that lives on
    Hermes's Telegram; none for other chats."""
    from agos_core.actions import hermes_channel

    if not chat_records.has_chat(core, workspace_id, chat_id):
        return []
    if hermes_channel.chat_on_hermes(core, chat_id) is None:
        return []
    return [HermesCommand(**c) for c in hermes_channel.commands(core, workspace_id)]


class TeamGroup(Body):
    group: str = Field(default="", max_length=30)


@router.get("/workspaces/{workspace_id}/telegram-groups")
def telegram_groups(core: CoreDep, workspace_id: str) -> dict[str, object]:
    """Groups the workspace's bot is in, and its team group (a topic per chat)."""
    from agos_core.actions import hermes_channel

    return hermes_channel.team_groups(core, workspace_id)


@router.put("/workspaces/{workspace_id}/telegram-group", status_code=204)
async def set_telegram_group(core: CoreDep, workspace_id: str, body: TeamGroup) -> None:
    from agos_core.actions import hermes_channel

    hermes_channel.set_team_group(core, workspace_id, body.group.strip())


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/telegram-topic", status_code=201)
async def telegram_topic(core: CoreDep, workspace_id: str, chat_id: int) -> Created:
    """The chat's own topic in the team group (Telegram), linked to the chat."""
    from agos_core.actions import hermes_channel

    return Created(
        id=await asyncio.to_thread(hermes_channel.topic_for, core, workspace_id, chat_id)
    )


@router.get("/workspaces/{workspace_id}/telegram-places")
def telegram_places(core: CoreDep, workspace_id: str) -> dict[str, object]:
    """Where in the workspace's Telegram a chat can be linked (private chat, each
    group's General and topics), and what is linked to each now."""
    from agos_core.actions import hermes_channel

    return hermes_channel.places(core, workspace_id)
