"""A team automation's steps: who does each and what each waits for.

The owner saves the steps on the automation; each run puts them on the
workspace's Hermes Kanban as cards (a step's cards wait on the cards of the steps
it waits on). Pure functions only: the steps are checked here.
"""

import re
from dataclasses import dataclass
from typing import Literal

# No cap on how many steps (the owner's rule: nothing stops the work but him).
MAX_STEPS: int | None = None

StepKind = Literal["work", "review", "approval", "answer"]

_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    description: str
    kind: StepKind
    agent: str | None  # a member's name; None = the Co-Founder itself / the owner (approval)
    waits_on: tuple[str, ...] = ()
    reviews: str | None = None  # review steps: the step they check


@dataclass(frozen=True)
class Plan:
    title: str
    steps: tuple[Step, ...]


class PlanError(ValueError):
    pass


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def parse_plan(data: object, members: list[str]) -> Plan:
    """A plan from the Co-Founder's JSON, checked: known members only, keys unique,
    every wait points at an earlier-declared or later step of the same plan, no
    cycles, reviews wait on what they review."""
    if not isinstance(data, dict):
        raise PlanError("the plan is not an object")
    raw = data.get("steps")
    if not isinstance(raw, list) or not raw:
        raise PlanError("the plan has no steps")
    if MAX_STEPS is not None and len(raw) > MAX_STEPS:
        raise PlanError(f"a plan has at most {MAX_STEPS} steps")
    by_lower = {m.lower(): m for m in members}
    steps: list[Step] = []
    keys: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise PlanError(f"step {i + 1} is not an object")
        key = _text(item.get("key") or f"s{i + 1}", 31).lower()
        if not _KEY.match(key) or key in keys:
            raise PlanError(f"step {i + 1} has a bad or repeated key")
        keys.add(key)
        kind = str(item.get("kind") or "work")
        if kind not in ("work", "review", "approval"):
            raise PlanError(f"step {key}: unknown kind {kind}")
        title = _text(item.get("title"), 140)
        if not title:
            raise PlanError(f"step {key} has no title")
        agent_raw = _text(item.get("agent"), 63).lstrip("@")
        agent: str | None = None
        if (
            kind != "approval"
            and agent_raw
            and agent_raw.lower() not in ("cofounder", "manager", "owner")
        ):
            agent = by_lower.get(agent_raw.lower())
            if agent is None:
                raise PlanError(f"step {key}: @{agent_raw} is not a member of this workspace")
        waits = item.get("waits_on") or []
        if not isinstance(waits, list):
            raise PlanError(f"step {key}: waits_on must be a list")
        waits_on = tuple(dict.fromkeys(_text(w, 31).lower() for w in waits if _text(w, 31)))
        reviews = _text(item.get("reviews"), 31).lower() or None
        if kind == "review":
            if not reviews:
                raise PlanError(f"step {key}: a review says which step it reviews")
            if reviews not in waits_on:
                waits_on = (*waits_on, reviews)
        steps.append(
            Step(
                key=key,
                title=title,
                description=_text(item.get("description"), 5_000),
                kind=kind,  # type: ignore[arg-type]
                agent=agent,
                waits_on=waits_on,
                reviews=reviews if kind == "review" else None,
            )
        )
    for s in steps:
        for w in s.waits_on:
            if w not in keys or w == s.key:
                raise PlanError(f"step {s.key} waits on an unknown step {w}")
        if s.reviews and next(x for x in steps if x.key == s.reviews).kind != "work":
            raise PlanError(f"step {s.key} can only review a work step")
    if _has_cycle(steps):
        raise PlanError("the steps wait on each other in a circle")
    return Plan(title=_text(data.get("title"), 140) or steps[0].title, steps=tuple(steps))


def _has_cycle(steps: list[Step]) -> bool:
    waits = {s.key: set(s.waits_on) for s in steps}
    done: set[str] = set()
    while waits:
        free = [k for k, w in waits.items() if w <= done]
        if not free:
            return True
        for k in free:
            done.add(k)
            del waits[k]
    return False
