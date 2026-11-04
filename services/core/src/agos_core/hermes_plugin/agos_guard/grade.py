"""`hermes agos-grade '<json>'`: Hermes's auxiliary model judges a skill test run for
AGOS's Skill Studio (actions/skill_tests.py grade). The JSON argument carries the
skill's name, the test input, the worker's output, the expected output (may be
empty) and the checklist (may be empty); the answer is one JSON line
{ok, pass, score, notes, model} (score: 0-1, how well the output does it;
Step 63 compares a candidate version's scores with the current version's). The call is Hermes's own auxiliary client (agent/
auxiliary_client.py call_llm) on its `review` task, so the owner's Helper models
settings choose the grader's model; nothing is kept here."""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any

TASK = "review"  # Hermes's auxiliary task the grader runs as (auxiliary.review.*)

SYSTEM = (
    "You grade one test run of an AI agent's skill. You get the skill's name, the test "
    "input, the agent's output, and either an expected output, a checklist of what the "
    "output must satisfy, or both. Decide whether the output passes: with an expected "
    "output, it passes when it conveys the same substance (wording may differ); with a "
    "checklist, every item must hold. Also score the output from 0 to 1 (1: fully does "
    "it, 0: not at all; a pass is at least 0.5). Answer with ONE JSON object only: "
    '{"pass": true|false, "score": <0..1>, "notes": "<one or two sentences: what passed '
    'or what is missing>"}.'
)


def setup(parser: Any) -> None:
    parser.add_argument("job", help="JSON: {skill, input, output, expected, checklist}")


def register(ctx: Any) -> None:
    """The one line agos_guard's register() calls: `hermes agos-grade`."""
    ctx.register_cli_command(
        "agos-grade", "Grade a skill test run with the auxiliary model (for AGOS)", setup, handle
    )


def _cap(text: Any, n: int) -> str:
    s = str(text or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _message(job: dict[str, Any]) -> str:
    parts = [f"Skill: {_cap(job.get('skill'), 100)}", f"Input:\n{_cap(job.get('input'), 8000)}"]
    if str(job.get("expected") or "").strip():
        parts.append(f"Expected output:\n{_cap(job.get('expected'), 8000)}")
    if str(job.get("checklist") or "").strip():
        parts.append(f"Checklist:\n{_cap(job.get('checklist'), 8000)}")
    parts.append(f"Agent's output:\n{_cap(job.get('output'), 8000) or '(empty)'}")
    return "\n\n".join(parts)


def verdict(raw: str) -> dict[str, Any] | None:
    """The model's {pass, notes} from its answer (a JSON object, maybe in prose)."""
    text = (raw or "").strip()
    try:
        m = None if text.startswith("{") else re.search(r"\{.*\}", text, re.DOTALL)
        found = json.loads(m.group(0) if m else text)
    except (ValueError, AttributeError):
        return None
    if not isinstance(found, dict) or "pass" not in found:
        return None
    out: dict[str, Any] = {
        "pass": bool(found.get("pass")),
        "notes": str(found.get("notes") or "")[:2000],
    }
    score = found.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        out["score"] = max(0.0, min(1.0, float(score)))
    return out


def handle(args: Any) -> int:
    try:
        job = json.loads(str(args.job))
        if not isinstance(job, dict) or not str(job.get("output") or "").strip():
            print(json.dumps({"ok": False, "reason": "nothing to grade: the run has no output"}))
            return 0
        if not (str(job.get("expected") or "").strip() or str(job.get("checklist") or "").strip()):
            print(json.dumps({"ok": False, "reason": "no expected output and no checklist"}))
            return 0
        from agent.auxiliary_client import call_llm  # type: ignore[import-not-found]

        resp = call_llm(
            task=TASK,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": _message(job)},
            ],
            temperature=0.0,
            max_tokens=400,
            timeout=90,
        )
        raw = str(resp.choices[0].message.content or "")
        found = verdict(raw)
        if found is None:
            print(json.dumps({"ok": False, "reason": "could not read a verdict from the model"}))
            return 0
        print(json.dumps({"ok": True, **found, "model": getattr(resp, "model", None)}))
    except Exception as error:  # noqa: BLE001 — AGOS shows the reason
        with contextlib.suppress(Exception):
            from . import bridge

            bridge._broken(bridge._name_of(error, "agent.auxiliary_client.call_llm"), error)
        print(json.dumps({"ok": False, "reason": f"{type(error).__name__}: {error}"[:300]}))
    return 0
