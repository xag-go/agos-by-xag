"""GET /docs lists the workspace's documentation and checks it: the team's
profiles and the docs folder are read once for both (each read walks the folder
or reads every member's profile)."""

from __future__ import annotations

from typing import Any

import pytest
from test_library import env, ws  # noqa: F401 - fixture


def test_the_docs_page_reads_the_team_and_the_files_once(
    env: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _core, _runner, _home = env
    from agos_core.actions import docs as docs_actions
    from agos_core.actions import team

    a = ws(client, "Alpha")
    reads: list[str] = []
    members, walk = team.members, docs_actions.all_docs

    def counted_members(*args: Any, **kw: Any) -> Any:
        reads.append("team")
        return members(*args, **kw)

    def counted_walk(*args: Any, **kw: Any) -> Any:
        reads.append("docs")
        return walk(*args, **kw)

    monkeypatch.setattr(team, "members", counted_members)
    monkeypatch.setattr(docs_actions, "all_docs", counted_walk)
    shown = client.get(f"/workspaces/{a}/docs")
    assert shown.status_code == 200 and shown.json()["files"]
    assert sorted(reads) == ["docs", "team"]
