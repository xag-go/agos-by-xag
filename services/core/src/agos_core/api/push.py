"""The installed app's notifications: the key to subscribe with, the browsers
subscribed, and a test ring (actions/web_push.py)."""

from fastapi import APIRouter, HTTPException
from pydantic import Field

from agos_core.actions import web_push
from agos_core.api.deps import CoreDep
from agos_core.api.schemas import Body
from agos_core.db.records import Record

router = APIRouter(tags=["push"])


class PushKey(Record):
    key: str


class PushSubscriptionBody(Body):
    endpoint: str = Field(min_length=12, max_length=2000)
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)
    label: str = Field(default="", max_length=120)


class PushEndpointBody(Body):
    endpoint: str = Field(min_length=12, max_length=2000)


class PushSubscription(Record):
    id: int
    endpoint: str
    label: str
    created_at: str
    seen_at: str


class PushSent(Record):
    sent: int


@router.get("/push/key")
def get_key(core: CoreDep) -> PushKey:
    return PushKey(key=web_push.public_key(core))


@router.get("/push/subscriptions")
def list_subscriptions(core: CoreDep) -> list[PushSubscription]:
    return [
        PushSubscription(
            id=int(s["id"]),
            endpoint=str(s["endpoint"]),
            label=str(s["label"]),
            created_at=str(s["created_at"]),
            seen_at=str(s["seen_at"]),
        )
        for s in web_push.subscriptions(core)
    ]


@router.put("/push/subscriptions", status_code=204)
def put_subscription(core: CoreDep, body: PushSubscriptionBody) -> None:
    try:
        web_push.subscribe(core, body.endpoint, body.p256dh, body.auth, body.label)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/push/unsubscribe", status_code=204)
def unsubscribe(core: CoreDep, body: PushEndpointBody) -> None:
    web_push.unsubscribe(core, body.endpoint)


@router.post("/push/test")
def test(core: CoreDep) -> PushSent:
    return PushSent(
        sent=web_push.notify(
            core,
            "AGOS",
            "Notifications work on this device.",
            url="/settings/notifications",
            tag="test",
        )
    )
