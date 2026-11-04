"""Settings → Models: Hermes's helper (auxiliary) models and its image mode, the
fallback chain, and who hears the owner's voice notes. Hermes keeps every value
(actions/hermes_helper_models.py, hermes_fallback.py, hermes_voice.py); where a
route sits in AGOS's model picker is actions/services/settings/model_routes.py.

Must not: read or write a Hermes config itself, or reach the engine.
"""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import hermes_fallback, hermes_helper_models, hermes_voice
from agos_core.actions.services.settings import model_routes
from agos_core.actions.services.settings.model_routes import fallback_chain
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

__all__ = [
    "FallbackEntry",
    "FallbackEntryBody",
    "FallbackSpread",
    "HelperChoice",
    "HelperField",
    "HelperPickBody",
    "HelperRoute",
    "HelperSpread",
    "HelperTask",
    "HermesFallback",
    "HermesFallbackBody",
    "HermesHelperModels",
    "HermesHelperModelsBody",
    "HermesVoice",
    "HermesVoiceBody",
    "VoiceOption",
    "fallback_chain",
    "router",
]

router = APIRouter()


class HelperSpread(Record):
    value: Any
    profiles: list[str]


class HelperField(Record):
    """One of Hermes's helper-model settings, as each workspace's Hermes reads it."""

    key: str
    name: str  # Hermes's field name: provider / model / base_url / api_mode / image_input_mode
    value: Any  # what most workspaces' Hermes reads (Hermes's default while unset)
    hermes_default: Any
    is_default: bool
    managed: bool  # held in Hermes's managed scope (one value for every workspace)
    spread: list[HelperSpread]  # when workspaces differ
    options: list[str]  # Hermes's own choices, where it has a list
    description: str  # Hermes's own words
    secret: bool  # Hermes masks it: never shown, never edited here
    in_hermes_list: bool


class HelperRoute(Record):
    """Where a helper's calls go, as AGOS's model picker shows it: `main` when Hermes
    uses the main model (its `auto`), else the provider + model and where they sit
    in the picker (`catalog_provider` + `mode`, the same mapping as the fallback
    list; None when the picker has no such provider, e.g. a custom endpoint)."""

    main: bool
    provider: str  # Hermes's provider name
    model: str
    base_url: str
    catalog_provider: str | None
    mode: Literal["cli", "api"] | None


class HelperTask(Record):
    task: str  # Hermes's auxiliary task name
    label: str  # plain name (Hermes's name for a task AGOS hasn't seen)
    summary: str  # one plain sentence of what it does ("" when AGOS has none)
    description: str  # Hermes's own words
    in_hermes_list: bool  # False: set in Hermes, but Hermes's defaults have no such task
    fields: list[HelperField]
    route: HelperRoute


class HelperChoice(Record):
    value: str  # Hermes's own value
    label: str
    hint: str


class HermesHelperModels(Record):
    """Hermes's auxiliary (helper) models and its image mode (no copy in AGOS)."""

    profiles: int
    tasks: list[HelperTask]
    image_mode: HelperField | None
    image_choices: list[HelperChoice]  # Hermes's picture modes in plain words


class HelperPickBody(Body):
    """A choice from AGOS's model picker (AGOS's provider id + way in + model)."""

    provider: str
    mode: Literal["cli", "api"]
    model: str


class HermesHelperModelsBody(Body):
    """Hermes key → value to set, keys to give back to Hermes's default, and
    picker choices per task (None: "Same as the main model")."""

    sets: dict[str, str] = Field(default_factory=dict)
    unsets: list[str] = Field(default_factory=list)
    picks: dict[str, HelperPickBody | None] = Field(default_factory=dict)


def _helper_field(found: dict[str, Any]) -> HelperField:
    return HelperField(
        **{k: v for k, v in found.items() if k != "spread"},
        spread=[HelperSpread(value=v, profiles=p) for v, p in found["spread"]],
    )


def _helper_route(task: dict[str, Any]) -> HelperRoute:
    return HelperRoute.model_validate(model_routes.helper_route(task))


def _helper_view(seen: dict[str, Any]) -> HermesHelperModels:
    image = seen.get("image_mode")
    return HermesHelperModels(
        profiles=seen["profiles"],
        tasks=[
            HelperTask(
                **{k: v for k, v in task.items() if k != "fields"},
                fields=[_helper_field(f) for f in task["fields"]],
                route=_helper_route(task),
            )
            for task in seen["tasks"]
        ],
        image_mode=None if image is None else _helper_field(image),
        image_choices=[HelperChoice(**c) for c in seen.get("image_choices", [])],
    )


@router.get("/preferences/hermes-helper-models")
async def get_hermes_helper_models(core: CoreDep) -> HermesHelperModels:
    return _helper_view(await asyncio.to_thread(hermes_helper_models.read, core))


@router.put("/preferences/hermes-helper-models")
async def put_hermes_helper_models(
    core: CoreDep, body: HermesHelperModelsBody
) -> HermesHelperModels:
    picks = {task: None if pick is None else pick.model_dump() for task, pick in body.picks.items()}
    seen = await asyncio.to_thread(
        hermes_helper_models.write, core, dict(body.sets), list(body.unsets), picks
    )
    return _helper_view(seen)


class FallbackEntry(Record):
    """One fallback model as Hermes has it, and where it sits in AGOS's model
    picker (`catalog_provider` + `mode`; None when the picker has no such provider,
    e.g. a custom endpoint set in Hermes itself)."""

    provider: str  # Hermes's provider name (fallback_providers[].provider)
    model: str
    base_url: str
    catalog_provider: str | None
    mode: Literal["cli", "api"] | None


class FallbackSpread(Record):
    chain: list[FallbackEntry]
    profiles: list[str]


class HermesFallback(Record):
    """Hermes's fallback_providers, as the workspaces' Hermes have it (no copy in AGOS)."""

    profiles: int
    chain: list[FallbackEntry]
    spread: list[FallbackSpread]


class FallbackEntryBody(Body):
    """A picker choice (provider + mode, AGOS's ids) or, without `mode`, a Hermes
    provider name as is (an entry the picker doesn't list, kept as it was)."""

    provider: str
    mode: Literal["cli", "api"] | None = None
    model: str
    base_url: str = ""


class HermesFallbackBody(Body):
    chain: list[FallbackEntryBody]


def _fallback_entry(entry: dict[str, str]) -> FallbackEntry:
    slug = entry["provider"]
    agos, mode = model_routes.picker_place(slug, entry["base_url"], keyed=bool(entry.get("keyed")))
    return FallbackEntry(
        provider=slug,
        model=entry["model"],
        base_url=entry["base_url"],
        catalog_provider=agos,
        mode=mode,
    )


def _fallback_view(seen: dict[str, Any]) -> HermesFallback:
    found = seen["seen"]
    return HermesFallback(
        profiles=seen["profiles"],
        chain=[_fallback_entry(e) for e in found.chain],
        spread=[
            FallbackSpread(chain=[_fallback_entry(e) for e in chain], profiles=labels)
            for chain, labels in found.spread
        ],
    )


@router.get("/preferences/hermes-fallback")
async def get_hermes_fallback(core: CoreDep) -> HermesFallback:
    return _fallback_view(await asyncio.to_thread(hermes_fallback.read, core))


@router.put("/preferences/hermes-fallback")
async def put_hermes_fallback(core: CoreDep, body: HermesFallbackBody) -> HermesFallback:
    chain = model_routes.fallback_chain([e.model_dump() for e in body.chain])
    return _fallback_view(await asyncio.to_thread(hermes_fallback.write, core, chain))


class VoiceOption(Record):
    """A speech-to-text provider Hermes has (or AGOS's plugin adds): its models,
    Hermes's default first (none listed: any model id, empty = Hermes's default)."""

    name: str  # stt.provider
    label: str
    hint: str
    models: list[str]
    model_key: str  # where Hermes reads its model (stt.<name>.model / model_id)


class HermesVoice(Record):
    """Who hears the owner's voice notes: Hermes's stt.provider and its model, one
    value for every workspace (Hermes's managed scope; no copy in AGOS)."""

    profiles: int
    provider: str
    model: str
    options: list[VoiceOption]


class HermesVoiceBody(Body):
    provider: str = Field(max_length=100)
    model: str = Field(default="", max_length=300)


def _voice_view(seen: dict[str, Any]) -> HermesVoice:
    return HermesVoice(
        profiles=seen["profiles"],
        provider=seen["provider"],
        model=seen["model"],
        options=[
            VoiceOption(
                name=o.name,
                label=o.label,
                hint=o.hint,
                models=list(o.models),
                model_key=o.model_key,
            )
            for o in seen["options"]
        ],
    )


@router.get("/preferences/hermes-voice")
async def get_hermes_voice(core: CoreDep) -> HermesVoice:
    return _voice_view(await asyncio.to_thread(hermes_voice.read, core))


@router.put("/preferences/hermes-voice")
async def put_hermes_voice(core: CoreDep, body: HermesVoiceBody) -> HermesVoice:
    return _voice_view(await asyncio.to_thread(hermes_voice.write, core, body.provider, body.model))
