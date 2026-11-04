"""A scripted OpenAI-compatible model for real-Hermes end-to-end runs (no account).

Run: python fake_llm.py <port> <log file>

It answers by looking at the conversation, the way the room / DM tests need:
- in a hosted-room turn (Hermes's "[Discussion: …] You are @<handle>" prompt) it plays
  Co-Founder / writer / editor (delegation by @mention, a final summary);
- "pingpong" makes the Co-Founder and the writer hand off forever, so the room stops on
  max_rounds without a final answer (AGOS's continuation is then tested);
- "read file <path>" makes the writer run `cat <path>` with the terminal tool first;
- "danger" makes the writer run a command Hermes asks approval for;
- AGOS's /task skill command makes its card with kanban_create;
- "work kanban task t_…" (a Kanban worker) completes its card with kanban_complete;
- Hermes's Kanban wake ("[kanban] Task t_… completed") gets the Co-Founder's own answer;
- "slow" in a DM makes its answer take a while (a message can land while it works);
- anything else (a DM) is echoed back as "DM answer: …".
Every request is appended to the log file as one JSON line (who, last user text).
"""

from __future__ import annotations

import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LOG = sys.argv[2] if len(sys.argv) > 2 else "/dev/null"
LAST_OWNER: dict[str, str] = {}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _handle_of(prompt: str) -> str | None:
    found = re.search(r"You are @([A-Za-z0-9_-]+), one participant", prompt)
    return found.group(1) if found else None


def _tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"tool_call": {"name": name, "arguments": json.dumps(args)}}


def _echo(words: str) -> str:
    """The owner's words for a DM answer: the last 300 characters, and the first 120
    too when there is more. On a workspace's very first message Hermes adds a long note
    AFTER the owner's text, so the tail alone would miss what he wrote."""
    joined = " / ".join(words.strip().splitlines())
    return joined if len(joined) <= 300 else joined[:120] + " … " + joined[-300:]


def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """{"text": …} or {"tool_call": {name, arguments}} for the next assistant step."""
    users = [m for m in messages if m.get("role") == "user"]
    prompt = _text(users[-1].get("content")) if users else ""
    # Hermes's surface-switch note (H: agent/surface_switch.py) rides on the user turn when a
    # session moves between interfaces (web -> Telegram topic); it is not what he wrote.
    prompt = prompt.split("\n\n[System: This conversation is now being answered on a", 1)[0]
    last = messages[-1] if messages else {}
    tool_result = _text(last.get("content")) if last.get("role") == "tool" else None
    handle = _handle_of(prompt)
    card = re.match(r"work kanban task (t_[0-9a-f]+)", prompt.strip())
    asked = re.search(
        r"# /task: one card on the Kanban[\s\S]*"
        r"(?:User instruction|instruction alongside the skill invocation): (.+)",
        prompt,
    )
    if asked is not None and handle is None:
        # AGOS's shared /task skill (Hermes's skill command): one card, kanban_create
        # (a tool answer since his last message is its card).
        since = max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=-1)
        made = [m for m in messages[since + 1 :] if m.get("role") == "tool"]
        if made:
            return {"text": f"On the Kanban: {str(made[-1].get('content'))[:200]}"}
        title = asked.group(1).strip()
        return _tool_call("kanban_create", {"title": title, "body": title, "assignee": "default"})
    if card is not None and handle is None:
        # A Kanban worker (Hermes's dispatcher spawned it): it finishes its card.
        done = any(
            m.get("role") == "assistant" and "kanban_complete" in json.dumps(m.get("tool_calls"))
            for m in messages
        )
        if done:
            return {"text": f"Card {card.group(1)} done."}
        return _tool_call(
            "kanban_complete", {"task_id": card.group(1), "summary": "e2e card finished"}
        )
    # Hermes stamps the turn with the owner's time first (gateway/message_timestamps.py).
    woken = re.search(r"^(?:\[[^\]]*\] )?\[kanban\] Task (t_[0-9a-f]+) (\w+)", prompt.strip())
    if woken is not None and handle is None and tool_result is None:
        # Hermes's Kanban wake (the card's subscription is wake only): the Co-Founder's
        # own turn is the one message the owner gets about the card.
        return {"text": f"Co-Founder here: card {woken.group(1)} {woken.group(2)}, all good."}
    if handle is None:
        # Hermes's own side calls (titles, compression, memory review…) and DMs.
        if tool_result is not None:
            return {"text": f"Tool said: {tool_result[:300]}"}
        if "danger" in prompt.lower():
            return _tool_call(
                "terminal", {"command": "rm -rf /tmp/agos-approval-probe && echo removed-ok"}
            )
        slow = "slow" in prompt.lower() and "DM answer" not in prompt
        # The owner's words, without agos-guard's language note (pre_llm_call, Step 38b)
        # after them: echoing the note's tail would cut his words out of the answer.
        owner_words = re.sub(r"\s*\[Language: [^\]]*\]\s*$", "", prompt)
        return {"slow": slow, "text": "DM answer: " + _echo(owner_words) if prompt else "ok"}
    # What is new in this room turn (Hermes's delta lines "  @who: text" / "  User (user): …").
    lines = [ln.strip() for ln in prompt.splitlines() if ln.startswith("  ")]
    # Only the owner's latest message counts (earlier ones are history).
    # A member's prompt only shows what is new since its last turn: the owner's
    # latest message is remembered per room.
    room = re.search(r'\[Discussion: "(.+?)"\]', prompt)
    room_name = room.group(1) if room else ""
    owners = [ln for ln in lines if ln.startswith("User (user):")]
    if owners:
        LAST_OWNER[room_name] = owners[-1].lower()
    owner = LAST_OWNER.get(room_name, "")
    said = {
        who: " ".join(ln for ln in lines if ln.startswith(f"@{who}:"))
        for who in ("cofounder", "writer", "editor")
    }
    if "pingpong" in owner and "carry on" not in owner:
        time.sleep(4)  # slow enough for a Stop to land while the room works
    if handle == "cofounder":
        if "carry on" in owner or "please wrap up" in owner:
            return {"text": "Summary for the owner: the work is finished. FINAL"}
        if "pingpong" in owner:
            return {"text": "@writer ping, your turn."}
        if said["editor"]:
            return {
                "text": "Summary for the owner: the writer wrote it and the editor approved. FINAL"
            }
        if said["writer"] and "@editor" in prompt.split("\n", 1)[0]:
            return {"text": "@editor please review the writer's draft."}
        if said["writer"]:
            return {"text": "Summary for the owner: the writer wrote it. FINAL"}
        return {"text": "@writer please write it."}
    if handle == "writer":
        if "pingpong" in owner:
            return {"text": "@cofounder pong, back to you."}
        if tool_result is not None:
            return {
                "text": f"I read the file. It says: {tool_result.strip()[:200]}. @cofounder done."
            }
        paths = re.findall(r"read file (/\S+)", owner)
        if paths:
            return _tool_call("terminal", {"command": f"cat {paths[-1]}"})
        if "danger" in owner:
            return _tool_call(
                "terminal", {"command": "rm -rf /tmp/agos-approval-probe && echo removed-ok"}
            )
        return {"text": "Draft: roses are red, violets are blue. @cofounder draft ready."}
    if handle == "editor":
        if said["writer"] or said["cofounder"]:
            return {"text": "Reviewed: it reads well. @cofounder approved."}
        return {"text": "(pass)"}
    return {"text": "(pass)"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        return

    def _json(self, code: int, body: Any) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [{"id": "fake-model", "object": "model", "context_length": 200000}],
                },
            )
        else:
            self._json(404, {"error": "no"})

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        step = decide(messages)
        users = [m for m in messages if m.get("role") == "user"]
        system = "\n".join(_text(m.get("content")) for m in messages if m.get("role") == "system")
        topic = re.search(r"\*\*Channel Topic:\*\* ([^\n]*)", system)
        member = re.search(r"You are ([^,\n]+), a member of the team", system)
        with Path(LOG).open("a") as out:
            out.write(
                json.dumps(
                    {
                        "at": time.time(),
                        "who": _handle_of(_text(users[-1].get("content")) if users else ""),
                        "step": step,
                        "last": _text(users[-1].get("content"))[-300:] if users else "",
                        "prompt": _text(users[-1].get("content"))[:8000] if users else "",
                        # What Hermes put in the system prompt (SOUL.md, session context).
                        "soulRules": "## Tasks on the board" in system,
                        "cofounderView": "the Co-Founder's view of this workspace" in system,
                        # The agos-guard plugin's system-prompt section (the owner's
                        # rules), as Hermes framed it.
                        "ownerRules": (
                            system.split("## Plugin Context: agos.owner-rules", 1)[1].split(
                                "<!-- hermes-plugin-sections:end -->", 1
                            )[0][:4000]
                            if "## Plugin Context: agos.owner-rules" in system
                            else ""
                        ),
                        "topic": topic.group(1).strip() if topic else "",
                        # Which team member's SOUL.md Hermes loaded ("" = the Co-Founder).
                        "member": member.group(1) if member else "",
                    }
                )
                + "\n"
            )
        if step.pop("slow", False):
            time.sleep(12)  # logged first: the test sees the request while it works
        created = int(time.time())
        if "tool_call" in step:
            call = {
                "id": f"call_{int(time.time() * 1000)}",
                "type": "function",
                "function": step["tool_call"],
            }
            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": [call]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": step["text"]}
            finish = "stop"
        usage = {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60}
        if not body.get("stream"):
            self._json(
                200,
                {
                    "id": "fake",
                    "object": "chat.completion",
                    "created": created,
                    "model": "fake-model",
                    "usage": usage,
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                },
            )
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()

        def chunk(delta: dict[str, Any], reason: str | None = None, **extra: Any) -> None:
            data = {
                "id": "fake",
                "object": "chat.completion.chunk",
                "created": created,
                "model": "fake-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": reason}],
                **extra,
            }
            self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())

        chunk({"role": "assistant"})
        if "tool_calls" in message:
            call = message["tool_calls"][0]
            chunk({"tool_calls": [{"index": 0, **call}]})
        else:
            chunk({"content": message["content"]})
        chunk({}, finish)
        data = {
            "id": "fake",
            "object": "chat.completion.chunk",
            "created": created,
            "model": "fake-model",
            "choices": [],
            "usage": usage,
        }
        self.wfile.write(f"data: {json.dumps(data)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
