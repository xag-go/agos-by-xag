"""The owner's rules reach every workspace (and only rules about him)."""

from typing import Any

from test_automations import env  # noqa: F401 - fixture
from test_cofounder_actions import _run

from agos_core.actions import cofounder_actions, owner_rules
from agos_core.engine import cofounder_actions as rules
from agos_core.engine import identity


def user_md(core: Any, ws: str) -> str:
    path = core.engine.profile_home(ws) / "memories" / "USER.md"
    return path.read_text() if path.is_file() else ""


def _section(client: Any, core: Any, ws: str) -> str:
    """What the agos-guard plugin's system-prompt section gets for this workspace."""
    import json

    bridge = json.loads((core.engine.profile_home(ws) / "agos-bridge.json").read_text())
    r = client.post(
        f"/hermes-bridge/{ws}/owner-rules",
        json={},
        headers={"authorization": f"Bearer {bridge['key']}"},
    )
    assert r.status_code == 200, r.text
    return str(r.json()["text"])


def test_a_rule_reaches_every_workspace_through_the_plugin_section(env: Any) -> None:  # noqa: F811
    """His rules are one plugin system-prompt section (Hermes's
    register_system_prompt_section), not copies in every USER.md: an old copy is
    taken out, what Hermes learned about him there stays."""
    client, core, _cron, ws = env
    other = client.post(
        "/workspaces",
        json={
            "name": "Second",
            "defaultModel": client.get(f"/workspaces/{ws}").json()["defaultModel"],
        },
    ).json()["id"]
    # An old copy (before step 27) next to what Hermes learned about him there.
    learned = core.engine.profile_home(ws) / "memories" / "USER.md"
    learned.parent.mkdir(parents=True, exist_ok=True)
    learned.write_text(
        owner_rules.MARK + "Old copy." + owner_rules.ENTRY_DELIMITER + "Owner likes short reports."
    )
    r = client.post("/owner-rules", json={"text": "Talk to me in Darija, Latin letters."})
    assert r.status_code == 201
    rid = r.json()["id"]
    for w in (ws, other):
        assert "Talk to me in Darija, Latin letters." in _section(client, core, w)
        assert owner_rules.MARK not in user_md(core, w)  # no copy any more
        assert "Latin letters." not in (core.engine.profile_home(w) / "SOUL.md").read_text()
    assert user_md(core, ws) == "Owner likes short reports."
    assert "short reports" not in user_md(core, other)
    # The same rule twice is one rule.
    assert (
        client.post("/owner-rules", json={"text": "talk to me in darija, latin letters."}).json()[
            "id"
        ]
        == rid
    )
    # They live in Hermes: the shared home's USER.md, no table of AGOS's.
    shared = core.engine.settings.hermes_home / "memories" / "USER.md"
    assert owner_rules.MARK + "Talk to me in Darija, Latin letters." in shared.read_text()
    assert client.put(f"/owner-rules/{rid}", json={"text": "Darija only."}).status_code == 204
    [rule] = client.get("/owner-rules").json()
    assert rule["text"] == "Darija only."
    rid = rule["id"]  # an id is its text's
    assert "Darija only." in _section(client, core, other)
    assert client.delete(f"/owner-rules/{rid}").status_code == 204
    assert _section(client, core, other) == ""
    assert user_md(core, ws) == "Owner likes short reports."


def _parts(client: Any, core: Any, ws: str) -> list[str]:
    import json

    bridge = json.loads((core.engine.profile_home(ws) / "agos-bridge.json").read_text())
    r = client.post(
        f"/hermes-bridge/{ws}/owner-rules",
        json={},
        headers={"authorization": f"Bearer {bridge['key']}"},
    )
    return [str(p) for p in r.json()["parts"]]


def _rendered(parts: list[str]) -> int:
    """Hermes's own count for the sections' block (H: hermes_cli/plugins_dispatch.py
    render_system_prompt_sections / format_system_prompt_section)."""
    start, end = "<!-- hermes-plugin-sections:start -->", "<!-- hermes-plugin-sections:end -->"
    total = len(start) + len(end) + 2
    for n, (sid, text) in enumerate(zip(owner_rules.SECTION_IDS, parts, strict=False)):
        block = (
            f"## Plugin Context: {sid}\n<!-- hermes-plugin-section-chars:{len(text)} -->\n\n{text}"
        )
        total += len(block) + (2 if n else 0)
    return total


def test_rules_over_one_section_are_split_into_the_plugins_sections(env: Any) -> None:  # noqa: F811
    """#43: Hermes caps one plugin section at 4,000 characters but all of them at
    8,000 (H: hermes_cli/plugins_dispatch.py MAX_SYSTEM_PROMPT_SECTION_CHARS,
    MAX_SYSTEM_PROMPT_SECTIONS_TOTAL_CHARS): rules up to about 8,000 go into the
    plugin's two sections, none into USER.md."""
    client, core, _cron, ws = env
    long_rules = [f"Rule {i}: " + "x" * 300 for i in range(14)]  # ~4,400 chars
    parts = owner_rules.section_parts(long_rules)
    assert len(parts) == 2 and all(len(p) <= owner_rules.SECTION_MAX for p in parts)
    assert _rendered(parts) <= owner_rules.TOTAL_MAX
    joined = "\n".join(parts)
    assert all(r in joined for r in long_rules)
    assert owner_rules.in_user_md(long_rules) == []
    for text in long_rules:
        assert client.post("/owner-rules", json={"text": text}).status_code == 201
    assert _parts(client, core, ws) == parts
    assert _section(client, core, ws) == parts[0]
    assert owner_rules.MARK not in user_md(core, ws)


def test_rules_beyond_hermess_total_stay_in_every_user_md(env: Any) -> None:  # noqa: F811
    """Over Hermes's 8,000 total (or one rule longer than a section): the sections
    stay empty and his rules are written into every USER.md, so none is lost."""
    client, core, _cron, ws = env
    long_rules = [f"Rule {i}: " + "x" * 300 for i in range(26)]  # ~8,200 chars
    assert owner_rules.section_parts(long_rules) == []
    assert owner_rules.section_parts(["y" * 4_100]) == []
    assert owner_rules.in_user_md(long_rules) == long_rules
    for text in long_rules:
        assert client.post("/owner-rules", json={"text": text}).status_code == 201
    assert _section(client, core, ws) == "" and _parts(client, core, ws) == []
    assert owner_rules.MARK + long_rules[-1] in user_md(core, ws)


def test_the_plugin_registers_one_section_per_part() -> None:
    from agos_core.hermes_plugin.agos_guard import bridge

    assert tuple(bridge.OWNER_RULES_SECTIONS) == owner_rules.SECTION_IDS
    assert len(owner_rules.SECTION_IDS) == 2
    bridge._owner_rules.clear()
    bridge._owner_rules["parts"] = ["one", "two"]
    assert bridge.owner_rules_part(1)() == "two"


def test_the_cofounder_proposes_one_and_it_waits_for_the_owner(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    from agos_core.actions import hermes_channel

    assert "add_owner_rule" in cofounder_actions.instructions(core, ws)
    item = {
        "do": "add_owner_rule",
        "text": "Never ask me about small things.",
        "why": "he said dima",
    }
    # Even in direct mode Hermes asks him first (its Allow / Deny before the tool runs).
    assert hermes_channel.tool_check(core, "agos_action", {"actions": [item]})["ask"] is True
    assert owner_rules.list_rules(core) == []
    [card] = _run(core, ws, item)  # he said Allow
    assert card["status"] == "done"
    assert [r["text"] for r in owner_rules.list_rules(core)] == ["Never ask me about small things."]
    assert owner_rules.list_rules(core)[0]["fromWorkspace"] == ws
    # Edited after: its id (its text's) changed, the Undo still finds it.
    owner_rules.edit(core, owner_rules.list_rules(core)[0]["id"], "Never ask me small things.")
    cofounder_actions.decide(core, ws, card["id"], "undo")
    assert owner_rules.list_rules(core) == []


def test_soul_without_rules_is_unchanged() -> None:
    assert identity.soul_text("A", "b", "") == identity.soul_text("A", "b", "", "")
    assert rules.ACTIONS["add_owner_rule"] == ("text",)
