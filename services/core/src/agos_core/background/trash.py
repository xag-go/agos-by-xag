"""Workspaces deleted more than 30 days ago are removed for good: folder and rows
(the "trash.purge" job, every EVERY_SECONDS: agos_core/background/schedule.py)."""

from datetime import UTC, datetime, timedelta

from agos_core.actions.engine import delete_engine_data
from agos_core.context import Core
from agos_core.db.workspaces import list_trashed, purge_deleted
from agos_core.storage.layout import purge_trash

TRASH_DAYS = 30
EVERY_SECONDS = 6 * 60 * 60


def purge_expired(core: Core, now: datetime | None = None) -> list[str]:
    moment = now or datetime.now(UTC)
    limit = moment - timedelta(days=TRASH_DAYS)
    expired = [
        t["id"]
        for t in list_trashed(core.db)
        if datetime.fromisoformat(t["deletedAt"].replace("Z", "+00:00")) < limit
    ]
    purge_trash(core.layout, TRASH_DAYS, int(moment.timestamp() * 1000))
    for workspace_id in expired:
        purge_deleted(core.db, workspace_id)
        delete_engine_data(core, workspace_id)
    return expired
