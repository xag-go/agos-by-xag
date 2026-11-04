"""The first notification moved onto the outbox: an AGOS error with no workspace yet
is told on the installed app (actions/error_alerts.py). It is queued as an outbox
row (actions/outbox_push.py) and sent by the delivery loop, retried when the push
service can't be reached, never twice for the same alert."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from agos_core.actions import (
    backups,
    error_alerts,
    error_issues,
    hermes_errors,
    ops_watch,
    outbox_push,
    staging,
    web_push,
)
from agos_core.api.app import create_app
from agos_core.config import Settings
from agos_core.jobs import runner as jobs_loop
from agos_core.outbox import delivery

SUB = {"endpoint": "https://push.example/abc", "p256dh": "k", "auth": "a"}


@pytest.fixture
def core(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=False)) as client:
        monkeypatch.setitem(delivery.SENDERS, outbox_push.CHANNEL, outbox_push.send)
        yield client.app.state.core  # type: ignore[attr-defined]


def _row(db: Any, row_id: int) -> Any:
    """An outbox row as the delivery loop left it (tests read it directly)."""
    return db.execute("SELECT * FROM outbox WHERE id = ?", (row_id,)).fetchone()


def _queued(core: Any) -> list[Any]:
    return list(core.db.execute("SELECT * FROM outbox WHERE channel = 'push'").fetchall())


def test_an_error_alert_with_no_workspace_is_queued_not_sent_inline(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    inline: list[Any] = []

    def notify(*a: Any, **_: Any) -> int:
        inline.append(a)
        return 1

    monkeypatch.setattr(web_push, "notify", notify)
    issue, _ = error_issues.record(
        core.db, source="core", where="agos.x", error_type="OSError", message="disk", frames=[]
    )
    assert error_alerts.tell(core, issue, "new")
    assert error_alerts.tell(core, issue, "new")  # the same alert again: one row
    assert inline == []
    [row] = _queued(core)
    payload = json.loads(row["payload"])
    assert payload["title"] == "AGOS error"
    assert "new error" in payload["body"] and payload["url"] == "/settings/errors"
    assert payload["tag"] == f"error:{issue}"
    assert row["status"] == "pending"


def test_the_loop_sends_a_queued_push_to_every_phone(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        web_push, "subscriptions", lambda c: [SUB, {**SUB, "endpoint": "https://p/2"}]
    )

    def send_one(http: Any, key: Any, endpoint: str, p256dh: str, auth: str, data: bytes) -> int:
        sent.append((endpoint, data))
        return 201

    monkeypatch.setattr(web_push, "send_one", send_one)
    outbox_push.queue(core, "Title", "Body", url="/x", tag="t")
    assert delivery.deliver_due(core) == 1
    assert [e for e, _ in sent] == ["https://push.example/abc", "https://p/2"]
    assert json.loads(sent[0][1]) == {
        "title": "Title",
        "body": "Body",
        "url": "/x",
        "tag": "t",
        "where": "",
    }


def test_a_gone_phone_is_forgotten_and_an_unreachable_service_is_retried(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gone: list[str] = []
    monkeypatch.setattr(web_push, "subscriptions", lambda c: [SUB])

    def unsubscribe(_core: Any, endpoint: str) -> bool:
        gone.append(endpoint)
        return True

    monkeypatch.setattr(web_push, "unsubscribe", unsubscribe)
    monkeypatch.setattr(web_push, "send_one", lambda *a: 410)
    outbox_push.queue(core, "Gone", "x")
    assert delivery.deliver_due(core) == 1
    assert gone == [SUB["endpoint"]]

    def down(*_a: Any) -> int:
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(web_push, "send_one", down)
    row_id = outbox_push.queue(core, "Later", "x")
    assert row_id is not None
    assert delivery.deliver_due(core) == 0
    row = _row(core.db, row_id)
    assert row is not None and row["status"] == "pending" and "no route" in row["last_error"]


def test_a_staging_copy_sends_no_push(core: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(staging, "on", lambda: True)
    monkeypatch.setattr(web_push, "subscriptions", lambda c: [SUB])
    called: list[Any] = []

    def send_one(*a: Any) -> int:
        called.append(a)
        return 201

    monkeypatch.setattr(web_push, "send_one", send_one)
    outbox_push.queue(core, "Quiet", "x")
    delivery.deliver_due(core)
    assert called == []


def test_the_core_runs_the_outbox_loop_with_its_other_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def idle(_core: Any) -> None:
        await asyncio.Event().wait()

    for module in (jobs_loop, backups, ops_watch, hermes_errors):
        monkeypatch.setattr(module, "run_forever", idle)
    sent: list[dict[str, Any]] = []
    monkeypatch.setitem(delivery.SENDERS, outbox_push.CHANNEL, outbox_push.send)  # restored after
    monkeypatch.setattr(outbox_push, "send", lambda c, p: sent.append(p))  # what register() takes
    settings = Settings(
        data_dir=tmp_path / "data",
        internal_token_file=tmp_path / "data" / "system" / "internal.token",
        documents_url=None,
    )
    with TestClient(create_app(settings, background=True)) as client:
        outbox_push.queue(client.app.state.core, "Live", "x")  # type: ignore[attr-defined]
        deadline = time.monotonic() + 5
        while not sent and time.monotonic() < deadline:
            time.sleep(0.05)
    assert [p["title"] for p in sent] == ["Live"]


def test_every_web_push_is_an_outbox_row_sent_by_the_loop(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """web_push.notify (cards, approvals, answers, the test ring) never sends inline:
    it queues a push row and the delivery loop sends it."""
    monkeypatch.setattr(web_push, "subscriptions", lambda c: [SUB])
    sent: list[str] = []

    def send_one(http: Any, key: Any, endpoint: str, p256dh: str, auth: str, data: bytes) -> int:
        sent.append(json.loads(data)["title"])
        return 201

    monkeypatch.setattr(web_push, "send_one", send_one)
    assert web_push.notify(core, "Queued", "x", tag="t") == 1
    time.sleep(0.1)  # no thread sends it behind our back
    assert sent == []
    [row] = _queued(core)
    assert json.loads(row["payload"])["title"] == "Queued"
    assert delivery.deliver_due(core) == 1
    assert sent == ["Queued"]
    assert delivery.deliver_due(core) == 0  # never twice


def test_a_push_queued_in_a_change_that_rolls_back_is_never_sent(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agos_core.uow import UnitOfWork

    monkeypatch.setattr(web_push, "subscriptions", lambda c: [SUB])
    with pytest.raises(RuntimeError), UnitOfWork(core, name="a change"):
        web_push.notify(core, "Rolled back", "x")
        raise RuntimeError("the change failed")
    assert _queued(core) == []


def test_an_owner_card_push_is_queued_once_per_source(
    core: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_push, "subscriptions", lambda c: [SUB])
    from agos_core.db.workspaces import insert_workspace

    insert_workspace(core.db, workspace_id="w", name="W", description="")
    web_push.card(core, "w", "**Allow** once?", None, "ask:1")
    web_push.card(core, "w", "**Allow** once?", None, "ask:1")
    [row] = _queued(core)
    assert row["workspace_id"] == "w" and row["dedupe_key"] == "card:w:ask:1"


def test_the_core_sends_no_notification_outside_an_outbox() -> None:
    """Guard: Telegram goes out only through `channel_outbox` (its Hermes gateway sends
    it) and phone push only through the outbox loop: no Telegram Bot API call and no
    sending thread anywhere in the core."""
    src = Path(delivery.__file__).parents[1]
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if "hermes_plugin" not in path.parts
        and ("api.telegram.org" in (text := path.read_text()) or "agos-web-push" in text)
    ]
    assert offenders == []
