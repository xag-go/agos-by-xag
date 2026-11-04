"""Settings → General and Notifications: the owner's account-wide preferences (usage
thresholds, notification rules, the tabs' and workspaces' order, his name, his
timezone). HTTP only: the rules live in the actions each route calls.

Must not: read or write app_settings or Hermes itself.
"""

import asyncio

from fastapi import APIRouter
from pydantic import Field

from agos_core.actions import founder, owner_time
from agos_core.actions.notification_rules import EVENTS, Delivery, delivery_for, save_notifications
from agos_core.actions.services.settings import account_prefs
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

__all__ = [
    "NotificationRule",
    "NotificationsBody",
    "OwnerNamePref",
    "TabsOrder",
    "TimezonePref",
    "UsagePrefs",
    "WorkspaceOrder",
    "router",
    "usage_prefs",
]

router = APIRouter()


class UsagePrefs(Body):
    enabled: bool = True
    warn_at: int = Field(default=80, ge=1, le=100)
    pause_at: int = Field(default=100, ge=1, le=100)


class NotificationRule(Record):
    event: str
    label: str
    delivery: Delivery


class NotificationsBody(Body):
    rules: dict[str, Delivery]


def usage_prefs(core: object) -> UsagePrefs:
    return UsagePrefs.model_validate(account_prefs.usage_prefs(core).model_dump())


@router.get("/preferences/usage")
def get_usage(core: CoreDep) -> UsagePrefs:
    return usage_prefs(core)


@router.put("/preferences/usage", status_code=204)
async def put_usage(core: CoreDep, body: UsagePrefs) -> None:
    account_prefs.save_usage(core, body.enabled, body.warn_at, body.pause_at)


@router.get("/preferences/notifications")
def get_notifications(core: CoreDep) -> list[NotificationRule]:
    return [
        NotificationRule(event=e, label=label, delivery=delivery_for(core, e))
        for e, (label, _default) in EVENTS.items()
    ]


@router.put("/preferences/notifications", status_code=204)
async def put_notifications(core: CoreDep, body: NotificationsBody) -> None:
    await asyncio.to_thread(save_notifications, core, dict(body.rules))


class TabsOrder(Body):
    order: list[str] = Field(max_length=20)


@router.get("/preferences/tabs")
def get_tabs(core: CoreDep) -> TabsOrder:
    return TabsOrder(order=account_prefs.tabs_order(core))


@router.put("/preferences/tabs", status_code=204)
async def put_tabs(core: CoreDep, body: TabsOrder) -> None:
    account_prefs.save_tabs(core, body.order)


class WorkspaceOrder(Body):
    order: list[str] = Field(max_length=500)


@router.put("/preferences/workspace-order", status_code=204)
def put_workspace_order(core: CoreDep, body: WorkspaceOrder) -> None:
    account_prefs.save_workspace_order(core, body.order)


class OwnerNamePref(Body):
    name: str = Field(default="", max_length=200)


@router.get("/preferences/owner-name")
def get_owner_name(core: CoreDep) -> OwnerNamePref:
    """His name (Settings → General): the Founder's box, his cards, his notices."""
    return OwnerNamePref(name=founder.owner_name(core))


@router.put("/preferences/owner-name")
def put_owner_name(core: CoreDep, body: OwnerNamePref) -> OwnerNamePref:
    return OwnerNamePref(name=founder.save_owner_name(core, body.name))


class TimezonePref(Body):
    timezone: str = Field(max_length=100)


@router.get("/preferences/timezone")
async def get_timezone(core: CoreDep) -> TimezonePref:
    """The owner's timezone: the clock times he gives the agents are in it."""
    return TimezonePref(timezone=await asyncio.to_thread(owner_time.owner_zone, core))


@router.put("/preferences/timezone")
async def put_timezone(core: CoreDep, body: TimezonePref) -> TimezonePref:
    """Hermes's own `timezone`, written into every workspace's Hermes."""
    return TimezonePref(
        timezone=await asyncio.to_thread(owner_time.save_timezone, core, body.timezone)
    )
