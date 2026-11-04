"""Settings → Hermes: every Hermes setting from Hermes's own schema as the
workspaces' Hermes have it (actions/hermes_all_settings.py), and Hermes's Tool
Search switch for the Co-Founder's tools (actions/tool_search.py, the token-cost
switch). AGOS keeps no copy.

Must not: read or write a Hermes config itself, or reach the engine.
"""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import hermes_all_settings, tool_search
from agos_core.actions.hermes_all_settings import CARD_LABELS
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

__all__ = [
    "HermesAllSettings",
    "HermesSettingBody",
    "HermesSettingMember",
    "HermesSettingNote",
    "HermesSettingPair",
    "HermesSettingRow",
    "HermesSettingRule",
    "HermesSettingWorkspace",
    "HermesSharedRow",
    "ToolSearchPref",
    "router",
]

router = APIRouter()


class HermesSettingRule(Record):
    """What AGOS does with a setting: `forced` (written on each sync, read-only
    here), `card` (an AGOS card changes it), `seeded` (a new profile starts on
    AGOS's value), `secret` (never shown), `locked` (AGOS doesn't write it but it
    must stay as it is while an AGOS part depends on it; the reason says why),
    `choice` (AGOS writes its recommended value into a new profile only; the
    owner's choice afterwards, editable here: engine/owner_choices.py)."""

    kind: Literal["forced", "card", "seeded", "secret", "locked", "choice"]
    card: str | None
    reason: str
    recommended: Any = None  # `choice`: AGOS's recommended value


class HermesSettingMember(Record):
    label: str
    value: Any


class HermesSettingWorkspace(Record):
    """One workspace's value (its Co-Founder's), and its members that differ."""

    id: str
    name: str
    value: Any
    members: list[HermesSettingMember]


class HermesSettingPair(Record):
    """A provider key and its model key: one model choice (AGOS's model picker)."""

    provider: str
    model: str


class HermesSettingNote(Record):
    """Why one profile's value holds an entry (e.g. a member's toolset turned off)."""

    label: str
    value: str
    reason: str


class HermesSettingRow(Record):
    key: str  # Hermes's own dotted key
    group: str
    type: str  # boolean / number / string / select / list / object
    description: str  # Hermes's own words
    default: Any  # Hermes's default (null: none)
    options: list[str]
    in_defaults: bool  # False: not in Hermes's DEFAULT_CONFIG
    value: Any  # the value most profiles have
    set_in: int  # profiles whose config.yaml sets it
    same: bool  # every profile has the same value
    workspaces: list[HermesSettingWorkspace]  # when they differ
    rule: HermesSettingRule | None
    editable: bool
    pair: HermesSettingPair | None
    notes: list[HermesSettingNote]
    # Where Hermes keeps it: config.yaml, or the profile's .env (Hermes's registry).
    source: Literal["config", "env"]


class HermesSharedRow(Record):
    """A key of the shared home (~/.hermes, the owner's own Hermes) that matters for
    AGOS: shown read-only, with why."""

    key: str
    value: Any  # this home's own value (null: not set, Hermes's default)
    set: bool
    managed: Any  # the managed scope's value AGOS's runs use instead (null: none)
    reason: str


class HermesAllSettings(Record):
    """Every Hermes setting, from Hermes's own schema, as the workspaces' Hermes
    have it (no copy in AGOS)."""

    profiles: int
    workspaces: int
    groups: list[str]
    not_used_why: str
    cards: dict[str, str]
    settings: list[HermesSettingRow]
    shared_home: str
    shared: list[HermesSharedRow]


class HermesSettingBody(Body):
    key: str = Field(min_length=1)
    value: Any = None
    # None: every workspace (each Co-Founder and member); else that workspace only.
    workspace_id: str | None = None
    # True: back to Hermes's default (`hermes config unset`).
    reset: bool = False


def _settings_view(found: dict[str, Any]) -> HermesAllSettings:
    return HermesAllSettings.model_validate({**found, "cards": CARD_LABELS})


@router.get("/preferences/hermes-settings")
async def get_hermes_settings(core: CoreDep) -> HermesAllSettings:
    return _settings_view(await asyncio.to_thread(hermes_all_settings.read, core))


@router.put("/preferences/hermes-settings")
async def put_hermes_setting(core: CoreDep, body: HermesSettingBody) -> HermesSettingRow:
    row = await asyncio.to_thread(
        hermes_all_settings.write,
        core,
        body.key,
        body.value,
        workspace_id=body.workspace_id,
        reset=body.reset,
    )
    return HermesSettingRow.model_validate(row)


class ToolSearchPref(Body):
    # Tools to keep eager (Hermes: the whole bridge off in the Co-Founder's profile)
    # and tools to defer on top of Hermes's own list (actions/tool_search.py).
    eager: list[str] = Field(default_factory=list, max_length=100)
    defer: list[str] = Field(default_factory=list, max_length=100)


@router.get("/preferences/tool-search")
def get_tool_search(core: CoreDep) -> ToolSearchPref:
    return ToolSearchPref.model_validate(tool_search.read(core))


@router.put("/preferences/tool-search")
async def put_tool_search(core: CoreDep, body: ToolSearchPref) -> ToolSearchPref:
    """Written into every workspace root's Hermes config (the Co-Founder's profile)."""
    saved = await asyncio.to_thread(tool_search.save, core, body.eager, body.defer)
    return ToolSearchPref.model_validate(saved)
