"""The Co-Founder asking for a capability from a chat: pure rules.

The Co-Founder calls its agos_capability tool (Hermes); AGOS says whether the owner
is asked first, and an app he never logged in to waits on its card for his login.
"""

import re
from dataclasses import dataclass

KINDS = ("app", "skill", "agent", "mcp", "tool")
_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


@dataclass(frozen=True)
class Ask:
    kind: str
    name: str
    on: bool
    why: str


@dataclass(frozen=True)
class Choice:
    """One thing the Co-Founder may ask for, as it is in this workspace now."""

    kind: str
    name: str
    title: str
    on: bool
    connected: bool  # apps: this workspace has its own login
    locked: str | None = None


def request_instructions(choices: list[Choice]) -> str:
    def line(c: Choice) -> str:
        state = "ON" if c.on else "off"
        extra = ""
        if c.locked:
            extra = " (locked: can't be used)"
        elif c.kind == "app" and not c.connected:
            extra = " (not connected yet: the owner logs in once when he approves)"
        return f"- {c.kind} `{c.name}` — {c.title}: {state}{extra}"

    listing = "\n".join(line(c) for c in choices) or "- (nothing available)"
    return f"""## Tools and apps of this workspace

You can use only what is ON here. What exists (kind, name, state):
{listing}

When the owner asks you to connect, turn on or turn off one of these, or when a
request clearly needs one that is off, say in one sentence what you ask for and
why, then call your agos_capability tool, e.g.
agos_capability(kind="app", name="notion", on=true, why="to read the content plan").
It answers whether it is done, or waits for the owner (his yes on a card, or his
login to an app): never say it is on before the tool says so. Never ask for
something locked or not in the list."""
