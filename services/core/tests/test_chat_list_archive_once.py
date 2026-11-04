"""A list of chats reads Hermes's archive (which chats the owner deleted, Hermes's
sessions.archived) once per list, not once per row: the SQL function agos_hidden
runs per row, and each read stats every profile's state.db."""

from __future__ import annotations

from typing import Any

import pytest
from test_library import env, ws  # noqa: F401 - fixture


def test_a_chat_list_reads_hermes_archive_once_not_per_row(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, core, _runner, _home = env
    a = ws(client, "Alpha")
    from agos_core.actions.services.chat import view as chat_view
    from agos_core.db import chats as repo
    from agos_core.db import hermes_chats as hc

    for i in range(20):
        repo.insert_chat(
            core.db, workspace_id=a, title=f"c{i}", channel="web", kind="chat", agent=None
        )
    store = hc.store()
    assert store is not None
    calls: list[str] = []
    real = store.archive_states

    def counted(workspace_id: str) -> Any:
        calls.append(workspace_id)
        return real(workspace_id)

    monkeypatch.setattr(store, "archive_states", counted)
    assert len(chat_view.list_chats(core.db, a, ("chat",))) >= 20
    assert calls == [a]
    # The next list reads it again (a chat Hermes archived since is hidden at once).
    chat_view.list_chats(core.db, a, ("chat",))
    assert calls == [a, a]
