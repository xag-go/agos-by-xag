"""Keys the owner pastes into his own chat messages, masked by Hermes's own masking
before AGOS keeps the message anywhere or hands it to Hermes (ADR 0023).

Hermes masks what the model and the tools say (`security.redact_secrets`), never the
user's own message: a key he pastes would sit in clear in its session (state.db and
its search index). His web chat messages pass through here first
(actions/chat.py); his Telegram messages are masked inside the gateway by the
agos-guard plugin (bridge.pre_gateway_dispatch), with the same code
(hermes_plugin/agos_guard/keys.py) and the same note.

The masking runs in Hermes's own runtime: one small helper process (keys.py serve,
started like engine/hermes_redact.py's), asked once per message. When something was
hidden, a short note is added so the agent tells him where keys go; a Hermes
/command is masked without the note (its arguments are Hermes's to parse).

When Hermes's runtime can't answer, the message goes on UNCHANGED (never blocked or
dropped: what he wrote reaches the agent) and one warning is logged; the Secrets
check on Settings → Health (actions/secrets_check.py) finds such a key later.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from agos_core.engine.guard_files import KEYS_SCRIPT
from agos_core.engine.hermes_redact import Redactor
from agos_core.engine.loop_guard import on_loop
from agos_core.shared.guard_contract import KEY_NOTE

log = logging.getLogger("agos.owner_keys")

NOTE = KEY_NOTE
_FILE = str(KEYS_SCRIPT)


class KeysHelper(Redactor):
    """keys.py's `serve` loop in Hermes's runtime: [masked text, keys found] per text."""

    LOOP = (
        "import sys, runpy\n"
        f"sys.argv = [{_FILE!r}, 'serve']\n"
        f"runpy.run_path({_FILE!r}, run_name='__main__')\n"
    )

    def hide_many(self, texts: list[str]) -> list[tuple[str, list[dict[str, str]]]] | None:
        out = self.ask(texts)
        if out is None:
            return None
        return [(str(pair[0]), list(pair[1])) for pair in out]


_current: dict[str, Any] = {"helper": None}
_warned = threading.Event()


def use(helper: Any) -> None:
    _current["helper"] = helper


def _unchecked(why: str) -> None:
    if not _warned.is_set():
        _warned.set()
        log.warning(
            "the owner's messages are not checked for keys (%s): they go on unchanged; "
            "Settings → Health → Secrets check finds a key later",
            why,
        )


def hide(text: str, *, command: bool = False) -> str:
    """His message as AGOS keeps it and hands it on: any key masked by Hermes, plus
    NOTE (not for a /command). Unchanged when there is nothing to hide, or when
    Hermes can't check it (logged once)."""
    if not text.strip():
        return text
    helper = _current["helper"]
    if helper is None:
        _unchecked("Hermes's runtime isn't there")
        return text
    running = getattr(helper, "running", None)
    if on_loop() and running is not None and not running():
        # Never start Hermes's runtime on the core's event loop (engine/loop_guard.py).
        _unchecked("asked on the event loop before Hermes's runtime was up")
        return text
    try:
        answer = helper.hide_many([text])
    except Exception as error:  # noqa: BLE001 - never lose his message over the check
        answer = None
        log.info("the key check failed: %s", type(error).__name__)
    if not answer:
        _unchecked("Hermes's runtime didn't answer")
        return text
    masked, found = answer[0]
    if not found:
        return text
    log.info("a key was hidden in an owner message (%d)", len(found))
    return masked if command else f"{masked}\n\n{NOTE}"
