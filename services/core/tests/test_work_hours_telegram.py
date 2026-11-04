"""Work hours on Telegram: his message to an off agent waits for its check-in (Hermes
stays quiet, he is told once), and goes to Hermes's conversation when it is on."""

from typing import Any

from channels_rig import OWNER, env, fake_telegram  # noqa: F401 — fixtures
from hermes_channel_rig import _bridge, _hermes_bot

from agos_core.actions import hermes_channel, work_hours

ALL_OFF = {d: None for d in work_hours.DAYS}


def test_a_telegram_message_to_an_off_agent_waits_for_check_in(env: Any) -> None:  # noqa: F811
    client, core, _fake, _tg, ws = env
    _cid, key = _hermes_bot(client, core, ws)
    r = client.put(f"/workspaces/{ws}/work-hours", json={"on": True, "days": ALL_OFF})
    assert r.status_code == 200, r.text
    got = _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "Still there?", "messageId": "41"},
    ).json()
    assert got["handled"] is True  # Hermes never starts a turn for it
    held = core.db.execute(
        "SELECT chat_ref, text, kind FROM hermes_inbox WHERE workspace_id = ?", (ws,)
    ).fetchall()
    assert [(r["text"], r["kind"]) for r in held] == [("Still there?", "message")]
    told = core.db.execute(
        "SELECT body FROM channel_outbox WHERE source LIKE 'work-hours:%'"
    ).fetchall()
    assert len(told) == 1 and "answered at check-in" in told[0]["body"]
    # A second message: held too, told only once.
    _bridge(
        client,
        ws,
        key,
        "incoming",
        {"chat": str(OWNER), "sender": str(OWNER), "text": "Hello?", "messageId": "42"},
    )
    assert (
        len(
            core.db.execute(
                "SELECT 1 FROM channel_outbox WHERE source LIKE 'work-hours:%'"
            ).fetchall()
        )
        == 1
    )
    assert hermes_channel.take_inbox(core, ws) == []
    # Wake now: Hermes's Telegram conversation gets both, in order.
    assert client.post(f"/workspaces/{ws}/work-hours/wake", json={"agent": ""}).status_code == 200
    taken = hermes_channel.take_inbox(core, ws)
    assert [t["text"] for t in taken] == ["Still there?", "Hello?"]
