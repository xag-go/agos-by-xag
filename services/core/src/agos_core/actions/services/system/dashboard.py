"""A workspace's Dashboard: its bots, Hermes's usage, its automations, its chats.

Moved out of api/overview.py (the router keeps only the HTTP mapping). Owns: the
Dashboard's one read of the workspace (nothing from other projects) and the
read-ahead that asks Hermes for it once after a start.

Must not: write, or ask Hermes for anything the page doesn't show.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from agos_core.actions import automations as automation_actions
from agos_core.actions.services.chat import view as chat_view
from agos_core.actions.workspaces import require_workspace
from agos_core.db import status_reads
from agos_core.db.records import Record
from agos_core.engine.hermes import EngineError

__all__ = [
    "OverviewAutomation",
    "OverviewChannel",
    "OverviewChat",
    "OverviewUsage",
    "UsageDay",
    "UsageModel",
    "WorkspaceOverview",
    "read_ahead",
    "workspace_overview",
]

log = logging.getLogger("agos.overview")


# ---- One workspace's own overview (the Dashboard). Nothing from other projects. ----


class OverviewChannel(Record):
    id: int
    kind: str
    name: str
    identity: str
    status: Literal["connecting", "connected", "error"]
    reason: str
    last_ok_at: str | None


class UsageDay(Record):
    day: str  # YYYY-MM-DD
    tokens: int
    replies: int


class UsageModel(Record):
    provider: str
    model: str
    tokens: int
    replies: int


class OverviewUsage(Record):
    tokens: int
    input_tokens: int  # not served from the prompt cache
    cached_tokens: int  # prompt tokens read from / written to the provider's cache
    output_tokens: int
    replies: int  # model calls this month (Hermes's count, every profile of the workspace)
    days: list[UsageDay]  # the last 30 days, oldest first, missing days = 0
    models: list[UsageModel]


class OverviewAutomation(Record):
    id: int
    name: str
    enabled: bool
    next_run_at: str | None
    last_result: str | None
    event: bool = False
    # Hermes's job state (scheduled / paused / completed / error; None: no job).
    state: str | None = None


class OverviewChat(Record):
    id: int
    title: str
    kind: str
    agent: str | None
    at: str
    preview: str
    href: str


class WorkspaceOverview(Record):
    channels: list[OverviewChannel]
    usage: OverviewUsage
    automations: list[OverviewAutomation]
    recent_chats: list[OverviewChat]
    done_this_week: int


def workspace_overview(core: Any, workspace_id: str) -> WorkspaceOverview:
    require_workspace(core, workspace_id)
    now = datetime.now(UTC)
    first_day = (now - timedelta(days=29)).date()

    channels = _channels(core, workspace_id)

    # What the workspace's Hermes counted, as Hermes's own usage analytics has it
    # (the dashboard's /api/analytics/usage over the root and each member): the
    # headline and the per-model lines since the 1st of the month (one count: the
    # lines add up to the headline), the bars its daily series.
    days = {(first_day + timedelta(days=i)).isoformat(): [0, 0] for i in range(30)}
    found = _usage(core, workspace_id, now)
    models: dict[str, dict[str, int]] = found.get("models") or {}
    for day, acc in (found.get("days") or {}).items():
        if day in days:
            days[day] = [int(acc.get("tokens") or 0), int(acc.get("calls") or 0)]
    total = sum(v["tokens"] for v in models.values())
    inp = sum(v.get("input", 0) for v in models.values())
    cached = sum(v.get("cached", 0) for v in models.values())
    out = sum(v.get("output", 0) for v in models.values())
    replies = sum(v["calls"] for v in models.values())

    # Their timing read live from the workspace's Hermes cron.
    automations = sorted(
        (
            OverviewAutomation(
                id=a.id,
                name=a.name,
                enabled=a.on,
                next_run_at=a.next_run_at,
                last_result=a.last_run.result if a.last_run else None,
                event=a.hook is not None,
                state=a.state,
            )
            for a in automation_actions.list_all(core, workspace_id)
        ),
        key=lambda a: (not a.enabled, a.next_run_at is None, a.next_run_at or "", a.name),
    )

    recent = _recent_chats(core, workspace_id)

    from agos_core.actions import kanban_board

    done = kanban_board.done_since(core, workspace_id, int((now - timedelta(days=7)).timestamp()))

    return WorkspaceOverview(
        channels=channels,
        usage=OverviewUsage(
            tokens=total,
            input_tokens=inp,
            cached_tokens=cached,
            output_tokens=out,
            replies=replies,
            days=[UsageDay(day=d, tokens=v[0], replies=v[1]) for d, v in days.items()],
            models=[
                UsageModel(provider="", model=m, tokens=v["tokens"], replies=v["calls"])
                for m, v in sorted(models.items(), key=lambda kv: -kv[1]["tokens"])
            ],
        ),
        automations=automations,
        recent_chats=recent,
        done_this_week=int(done),
    )


def _channels(core: Any, workspace_id: str) -> list[OverviewChannel]:
    """The workspace's bots and their lamps, read live from Hermes."""
    from agos_core.actions import hermes_channel

    channels = []
    for r in status_reads.bot_connections(core.db, workspace_id):
        status, reason = hermes_channel.channel_state(core, r)  # live, from Hermes
        channels.append(
            OverviewChannel(
                id=r["id"],
                kind=r["kind"],
                name=r["name"],
                identity=r["identity"],
                status=status,  # type: ignore[arg-type]
                reason=reason,
                last_ok_at=hermes_channel.channel_ok_at(core, r),
            )
        )
    return channels


def _recent_chats(core: Any, workspace_id: str) -> list[OverviewChat]:
    """The six chats with the newest last words."""
    recent: list[OverviewChat] = []
    # Each chat's last words: Hermes's (its conversation), a room's: AGOS's lines.
    every = chat_view.list_chats(core.db, workspace_id, ("chat", "dm", "group"))
    for c in [c for c in every if c.preview][:6]:
        href = (
            f"/w/{workspace_id}/sessions?chat={c.id}"
            if c.kind == "chat"
            else f"/w/{workspace_id}/messages?c={c.id}"
        )
        text = " ".join(c.preview.split())
        recent.append(
            OverviewChat(
                id=c.id,
                title=c.title or "Chat",
                kind=c.kind,
                agent=c.agent,
                at=c.updated_at,
                preview=text[:200] + ("…" if len(text) > 200 else ""),
                href=href,
            )
        )
    return recent


def _usage(core: Any, workspace_id: str, now: datetime) -> dict[str, Any]:
    """Hermes's usage analytics of the workspace (root and members) since the 1st
    of the month, its daily series over 30 days (engine.hermes_usage: Hermes
    counts again only when their sessions changed)."""
    if core.engine is None:
        return {"models": {}, "days": {}}
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prefix = core.engine.settings.profile_prefix
    root = core.engine.profile_home(workspace_id)
    members = [
        Path(core.engine.profile_home(p[len(prefix) :])).name
        for p in core.engine.own_profiles(workspace_id)
        if p[len(prefix) :] != workspace_id
    ]
    try:
        found: dict[str, Any] = core.engine.hermes_usage(
            root, members, max((now - month).total_seconds(), 60.0) / 86400, 30
        )
    except (EngineError, OSError, ValueError) as error:
        log.info("Hermes's usage of %s not read: %s", workspace_id, error)
        return {"models": {}, "days": {}}
    return found


def read_ahead(core: Any) -> None:
    """engine/read_ahead.py: what the Dashboard asks Hermes for each workspace (its
    usage, its bots' lamps), asked once after a start so the first Dashboard
    doesn't wait for Hermes."""
    from agos_core.actions import hermes_channel
    from agos_core.db import workspaces as workspaces_repo

    if core.engine is None:
        return
    now = datetime.now(UTC)
    for ws in workspaces_repo.list_workspaces(core.db):
        if not (core.engine.profile_home(ws.id) / "config.yaml").is_file():
            continue  # no Hermes root yet: nothing to ask
        _usage(core, ws.id, now)
        for row in status_reads.bot_connections(core.db, ws.id):
            hermes_channel.channel_state(core, row)
