"""The owner's "Suggest hires" (Hierarchy): one Hermes Kanban card on the Co-Founder
asking for the hires the team needs, each its own proposal; the owner's note on the
card word for word; while one is open a second ask returns it (read from Hermes's
board, no AGOS copy); once it is closed a new ask makes a new card."""

from __future__ import annotations

from work_env import Env, env, fake_board, kanban_of  # noqa: F401  (fixtures)

from agos_core.actions import hire_suggestions


def test_suggest_hires_hands_the_cofounder_one_card(env: Env, fake_board: None) -> None:  # noqa: F811
    client, _fake, core, ws = env
    url = f"/workspaces/{ws}/team/suggest-hires"
    assert client.get(url).json() == {"card": None, "created": False}
    note = "We post too little on TikTok.\nAnd nobody edits the videos." + " more" * 400
    r = client.post(url, json={"note": note})
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["created"] is True and first["card"]
    card = kanban_of(core, ws)[first["card"]]
    # On the Co-Founder (the workspace's own profile), by Hermes's Kanban.
    assert card["assignee"] == core.engine.hermes_name(ws)
    assert card["title"].startswith("Suggest hires: We post too little on TikTok. And nobody")
    body = str(card["body"])
    assert note in body  # word for word, no limit
    for words in (
        "team-design skill",
        "OWN proposal with agos_propose",
        'kind "hire"',
        "goal_id",
        "source_card",
        "one by one",
        "If no hire is needed",
        "one-paragraph summary",
    ):
        assert words in body, words
    assert str(card["key"]).startswith(hire_suggestions.KEY)
    # A second click while it is open: the same card, nothing new.
    again = client.post(url, json={"note": "something else"}).json()
    assert again == {"card": first["card"], "created": False}
    assert len(kanban_of(core, ws)) == 1
    assert client.get(url).json()["card"] == first["card"]
    # Closed on the board: a new ask makes a new card (no note: the bare title).
    card["status"] = "done"
    assert client.get(url).json()["card"] is None
    third = client.post(url, json={}).json()
    assert third["created"] is True and third["card"] != first["card"]
    made = kanban_of(core, ws)[third["card"]]
    assert made["title"] == "Suggest hires"
    assert "The owner's note" not in str(made["body"])
    card["status"] = "archived"
    assert client.get(url).json()["card"] == third["card"]


def test_suggest_hires_needs_a_real_workspace(env: Env) -> None:  # noqa: F811
    client, _fake, _core, _ws = env
    assert client.post("/workspaces/nope/team/suggest-hires", json={}).status_code == 404
    assert client.get("/workspaces/nope/team/suggest-hires").status_code == 404
