"""Guard (C4, 925047d area 2): General settings → Voice notes offers the
speech-to-text providers, models and model keys of Hermes's own settings schema
(engine/stt.py reads them from engine.config_schema), not a copied table: AGOS's
code names no Hermes model id, and a provider or model a Hermes upgrade adds shows
by itself."""

import ast
from pathlib import Path
from typing import Any

import pytest
from hermes_stt_rig import hermes_stt_fields

from agos_core.engine import hermes_schema as hs
from agos_core.engine import stt

HERMES = Path.home() / ".hermes" / "hermes-agent"
COMMON = HERMES / "tools" / "transcription_common.py"

pytestmark = pytest.mark.skipif(not COMMON.is_file(), reason="Hermes isn't installed")


def _catalog() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in ast.parse(COMMON.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def test_the_options_are_hermess_schema() -> None:
    found = _catalog()
    by = stt.by_name(hermes_stt_fields())
    assert next(iter(by)) == stt.GEMINI.name  # AGOS's plugin first
    for name, models in found["STT_MODEL_CATALOG"].items():
        assert list(by[name].models) == models, name
        assert by[name].model_name == found["STT_MODEL_CONFIG_KEY"].get(name, "model"), name
    # DeepInfra: in Hermes's provider select, no model select (a live list): any id.
    assert by["deepinfra"].models == () and by["deepinfra"].model_key == "stt.deepinfra.model"


def test_a_provider_hermes_adds_shows_by_itself() -> None:
    fields = [
        hs.Field("stt.provider", "select", "x", "local", ["local", "newvoice"]),
        hs.Field("stt.newvoice.model_id", "select", "x", "v2", ["v2", "v1"]),
    ]
    new = stt.by_name(fields)["newvoice"]
    assert new.models == ("v2", "v1") and new.model_key == "stt.newvoice.model_id"
    assert new.label == "newvoice"
    assert "stt.newvoice.model_id" in stt.card_keys(fields)


def test_agos_names_no_hermes_model_id() -> None:
    source = (Path(stt.__file__)).read_text()
    for models in _catalog()["STT_MODEL_CATALOG"].values():
        for model in models:
            assert f'"{model}"' not in source, model
