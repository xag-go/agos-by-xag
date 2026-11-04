"""Request bodies. Limits here are the real validation; the web's are only for UX."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from agos_core.db.records import (
    AutomationStep,
    AutomationVariable,
    CatchUp,
    HookCondition,
    Policy,
    Record,
    TicketMapping,
)
from agos_core.domain.models import ModelSelection
from agos_core.ops.specs.workspace import NewWorkspace as NewWorkspace  # the operation's input


class Body(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


Name = Field(min_length=1)


class WorkspaceSettingsBody(Body):
    name: str = Name
    description: str = Field(default="")
    default_model: ModelSelection
    # Default for new chats: "ask" before risky commands, or "full" access.
    chat_access: Literal["ask", "full"] = "ask"


class NewFolder(Body):
    path: str = Field(min_length=1, max_length=4096)
    access: Literal["read", "read-write"] = "read"


class FolderAccess(Body):
    access: Literal["read", "read-write"]


class Confirm(Body):
    confirm: str = Field(max_length=100)


class NewAttachment(Body):
    kind: Literal["image", "audio", "file"]
    name: str = Field(min_length=1, max_length=200)
    mime: str = Field(min_length=1, max_length=120)
    # Base64 of the file (up to 20 MB each, 30 MB per message).
    data: str = Field(min_length=1, max_length=28_000_000)
    duration: float | None = Field(default=None, ge=0, le=1_800)


class NewChatMessage(Body):
    body: str = Field(default="")
    reply_to: int | None = None
    # The selected part of the replied message (empty = the whole message).
    reply_excerpt: str | None = Field(default=None, max_length=4000)
    attachments: list[NewAttachment] = Field(default=[], max_length=8)


class NewChat(Body):
    title: str = Field(default="New chat", min_length=1)


class AutomationBody(Body):
    name: str = Name
    instructions: str = Field(min_length=1)
    schedule: str = Field(max_length=100)
    model: ModelSelection
    on: bool = True
    # Who does it: one agent (empty = the Co-Founder), or a team plan's steps.
    agent: str | None = None
    steps: list[AutomationStep] = Field(default_factory=list)
    # True = an event (starts the moment something happens outside, no schedule);
    # False = a scheduled automation; None = keep what it is.
    hook: bool | None = None
    # The owner approves before the work starts (otherwise it runs by itself).
    check_first: bool = False
    # Step 48: typed variables, the policy while the last run is open, a ticket
    # on-ramp. None keeps what the automation has (variables, policy); the dialog
    # always sends the ticket it shows (None = no on-ramp).
    variables: list[AutomationVariable] | None = Field(default=None, max_length=20)
    policy: Policy | None = None
    ticket: TicketMapping | None = None
    # A run missed while the server was off: run it once when AGOS is back, or
    # skip it (None keeps what it has; actions/catch_up.py).
    catch_up: CatchUp | None = None


class RunNowBody(Body):
    """Run now with variables: the values for this run (name → value as text)."""

    variables: dict[str, str] = Field(default_factory=dict)


class HeartbeatBody(Body):
    on: bool
    interval: Literal["15m", "1h", "4h", "daily"] = "1h"


class ObserveBody(Body):
    """A watchdog job's stop fingerprint: `id:status,id:status` of the open leaves."""

    fingerprint: str = Field(default="", max_length=4000)


class HookBody(Body):
    on: bool
    # "" removes the signing secret, None keeps it.
    secret: str | None = Field(default=None, max_length=300)
    events: list[str] = Field(default_factory=list, max_length=50)
    # None keeps the webhook's "Only if" lines as they are.
    conditions: list[HookCondition] | None = Field(default=None, max_length=50)
    new_address: bool = False
    # A new random signing secret (shown once in the answer).
    new_secret: bool = False


class HooksSettings(Body):
    # The public https address that reaches this machine's webhook relay.
    public_url: str = Field(default="", max_length=300)


class Toggle(Body):
    on: bool


class Created(Record):
    id: str | int


class WorkspaceFolderOut(Record):
    name: str
    access: Literal["read", "read-write"]
    own: bool
    host_path: str | None


class GatewayRestartOut(Record):
    """The gateway restart after a folder click: restarting, done (also: none since
    the core started) or failed, with the reason the owner reads."""

    state: Literal["restarting", "done", "failed"]
    reason: str


class TrashedWorkspace(Record):
    id: str
    name: str
    trash_name: str
    deleted_at: str
