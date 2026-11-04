"""How a workspace chat talks to Hermes: pure rules, tested once.

- how Hermes run events become the live view of a turn (`LiveTurn.apply`):
  streamed text, and one folded "Activity" list of tools, thinking and
  approvals.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from agos_core.engine import owner_asks

ActivityKind = Literal["tool", "thinking", "note", "approval", "subagent"]


# ---- live turn --------------------------------------------------------------

_PREVIEW = 400


def live_key(chat_id: int) -> str:
    """The doorbell an open chat's live view hears for \"a turn opened in this chat\"."""
    return f"chat:{chat_id}"


def turn_key(turn_id: int) -> str:
    """The doorbell an open chat's live view hears for \"this answer moved or ended\"."""
    return f"turn:{turn_id}"


@dataclass
class Activity:
    id: str
    kind: ActivityKind
    title: str
    detail: str = ""
    status: Literal["running", "done", "failed", "waiting"] = "done"
    duration: float | None = None
    choices: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "detail": self.detail,
            "status": self.status,
            "duration": self.duration,
            "choices": self.choices,
        }


TOOL_TITLES = {
    "terminal": "Ran a command",
    "read_file": "Read a file",
    "write_file": "Wrote a file",
    "patch": "Edited a file",
    "search_files": "Searched files",
    "web_search": "Searched the web",
    "web_extract": "Read a web page",
    "todo_list": "Updated the plan",
    "delegate_task": "Asked a helper",
    "execute_code": "Ran code",
    "memory": "Updated memory",
}


def tool_title(tool: str) -> str:
    return TOOL_TITLES.get(tool, tool.replace("_", " ").capitalize())


@dataclass
class LiveTurn:
    """What the owner sees while a turn runs; `version` bumps on every change."""

    turn_id: int
    status: str = "running"
    text: str = ""
    activity: list[Activity] = field(default_factory=list)
    output: str | None = None
    error: str | None = None
    version: int = 0
    # Full access: AGOS answers "once" for the owner (Hermes's hard blocks and
    # deny rules still run before any approval is asked).
    # The waiting approval is one of the owner's "Ask me" rules (asked even on Full access).
    owner_ask: bool = False
    # Every tool call (name, what it was given), for the goal judge in chats.
    calls: list[tuple[str, str]] = field(default_factory=list)
    # When the owner first saw something of it (text or an activity line): the
    # chat first-output SLI (actions/slis.py).
    first_output_at: datetime | None = None
    _seq: int = 0

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if (
            name == "version"
            and value
            and self.first_output_at is None
            and (self.text or self.activity)
        ):
            super().__setattr__("first_output_at", datetime.now(UTC))
        if name == "version" and value:
            # Every change bumps the version (here and in the actions): the chat's open
            # live views hear it at once instead of looking every 0.15 s.
            from agos_core.engine import doorbell

            doorbell.ring(doorbell.LIVE, turn_key(self.turn_id))

    def note_phase(self, title: str) -> None:
        """A step before the run starts (e.g. transcribing a voice note)."""
        self._add("tool", title, status="running")
        self.version += 1

    def end_phase(self) -> None:
        for item in self.activity:
            if item.status == "running":
                item.status = "done"
        self.version += 1

    def _add(self, kind: ActivityKind, title: str, **kw: Any) -> Activity:
        self._seq += 1
        item = Activity(id=f"{self.turn_id}-{self._seq}", kind=kind, title=title, **kw)
        self.activity.append(item)
        return item

    def _open_tool(self, tool: str) -> Activity | None:
        for item in reversed(self.activity):
            if item.kind == "tool" and item.status == "running" and item.title == tool_title(tool):
                return item
        return None

    def apply(self, event: dict[str, Any]) -> bool:
        """Folds one Hermes run event in. Returns True when the turn has ended."""
        name = str(event.get("event") or "")
        ended = False
        if name == "message.delta":
            self.text += str(event.get("delta") or "")
        elif name == "message.interim":
            if not event.get("already_streamed"):
                note = str(event.get("text") or "").strip()
                if note:
                    self._add("note", "Note", detail=note[:2_000])
        elif name == "reasoning.available":
            text = str(event.get("text") or "").strip()
            if text:
                last = self.activity[-1] if self.activity else None
                if last and last.kind == "thinking":
                    last.detail = (last.detail + "\n" + text)[-4_000:]
                else:
                    self._add("thinking", "Thought", detail=text[-4_000:])
        elif name == "tool.started":
            tool = str(event.get("tool") or "tool")
            self.calls.append((tool, str(event.get("preview") or "")))
            self._add(
                "tool",
                tool_title(tool),
                detail=str(event.get("preview") or "")[:_PREVIEW],
                status="running",
            )
        elif name == "tool.completed":
            tool = str(event.get("tool") or "tool")
            item = self._open_tool(tool) or self._add("tool", tool_title(tool))
            item.status = "failed" if event.get("error") else "done"
            item.duration = _float(event.get("duration"))
            result = str(event.get("preview") or "").strip()
            if result:
                item.detail = (item.detail + "\n→ " + result[:_PREVIEW]).strip()
        elif name == "subagent.start":
            self._add(
                "subagent", "Started a helper", detail=str(event.get("goal") or "")[:_PREVIEW]
            )
        elif name == "subagent.complete":
            self._add(
                "subagent",
                "A helper finished",
                detail=str(event.get("summary") or "")[:_PREVIEW],
                status="failed" if str(event.get("status")) == "failed" else "done",
            )
        elif name == "approval.request":
            self.owner_ask = owner_asks.owner_rule(event)
            self._add(
                "approval",
                "Asks you first (your rule)" if self.owner_ask else "Asks to run a risky command",
                detail="\n".join(
                    x
                    for x in (
                        str(event.get("description") or "").strip(),
                        str(event.get("command") or "").strip(),
                    )
                    if x
                )[:1_000],
                status="waiting",
                # Never "always"/"session": a chat can't widen what the agent may do.
                choices=["once", "deny"],
            )
            self.status = "waiting"
        elif name == "approval.responded":
            for item in self.activity:
                if item.kind == "approval" and item.status == "waiting":
                    item.status = "failed" if event.get("choice") == "deny" else "done"
                    item.title = "Refused" if event.get("choice") == "deny" else "Allowed once"
                    item.choices = []
            self.status = "running"
        elif name.startswith("run."):
            ended = self.finish_from(name[4:], event)
        else:
            return False
        self.version += 1
        return ended

    def finish_from(self, status: str, data: dict[str, Any]) -> bool:
        """Terminal status from an event or a polled run. False if not terminal."""
        if status not in ("completed", "failed", "cancelled", "interrupted"):
            return False
        self.status = status
        output = data.get("output")
        self.output = output if isinstance(output, str) else None
        error = data.get("error")
        self.error = str(error)[:1_000] if error else None
        for item in self.activity:
            if item.status in ("running", "waiting"):
                item.status = "failed" if status != "completed" else "done"
                item.choices = []
        self.version += 1
        return True

    def final_text(self) -> str:
        return (self.output if self.output is not None else self.text).strip()

    def snapshot(self) -> dict[str, Any]:
        text = self.text
        return {
            "turnId": self.turn_id,
            "status": self.status,
            "text": text,
            "activity": [a.as_json() for a in self.activity],
            "version": self.version,
            # Full access answers by itself, except the owner's "Ask me" rules.
        }


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None
