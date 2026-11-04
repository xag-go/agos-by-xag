"""Phone and browser push (the installed app) on the outbox: the push channel's
sender. Every push is queued as an outbox row by `web_push.queue` / `notify` (on
the caller's connection, inside its Unit of Work when there is one); the delivery
loop (agos_core/outbox/delivery.py) sends it with `send` and retries it while the
push service can't be reached.

Owns: the push channel's sender. Must not: hold the Web Push crypto, payload or
subscriptions (actions/web_push.py) or decide who is told (the caller).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

from agos_core.actions import staging, web_push
from agos_core.actions.web_push import CHANNEL as CHANNEL
from agos_core.actions.web_push import queue as queue
from agos_core.outbox import delivery

__all__ = ["CHANNEL", "queue", "register", "send"]

log = logging.getLogger("agos.web_push")


def send(core: Any, payload: dict[str, Any]) -> None:
    """Every subscribed browser gets it; a gone one (404/410) is forgotten. Raises
    when none could be reached, so the outbox tries again later. A staging copy
    (actions/staging.py) sends none."""
    if staging.on():
        return
    subs = web_push.subscriptions(core)
    if not subs:
        return
    data = json.dumps(payload, ensure_ascii=False).encode()
    key = web_push._private_key(core)  # the push keys stay web_push's
    failures: list[Exception] = []
    with web_push._client() as http:
        for s in subs:
            endpoint = str(s["endpoint"])
            try:
                status = web_push.send_one(
                    http, key, endpoint, str(s["p256dh"]), str(s["auth"]), data
                )
            except Exception as error:  # noqa: BLE001 - one bad phone never stops the others
                failures.append(error)
                continue
            if status in (404, 410):
                web_push.unsubscribe(core, endpoint)
            elif status >= 400:
                log.warning("web push to %s refused: HTTP %s", urlsplit(endpoint).netloc, status)
    if failures and len(failures) == len(subs):
        raise failures[0]


def register() -> None:
    """The delivery loop sends this channel's rows with `send` (at the core's start)."""
    delivery.SENDERS[CHANNEL] = send
