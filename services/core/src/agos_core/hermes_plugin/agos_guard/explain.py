"""`hermes agos-explain '<json>'`: Hermes's auxiliary model says in plain words what
a held-back memory or skill write would change, for AGOS's Held-back writes page
(actions/held_writes.py explain). The JSON argument carries the agent's name, the
kind (memory / skills), and either the note changes (action, before, after) or a
skill's diff; the answer is one JSON line {ok, text, model}. The call is Hermes's
own auxiliary client (agent/auxiliary_client.py call_llm) on its `review` task, so
the owner's Helper models settings choose the model; nothing is kept here."""

from __future__ import annotations

import contextlib
import json
from typing import Any

TASK = "review"  # Hermes's auxiliary task the explainer runs as (auxiliary.review.*)

SYSTEM = (
    "An AI agent wants to change its own saved notes (memory) or one of its skills, and "
    "the change waits for the owner's approval. The owner is busy and not technical. In "
    "one or two short, plain sentences, say what the change does and the most likely "
    "reason for it (for example: an old note is out of date, two notes say the same "
    "thing, a new lesson was learned). Talk about the agent in the third person by its "
    "name. No file paths, no code, no ids, no quotes of the notes, no advice on what to "
    "click. Answer with the sentences only."
)


def setup(parser: Any) -> None:
    parser.add_argument("job", help="JSON: {agent, kind, target, changes, diff}")


def register(ctx: Any) -> None:
    """The one line agos_guard's register() calls: `hermes agos-explain`."""
    ctx.register_cli_command(
        "agos-explain",
        "Explain a held-back memory/skill write in plain words (for AGOS)",
        setup,
        handle,
    )


def _cap(text: Any, n: int) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _message(job: dict[str, Any]) -> str:
    what = "a skill" if job.get("kind") == "skills" else "its memory"
    parts = [f"Agent: {_cap(job.get('agent'), 100)}", f"It wants to change {what}."]
    if job.get("kind") == "skills":
        parts.append(f"Skill: {_cap(job.get('target'), 100)}")
    for n, change in enumerate(job.get("changes") or [], 1):
        if not isinstance(change, dict):
            continue
        lines = [f"Change {n}: {change.get('action')} ({change.get('where') or 'own notes'})"]
        if str(change.get("before") or "").strip():
            lines.append(f"Note now:\n{_cap(change.get('before'), 6000)}")
        if str(change.get("after") or "").strip():
            lines.append(f"Note after:\n{_cap(change.get('after'), 6000)}")
        parts.append("\n".join(lines))
    if str(job.get("diff") or "").strip():
        parts.append(f"The change:\n{_cap(job.get('diff'), 6000)}")
    return "\n\n".join(parts)


def handle(args: Any) -> int:
    try:
        job = json.loads(str(args.job))
        if not isinstance(job, dict) or not (job.get("changes") or job.get("diff")):
            print(json.dumps({"ok": False, "reason": "nothing to explain"}))
            return 0
        from agent.auxiliary_client import call_llm  # type: ignore[import-not-found]

        resp = call_llm(
            task=TASK,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _message(job)},
            ],
            temperature=0.0,
            max_tokens=300,
            timeout=90,
        )
        text = " ".join(str(resp.choices[0].message.content or "").split())
        if not text:
            print(json.dumps({"ok": False, "reason": "the model gave no answer"}))
            return 0
        print(json.dumps({"ok": True, "text": text[:1000], "model": getattr(resp, "model", None)}))
    except Exception as error:  # noqa: BLE001 — AGOS shows the reason
        with contextlib.suppress(Exception):
            from . import bridge

            bridge._broken(bridge._name_of(error, "agent.auxiliary_client.call_llm"), error)
        print(json.dumps({"ok": False, "reason": f"{type(error).__name__}: {error}"[:300]}))
    return 0
