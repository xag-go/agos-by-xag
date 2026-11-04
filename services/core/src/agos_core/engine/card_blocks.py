"""Machine-readable blocks in a Kanban card's body (Hermes's card holds them; AGOS
keeps no copy): a fenced code block whose language names the block, with one JSON
object inside, e.g.

    ```agos-skill-pins
    {"invoice-check": 3}
    ```

The agent reads the card body as text, so the block says what it is. AGOS reads
the block back from the card (`read_block`) and shows the body without it."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = r"```{lang}[ \t]*\n(.*?)\n```"


def with_block(body: str, lang: str, data: dict[str, Any]) -> str:
    text = body.rstrip()
    block = f"```{lang}\n{json.dumps(data, ensure_ascii=False, sort_keys=True)}\n```"
    return f"{text}\n\n{block}" if text else block


def _pattern(lang: str) -> re.Pattern[str]:
    return re.compile(_FENCE.format(lang=re.escape(lang)), re.S)


def read_block(body: str, lang: str) -> dict[str, Any] | None:
    """The block's JSON object (the last one when repeated), None without one."""
    found = _pattern(lang).findall(body or "")
    for raw in reversed(found):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def strip_block(body: str, lang: str) -> str:
    return _pattern(lang).sub("", body or "").strip()
