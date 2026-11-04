# ruff: noqa: RUF001  (Darija in Arabic letters is meant)
"""How the team talks to the owner in its notices: like a person, in his language.

Every notice (a task done, stuck, a question, an Approve, a command to allow, a
proposed task / plan, an automation's result) is said by the one it's about, by
name ("Script Writer here: ..."), in the language the owner uses with them in the
chat: Darija in Arabic letters, Darija in Latin letters, or English.

Written right away from templates (no AI call): arrives in seconds, costs nothing.
"""

from __future__ import annotations

import re
import zlib
from typing import Any, Literal

from agos_core.context import Core
from agos_core.db import chat_lines

Lang = Literal["en", "darija", "ar"]

_ARABIC = re.compile(r"[\u0600-\u06FF]")
_LATIN = re.compile(r"[A-Za-z]")
# Darija written in Latin letters: common words and the 3/7/9 letters inside words.
_DARIJA = re.compile(
    r"\b(wach|wash|bghit|bghiti|dyal|dial|khass|khassni|khasso|chno|chnou|3lach|kifach|"
    r"daba|db|dir|chouf|mzyan|wakha|walakin|ila|hna|ana|nta|rah|ghir|kolchi|gua3|bach|"
    r"m3a|mn|men|ma3arf|salit|salat|kayn|kayna|makayn|fhamty|fhamti)\b"
    r"|[a-z][379][a-z]",
    re.IGNORECASE,
)

SAMPLE = 8


def classify(texts: list[str]) -> Lang | None:
    """The language of the owner's own messages (most recent first)."""
    arabic = latin = darija = 0
    for text in texts:
        a, l_ = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
        if a == 0 and l_ == 0:
            continue
        if a >= l_:
            arabic += 1
        else:
            latin += 1
            if _DARIJA.search(text):
                darija += 1
    if arabic == 0 and latin == 0:
        return None
    if arabic > latin:
        return "ar"
    return "darija" if darija * 3 >= latin else "en"


def language(core: Core, workspace_id: str, speaker: str | None) -> Lang:
    """What the owner speaks with `speaker` (None = the Co-Founder); else in the
    workspace; else English."""
    found = classify(chat_lines.owner_words_in_dm(core.db, workspace_id, speaker, SAMPLE))
    if found is None:
        found = classify(chat_lines.owner_words_in_workspace(core.db, workspace_id, SAMPLE))
    return found or "en"


def name_of(core: Core, workspace_id: str, agent: str | None) -> str:
    """The job title the owner gave the agent ("Script Writer"); the Co-Founder."""
    if not agent:
        return "Co-Founder"
    if agent == "AGOS":  # AGOS's own notes in a group (rooms.SPEAKER_AGOS)
        return "AGOS"
    from agos_core.actions import team

    return team.title_of(core, workspace_id, agent)


# ---- the lines -------------------------------------------------------------------
# Written like a colleague texting him: plain words, no "X here:" header, no report
# tone. A few ways to say each thing so the same message doesn't read like a bot.
# Agents sign at the end ("— Script Writer"); the Co-Founder doesn't need to.

_T: dict[str, dict[Lang, list[str]]] = {
    "command_why": {
        "darija": ["\n\nBghitha bach {why}."],
        "ar": ["\n\nباش {why}."],
        "en": ["\n\nIt's to {why}."],
    },
    "tokens": {
        "darija": [
            "3la bal: {task} kat-kol bzaf dyal tokens 🔥 {used} 7tta daba, w 3adatan task hna kat7taj chi {usual}. "
            "Ana mazal khddam, ma w9eftch. Chouf nta: nkmmel wla n7bes?"
        ],
        "ar": [
            "على بال: {task} كتاكل بزاف ديال tokens 🔥 {used} حتى دابا، وعادة task هنا كتحتاج شي {usual}. "
            "أنا مازال خدام، ما وقفتش. شوف نتا: نكمل ولا نحبس؟"
        ],
        "en": [
            "Heads up: {task} is using a lot of tokens 🔥 {used} so far, when a card here usually "
            "takes about {usual}. I'm still working on it. Your call: keep going or stop?"
        ],
    },
    "chat_command": {
        "darija": ["Bach njawbek khassni nkhdem had l-command:\n\n{command}{why}\n\nN9der?"],
        "ar": ["باش نجاوبك خاصني نخدم هاد الكوماند:\n\n{command}{why}\n\nنقدر؟"],
        "en": ["To answer you I need to run this:\n\n{command}{why}\n\nOK with you?"],
    },
}


def say(key: str, lang: Lang, who: str = "Co-Founder", **values: Any) -> str:
    """One of the ways to say it (the same message always gets the same one),
    signed by the agent (the Co-Founder needs no signature: it's his chat)."""
    options = _T[key][lang]
    seed = zlib.crc32(f"{key}|{sorted((k, str(v)) for k, v in values.items())}".encode())
    text = options[seed % len(options)].format(**values)
    if who and who != "Co-Founder" and key not in ("command_why",):
        text += f"\n— {who}"
    return text


def for_cofounder(core: Core, workspace_id: str, key: str, **values: Any) -> str:
    lang = language(core, workspace_id, None)
    return say(key, lang, who="Co-Founder", **values)
