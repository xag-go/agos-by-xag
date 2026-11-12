"""The Co-Founder can do anything the owner does in AGOS (owner rule 2026-10-28): every
server action of the web app maps to a Co-Founder action or tool, a read, or an
owner-only exception with its reason (engine/cofounder_parity/). A new web action
with none of these fails here, by name."""

import re
from pathlib import Path

from agos_core.actions import cofounder_more
from agos_core.engine import cofounder_actions as rules
from agos_core.engine import cofounder_parity as parity

REPO = Path(__file__).resolve().parents[3]
FEATURES = REPO / "apps" / "web" / "src" / "features"
PLUGIN = Path(rules.__file__).resolve().parents[1] / "hermes_plugin" / "agos_guard"
_EXPORT = re.compile(r"^export\s+async\s+function\s+([A-Za-z0-9_]+)", re.M)
_ARROW = re.compile(r"^export\s+const\s+([A-Za-z0-9_]+)\s*=\s*async\b", re.M)


def web_actions() -> dict[str, str]:
    """Every exported async function of features/**/(actions|*-actions).ts -> its file."""
    found: dict[str, str] = {}
    for path in sorted(FEATURES.rglob("*.ts")):
        if path.name != "actions.ts" and not path.name.endswith("-actions.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        for name in [*_EXPORT.findall(text), *_ARROW.findall(text)]:
            found.setdefault(name, str(path.relative_to(REPO)))
    return found


def test_the_web_actions_are_found() -> None:
    found = web_actions()
    assert len(found) > 200, len(found)
    for name in ("savePipelineRule", "createLabel", "linkTelegramAccount", "readSkillTests"):
        assert name in found


def test_every_web_action_has_a_cofounder_way_a_read_or_an_owner_only_reason() -> None:
    unknown = [
        f"{name} ({where})"
        for name, where in web_actions().items()
        if name not in parity.DO and name not in parity.READS and name not in parity.OWNER_ONLY
    ]
    assert not unknown, (
        "These web server actions have no Co-Founder counterpart: add an agos_action kind "
        "(engine/cofounder_parity/ KINDS + actions/cofounder_more.py) and map it in "
        "cofounder_parity.DO, or list it in READS (it changes nothing) or OWNER_ONLY "
        "(with the reason): " + ", ".join(unknown)
    )


def test_each_web_action_is_in_one_table_only_and_every_entry_is_a_real_one() -> None:
    tables = {
        "DO": set(parity.DO),
        "READS": set(parity.READS),
        "OWNER_ONLY": set(parity.OWNER_ONLY),
    }
    names = list(tables)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            both = tables[a] & tables[b]
            assert not both, f"in both {a} and {b}: {sorted(both)}"
    web = set(web_actions())
    stale = sorted(n for t in tables.values() for n in t if n not in web)
    assert not stale, f"no such web server action any more (drop it from the table): {stale}"
    assert all(reason.strip() for reason in parity.OWNER_ONLY.values())


def _plugin_tools() -> set[str]:
    names: set[str] = set()
    for path in PLUGIN.glob("*.py"):
        names |= set(re.findall(r'"name":\s*"(agos_[a-z_]+)"', path.read_text(encoding="utf-8")))
    return names


def _hermes_tools() -> set[str] | None:
    source = Path.home() / ".hermes" / "hermes-agent" / "toolsets.py"
    if not source.is_file():
        return None
    return set(re.findall(r'"([a-z_]+)"', source.read_text(encoding="utf-8")))


def test_every_mapped_way_exists() -> None:
    tools = _plugin_tools()
    hermes = _hermes_tools()
    assert {"agos_action", "agos_capability", "agos_goals", "agos_label"} <= tools
    for web, way in parity.DO.items():
        kind, _, name = way.partition(":")
        if kind == "do":
            assert name in rules.ACTIONS, f"{web}: no agos_action kind {name}"
        elif kind == "tool":
            assert name in tools, f"{web}: no AGOS tool {name}"
        else:
            assert kind == "hermes", f"{web}: {way}"
            if hermes is not None:
                assert name in hermes, f"{web}: Hermes has no tool {name}"


def test_every_new_kind_runs_its_page_code_and_its_gate_matches_its_undo() -> None:
    assert set(parity.KINDS) == set(cofounder_more.DOES), set(parity.KINDS) ^ set(
        cofounder_more.DOES
    )
    for name, kind in parity.KINDS.items():
        # the base kinds (domain chat) are taught by the always-on prompt, not the skill
        assert kind.domain in (*parity.DOMAINS, "chat"), name
        if kind.gate == "undo":
            assert name in cofounder_more.UNDOES, f"{name} says Undo but has none"
        if kind.gate == "once":
            assert name not in cofounder_more.UNDOES, f"{name} is once but has an Undo"
        assert rules.title_of(rules.Action(name, {k: "x" for k in kind.required}))
    # The table the Undo button reads has them all.
    from agos_core.actions import cofounder_actions

    assert set(cofounder_more.UNDOES) <= cofounder_actions._UNDO


def test_the_prompt_names_each_domain_and_the_skill_holds_every_kind() -> None:
    prompt = rules.instructions([], True, [], [])
    assert "cofounder-actions (skill_view it" in prompt
    for domain in parity.DOMAINS:
        assert f"- {domain}: " in prompt
    text = parity.skill_text()
    assert text.startswith("---\nname: cofounder-actions\n")
    for name, kind in parity.KINDS.items():
        if kind.domain != "chat":
            assert f"- {name} (" in text, name
    # The per-kind fields stay out of the always-on prompt.
    assert "save_skill_test_settings" not in prompt


def test_risky_kinds_wait_for_the_owner() -> None:
    for name in (
        "import_bundle",
        "install_template",
        "run_updates",
        "approve_person",
        "remove_person",
        "delete_library_item",
        "delete_doc",
        "remove_tool_key",
        "set_rhythm",
        "save_vision_notes",
    ):
        action = rules._clean({"do": name, **{k: "x" for k in parity.KINDS[name].required}})
        assert action is not None and rules.needs_owner(action), name
    archive = rules._clean({"do": "card_action", "card": "t_1", "action": "archive"})
    done = rules._clean({"do": "card_action", "card": "t_1", "action": "done"})
    assert archive is not None and rules.needs_owner(archive)
    assert done is not None and not rules.needs_owner(done)
    label = rules._clean({"do": "create_label", "name": "urgent"})
    assert label is not None and not rules.needs_owner(label)


def test_structured_fields_are_read_only_where_the_kind_takes_them() -> None:
    ok = {"do": "create_group", "title": "Ops", "members": ["writer", "editor"]}
    assert rules.unreadable(ok) == []
    action = rules._clean(ok)
    assert action is not None and action.fields["members"] == ["writer", "editor"]
    assert rules.unreadable({"do": "create_label", "name": "x", "members": ["a"]}) == ["members"]
