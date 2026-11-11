"""The order a team automation's steps really run in, as parallel levels (display
only; engine/automation_run.py decides how they run). Twin of the web helper
features/setup/step-levels.ts: a step starts after the steps it waits_on (keys
that are not steps are ignored); one with none of them starts with the first level."""

from typing import Any


def step_levels(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    keys = {s.get("key") for s in steps if s.get("key")}

    def waits(s: dict[str, Any]) -> list[str]:
        # a review also waits on the step it reviews (engine/team_steps.py adds it)
        own = [
            *(s.get("waits_on") or []),
            *([s["reviews"]] if s.get("kind") == "review" and s.get("reviews") else []),
        ]
        return [w for w in own if w in keys and w != s.get("key")]

    levels: list[list[dict[str, Any]]] = []
    done: set[str] = set()
    left = list(steps)
    while left:
        ready = [s for s in left if all(w in done for w in waits(s))]
        if not ready:  # a cycle: never loop, the rest goes last
            levels.append(left)
            break
        levels.append(ready)
        done.update(str(s["key"]) for s in ready if s.get("key"))
        left = [s for s in left if s not in ready]
    return levels


def done_by(steps: list[dict[str, Any]]) -> str:
    """`@a → (@b + @c) → Co-Founder`: levels in order, same-level members together,
    a member repeated side by side reads once."""

    def name(s: dict[str, Any]) -> str:
        if s.get("agent"):
            return f"@{s['agent']}"
        return "you" if s.get("kind") == "approval" else "Co-Founder"

    out: list[list[str]] = []
    for level in step_levels(steps):
        names = list(dict.fromkeys(name(s) for s in level))
        if len(names) == 1 and out and out[-1] == names:
            continue
        out.append(names)
    return " → ".join(n[0] if len(n) == 1 else f"({' + '.join(n)})" for n in out)
