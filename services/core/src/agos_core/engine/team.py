"""Workers: the workspace's team (like Slack/Teams), pure logic.

- The **Co-Founder** is the workspace's own agent (its SOUL). It runs the project with the owner.
- **Members** are the library agents turned on in the workspace's Connectors.
- A **DM** is a conversation with one of them (or with the Co-Founder).
- A **group** is a Hermes room (ADR 0020): Hermes decides who speaks; AGOS adds
  nothing to it (actions/rooms.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    name: str
    title: str
    summary: str
