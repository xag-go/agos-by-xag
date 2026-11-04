"""Workspaces are fully isolated: a chat of workspace B is never read or switched through
workspace A, whatever chat id A's call names (workspace-scope scan, lane p2)."""

from typing import Any

import pytest
from test_library import env, ws  # noqa: F401 - fixture

from agos_core.actions import access
from agos_core.actions.errors import NotFoundError
from agos_core.actions.services.chat import view as chat_view


def _chat(client: Any, w: str) -> int:
    r = client.post(f"/workspaces/{w}/chats", json={"title": "Plans"})
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def test_full_access_is_never_switched_on_another_workspaces_chat(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    theirs = _chat(client, b)
    queued = core.db.execute("SELECT count(*) FROM hermes_inbox").fetchone()[0]
    with pytest.raises(NotFoundError):
        access.set_chat(core, a, theirs, True)
    assert core.db.execute("SELECT count(*) FROM hermes_inbox").fetchone()[0] == queued
    # Through the route too (it refused before only because it set the agent first).
    r = client.put(f"/workspaces/{a}/chats/{theirs}", json={"access": "full"})
    assert r.status_code == 404


def test_a_chats_turns_are_read_in_its_own_workspace_only(env: Any) -> None:  # noqa: F811
    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    theirs = _chat(client, b)
    core.db.execute(
        "INSERT INTO chat_turns (chat_id, workspace_id, asked_up_to, status, started_at)"
        " VALUES (?, ?, 0, 'completed', '2026-11-04T00:00:00.000Z')",
        (theirs, b),
    )
    assert chat_view.turns_of(core.db, a, theirs) == []
    assert len(chat_view.turns_of(core.db, b, theirs)) == 1


def test_an_answers_push_names_only_a_chat_of_its_own_workspace(env: Any) -> None:  # noqa: F811
    from agos_core.actions import web_push

    client, core, _runner, _home = env
    a, b = ws(client, "Alpha"), ws(client, "Beta")
    theirs = _chat(client, b)
    sent: list[tuple[str, str]] = []

    def notify(_core: Any, title: str, body: str, **_kw: Any) -> int:
        sent.append((title, body))
        return 1

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(web_push, "notify", notify)
        assert web_push.answered(core, a, theirs, "Done.") == 0  # B's chat title never in A's push
        assert web_push.answered(core, b, theirs, "Done.") == 1
    assert len(sent) == 1 and "Plans" in sent[0][0]
