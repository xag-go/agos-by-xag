"""Workspace chats: each answer is a Hermes run in the chat's own session."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agos_core.actions import chat as actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.services.chat import chat_records
from agos_core.actions.services.chat import messages as chat_messages
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.workspaces import require_workspace
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body, Created, NewChat, NewChatMessage
from agos_core.db.records import Chat, ChatActivity, Record
from agos_core.domain.models import ModelSelection

router = APIRouter(tags=["chats"])


class ChatUpdate(Body):
    title: str | None = None
    model: ModelSelection | None = None
    access: Literal["ask", "full"] | None = None
    # A library agent that is on in this workspace; "" for none.
    agent: str | None = Field(default=None, max_length=63)


class ApprovalAnswer(Body):
    choice: Literal["once", "deny"]


class LiveTurnView(Record):
    turn_id: int
    status: str
    text: str
    activity: list[ChatActivity]
    version: int
    # Workers: the agent writing this answer (None = the Co-Founder / chat's agent).
    speaker: str | None = None


class KanbanAskView(Record):
    id: int
    card: str
    member: str
    member_name: str
    label: str
    detail: str
    created_at: str


class KanbanQuestion(Record):
    card: str
    title: str
    member_title: str
    question: str


class TokenWarning(Record):
    card: str
    title: str
    used: str


class OffLine(Record):
    agent: str  # "" = the Co-Founder
    until: str | None = None
    until_text: str = ""


class LiveView(Record):
    live: LiveTurnView | None
    # Owner messages the agent hasn't started answering yet (it will).
    pending: bool = False
    # The Co-Founder's chat: what team members working Kanban cards wait on.
    asks: list[KanbanAskView] = Field(default_factory=list)
    # Cards waiting for his answer (❓): answered right here.
    questions: list[KanbanQuestion] = Field(default_factory=list)
    # Cards using far more tokens than usual: Let it go on / Stop it.
    tokens: list[TokenWarning] = Field(default_factory=list)
    # The chat's agent is off-hours (Settings → Work hours): until when, and who (Wake
    # now); his messages wait for its check-in.
    off: OffLine | None = None
    # The core held this ask until something here changed (or `wait` passed): the web
    # asks again at once (an older core answered at once: the web waited between asks).
    held: bool = False


class SearchHit(Record):
    chat_id: int
    chat_title: str
    message_id: int
    from_: Literal["owner", "agent"] = Field(alias="from")
    body: str


def _require_chat(core: Any, workspace_id: str, chat_id: int) -> None:
    chat_records.require_chat(core, workspace_id, chat_id)


@router.get("/workspaces/{workspace_id}/chats")
def list_chats(core: CoreDep, workspace_id: str) -> list[Chat]:
    require_workspace(core, workspace_id)
    return chat_view.list_chats(core.db, workspace_id)


@router.get("/workspaces/{workspace_id}/chats/search")
def search(
    core: CoreDep, workspace_id: str, q: str = Query(min_length=1, max_length=200)
) -> list[SearchHit]:
    require_workspace(core, workspace_id)
    return [
        SearchHit(
            chat_id=h["chatId"],
            chat_title=h["chatTitle"],
            message_id=h["messageId"],
            from_=h["from"],
            body=h["body"][:400],
        )
        for h in chat_records.search(core, workspace_id, q)
    ]


@router.get("/workspaces/{workspace_id}/chats/{chat_id}")
async def get_chat(core: CoreDep, workspace_id: str, chat_id: int) -> Chat:
    # Off the event loop: reading a chat reads Hermes's store, never freezing the app.
    chat = await asyncio.to_thread(chat_view.get_chat, core.db, workspace_id, chat_id)
    if chat is None:
        raise NotFoundError("This chat")
    return chat.model_copy(update={"pending": _pending(core, chat_id)})


@router.post("/workspaces/{workspace_id}/chats", status_code=201)
async def create_chat(core: CoreDep, workspace_id: str, body: NewChat) -> Created:
    require_workspace(core, workspace_id)
    return Created(id=chat_records.create_chat(core, workspace_id, body.title.strip()))


@router.put("/workspaces/{workspace_id}/chats/{chat_id}", status_code=204)
async def update_chat(core: CoreDep, workspace_id: str, chat_id: int, body: ChatUpdate) -> None:
    title = body.title.strip() if body.title is not None else None
    if title == "":
        raise ActionError("Give the chat a name.")
    chat_records.set_agent(core, workspace_id, chat_id, body.agent)
    if title is not None:
        await asyncio.to_thread(actions.rename, core, workspace_id, chat_id, title)
    if body.model is not None:
        actions.set_model(core, workspace_id, chat_id, body.model)
    if body.access is not None:
        # Hermes's own /yolo for the chat's conversation (actions/access.py).
        from agos_core.actions import access

        await asyncio.to_thread(access.set_chat, core, workspace_id, chat_id, body.access == "full")


@router.delete("/workspaces/{workspace_id}/chats/{chat_id}", status_code=204)
def delete_chat(core: CoreDep, workspace_id: str, chat_id: int) -> None:
    actions.delete_chat(core, workspace_id, chat_id)


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/messages", status_code=201)
async def post_message(
    core: CoreDep, workspace_id: str, chat_id: int, body: NewChatMessage
) -> Created:
    attached = chat_messages.checked_attachments(body.attachments)
    return Created(
        id=await actions.in_thread(
            actions.post_message,
            core,
            workspace_id,
            chat_id,
            body.body.strip(),
            attached,
            reply_to=body.reply_to,
            reply_excerpt=body.reply_excerpt,
        )
    )


class EditedMessage(BaseModel):
    body: str = Field(min_length=1)
    # Already answered: the agent answers the new version now.
    reanswer: bool = False


@router.put("/workspaces/{workspace_id}/chats/{chat_id}/messages/{message_id}", status_code=204)
async def edit_message(
    core: CoreDep, workspace_id: str, chat_id: int, message_id: int, body: EditedMessage
) -> None:
    await actions.in_thread(
        actions.edit_message,
        core,
        workspace_id,
        chat_id,
        message_id,
        body.body,
        reanswer=body.reanswer,
    )


@router.delete("/workspaces/{workspace_id}/chats/{chat_id}/messages/{message_id}", status_code=204)
async def delete_message(core: CoreDep, workspace_id: str, chat_id: int, message_id: int) -> None:
    await actions.in_thread(actions.delete_message, core, workspace_id, chat_id, message_id)


@router.get(
    "/workspaces/{workspace_id}/chats/{chat_id}/attachments/{attachment_id}",
    response_class=FileResponse,
)
def attachment(core: CoreDep, workspace_id: str, chat_id: int, attachment_id: int) -> FileResponse:
    path, mime, name = actions.attachment_file(core, workspace_id, chat_id, attachment_id)
    inline = chat_messages.shown_inline(mime)
    return FileResponse(
        path,
        media_type=mime if inline else "application/octet-stream",
        filename=name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600"},
    )


@router.get("/workspaces/{workspace_id}/chats/{chat_id}/live")
async def live(
    core: CoreDep,
    workspace_id: str,
    chat_id: int,
    after: int = Query(default=-1, ge=-1),
    wait: float = Query(default=0, ge=0, le=25),
) -> LiveView:
    """The answer being written. With `wait`, holds until it changes past `after`, one
    starts, or what waits on him beside it changed (actions/chat.py wait_live)."""
    await asyncio.to_thread(_require_chat, core, workspace_id, chat_id)
    # Every open chat asks this all the time: the board and the team are read in
    # a thread, never on the loop.
    if wait <= 0:
        return LiveView.model_validate(
            {
                "live": actions.live_snapshot(core, chat_id),
                **await asyncio.to_thread(_around, core, workspace_id, chat_id),
            }
        )
    view = await actions.wait_live(
        core, chat_id, after, timeout=wait, around=lambda: _around(core, workspace_id, chat_id)
    )
    return LiveView.model_validate(view)


def _around(core: Any, workspace_id: str, chat_id: int) -> dict[str, Any]:
    """What waits on him around the live answer (the Co-Founder's chat). Which chat is
    the Co-Founder's is asked once per poll (it checks Hermes's archive of every DM)."""
    from agos_core.actions import work_hours
    from agos_core.actions.services.channel import owner_needs

    cofounder = owner_needs.cofounder_chat(core, workspace_id) == chat_id
    return {
        "off": work_hours.off_line(core, workspace_id, chat_id),
        "pending": _pending(core, chat_id),
        "asks": _asks(core, workspace_id) if cofounder else [],
        "questions": _questions(core, workspace_id) if cofounder else [],
        "tokens": _tokens(core, workspace_id) if cofounder else [],
    }


def _questions(core: Any, workspace_id: str) -> list[dict[str, Any]]:
    from agos_core.actions import kanban_board

    return kanban_board.questions(core, workspace_id)


def _tokens(core: Any, workspace_id: str) -> list[dict[str, Any]]:
    from agos_core.actions import token_watch

    return token_watch.waiting(core, workspace_id)


def _asks(core: Any, workspace_id: str) -> list[dict[str, Any]]:
    """What the team's members working Kanban cards wait on: in the Co-Founder's chat."""
    from agos_core.actions import kanban_asks

    return kanban_asks.waiting(core, workspace_id)


def _pending(core: Any, chat_id: int) -> bool:
    return actions.pending(core, chat_id)


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/stop")
async def stop(core: CoreDep, workspace_id: str, chat_id: int) -> dict[str, bool]:
    await asyncio.to_thread(_require_chat, core, workspace_id, chat_id)
    return {"stopped": await actions.in_thread(actions.stop_turn, core, workspace_id, chat_id)}


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/retry", status_code=202)
async def retry(core: CoreDep, workspace_id: str, chat_id: int) -> None:
    await actions.in_thread(actions.retry, core, workspace_id, chat_id)


@router.post("/workspaces/{workspace_id}/chats/{chat_id}/approval", status_code=204)
async def approval(core: CoreDep, workspace_id: str, chat_id: int, body: ApprovalAnswer) -> None:
    await asyncio.to_thread(_require_chat, core, workspace_id, chat_id)
    await actions.in_thread(actions.answer_approval, core, workspace_id, chat_id, body.choice)


class KanbanAnswer(BaseModel):
    allow: bool


@router.post("/workspaces/{workspace_id}/kanban-asks/{ask_id}")
async def answer_kanban_ask(
    core: CoreDep, workspace_id: str, ask_id: int, body: KanbanAnswer
) -> dict[str, str]:
    """Allow once / Deny what a member working a Kanban card asks."""
    from agos_core.actions import kanban_asks

    require_workspace(core, workspace_id)
    message = await asyncio.to_thread(kanban_asks.answer, core, workspace_id, ask_id, body.allow)
    return {"message": message}


class TokenChoice(BaseModel):
    go: bool


@router.post("/workspaces/{workspace_id}/card-tokens/{card}")
async def answer_card_tokens(
    core: CoreDep, workspace_id: str, card: str, body: TokenChoice
) -> dict[str, str]:
    """Let it go on / Stop it, for a card using far more tokens than usual."""
    from agos_core.actions import token_watch

    require_workspace(core, workspace_id)
    message = await asyncio.to_thread(
        token_watch.answer, core, workspace_id, card, "go" if body.go else "stop"
    )
    return {"message": message}
