"""Feature flags: a new behaviour ships off (or on) behind a name the owner can flip.

- `FLAGS` is the whole registry: name -> Flag(default, title, about). A name not in
  it is refused when set and reads off, so a typo never turns something on.
- The owner's value lives in `app_settings["ops.flags"]` (Settings → General → Labs, or
  the Co-Founder's `set_flag`, with Undo).
- `AGOS_FLAG_<NAME>=1|0` in the core's environment wins over both (a staging copy
  can force one on; `agos staging` writes it in its own config only).
- Kill switch: turn it off. Code asks `flags.on(core, "name")`; the web reads
  `GET /flags`.

Undo puts back what the owner had saved, not what was in force: no saved value =
the key is removed again (the default and an AGOS_FLAG_ override keep working).

Who may flip a switch: the owner always; the Co-Founder through `set_flag`, a power
action (engine/power.py) with Undo and an audit row. A flag that turns OFF a safety
or security check (an approval, the wall, a redaction) must not be the agent's to
flip: in the same change, make setting THAT flag an owner-only power
(engine/power.py, the owner gate), not just Undo. Today's flags change nothing of
the kind.

Remove a flag (and its `if`) once its behaviour is the only one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.db.records import Record

KEY = "ops.flags"


@dataclass(frozen=True)
class Flag:
    default: bool
    title: str
    about: str


FLAGS: dict[str, Flag] = {
    "labs_demo": Flag(
        default=False,
        title="Labs preview",
        about="Shows that Labs switches work. It changes nothing else in AGOS.",
    ),
}


_TRUE = ("1", "true", "on", "yes")
_FALSE = ("0", "false", "off", "no")


def parse_on(value: object) -> bool:
    """A switch's value from text or a bool; anything else is refused (never "off")."""
    if isinstance(value, bool):
        return value
    raw = str(value if value is not None else "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ActionError(f"A Labs switch is on or off (true or false), not “{value}”.")


class FlagView(Record):
    name: str
    title: str
    about: str
    on: bool
    default: bool
    forced: bool  # set by AGOS_FLAG_<NAME> on this machine: the switch can't change it


def _forced(name: str) -> bool | None:
    raw = os.environ.get(f"AGOS_FLAG_{name.upper()}", "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return None


def _saved(core: Any) -> dict[str, bool]:
    value = get_setting(core.db, KEY, {})
    return {str(k): bool(v) for k, v in value.items()} if isinstance(value, dict) else {}


def on(core: Any, name: str) -> bool:
    flag = FLAGS.get(name)
    if flag is None:
        return False
    forced = _forced(name)
    if forced is not None:
        return forced
    return _saved(core).get(name, flag.default)


def listed(core: Any) -> list[FlagView]:
    saved = _saved(core)
    out = []
    for name in sorted(FLAGS):
        flag = FLAGS[name]
        forced = _forced(name)
        value = forced if forced is not None else saved.get(name, flag.default)
        out.append(
            FlagView(
                name=name,
                title=flag.title,
                about=flag.about,
                on=value,
                default=flag.default,
                forced=forced is not None,
            )
        )
    return out


def set_flag(core: Any, name: str, value: bool) -> bool | None:
    """Sets the owner's value; returns the value the OWNER had saved (None = none),
    which is what Undo puts back (`restore_flag`), never a forced or default value."""
    if name not in FLAGS:
        raise ActionError(f"There is no Labs switch named “{name}”.", 404)
    saved = _saved(core)
    before = saved.get(name)
    saved[name] = bool(value)
    set_setting(core.db, KEY, saved)
    return before


def put(core: Any, name: str, value: bool) -> bool:
    """Settings → Labs: sets the owner's value; returns whether it was on before."""
    before = on(core, name) if name in FLAGS else False
    set_flag(core, name, value)
    return before


def restore_flag(core: Any, name: str, before: bool | None) -> None:
    """Undo: the owner's saved value back, or no saved value at all."""
    if name not in FLAGS:
        raise ActionError(f"There is no Labs switch named “{name}”.", 404)
    saved = _saved(core)
    if before is None:
        saved.pop(name, None)
    else:
        saved[name] = bool(before)
    set_setting(core.db, KEY, saved)
