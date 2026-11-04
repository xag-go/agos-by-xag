"""Small helpers shared by the repositories."""

import json
from datetime import UTC, datetime
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_json(value: str) -> Any:
    return json.loads(value)


def dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
