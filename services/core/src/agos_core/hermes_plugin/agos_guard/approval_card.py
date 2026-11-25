"""The owner's Allow / Deny card in Telegram (and every chat app Hermes serves) for
one of AGOS's own tools, in plain words.

Hermes renders the card (gateway/platforms/base.py `send_exec_approval`); for a
plugin's ask it shows the raw label "<agos_action> (plugin approval rule)" where a
command would be, and its own header names the engine. AGOS fixes the words only,
nothing of how the card works (buttons, whole-command check, Deny-only fallback):

- `register_words(ctx)`: Hermes's own language-pack layer (`ctx.register_locale`)
  for the header, the reason label and the deadline line: no engine name, no
  "8760 hours".
- `install()`: before Hermes renders a plugin rule's card, the label is swapped for
  the card's first line (the change itself, engine/approval_words.py in the core)
  and the rest stays as the reason. Any other card (a terminal command) is untouched.

Must not: decide who is asked (gate.py, owner_approval.py) or answer a card.
"""

from __future__ import annotations

import functools
import inspect
import re
from typing import Any

from . import runtime

__all__ = ["WORDS", "install", "register", "register_words", "split", "wrap"]

# Hermes's catalog keys (H: locales/en.yaml gateway.exec_approval.*), English: AGOS's
# own lines stay English (the owner-language setting covers what agents write).
WORDS: dict[str, str] = {
    "gateway.exec_approval.header": "Your agent needs your OK",
    "gateway.exec_approval.reason_label": "Why",
    "gateway.exec_approval.deadline": "No answer = nothing happens.",
}

# H: tools/approval.py request_tool_approval: display_target=f"<{tool_name}> (plugin approval rule)"
_LABEL = re.compile(r"<agos_[a-z_]{1,64}> \(plugin approval rule\)")
_MARK = "_agos_card_words"


def split(command: str, description: str | None) -> tuple[str, str | None]:
    """(what the card shows as the action, the reason) for one card.

    The card of one of AGOS's tools whose words (engine/approval_words.py) put the
    change on line 1 and the reason below: that line replaces the label. Anything
    else (a terminal command, a one-line message) comes back unchanged."""
    if not _LABEL.fullmatch(str(command or "").strip()) or not description:
        return command, description
    first, _, rest = str(description).strip().partition("\n")
    if not first.strip() or not rest.strip():
        return command, description
    return first.strip(), rest.strip()


def register(ctx: Any) -> None:
    """Both, at plugin load. Never breaks the plugin: the card then keeps Hermes's words."""
    try:
        register_words(ctx)
        install()
    except Exception as error:  # noqa: BLE001 — wording only; the guard must load
        runtime._report("agos_guard.approval_card", error)


def register_words(ctx: Any) -> None:
    """The card's header, reason label and deadline in AGOS's words (Hermes's
    language-pack layer: the top one, so they win over its bundled English)."""
    register = runtime._missing(
        "hermes_cli.plugins.PluginContext.register_locale",
        getattr(ctx, "register_locale", None),
    )
    if register is None:
        return
    with runtime._guard("hermes_cli.plugins.PluginContext.register_locale"):
        register("en", dict(WORDS))


def install() -> bool:
    """Wrap Hermes's `BasePlatformAdapter.send_exec_approval` once per process so a
    plugin rule's card shows the change instead of the raw label. False when this
    Hermes has no such method (the card then keeps Hermes's words)."""
    name = "gateway.platforms.base.BasePlatformAdapter.send_exec_approval"
    with runtime._guard(name):
        from gateway.platforms.base import BasePlatformAdapter  # type: ignore[import-not-found]

        return wrap(BasePlatformAdapter)
    return False


def wrap(owner: Any) -> bool:
    """Wrap `owner.send_exec_approval` (idempotent)."""
    original = runtime._missing(
        "gateway.platforms.base.BasePlatformAdapter.send_exec_approval",
        getattr(owner, "send_exec_approval", None),
    )
    if original is None:
        return False
    if getattr(original, _MARK, False):
        return True
    signature = inspect.signature(original)

    @functools.wraps(original)
    async def send_exec_approval(*args: Any, **kwargs: Any) -> Any:
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError:
            return await original(*args, **kwargs)
        said = bound.arguments
        if "command" in said:
            said["command"], said["description"] = split(
                str(said["command"] or ""), said.get("description")
            )
        return await original(*bound.args, **bound.kwargs)

    setattr(send_exec_approval, _MARK, True)
    owner.send_exec_approval = send_exec_approval
    return True
