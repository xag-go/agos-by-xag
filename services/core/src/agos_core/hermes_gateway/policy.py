"""What a call is, for the gateway's policies (ADR 0024): whether it runs Hermes,
which root it runs in, whether it is a pure read or a recovery command, and the
words it may be logged by (never a value)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

SHARED = "shared"  # a Hermes call with no HERMES_HOME: the shared home
_WORD = re.compile(r"^(?:[a-z][a-z0-9-]{0,23}|--version)$")
_SHOWN_WORDS = 2
_PROFILE_FLAGS = {"-p", "--profile"}

# Pure reads of Hermes's CLI (no write, any number of runs gives the same answer).
READS: dict[str, set[str] | None] = {
    "kanban": {"list", "show", "stats"},
    "config": {"get", "show", "path", "check"},
    "cron": {"list", "status"},
    "skills": {"list"},
    "mcp": {"list"},
    "sessions": {"list"},
    "profile": {"list", "show"},
    "plugins": {"list"},
    "pairing": {"list"},
    "status": None,
    "version": None,
    "--version": None,
}
# Commands that repair, update or start Hermes: never held back by an open circuit.
RECOVERY = {"update", "pm", "gateway", "doctor", "version", "--version", "setup", "install"}


def _command(args: Sequence[str]) -> tuple[bool, list[str]]:
    """(walled, the command itself): the part after the wall's launcher."""
    parts = [str(a) for a in args]
    if parts and Path(parts[0]).name.startswith("python") and "--" in parts:
        return True, parts[parts.index("--") + 1 :]
    return False, parts


def _subcommand(command: list[str]) -> list[str]:
    """The tokens after the executable, the profile flag and its value skipped."""
    out: list[str] = []
    rest = command[1:]
    i = 0
    while i < len(rest):
        if rest[i] in _PROFILE_FLAGS:
            i += 2
            continue
        out.append(rest[i])
        i += 1
    return out


def is_hermes(args: Sequence[str], env: dict[str, str] | None) -> bool:
    """A call into Hermes (its CLI, walled or not, or its runtime in a home)."""
    if env and env.get("HERMES_HOME"):
        return True
    _walled, command = _command(args)
    return bool(command) and Path(command[0]).name.startswith("hermes")


def root_of(env: dict[str, str] | None) -> str:
    """The workspace root a call runs in: a member home counts as its root."""
    home = (env or {}).get("HERMES_HOME")
    if not home:
        return SHARED
    path = Path(home)
    if path.parent.name == "profiles":
        path = path.parent.parent
    return str(path)


def words(args: Sequence[str]) -> list[str]:
    _walled, command = _command(args)
    return _subcommand(command)


def is_read(args: Sequence[str]) -> bool:
    said = words(args)
    if not said or said[0] not in READS:
        return False
    subs = READS[said[0]]
    return subs is None or (len(said) > 1 and said[1] in subs)


def is_recovery(args: Sequence[str]) -> bool:
    said = words(args)
    return bool(said) and said[0] in RECOVERY


def shown(args: Sequence[str]) -> str:
    """The call as the log may show it: the executable's name and at most two
    command words; everything else only counted."""
    walled, command = _command(args)
    if not command:
        return "?"
    rest = command[1:]
    head: list[str] = []
    for token in _subcommand(command):
        if len(head) >= _SHOWN_WORDS or not _WORD.match(token):
            break
        head.append(token)
    hidden = len(rest) - len(head)
    text = " ".join([Path(command[0]).name, *head])
    if hidden:
        text += f" (+{hidden} args)"
    return f"walled {text}" if walled else text
