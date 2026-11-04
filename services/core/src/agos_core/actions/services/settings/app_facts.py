"""Limits the core keeps that the web reads instead of repeating them: what a chat
message may carry (engine/attachments.py checks it) and how long a workspace stays
in the trash (background/trash.py deletes it after).

Must not: hold a limit of its own (each lives with the code that enforces it).
"""

from __future__ import annotations

from typing import Any

from agos_core.background.trash import TRASH_DAYS
from agos_core.engine import attachments

__all__ = ["app_facts"]


def app_facts() -> dict[str, Any]:
    return {
        "attachments": {
            "max_files": attachments.MAX_FILES,
            "max_file_bytes": attachments.MAX_FILE_BYTES,
            "max_total_bytes": attachments.MAX_TOTAL_BYTES,
            "image_types": sorted(attachments.IMAGE_TYPES),
            "max_voice_seconds": attachments.MAX_VOICE_SECONDS,
        },
        "trash_days": TRASH_DAYS,
    }
