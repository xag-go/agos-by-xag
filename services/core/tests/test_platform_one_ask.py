"""One platform-next ask per gateway (F3): a root's gateway serves several Hermes
profiles (the Co-Founder's and its members', Hermes's served_profiles), each with its
own copy of the plugin and its own agos platform adapter. One copy asks AGOS for
all of them; AGOS answers each item with its member, and the copy hands it to its
profile's adapter. An older core (no `members` in its answer) is asked by each copy
on its own, as before; an older plugin's ask is answered as before."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from test_hermes_roots import _new, roots_env  # noqa: F401 - fixture

from agos_core.actions import agent_profiles, hermes_channel
from agos_core.db.connection import transaction
from agos_core.db.rows import now
from agos_core.hermes_plugin.agos_guard import bridge

ROOT = {"core": "http://127.0.0.1:1", "workspace": "w", "key": "k"}


def _as(member: str) -> dict[str, str]:
    return {**ROOT, "member": member} if member else dict(ROOT)


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    monkeypatch.setitem(bridge._shared, bridge.PLATFORM_GROUPS, {})
    return []


def _core(asked: list[tuple[str, dict[str, Any]]], answer: dict[str, Any]) -> Any:
    def post(path: str, body: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        asked.append((path, body))
        return answer

    return post


def test_one_ask_carries_every_profile_and_each_gets_its_own(
    asked: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = {
        "items": [
            {"id": 1, "chat": "agos:5", "member": ""},
            {"id": 2, "chat": "agos:5.writer", "member": "writer"},
        ],
        "members": ["", "writer"],
    }
    monkeypatch.setattr(bridge, "post", _core(asked, answer))

    async def gateway() -> tuple[Any, Any, Any]:
        root: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        writer: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        bridge._platform_join(_as(""), root)
        bridge._platform_join(_as("writer"), writer)
        mine = await bridge._platform_items(_as(""), root)
        theirs = await bridge._platform_items(_as("writer"), writer)
        # A profile whose copy came after the ask went asks on its own until the
        # gateway's next ask carries it.
        late: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        alone = await bridge._platform_items(_as("editor"), late)
        return mine, theirs, alone

    mine, theirs, _alone = asyncio.run(gateway())
    assert [i["id"] for i in mine] == [1]
    assert [i["id"] for i in theirs] == [2]
    assert asked[0] == ("platform-next", {"members": ["", "writer"]})
    assert asked[1:] == [("platform-next", {})]  # the late one alone; the writer never asked


def test_an_older_core_is_asked_by_each_copy_as_before(
    asked: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An older core takes only the asking copy's own member (it has no `members`).
    monkeypatch.setattr(bridge, "post", _core(asked, {"items": [{"id": 1, "chat": "agos:5"}]}))

    async def gateway() -> list[Any]:
        root: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        writer: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        bridge._platform_join(_as(""), root)
        bridge._platform_join(_as("writer"), writer)
        first = await bridge._platform_items(_as(""), root)
        return [first, await bridge._platform_items(_as("writer"), writer)]

    first, _writer = asyncio.run(gateway())
    assert [i["id"] for i in first] == [1]
    assert asked == [("platform-next", {"members": ["", "writer"]}), ("platform-next", {})]


def test_a_copy_that_goes_leaves_the_ask_to_another(
    asked: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bridge, "post", _core(asked, {"items": [], "members": ["writer"]}))

    async def gateway() -> None:
        root: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        writer: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        bridge._platform_join(_as(""), root)
        bridge._platform_join(_as("writer"), writer)
        await bridge._platform_items(_as(""), root)
        bridge._platform_leave(_as(""), root)  # the Co-Founder's adapter disconnected
        await bridge._platform_items(_as("writer"), writer)

    asyncio.run(gateway())
    assert asked[-1] == ("platform-next", {"members": ["writer"]})


def test_the_core_takes_for_every_member_asked(roots_env: Any, monkeypatch: Any) -> None:  # noqa: F811
    client, _runner, _tmp, core = roots_env
    ws = _new(client)
    monkeypatch.setattr(agent_profiles, "ready", lambda _c, w, a: w == ws and a == "writer")
    chat = hermes_channel.cofounder_chat(core, ws)  # the Co-Founder's own chat
    assert chat is not None

    def queue(ref: str) -> None:
        with transaction(core.db):
            core.db.execute(
                """INSERT INTO hermes_inbox (workspace_id, chat_ref, text, kind, created_at)
                   VALUES (?, ?, 'hi', 'message', ?)""",
                (ws, ref, now()),
            )

    key = hermes_channel.bridge_key(core, ws)

    def ask(body: dict[str, Any]) -> dict[str, Any]:
        got = client.post(
            f"/hermes-bridge/{ws}/platform-next",
            json=body,
            headers={"authorization": f"Bearer {key}"},
        )
        assert got.status_code == 200, got.text
        found: dict[str, Any] = got.json()
        return found

    queue(f"agos:{chat}")
    queue(f"agos:{chat}.writer")
    got = ask({"members": ["", "writer"]})
    assert got["members"] == ["", "writer"]
    assert sorted((i["chat"], i["member"]) for i in got["items"]) == [
        (f"agos:{chat}", ""),
        (f"agos:{chat}.writer", "writer"),
    ]
    # An older plugin's own ask: only its member's, answered as before.
    queue(f"agos:{chat}")
    queue(f"agos:{chat}.writer")
    old = ask({"member": "writer"})
    assert "members" not in old
    assert [(i["chat"], "member" in i) for i in old["items"]] == [(f"agos:{chat}.writer", False)]
