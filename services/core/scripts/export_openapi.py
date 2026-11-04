"""Writes the API contract to openapi.json; the web app generates its types from it."""

import json
import sys
from pathlib import Path

from agos_core.api.app import create_app


def contract() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "openapi.json"
    target.write_text(contract())
    sys.stdout.write(f"wrote {target}\n")
