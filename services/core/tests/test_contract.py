"""The committed contract must match the code, so the web's generated types
can't silently drift. Fix: `uv run python scripts/export_openapi.py`, then
`pnpm --filter @agos/web gen:api`."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openapi_is_up_to_date() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_openapi", ROOT / "scripts" / "export_openapi.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (ROOT / "openapi.json").read_text() == module.contract(), "openapi.json is out of date"
