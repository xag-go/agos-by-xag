"""Settings → Health: Hermes's own status and doctor of every workspace's root
(actions/hermes_health.py) and the secrets check (actions/secrets_check.py).
Both only read.

Must not: run Hermes or open its files itself (the actions do).
"""

import asyncio

from fastapi import APIRouter

from agos_core.actions import hermes_health, secrets_check
from agos_core.api.deps import CoreDep
from agos_core.db.records import Record

__all__ = [
    "HermesHealth",
    "HermesReport",
    "HermesRootHealth",
    "LogKey",
    "SecretKeyFound",
    "SecretKeyInLog",
    "SecretsCheck",
    "WrongMode",
    "router",
]

router = APIRouter()


class HermesReport(Record):
    """One of Hermes's own reports, as its CLI printed it."""

    text: str
    error: str | None
    # Not taken yet: its first run since the start is on its way (not an error).
    pending: bool = False
    # Hermes's own yes/no: doctor's exit code (None for status, or not read).
    has_problems: bool | None = None
    problems: int  # lines Hermes marked ✗
    warnings: int  # lines Hermes marked ⚠


class HermesRootHealth(Record):
    workspace_id: str
    name: str
    status: HermesReport  # `hermes status --full`
    doctor: HermesReport  # `hermes doctor` (no --fix), incl. its managed scope line
    # When the older of the two was taken (ISO, UTC; None until both are in), and
    # whether Hermes is checking again right now (the page then asks again).
    checked_at: str | None = None
    checking: bool = False


class HermesHealth(Record):
    """Settings → Health: Hermes's own status and doctor of every workspace's root."""

    roots: list[HermesRootHealth]


@router.get("/preferences/hermes-health")
async def get_hermes_health(
    core: CoreDep, workspace_id: str | None = None, fresh: bool = False
) -> HermesHealth:
    """The last reports at once; `fresh` asks Hermes again behind the page."""
    return HermesHealth.model_validate(
        await asyncio.to_thread(hermes_health.read, core, workspace_id, fresh=fresh)
    )


class SecretKeyFound(Record):
    """A key kept in a chat's history (never its value: its kind and last 4)."""

    workspace_id: str
    workspace: str
    profile: str  # the Hermes profile that keeps the session ("default": the Co-Founder)
    session: str  # the conversation's title ("" when it has none)
    source: str  # where it was said (telegram, agos, cli, …)
    role: str  # user / assistant / tool
    at: str | None
    column: str
    kind: str
    last4: str


class LogKey(Record):
    kind: str
    last4: str


class SecretKeyInLog(Record):
    workspace_id: str
    workspace: str
    file: str  # relative to the workspace's Hermes root
    count: int  # lines holding a key
    keys: list[LogKey]


class WrongMode(Record):
    path: str
    mode: str  # octal, e.g. "644"
    want: str  # "600" for a file, "700" for a folder


class SecretsCheck(Record):
    """Settings → Health → Secrets check (actions/secrets_check.py): read-only."""

    checked_at: str
    problems: int
    chats: list[SecretKeyFound]
    chats_more: int  # more keys in chat history than listed
    logs: list[SecretKeyInLog]
    permissions: list[WrongMode]
    not_checked: list[str]


@router.post("/preferences/secrets-check")
def run_secrets_check(core: CoreDep) -> SecretsCheck:
    """Keys in chat history and logs, and secret files others may read, in every
    workspace. It only reads (a plain `def`: runs in the threadpool)."""
    return SecretsCheck.model_validate(secrets_check.run(core))
