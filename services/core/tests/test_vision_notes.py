"""Step 60: the owner's Vision notes and Organize.

- The notes are a revised document in the workspace folder (vision/notes.md, each save
  a revision with its CHANGES.md line); the same text again is no new revision.
- Organize runs the Co-Founder once through Hermes (`hermes chat -Q -q` in the root,
  no model override, the todo toolset only) with the notes, the plan and the team;
  its JSON answer fills a preview (nothing saved) and its goals become goal
  proposals in the Inbox, once per notes revision (agos-vision-notes:<rev>:<n>).
- Without a Vision the goals wait and are proposed when the owner saves his Vision;
  approving one makes the goal with its key results and projects.
- A bad answer or a failed run is a plain error; workspaces stay apart.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import pytest
from test_automations import env  # noqa: F401 - fixture
from test_team_hierarchy import _agent

from agos_core.actions import goals, proposals, vision_notes
from agos_core.actions.services.channel import owner_needs
from agos_core.engine.hermes import EngineError

ANSWER = {
    "vision": "Become the go-to argan oil brand for Moroccan women online",
    "why": "I started because the oil my mother made never reached buyers.",
    "strategy": ["Sell direct on Instagram", "Partner with 3 cooperatives"],
    "goals": [
        {
            "title": "Grow the Instagram audience",
            "why": "Buyers find us there.",
            "key_results": [
                {
                    "title": "Followers",
                    "target": "10,000",
                    "unit": "followers",
                    "due_on": "2027-06-30",
                },
                {"title": "Bad date", "target": 5, "unit": "posts", "due_on": "next year"},
            ],
            "projects": [{"title": "Daily reels"}, "Weekly live"],
        },
        {
            "title": "Sign the cooperatives",
            "why": "Steady supply.",
            "key_results": [],
            "projects": [],
        },
    ],
}


class Chat:
    """Hermes's one-shot query in the fake runner: records each run, answers `said`."""

    def __init__(self, core: Any) -> None:
        self.runs: list[list[str]] = []
        self.said: str | Exception = json.dumps(ANSWER)
        self._run = core.engine.runner.run
        core.engine.runner.run = self.run

    def run(self, args: Sequence[str], *, timeout: float, **kw: Any) -> str:
        argv = list(args)
        if "chat" in argv and "-q" in argv:
            self.runs.append(argv)
            if isinstance(self.said, Exception):
                raise self.said
            return self.said
        return str(self._run(args, timeout=timeout, **kw))


@pytest.fixture
def space(env: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, str, Chat]:  # noqa: F811
    client, core, _cron, ws = env
    _agent(client, ws, "editor")
    monkeypatch.setattr(owner_needs, "push", lambda *a, **k: 1)
    return client, core, ws, Chat(core)


def _notes(client: Any, ws: str, text: str) -> dict[str, Any]:
    r = client.put(f"/workspaces/{ws}/vision/notes", json={"text": text})
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_notes_are_saved_with_revisions_in_the_workspace_folder(space: Any) -> None:
    client, core, ws, _chat = space
    assert client.get(f"/workspaces/{ws}/vision/notes").json() == {
        "text": "",
        "revision": 0,
        "updatedAt": None,
        "revisions": [],
    }
    first = _notes(client, ws, "bghit ndir brand dyal argan\n10k followers f 6 mois")
    assert first["revision"] == 1
    again = _notes(client, ws, "bghit ndir brand dyal argan\n10k followers f 6 mois  ")
    assert again["revision"] == 1  # the same text: no new revision
    second = _notes(client, ws, "bghit ndir brand dyal argan\n20k followers")
    assert second["revision"] == 2 and [r["n"] for r in second["revisions"]] == [2, 1]
    assert second["revisions"][0]["who"] == "the owner"
    page = client.get(f"/workspaces/{ws}/vision").json()  # the page's one read has them
    assert page["notes"]["text"] == second["text"] and page["notes"]["revision"] == 2
    folder = vision_notes._folder(core, ws)
    assert (folder / "notes.md").read_text() == "bghit ndir brand dyal argan\n20k followers\n"
    assert (folder / ".revisions" / "notes" / "v1.md").read_text().endswith("6 mois\n")
    old = client.get(f"/workspaces/{ws}/vision/notes/revisions/2").json()
    assert "-10k followers f 6 mois" in old["diff"] and "+20k followers" in old["diff"]
    assert client.get(f"/workspaces/{ws}/vision/notes/revisions/9").status_code == 404
    r = client.put(f"/workspaces/{ws}/vision/notes", json={"text": "x" * 30_001})
    assert r.status_code == 422


def test_organize_fills_the_preview_and_proposes_each_goal_once(space: Any) -> None:
    client, core, ws, chat = space
    goals.set_vision(core, ws, title="Old vision", why="Old why", strategy="Old strategy")
    _notes(client, ws, "bghit nkon brand lwla dyal argan, 10k followers 9bel juin")
    r = client.post(f"/workspaces/{ws}/vision/notes/organize")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["vision"] == ANSWER["vision"]
    assert got["strategy"] == "- Sell direct on Instagram\n- Partner with 3 cooperatives"
    assert got["proposed"] == 2 and got["already"] == 0 and got["waiting"] == 0
    [first, _second] = got["goals"]
    assert first["keyResults"][0] == {
        "title": "Followers",
        "target": 10000,
        "unit": "followers",
        "dueOn": "2027-06-30",
    }
    assert first["keyResults"][1]["dueOn"] == ""  # not a date: left for the owner
    assert [p["title"] for p in first["projects"]] == ["Daily reels", "Weekly live"]
    # A preview: the Vision itself did not change.
    vision = goals.top(core, ws)
    assert vision is not None and vision.title == "Old vision" and vision.children == []
    # One Hermes run in the root, the Co-Founder's own model (no override), no tools
    # but the todo list, hidden from the session lists; the prompt carries it all.
    [run] = chat.runs
    assert run[run.index("chat") :][:2] == ["chat", "-Q"]
    assert "-m" not in run and "--model" not in run and "--provider" not in run
    assert run[run.index("-t") + 1] == "todo" and run[run.index("--source") + 1] == "tool"
    text = run[run.index("-q") + 1]
    assert "bghit nkon brand" in text and "Old strategy" in text and "editor" in text
    assert "in clear, simple English" in text and "(revision 1)" in text
    # The goals wait in the Inbox, one proposal each, with their key results.
    shown = proposals.waiting(core, ws)
    assert sorted(s["label"] for s in shown) == [
        "Add the goal: Grow the Instagram audience",
        "Add the goal: Sign the cooperatives",
    ]
    keys = sorted(s["payload"]["notes_key"] for s in shown)
    assert keys == ["agos-vision-notes:1:1", "agos-vision-notes:1:2"]
    cards = core.engine.runner.kanban[core.engine.profile(ws)]
    assert sorted(str(c.get("key")) for c in cards.values()) == keys  # Hermes's own dedup too
    # Organize again on the same notes: nothing new in the Inbox.
    again = client.post(f"/workspaces/{ws}/vision/notes/organize").json()
    assert again["proposed"] == 0 and again["already"] == 2
    assert len(proposals.waiting(core, ws)) == 2
    # Approve: the goal comes with its key results and projects.
    grow = next(s for s in shown if s["payload"]["notes_key"].endswith(":1"))
    r = client.post(f"/workspaces/{ws}/proposals/{grow['id']}", json={"choice": "approve"})
    assert r.status_code == 200, r.text
    vision = goals.top(core, ws)
    assert vision is not None
    [goal] = vision.children
    assert goal.title == "Grow the Instagram audience" and goal.why == "Buyers find us there."
    assert [(k.title, k.target, k.unit) for k in goal.results] == [
        ("Followers", 10000, "followers"),
        ("Bad date", 5, "posts"),
    ]
    assert [p.title for p in goal.children] == ["Daily reels", "Weekly live"]


def test_the_owner_edits_the_key_results_before_approving(space: Any) -> None:
    client, core, ws, chat = space
    goals.set_vision(core, ws, title="Grow")
    chat.said = json.dumps({**ANSWER, "goals": ANSWER["goals"][:1]})
    _notes(client, ws, "notes")
    client.post(f"/workspaces/{ws}/vision/notes/organize")
    [shown] = proposals.waiting(core, ws)
    r = client.post(
        f"/workspaces/{ws}/proposals/{shown['id']}",
        json={
            "choice": "approve",
            "payload": {
                "key_results": [{"title": "Followers", "target": 20000, "unit": "followers"}],
                "projects": [],
            },
        },
    )
    assert r.status_code == 200, r.text
    [goal] = goals.top(core, ws).children  # type: ignore[union-attr]
    assert [(k.title, k.target) for k in goal.results] == [("Followers", 20000)]
    assert goal.children == []


def test_without_a_vision_the_goals_wait_for_the_first_save(space: Any) -> None:
    client, core, ws, _chat = space
    _notes(client, ws, "bghit ndir argan brand")
    got = client.post(f"/workspaces/{ws}/vision/notes/organize").json()
    assert got["proposed"] == 0 and got["waiting"] == 2
    assert goals.top(core, ws) is None and proposals.waiting(core, ws) == []
    r = client.put(
        f"/workspaces/{ws}/vision",
        json={"title": got["vision"], "why": got["why"], "strategy": got["strategy"]},
    )
    assert r.status_code == 200, r.text
    assert len(proposals.waiting(core, ws)) == 2
    client.put(f"/workspaces/{ws}/vision", json={"title": "Edited"})
    assert len(proposals.waiting(core, ws)) == 2  # once


def test_a_bad_answer_or_a_failed_run_is_a_plain_error(space: Any) -> None:
    client, core, ws, chat = space
    url = f"/workspaces/{ws}/vision/notes/organize"
    r = client.post(url)
    assert r.status_code == 400 and "Write your notes first" in r.text
    assert chat.runs == []
    _notes(client, ws, "notes")
    chat.said = "Sure! Here is my plan: grow."
    r = client.post(url)
    assert r.status_code == 502 and "couldn't be read" in r.text
    chat.said = '```json\n{"vision": "", "why": "x"}\n```'
    assert client.post(url).status_code == 502
    chat.said = EngineError("hermes did not answer")
    r = client.post(url)
    assert r.status_code == 502 and "didn't answer in time" in r.text
    # Prose around a fenced answer is fine.
    chat.said = "Here it is:\n```json\n" + json.dumps({**ANSWER, "goals": []}) + "\n```\n"
    r = client.post(url)
    assert r.status_code == 200 and r.json()["vision"] == ANSWER["vision"]
    assert goals.top(core, ws) is None


def test_each_workspace_has_its_own_notes(space: Any) -> None:
    client, core, ws, chat = space
    other = client.post(
        "/workspaces",
        json={
            "name": "Other",
            "defaultModel": {"provider": "claude", "mode": "cli", "model": "m", "effort": "high"},
        },
    ).json()["id"]
    goals.set_vision(core, ws, title="Mine")
    _notes(client, ws, "my secret plan")
    assert client.get(f"/workspaces/{other}/vision/notes").json()["text"] == ""
    assert client.get(f"/workspaces/{other}/vision/notes/revisions/1").status_code == 404
    r = client.post(f"/workspaces/{other}/vision/notes/organize")
    assert r.status_code == 400 and chat.runs == []
    client.post(f"/workspaces/{ws}/vision/notes/organize")
    assert proposals.waiting(core, other) == []
    assert client.get("/workspaces/nope/vision/notes").status_code == 404
