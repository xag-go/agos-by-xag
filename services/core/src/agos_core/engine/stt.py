"""Who hears the owner's voice notes: Hermes's speech-to-text (`stt.provider` and
that provider's `stt.<provider>.model`), read the way Hermes v0.22.2 reads them.

The providers, their models and the key each reads its model from are Hermes's
own dashboard schema (hermes_cli/web_server_config.py: the `stt.provider` select
and each `stt.<provider>.model` / `model_id` select, built from
tools/transcription_common.py STT_MODEL_CATALOG / STT_MODEL_CONFIG_KEY; read with
engine.config_schema, engine/hermes_schema.py), never a copied table: a provider or
model a Hermes upgrade adds shows by itself. A provider without a model select
(DeepInfra: a live list) takes any id under `stt.<provider>.model`. On top, the
`gemini` provider AGOS's agos-guard plugin registers with Hermes
(hermes_plugin/agos_guard/stt_gemini.py; Hermes reads its model from
`stt.gemini.model`, tools/transcription_tools.py `_route_stt_provider`). The labels
and hints are AGOS's words.

AGOS keeps no copy of the choice: one value for every workspace in Hermes's managed
scope (General settings → Voice notes, actions/hermes_voice.py).

Off is Hermes's own `stt.enabled: false` (tools/transcription_tools.py
`is_stt_enabled`). A fresh install starts there: nobody hears a voice note until
the owner picks a provider (Gemini, OpenAI, local Whisper, ...). An install that
already holds a provider keeps it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agos_core.shared.guard_contract import STT_DEFAULT_MODEL, STT_NAME

PROVIDER_KEY = "stt.provider"
ENABLED_KEY = "stt.enabled"  # Hermes's own on/off switch for speech-to-text
OFF_NAME = "off"  # the card's "Off" choice: stt.enabled false, no provider


@dataclass(frozen=True)
class SttProvider:
    name: str  # stt.provider
    label: str
    models: tuple[str, ...]  # what Hermes lists, its default first (empty: any id)
    model_name: str = "model"  # the key under stt.<name>
    hint: str = ""

    @property
    def model_key(self) -> str:
        return f"stt.{self.name}.{self.model_name}"


# AGOS's words for each (the names, models and keys are Hermes's).
LABELS: dict[str, tuple[str, str]] = {
    STT_NAME: (
        "Gemini (AGOS's plugin)",
        "Hears many languages well, Darija included; uses the Gemini key from Settings → Models.",
    ),
    "local": ("Local Whisper", "faster-whisper on this machine, no key."),
    "groq": ("Groq", "Needs GROQ_API_KEY."),
    "openai": ("OpenAI", "Needs an OpenAI key."),
    "mistral": ("Mistral Voxtral", "Needs MISTRAL_API_KEY."),
    "xai": ("xAI", "xAI Grok login or XAI_API_KEY."),
    "elevenlabs": ("ElevenLabs Scribe", "Needs an ElevenLabs key."),
    "deepinfra": ("DeepInfra", "Needs a DeepInfra key; no model = the first of its live list."),
}

GEMINI = SttProvider(
    STT_NAME,
    LABELS[STT_NAME][0],
    (STT_DEFAULT_MODEL,),
    hint=LABELS[STT_NAME][1],
)

# The card's "Off" choice (not a Hermes provider: it is `stt.enabled: false`).
OFF = SttProvider(
    OFF_NAME,
    "Off",
    (),
    hint="Voice notes aren't turned into text. Pick a provider to turn them on.",
)

# What the managed scope starts with when no profile had a choice: off.
DEFAULT_SETTINGS: tuple[tuple[str, str], ...] = ((ENABLED_KEY, "false"),)


def _schema() -> list[Any]:
    """Hermes's settings list as last read (engine.config_schema); [] before."""
    from agos_core.engine import hermes_schema

    return hermes_schema.cached() or []


def providers(fields: Iterable[Any] | None = None) -> tuple[SttProvider, ...]:
    """AGOS's plugin's provider, then each one Hermes's schema offers, with the
    models and model key Hermes's schema gives it."""
    by = {f.key: f for f in (_schema() if fields is None else fields)}
    found = by.get(PROVIDER_KEY)
    names = [str(o) for o in (found.options if found is not None else [])]
    out = [GEMINI]
    for name in names:
        if name == GEMINI.name or not name:
            continue
        model_name = next((k for k in ("model", "model_id") if f"stt.{name}.{k}" in by), "model")
        select = by.get(f"stt.{name}.{model_name}")
        models = tuple(str(o) for o in (select.options if select is not None else []))
        label, hint = LABELS.get(name, (name, ""))
        out.append(SttProvider(name, label, models, model_name, hint))
    return tuple(out)


def by_name(fields: Iterable[Any] | None = None) -> dict[str, SttProvider]:
    return {p.name: p for p in providers(fields)}


def card_keys(fields: Iterable[Any] | None = None) -> tuple[str, ...]:
    """Every config key of the card: the on/off switch, the provider and each
    provider's model (the ones Hermes's schema lists once it was read)."""
    return (ENABLED_KEY, PROVIDER_KEY, *(p.model_key for p in providers(fields)))


def model_key(provider: str, fields: Iterable[Any] | None = None) -> str | None:
    found = by_name(fields).get(provider)
    return found.model_key if found is not None else None
