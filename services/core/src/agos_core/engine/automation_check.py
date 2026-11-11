"""Check an automation before it is saved, and say in plain words how it will run.

Pure functions, no I/O. `check` returns ALL the problems at once (each names its
step in the owner's words; problems block the save) and the warnings (they never
do). `preview` is the "this is how it will run" text. The run order mirrors the
real run (engine/automation_run.py `start`): the steps are put on the board in
list order; a card waits on the cards of the steps it waits on that are ALREADY
made (an earlier step). A step with no such parent (empty `waits_on`, or only waits
on later steps) waits on the last run's last cards: it starts with the first steps.

Owns: the checks, the preview text and the stable step order. Must not: read the
workspace (the service in actions/services/automation/check.py hands it the team).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agos_core.engine import step_conditions
from agos_core.engine.step_levels import step_levels

__all__ = ["HOLE", "Report", "Who", "check", "ordered", "preview"]

# The same {name} / {payload.a.b} / {run.date} hole automation_run fills (a test pins it).
HOLE = re.compile(r"\{([a-z][a-z0-9_]*(?:\.[A-Za-z0-9_-]+)*)\}")
_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")
_KINDS = ("work", "review", "approval")
_ALIASES = ("cofounder", "manager", "owner")
LONG_CHAIN = 8  # levels one after another; more is a warning


@dataclass(frozen=True)
class Who:
    """A member of the team as the owner reads it."""

    label: str
    on: bool = True


@dataclass(frozen=True)
class Report:
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    preview: str = ""

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class _Step:
    index: int
    key: str
    title: str
    kind: str
    agent: str  # as written, "" = the Co-Founder
    waits_on: list[str]
    reviews: str
    description: str
    only_if: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"“{self.title}”" if self.title else f"step {self.index + 1}"


def _text(value: object, limit: int = 5000) -> str:
    return str(value or "").strip()[:limit]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _only_if(raw: Mapping[str, Any]) -> str:
    """The step's "Only if" lines (engine/step_conditions.py) in plain words."""
    return step_conditions.describe(raw.get("only_if", raw.get("onlyIf")))


def _only_if_problem(s: _Step) -> list[str]:
    try:
        step_conditions.parse_only_if(s.raw.get("only_if", s.raw.get("onlyIf")), s.key, s.kind)
    except step_conditions.ConditionError as error:
        return [f"{_cap(s.name)}: {error}."]
    return []


def _normal(raw_steps: Sequence[object]) -> tuple[list[_Step], list[str]]:
    """The steps as the plan reads them (parse_plan's own rules), and what is unreadable."""
    steps: list[_Step] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, item in enumerate(raw_steps):
        if not isinstance(item, Mapping):
            problems.append(f"Step {i + 1} is not readable.")
            continue
        title = _text(item.get("title"), 140)
        key = _text(item.get("key") or f"s{i + 1}", 31).lower()
        step = _Step(
            index=i,
            key=key,
            title=title,
            kind=_text(item.get("kind")) or "work",
            agent=_text(item.get("agent"), 63).lstrip("@"),
            waits_on=[],
            reviews=_text(item.get("reviews"), 31).lower(),
            description=_text(item.get("description")),
            only_if=_only_if(item),
            raw=dict(item),
        )
        waits = item.get("waits_on") or []
        if not isinstance(waits, list):
            problems.append(f"{_cap(step.name)}: what it waits on must be a list of steps.")
            waits = []
        step.waits_on = list(dict.fromkeys(_text(w, 31).lower() for w in waits if _text(w, 31)))
        if step.kind == "review" and step.reviews and step.reviews not in step.waits_on:
            step.waits_on.append(step.reviews)
        if not _KEY.match(key):
            problems.append(f"{_cap(step.name)} has no usable key (letters, digits, - or _).")
        elif key in seen:
            problems.append(f"Two steps share the key “{key}”: each step needs its own.")
        seen.add(key)
        steps.append(step)
    return steps, problems


def _find_cycles(steps: list[_Step]) -> list[list[_Step]]:
    """Groups of steps that wait on each other (or a step waiting on itself)."""
    by_key = {s.key: s for s in steps}

    def reach(key: str) -> set[str]:
        seen: set[str] = set()
        todo = list(by_key[key].waits_on)
        while todo:
            k = todo.pop()
            if k in by_key and k not in seen:
                seen.add(k)
                todo += by_key[k].waits_on
        return seen

    reaches = {s.key: reach(s.key) for s in steps}
    groups: list[list[_Step]] = []
    used: set[str] = set()
    for s in steps:
        if s.key in used or s.key not in reaches[s.key]:
            continue
        group = [t for t in steps if t.key in reaches[s.key] and s.key in reaches[t.key]]
        used |= {t.key for t in group}
        groups.append(group)
    return groups


def _names(steps: list[_Step]) -> str:
    names = [s.name for s in steps]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _agent_problems(
    s: _Step, team: Mapping[str, Who], problems: list[str], warnings: list[str]
) -> None:
    if s.kind == "approval":
        if s.agent and s.agent.lower() not in _ALIASES:
            warnings.append(
                f"{_cap(s.name)} is an approval: you approve it yourself, so @{s.agent} is not asked."
            )
    elif s.agent and s.agent.lower() not in _ALIASES:
        who = team.get(s.agent.lower())
        if who is None:
            problems.append(
                f"{_cap(s.name)} is given to @{s.agent}, who is not in this team "
                "(never hired, or removed). Pick another member."
            )
        elif not who.on:
            warnings.append(f"{who.label} is turned off, so the Co-Founder does {s.name} instead.")


def _review_problems(s: _Step, keys: Mapping[str, _Step]) -> list[str]:
    if s.kind != "review":
        return []
    if not s.reviews:
        return [f"{_cap(s.name)} is a review but says no step to check."]
    if s.reviews == s.key:
        return [f"{_cap(s.name)} reviews itself."]
    if s.reviews not in keys:
        return [f"{_cap(s.name)} reviews the step “{s.reviews}”, which does not exist."]
    if keys[s.reviews].kind != "work":
        return [f"{_cap(s.name)} can only review a work step, not {keys[s.reviews].name}."]
    return []


def _wait_problems(s: _Step, keys: Mapping[str, _Step]) -> list[str]:
    out: list[str] = []
    for w in s.waits_on:
        if w == s.key:
            out.append(f"{_cap(s.name)} waits on itself.")
        elif w not in keys and not (s.kind == "review" and w == s.reviews):
            out.append(f"{_cap(s.name)} waits on the step “{w}”, which does not exist.")
    return out


def _step_problems(steps: list[_Step], team: Mapping[str, Who]) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    keys = {s.key: s for s in steps}
    for s in steps:
        if not s.title:
            problems.append(f"Step {s.index + 1} has no title.")
        if s.kind not in _KINDS:
            problems.append(f"{_cap(s.name)} is of an unknown kind “{s.kind}”.")
        _agent_problems(s, team, problems, warnings)
        problems += _review_problems(s, keys)
        problems += _wait_problems(s, keys)
        problems += _only_if_problem(s)
    if steps and all(s.kind == "approval" for s in steps):
        problems.append("Every step is an approval: nobody does any work. Add a step for a member.")
    stuck: set[str] = set()
    for group in _find_cycles(steps):
        stuck |= {s.key for s in group}
        problems.append(
            f"{_names(group)} wait on each other in a circle, so none of them can ever start."
            if len(group) > 1
            else f"{_cap(group[0].name)} waits on itself."
        )
    problems += _blocked(steps, stuck)
    return problems, warnings


def _blocked(steps: list[_Step], stuck: set[str]) -> list[str]:
    """Steps that can never start because something they wait on is stuck in a circle."""
    by_key = {s.key: s for s in steps}
    blocked: set[str] = set()
    changed = True
    while changed:
        changed = False
        for s in steps:
            if s.key in stuck or s.key in blocked:
                continue
            if any(w in stuck or w in blocked for w in s.waits_on if w in by_key):
                blocked.add(s.key)
                changed = True
    return [
        f"{_cap(s.name)} can never start: a step it waits for is stuck in a circle."
        for s in steps
        if s.key in blocked
    ]


def _levels(steps: list[_Step]) -> dict[str, int]:
    """1 = starts with the run; else one more than its deepest parent. The one level
    rule of the Automations list (engine/step_levels.py, twin of the web's
    step-levels.ts): the save puts every step after the ones it waits on (`ordered`),
    so the run starts them in these levels."""
    shown = [
        {"key": s.key, "waits_on": s.waits_on, "kind": s.kind, "reviews": s.reviews} for s in steps
    ]
    return {str(s["key"]): n for n, group in enumerate(step_levels(shown), start=1) for s in group}


def ordered(raw_steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The steps with every step after the ones it waits on (stable: a list that is
    already in order is returned as it is). The run only waits on earlier steps."""
    steps, _ = _normal(list(raw_steps))
    if len(steps) != len(raw_steps):
        return [dict(s) for s in raw_steps]
    waits = {s.key: set(s.waits_on) for s in steps}
    done: set[str] = set()
    out: list[_Step] = []
    left = list(steps)
    while left:
        nxt = next((s for s in left if all(w in done for w in waits[s.key] if w in waits)), None)
        if nxt is None:  # a circle: keep the rest as written (check reports it)
            out += left
            break
        left.remove(nxt)
        done.add(nxt.key)
        out.append(nxt)
    return [dict(s.raw) for s in out]


def _used(text: str) -> set[str]:
    return set(HOLE.findall(text))


def _variable_problems(
    spec: Mapping[str, Any], steps: list[_Step], hook: bool
) -> tuple[list[str], list[str]]:
    defined = {
        _text(v.get("name") if isinstance(v, Mapping) else v, 40)
        for v in spec.get("variables") or []
    }
    sources = [("The instructions", _text(spec.get("instructions")))] if not steps else []
    for s in steps:
        sources.append((_cap(s.name), f"{s.title}\n{s.description}"))
    problems: list[str] = []
    warnings: list[str] = []
    for where, text in sources:
        used = _used(text)
        missing = sorted(
            u
            for u in used
            if u not in defined
            and u not in ("run.date", "run.time")
            and not u.startswith("payload.")
        )
        if missing:
            # A warning, never a refusal (owner decision): an automation saved before
            # this check stays editable; the hole stays as written in that run.
            shown = ", ".join("{" + m + "}" for m in missing)
            warnings.append(
                f"{where} uses {shown}, but no variable of that name is defined: it stays "
                "as written (add it in Variables, or remove it from the text)."
            )
        if not hook and any(u.startswith("payload.") for u in used):
            warnings.append(
                f"{where} uses data of a webhook delivery, but the webhook is off: it stays empty."
            )
    return problems, warnings


def _shape_warnings(steps: list[_Step]) -> list[str]:
    warnings: list[str] = []
    if not steps:
        return warnings
    level = _levels(steps)
    top = max(level.values())
    if top >= LONG_CHAIN:
        warnings.append(
            f"{top} steps one after another is a long chain: it is slow, and a step that "
            "fails in the middle holds back everything after it."
        )
    waited = {w for s in steps for w in s.waits_on}
    for s in steps:
        if s.kind == "work" and s.key not in waited and level[s.key] < top:
            warnings.append(f"The result of {s.name} is not used: no later step waits for it.")
        if s.index > 0 and not s.waits_on and steps[0].key != s.key:
            warnings.append(
                f"{_cap(s.name)} waits for nothing, so it starts together with the "
                "first step, not after the step above it."
            )
    return warnings


def check(
    spec: Mapping[str, Any],
    team: Mapping[str, Who],
    *,
    schedule_problem: str | None = None,
    schedule_text: str | None = None,
) -> Report:
    """All the problems and warnings of an automation as the owner (or the Co-Founder)
    is about to save it. `team`: the members by lowercase name. spec: name,
    instructions, schedule, hook, agent, steps, variables, check_first."""
    problems: list[str] = []
    warnings: list[str] = []
    if not _text(spec.get("name")):
        problems.append("The automation has no name.")
    if not _text(spec.get("instructions")):
        problems.append("It has no instructions: write what it should do.")
    schedule = _text(spec.get("schedule"), 500)
    hook = bool(spec.get("hook"))
    if not schedule and not hook:
        problems.append(
            "Nothing starts it: add a schedule, turn on the webhook "
            "(the moment something happens), or both."
        )
    if schedule_problem:
        problems.append(f"Schedule: {schedule_problem}.")
    raw = spec.get("steps") or []
    steps, shape = _normal(raw if isinstance(raw, list) else [])
    problems += shape
    if steps:
        more, warn = _step_problems(steps, team)
        problems += more
        warnings += warn + _shape_warnings(steps) if not more else warn
    else:
        agent = _text(spec.get("agent"), 63).lstrip("@")
        if agent and agent.lower() not in _ALIASES:
            who = team.get(agent.lower())
            if who is None:
                problems.append(f"@{agent} is not in this team (never hired, or removed).")
            elif not who.on:
                warnings.append(f"{who.label} is turned off, so the Co-Founder does it instead.")
    more, warn = _variable_problems(spec, steps, hook)
    problems += more
    warnings += warn
    shown = "" if problems else preview(spec, team, schedule_text=schedule_text)
    return Report(tuple(dict.fromkeys(problems)), tuple(dict.fromkeys(warnings)), shown)


# ---- the preview -------------------------------------------------------------------------


def _when(spec: Mapping[str, Any], schedule_text: str | None) -> str:
    schedule = _text(spec.get("schedule"), 500)
    hook = bool(spec.get("hook"))
    said = (
        f"on its schedule ({schedule_text})" if schedule_text else f"on the schedule “{schedule}”"
    )
    if schedule and hook:
        return f"Starts {said}, and the moment something arrives on its webhook address."
    if hook:
        return "Starts the moment something arrives on its webhook address."
    if schedule:
        return f"Starts {said}."
    return "Starts only when you run it."


def _who(step: _Step, team: Mapping[str, Who]) -> str:
    if step.agent and step.agent.lower() not in _ALIASES:
        found = team.get(step.agent.lower())
        if found is not None and found.on:
            return found.label
    return "The Co-Founder"


def _phrase(step: _Step, team: Mapping[str, Who], titles: Mapping[str, str]) -> str:
    cond = f", only if {step.only_if}" if step.only_if else ""
    if step.kind == "approval":
        return f"you approve “{step.title}”{cond}"
    who = _who(step, team)
    if step.kind == "review":
        return f"{who} checks “{titles.get(step.reviews, step.reviews)}”{cond}"
    return f"{who} does “{step.title}”{cond}"


def _line(group: list[_Step], team: Mapping[str, Who], titles: Mapping[str, str]) -> str:
    if len(group) == 1:
        return _cap(_phrase(group[0], team, titles)) + "."
    if all(s.kind == "work" for s in group):
        parts = [
            f"{_who(s, team)} (“{s.title}”{', only if ' + s.only_if if s.only_if else ''})"
            for s in group
        ]
        return f"{_names_plain(parts)} work at the same time."
    parts = [_phrase(s, team, titles) for s in group]
    return _cap(_names_plain(parts)) + ", all at the same time."


def _names_plain(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def preview(
    spec: Mapping[str, Any], team: Mapping[str, Who], *, schedule_text: str | None = None
) -> str:
    """How the automation will run, in plain words (the order of the real run)."""
    lines = [_when(spec, schedule_text)]
    if spec.get("check_first"):
        lines.append("Before anything starts, you approve the run (on the Board).")
    raw = spec.get("steps") or []
    steps, _ = _normal(raw if isinstance(raw, list) else [])
    if not steps:
        agent = _text(spec.get("agent"), 63).lstrip("@")
        found = team.get(agent.lower()) if agent else None
        who = found.label if found is not None and found.on else "The Co-Founder"
        lines.append(f"1) {who} does what the instructions say, alone.")
    else:
        level = _levels(steps)
        titles = {s.key: s.title for s in steps}
        for n in range(1, max(level.values()) + 1):
            group = [s for s in steps if level[s.key] == n]
            lines.append(f"{n}) {_line(group, team, titles)}")
        lines.append("Each step starts once the steps it waits for are done.")
    names = [
        _text(v.get("name") if isinstance(v, Mapping) else v, 40)
        for v in spec.get("variables") or []
    ]
    if names:
        lines.append("Variables: " + ", ".join("{" + n + "}" for n in names if n) + ".")
    lines.append("It runs by itself to the end and the report comes back to you.")
    return "\n".join(lines)
