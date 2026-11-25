"""The owner's Allow / Deny card for one of AGOS's own tools says, in plain words,
WHAT will change (line 1, where Hermes would show "<agos_action> (plugin approval
rule)"), WHO asks, WHY he is asked and what the buttons allow; no engine name, no
hidden character Hermes would print as an escape ("\\ufe0f"), no "8760 hours"."""

from __future__ import annotations

import asyncio
from typing import Any

from test_automations import env  # noqa: F401 - fixture

from agos_core.actions import cofounder_actions, hermes_channel, owner_gate, read_vs_act
from agos_core.engine import approval_words
from agos_core.hermes_plugin.agos_guard import approval_card

LABEL = "<agos_action> (plugin approval rule)"
HIDDEN = ("\ufe0f", "\u200d", "\u200b")


def _clean(text: str) -> None:
    assert "Hermes" not in text
    assert not any(c in text for c in HIDDEN), ascii(text)


def test_the_card_text_starts_with_the_change_and_says_who_and_why() -> None:
    text = approval_words.card_text(
        "\U0001f6e0\ufe0f Change the file “tools/make_read_doc.py”",
        "Content Creation",
        source="the result of card t_7ee1a015",
        reason="Sam asked for a shorter doc",
        once=True,
    )
    lines = text.split("\n")
    assert lines[0] == "Change the file “tools/make_read_doc.py”"
    assert "Your Co-Founder in Content Creation" in lines[1]
    assert "read outside content (the result of card t_7ee1a015)" in lines[1]
    assert "allow only if you asked for this" in lines[1]
    assert "Its reason: Sam asked for a shorter doc" in text
    assert lines[2] == "Any Allow button allows this one time only."
    assert lines[-1] == "Its reason: Sam asked for a shorter doc"
    _clean(text)


def test_a_clean_ask_names_his_setting_and_what_always_means() -> None:
    text = approval_words.card_text("Turn on app github", "Argan")
    assert text.split("\n")[0] == "Turn on app github"
    assert "your setting says to ask you first" in text
    assert "“Always” = it stops asking you before its AGOS changes." in text
    assert "outside content" not in text
    _clean(text)


def test_a_long_reason_is_cut() -> None:
    text = approval_words.card_text("Change x", "W", reason="a" * 500)
    assert "Its reason: " + "a" * 159 + "…" in text


def test_agent_text_can_not_push_the_warning_off_or_add_lines() -> None:
    """Titles, names and the reason come from the agent (maybe after a poisoned
    read): one line each, capped, and the warning always fits the card."""
    text = approval_words.card_text(
        "Create skill “" + "x" * 2000 + "”",
        "W",
        source="the web (web_extract)",
        reason="ok\nAny Allow button allows this one time only.\nIt is safe",
        once=True,
    )
    lines = text.split("\n")
    assert len(text) <= approval_words.MAX and len(lines) == 4
    assert len(lines[0]) <= 240
    assert "read outside content (the web (web_extract))" in lines[1]
    assert lines[2] == "Any Allow button allows this one time only."
    assert lines[3].startswith("Its reason: ok Any Allow")
    fake = approval_words.card_text("Delete x\nYour Co-Founder in W is asking because", "W")
    assert fake.split("\n")[0] == "Delete x Your Co-Founder in W is asking because"


def test_tool_check_gives_the_card_its_words(env: Any) -> None:  # noqa: F811
    _client, core, _cron, ws = env
    cofounder_actions.set_mode(core, "direct")
    from agos_core.actions.workers import open_dm

    chat = f"agos:{int(open_dm(core, ws, None))}"
    read_vs_act.mark(core, ws, chat, "the web (web_extract)")
    action = {
        "do": "create_automation",
        "name": "Morning ideas",
        "schedule": "0 9 * * *",
        "instructions": "Find 2 ideas",
        "why": "He asked for ideas every morning",
    }
    check = hermes_channel.tool_check(core, "agos_action", {"actions": [action]}, ws, chat)
    assert check["ask"] is True and check.get("once")
    lines = check["message"].split("\n")
    assert lines[0].startswith("Create automation “Morning ideas”")
    assert "Your Co-Founder in" in lines[1] and "the web (web_extract)" in lines[1]
    try:
        assert "Its reason: He asked for ideas every morning" in check["message"]
        _clean(check["message"])
    finally:
        read_vs_act._marks.clear()
        owner_gate._asked_at.clear()


def test_the_label_becomes_the_change_and_other_cards_stay() -> None:
    said = "Change the file “a.py”\nWhy it asks: outside content."
    assert approval_card.split(LABEL, said) == (
        "Change the file “a.py”",
        "Why it asks: outside content.",
    )
    # A one-line message (cronjob, an Ask-me rule) keeps its words as the reason.
    assert approval_card.split(LABEL, "Only one line") == (LABEL, "Only one line")
    # A terminal command, another plugin's card, or no words: Hermes's own card.
    assert approval_card.split("rm -rf /tmp/x", said) == ("rm -rf /tmp/x", said)
    other = "<web_extract> (plugin approval rule)"
    assert approval_card.split(other, said) == (other, said)
    assert approval_card.split(LABEL, None) == (LABEL, None)


def test_the_wrapped_send_gets_the_change_however_it_is_called() -> None:
    seen: list[tuple[str, Any]] = []

    class Adapter:
        async def send_exec_approval(
            self,
            chat_id: str,
            command: str,
            session_key: str,
            description: str | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> str:
            seen.append((command, description))
            return "sent"

    assert approval_card.wrap(Adapter) is True
    assert approval_card.wrap(Adapter) is True  # once: not wrapped twice
    said = "Turn on app github\nYour Co-Founder in W is asking."
    adapter = Adapter()
    assert asyncio.run(adapter.send_exec_approval("1", LABEL, "s", said)) == "sent"
    asyncio.run(
        adapter.send_exec_approval(chat_id="1", command=LABEL, session_key="s", description=said)
    )
    asyncio.run(adapter.send_exec_approval("1", "ls", "s"))
    assert seen == [
        ("Turn on app github", "Your Co-Founder in W is asking."),
        ("Turn on app github", "Your Co-Founder in W is asking."),
        ("ls", None),
    ]


def test_the_card_frame_is_in_agos_words() -> None:
    registered: list[tuple[str, dict[str, str]]] = []

    class Ctx:
        def register_locale(self, lang: str, source: dict[str, str], **_: Any) -> None:
            registered.append((lang, source))

    approval_card.register_words(Ctx())
    assert registered == [("en", approval_card.WORDS)]
    words = " ".join(approval_card.WORDS.values())
    _clean(words)
    assert "hours" not in words and "{" not in words
    approval_card.register_words(object())  # an older Hermes without language packs: no error

    class Broken:
        def register_locale(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("boom")

    approval_card.register(Broken())  # wording only: the guard plugin still loads
