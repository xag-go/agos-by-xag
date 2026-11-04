"""The workspace's Telegram bot on Hermes, over HTTP: his messages in, AGOS's outbox
out (and its done marks), commands both ways, the members' commands, AGOS's
buttons pressed, the bot connected.

Owns: the Telegram routes (actions/services/channel/gateway_messages.py, gateway_commands.py).
Must not: talk to Telegram itself (the plugin does).

Part of the bridge API (moved out of api/hermes_bridge.py, which keeps the one router
app.py mounts and re-exports every name). Not behind the web app's internal token:
each call carries the workspace's own bridge key (bridge_access._checked)."""

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from agos_core.actions import hermes_channel as actions
from agos_core.actions import telegram_people
from agos_core.api.bridge_access import ADDRESS, Auth, _checked
from agos_core.api.deps import CoreDep
from agos_core.context import Core

__all__ = [
    "Callback",
    "CommandIn",
    "CommandList",
    "CommandOut",
    "Incoming",
    "MemberCommandIn",
    "callback",
    "command_in",
    "command_out",
    "incoming",
    "member_command",
    "telegram_connected",
]

router = APIRouter(prefix="/hermes-bridge/{workspace_id}", include_in_schema=False)


class Incoming(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    sender: str = Field(default="", max_length=40)
    text: str = Field(default="", max_length=200_000)
    message_id: str = Field(default="", alias="messageId", max_length=40)
    reply_to: str | None = Field(default=None, alias="replyTo", max_length=40)
    chat_name: str = Field(default="", alias="chatName", max_length=200)
    topic_name: str = Field(default="", alias="topicName", max_length=200)
    # Files Hermes's Telegram saved for it (voice note, photo, file): {path, mime}.
    media: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    # Hermes admitted the sender (the plugin's post_gateway_admission hook: Hermes's
    # own allowlist and pairing already let him in; AGOS keeps none).
    authorized: bool = False


class Callback(BaseModel):
    """One of AGOS's buttons, pressed by someone Hermes's gateway lets in."""

    chat: str = Field(max_length=90, pattern=ADDRESS)
    data: str = Field(max_length=128)
    message_id: str = Field(default="", alias="messageId", max_length=40)


@router.post("/incoming")
async def incoming(
    core: CoreDep, workspace_id: str, body: Incoming, authorization: Auth = None
) -> dict[str, bool]:
    ws = _checked(core, workspace_id, authorization)
    loop = asyncio.get_running_loop()

    def answer(chat_id: int) -> None:
        # A chat AGOS answers itself (a group's or a member's topic): its answer
        # starts on the app's loop, like a message written in AGOS.
        from agos_core.actions import chat as chat_actions

        loop.call_soon_threadsafe(chat_actions._kick, core, ws, chat_id)

    handled = await asyncio.to_thread(
        actions.incoming,
        core,
        ws,
        body.chat,
        body.sender,
        body.text,
        body.message_id,
        body.reply_to,
        body.chat_name,
        body.topic_name,
        body.media,
        answer,
        authorized=body.authorized,
    )
    return _handled(core, ws, handled, body.chat, body.message_id)


def _handled(core: Core, ws: str, handled: bool, chat: str, message_id: str) -> dict[str, bool]:
    """`keepEyes`: AGOS answers it itself, Hermes keeps its 👀 until that answer is out."""
    if handled and actions.keeps_eyes(core, ws, chat, message_id):
        return {"handled": True, "keepEyes": True}
    return {"handled": handled}


class CommandIn(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    sender: str = Field(default="", max_length=40)
    text: str = Field(max_length=4_000)


class CommandOut(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    text: str = Field(max_length=200_000)


class CommandList(BaseModel):
    # An older plugin still sends Telegram's menu: ignored (read from Hermes).
    commands: list[dict[str, str]] = Field(default_factory=list, max_length=200)
    bot: str = Field(default="", max_length=40)  # its @name, as Hermes's Telegram knows it


@router.post("/command")
async def command_in(
    core: CoreDep, workspace_id: str, body: CommandIn, authorization: Auth = None
) -> dict[str, bool]:
    """A Hermes /command he typed in Telegram: shown in the AGOS chat too."""
    ws = _checked(core, workspace_id, authorization)
    allowed = await asyncio.to_thread(telegram_people.lets_in, core, ws, body.sender)
    shown = await asyncio.to_thread(
        actions.command_in, core, ws, body.chat, body.sender, body.text, allowed
    )
    return {"shown": shown}


class MemberCommandIn(BaseModel):
    chat: str = Field(max_length=90, pattern=ADDRESS)
    sender: str = Field(default="", max_length=40)
    text: str = Field(max_length=4_000)
    message_id: str = Field(default="", alias="messageId", max_length=40)


@router.post("/member-command")
async def member_command(
    core: CoreDep, workspace_id: str, body: MemberCommandIn, authorization: Auth = None
) -> dict[str, bool]:
    """/ideas_generator … in a Telegram group: that group member's message (handled),
    or not one of AGOS's (Hermes runs it as its own command)."""
    ws = _checked(core, workspace_id, authorization)
    loop = asyncio.get_running_loop()

    def answer(chat_id: int) -> None:
        # The member's message is answered at once, like one written in AGOS.
        from agos_core.actions import chat as chat_actions

        loop.call_soon_threadsafe(chat_actions._kick, core, ws, chat_id)

    allowed = await asyncio.to_thread(telegram_people.lets_in, core, ws, body.sender)
    handled = await asyncio.to_thread(
        lambda: actions.member_command(
            core,
            ws,
            body.chat,
            body.sender,
            body.text,
            body.message_id,
            answer,
            authorized=allowed,
        )
    )
    return _handled(core, ws, handled, body.chat, body.message_id)


@router.post("/command-reply")
async def command_out(
    core: CoreDep, workspace_id: str, body: CommandOut, authorization: Auth = None
) -> dict[str, bool]:
    """Hermes's own answer to a command: shown in the AGOS chat too."""
    ws = _checked(core, workspace_id, authorization)
    shown = await asyncio.to_thread(actions.command_out, core, ws, body.chat, body.text)
    return {"shown": shown}


@router.post("/commands")
async def telegram_connected(
    core: CoreDep, workspace_id: str, body: CommandList, authorization: Auth = None
) -> dict[str, bool]:
    """The bot's @name, once Hermes's Telegram connected (its "/" menu is read from
    Hermes's registry, not kept: actions.commands)."""
    ws = _checked(core, workspace_id, authorization)
    if body.bot:
        actions.bot_is(core, ws, body.bot)
    return {"ok": True}


@router.post("/callback")
async def callback(
    core: CoreDep, workspace_id: str, body: Callback, authorization: Auth = None
) -> dict[str, str]:
    ws = _checked(core, workspace_id, authorization)
    outcome, shown = await asyncio.to_thread(
        actions.callback, core, ws, body.chat, body.data, body.message_id
    )
    return {"outcome": outcome, "text": shown}
