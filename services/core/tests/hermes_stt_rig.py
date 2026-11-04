"""Hermes's own speech-to-text settings rows, read from the installed Hermes's source
(test_stt_guard.py, test_hermes_voice.py)."""

from __future__ import annotations

import ast
import contextlib
from pathlib import Path
from typing import Any

from agos_core.engine import hermes_schema as hs

__all__ = ["hermes_stt_fields"]


def hermes_stt_fields() -> list[Any]:
    """The speech-to-text rows of Hermes's own settings schema, as its dashboard
    builds them (hermes_cli/web_server_config.py: the `stt.provider` select and each
    `stt.<provider>.model` / `model_id` select from tools/transcription_common.py
    STT_MODEL_CATALOG / STT_MODEL_CONFIG_KEY), taken from the installed Hermes's
    source by AST. The real schema runs in Hermes's runtime (test_hermes_voice_live)."""
    hermes = Path.home() / ".hermes/hermes-agent"
    literals: dict[str, Any] = {}
    for node in ast.parse((hermes / "tools/transcription_common.py").read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            with contextlib.suppress(ValueError):
                literals[node.targets[0].id] = ast.literal_eval(node.value)
    catalog: dict[str, list[str]] = literals["STT_MODEL_CATALOG"]
    names: dict[str, str] = literals["STT_MODEL_CONFIG_KEY"]
    providers: list[str] = []
    tree = ast.parse((hermes / "hermes_cli/web_server_config.py").read_text())
    for found in ast.walk(tree):
        if isinstance(found, ast.Dict):
            for key, value in zip(found.keys, found.values, strict=False):
                if isinstance(key, ast.Constant) and key.value == "stt.provider":
                    assert isinstance(value, ast.Call)
                    providers = [
                        str(a.value) for a in value.args[1:] if isinstance(a, ast.Constant)
                    ]
    fields = [hs.Field("stt.provider", "select", "Speech-to-text provider", "local", providers)]
    for name, models in catalog.items():
        row = f"stt.{name}.{names.get(name, 'model')}"
        fields.append(hs.Field(row, "select", row, models[0], list(models)))
    return fields
