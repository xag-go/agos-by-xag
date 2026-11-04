"""Limits the core keeps, read by the web instead of repeating them (a chat
message's attachments, the trash's days): actions/services/settings/app_facts.py.

Must not: hold a limit of its own.
"""

from fastapi import APIRouter

from agos_core.actions.services.settings.app_facts import app_facts
from agos_core.db.records import Record

__all__ = ["AppFacts", "AttachmentLimits", "router"]

router = APIRouter()


class AttachmentLimits(Record):
    """What a chat message may carry (engine/attachments.py: the core checks it)."""

    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    image_types: list[str]
    max_voice_seconds: int  # a voice note's longest recording


class AppFacts(Record):
    """Limits the core keeps, read by the web instead of repeating them."""

    attachments: AttachmentLimits
    trash_days: int  # a workspace in the trash is deleted for good after this


@router.get("/app/facts")
def get_app_facts() -> AppFacts:
    return AppFacts.model_validate(app_facts())
