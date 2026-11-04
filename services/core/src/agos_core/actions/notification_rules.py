"""The owner's notification rules: which AGOS events reach him, and how.

Only AGOS's own cards on the phone read these (owner_needs, token_watch,
error_alerts, the Daily digest): an automation's run news and account-limit news
are Hermes's (its cron delivery, its own limits), so AGOS has no switch for them.
Settings → Notifications (api/preferences.py) and the Co-Founder's
`set_notifications` both write through `save_notifications`.
"""

from typing import Any, Literal

from agos_core.db.app_settings import get_setting, set_setting

Delivery = Literal["instant", "batched", "silent"]
EVENTS: dict[str, tuple[str, Delivery]] = {
    "task.waiting": ("An agent is waiting for your approval", "instant"),
    "task.tokens": ("A card is using far more tokens than usual", "instant"),
    "agos.error": ("AGOS hit a new error, one came back, or one happens a lot", "instant"),
    "agos.agent_power": (
        "An agent made an automation, MCP server, skill or key by itself, or many changes at once",
        "instant",
    ),
}


def delivery_for(core: object, event: str) -> Delivery:
    saved = get_setting(core.db, "notifications", {})  # type: ignore[attr-defined]
    value = saved.get(event) if isinstance(saved, dict) else None
    if value in ("instant", "batched", "silent"):
        return value  # type: ignore[no-any-return]
    return EVENTS.get(event, ("", "instant"))[1]


def save_notifications(core: Any, rules: dict[str, str]) -> None:
    """The owner's page and the Co-Founder's action: only known events and deliveries."""
    clean = {
        e: d for e, d in rules.items() if e in EVENTS and d in ("instant", "batched", "silent")
    }
    set_setting(core.db, "notifications", clean)
    from agos_core.actions import digest

    # The Daily digest's clock is a Hermes cron job in each root: made or removed now.
    digest.keep_all(core)
