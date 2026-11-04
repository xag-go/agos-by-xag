"""The team speaks to the owner like people, in the language he uses with them."""

import re

from agos_core.actions import voice


def test_language_of_the_owner() -> None:
    assert voice.classify(["علاش وقفات task 56", "واش سالات"]) == "ar"
    assert voice.classify(["chouf 3lach mab9ach kaykhdem", "dir liya task jdida"]) == "darija"
    assert voice.classify(["Please check the invoices", "Looks good, ship it"]) == "en"
    assert voice.classify(["👍", "56"]) is None


def test_lines_sound_like_a_person() -> None:
    ask = voice.say("chat_command", "darija", who="Script Writer", command="pip install x", why="")
    assert ask == (
        "Bach njawbek khassni nkhdem had l-command:\n\npip install x\n\nN9der?\n— Script Writer"
    )
    # The Co-Founder speaks in his own chat: no signature, no "Co-Founder here:" header.
    ref = "t_7 “Hook script”"
    heads_up = voice.say("tokens", "en", who="Co-Founder", task=ref, used="9M", usual="1M")
    assert ref in heads_up and "Co-Founder" not in heads_up and "here:" not in heads_up
    # The same message always reads the same (no flicker between two sends).
    assert heads_up == voice.say("tokens", "en", who="Co-Founder", task=ref, used="9M", usual="1M")
    # Every line exists in every language, and never opens with a robotic header.
    for key, lines in voice._T.items():
        assert set(lines) == {"en", "darija", "ar"}, key
        for options in lines.values():
            for text in options:
                assert not re.match(r"^\W*\w+ (here|hna|هنا):", text), text
