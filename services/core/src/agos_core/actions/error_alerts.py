"""The owner hears about AGOS's own errors (Settings → Errors, error_issues.py).

Told once, when an issue is new, when one he marked fixed comes back, and when one
suddenly happens many times (a spike) — never once per error. The path is the one
every AGOS alert takes (like contract_alert and token_watch), as his Notifications
setting for `agos.error` says:

- Instant: the Co-Founder's chat in AGOS (`owner_needs.tell_owner`), and his
  phone: Telegram + the installed app (`owner_needs.push`). With no workspace
  yet, the installed app only (`outbox_push.queue`, sent by the outbox loop).
- Daily digest: the chat in AGOS now; a line in the next digest.
- Silent: nothing (the Errors screen still lists it).

The alerts are sent by one thread of their own (`Alerts`), never inside the log
call that found the error: that call may hold the database or be a request.
At most `PER_HOUR` alerts an hour, so an error storm is one or two messages.
Errors logged while an alert is sent don't alert again.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
import time
from typing import Any

from agos_core.actions import error_issues

log = logging.getLogger("agos.errors")

EVENT = "agos.error"
PER_HOUR = 10
_THREAD = "agos-error-alerts"


def text_for(issue: error_issues.ErrorIssue, kind: str, where: str) -> str:
    what = f"{issue.error_type}: {issue.message}" if issue.error_type else issue.message
    what = " ".join(what.split())[:240]
    place = f" ({where})" if where else ""
    if kind == "back":
        head = "⚠️ An AGOS error you marked fixed came back"
    elif kind == "spike":
        head = f"⚠️ An AGOS error is happening a lot ({issue.count} times so far)"
    else:
        head = "⚠️ AGOS hit a new error"
    return f"{head}{place}: {what}. See Settings → Errors."


def _where(core: Any, issue: error_issues.ErrorIssue) -> str:
    # The owner's words only (spec 2026-11-04 no-engine-name): the engine is never
    # named; `issue.source` itself stays "hermes" for diagnostics.
    source = {"core": "AGOS core", "web": "AGOS web app", "hermes": "the engine"}[issue.source]
    if issue.workspace_id:
        from agos_core.db.workspaces import name_of

        return f"{source}, workspace {name_of(core.db, issue.workspace_id)}"
    return source


def tell(core: Any, issue_id: int, kind: str) -> bool:
    """Tells the owner about one issue now (on the alerts thread). True when told."""
    from agos_core.actions import contract_alert, outbox_push
    from agos_core.actions.notification_rules import delivery_for
    from agos_core.actions.services.channel import owner_needs

    issue = error_issues.get(core.db, issue_id)
    if issue is None:
        return False
    delivery = delivery_for(core, EVENT)
    if delivery == "silent":
        return False
    text = text_for(issue, kind, _where(core, issue))
    workspace = issue.workspace_id or contract_alert.owner_workspace(core)
    if workspace is None:  # no workspace yet: the installed app is the only place
        if delivery == "instant":  # through the outbox: retried, never twice
            outbox_push.queue(
                core,
                "AGOS error",
                text,
                url="/settings/errors",
                tag=f"error:{issue_id}",
                dedupe_key=f"error:{issue_id}:{kind}:{issue.count}",
            )
        return True
    message_id = owner_needs.tell_owner(core, workspace, text)
    if delivery == "batched":
        from agos_core.actions import digest

        digest.hold(core, workspace, EVENT, text)
        return True
    owner_needs.push(
        core,
        workspace,
        text,
        f"msg:{message_id}" if message_id else f"error:{issue_id}:{kind}:{issue.count}",
        chat_id=owner_needs.cofounder_chat(core, workspace),
    )
    return True


def sending() -> bool:
    """True on the alerts thread (an error logged while telling one doesn't alert)."""
    return threading.current_thread().name == _THREAD


class Alerts:
    """One thread that sends the alerts, in order, at most PER_HOUR an hour."""

    def __init__(self, core: Any) -> None:
        self.core = core
        self.waiting: queue.Queue[tuple[int, str] | None] = queue.Queue(maxsize=200)
        self.sent: list[float] = []
        self.thread = threading.Thread(target=self._run, name=_THREAD, daemon=True)
        self.thread.start()

    def __call__(self, issue_id: int, kind: str) -> None:
        if sending():
            return
        with contextlib.suppress(queue.Full):
            self.waiting.put_nowait((issue_id, kind))

    def _run(self) -> None:
        while True:
            item = self.waiting.get()
            if item is None:
                return
            moment = time.monotonic()
            self.sent = [t for t in self.sent if moment - t < 3600]
            if len(self.sent) >= PER_HOUR:
                continue
            try:
                if tell(self.core, *item):
                    self.sent.append(moment)
            except Exception as error:  # noqa: BLE001 - an alert must never break AGOS
                log.warning("error alert not sent: %s", type(error).__name__)

    def stop(self) -> None:
        with contextlib.suppress(queue.Full):
            self.waiting.put_nowait(None)
        self.thread.join(timeout=5)
