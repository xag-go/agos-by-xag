"""The workspace's plan as the agents read it: pure rules (Step 51, Step 53).

The plan is a tree of three levels (the goals table, one row each):
- the Vision: the owner's sentence, its why and the strategy (how we get there);
  the row with no parent, one per workspace;
- its goals (2-4: owner, due date), each with key results: numbers with a start,
  a current value, a target, a unit and a due date (the key_results table);
- each goal's projects (1-3: dated with a start / end, or recurring with a rhythm
  such as "4 reels a week"; an owner member). Cards serve a project or a goal.

- The plan's text reaches every agent in ONE place: its SOUL.md (Hermes's slot #1
  of the system prompt), between the GOAL markers (engine/identity.py). A member's
  lists the goals and projects it owns first.
- A card made for a project (or a goal) carries the link in its own Hermes body, as
  its first section, the line the agent working it reads:

      ## Goal
      Project #12: Ship 4 reels a week (goal #5: Grow the channel to 10k)

  Cards made before step 53 say "Sub-goal #12: ..." and are read the same way. A
  card without one serves the goal of its nearest parent that has one (Hermes's
  task_links).
- Progress rolls up: a project's cards (done / open / blocked, one read of the
  board) -> the project; a goal is its key results' progress (their mean), or its
  cards' when it has no key result with a target; the Vision is its active goals'
  mean.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

CARD_HEAD = "## Goal"
STATUSES = ("active", "paused", "done", "dropped")  # paused: on hold, comes back
LEVELS = ("vision", "goal", "project")
PROJECT_KINDS = ("dated", "recurring")
TITLE_MAX = 200
TEXT_MAX = 2000
UNIT_MAX = 40
RHYTHM_MAX = 120
PROMPT_GOALS = 6  # the most goals a prompt lists (a member's own first)
PROMPT_PROJECTS = 5  # per goal
PROMPT_RESULTS = 4  # per goal

_CARD_LINE = re.compile(
    r"^## Goal[ \t]*\r?\n(?:Sub-goal|Goal|Project|Vision) #(\d+)\b[^\n]*(?:\n|$)", re.M
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class KeyResult:
    id: int
    goal_id: int
    title: str
    start: float = 0.0
    current: float = 0.0
    target: float | None = None
    unit: str = ""
    due_on: str = ""
    source: str = ""
    position: int = 0


@dataclass(frozen=True)
class Goal:
    id: int
    parent_id: int | None
    title: str
    why: str = ""
    measure: str = ""
    owner: str = ""
    status: str = "active"
    position: int = 0
    level: str = "goal"
    strategy: str = ""
    due_on: str = ""
    project_kind: str = ""
    starts_on: str = ""
    ends_on: str = ""
    rhythm: str = ""
    children: list[Goal] = field(default_factory=list)
    results: list[KeyResult] = field(default_factory=list)


def is_date(text: str) -> bool:
    return bool(_DATE.match(text or ""))


# ---- a card's link ------------------------------------------------------------------


def card_goal(body: str) -> int | None:
    """The goal or project a card body names in its '## Goal' section (None: none)."""
    found = _CARD_LINE.search(body or "")
    return int(found.group(1)) if found else None


def without_card_goal(body: str) -> str:
    """The body without its '## Goal' section (the web shows the chip instead)."""
    return _CARD_LINE.sub("", body or "", count=1).lstrip("\n")


def card_line(goal: Goal, parent: Goal | None) -> str:
    """The section a card made for this goal / project starts with."""
    kind = {"vision": "Vision", "project": "Project"}.get(goal.level, "Goal")
    above = ""
    if parent is not None and parent.id != goal.id:
        above = (
            f" (goal #{parent.id}: {parent.title})"
            if goal.level == "project"
            else f" (toward: {parent.title})"
        )
    return f"{CARD_HEAD}\n{kind} #{goal.id}: {goal.title}{above}"


def with_card_goal(body: str, goal: Goal | None, parent: Goal | None) -> str:
    """The body with its '## Goal' section set to `goal` (None: taken out)."""
    rest = without_card_goal(body).strip()
    if goal is None:
        return rest
    return f"{card_line(goal, parent)}\n\n{rest}".strip()


# ---- the tree -----------------------------------------------------------------------


def tree(rows: Iterable[Goal], results: Iterable[KeyResult] = ()) -> Goal | None:
    """The Vision with its goals (and their key results) and their projects nested
    (None: no Vision set). A row whose parent is gone hangs under the Vision."""
    goals = list(rows)
    top = next((g for g in goals if g.parent_id is None), None)
    if top is None:
        return None
    ids = {g.id for g in goals}
    kids: dict[int, list[Goal]] = {}
    for g in goals:
        if g.parent_id is None:
            continue
        parent = g.parent_id if g.parent_id in ids else top.id
        kids.setdefault(parent, []).append(g)
    krs: dict[int, list[KeyResult]] = {}
    for k in results:
        krs.setdefault(k.goal_id, []).append(k)

    def build(g: Goal, seen: frozenset[int]) -> Goal:
        mine = sorted(kids.get(g.id, []), key=lambda k: (k.position, k.id))
        return dataclasses.replace(
            g,
            level="vision" if g.parent_id is None else g.level,
            children=[build(k, seen | {g.id}) for k in mine if k.id not in seen],
            results=sorted(krs.get(g.id, []), key=lambda k: (k.position, k.id)),
        )

    return build(top, frozenset())


def walk(goal: Goal | None) -> list[Goal]:
    """Every row of the tree, depth first (the Vision first)."""
    if goal is None:
        return []
    out = [goal]
    for child in goal.children:
        out += walk(child)
    return out


def parent_of(top: Goal | None, goal_id: int) -> Goal | None:
    for g in walk(top):
        if any(c.id == goal_id for c in g.children):
            return g
    return None


def loops(parents: Mapping[int, int | None], goal_id: int, new_parent: int | None) -> bool:
    """Would `goal_id` under `new_parent` make a loop (itself or one of its own
    rows below, through any number of steps)?"""
    seen: set[int] = set()
    walk_id = new_parent
    while walk_id is not None:
        if walk_id == goal_id or walk_id in seen:
            return True
        seen.add(walk_id)
        walk_id = parents.get(walk_id)
    return False


# ---- progress -----------------------------------------------------------------------


def result_progress(k: KeyResult) -> float | None:
    """How far a key result is from its start to its target, 0..1 (None: no target)."""
    if k.target is None:
        return None
    if k.target == k.start:
        return 1.0 if k.current >= k.target else 0.0
    return max(0.0, min(1.0, (k.current - k.start) / (k.target - k.start)))


def _card_ratio(c: Mapping[str, int] | None) -> float | None:
    if not c:
        return None
    total = c.get("done", 0) + c.get("open", 0) + c.get("blocked", 0)
    return c.get("done", 0) / total if total else None


def _mean(values: Iterable[float | None]) -> float | None:
    found = [v for v in values if v is not None]
    return sum(found) / len(found) if found else None


def progress(g: Goal, counts: Mapping[int, Mapping[str, int]]) -> float | None:
    """A row's progress, 0..1 (None: nothing to measure yet)."""
    if g.level == "project":
        return _card_ratio(counts.get(g.id))
    if g.level == "vision":
        return _mean(progress(c, counts) for c in g.children if c.status == "active")
    by_results = _mean(result_progress(k) for k in g.results)
    return by_results if by_results is not None else _card_ratio(counts.get(g.id))


def _number(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def result_line(k: KeyResult) -> str:
    unit = f" {k.unit}" if k.unit else ""
    if k.target is None:
        numbers = f"{_number(k.current)}{unit} now, target not set yet"
    else:
        share = result_progress(k)
        numbers = f"{_number(k.current)} / {_number(k.target)}{unit}" + (
            f" ({round(share * 100)}%)" if share is not None else ""
        )
    due = f", due {k.due_on}" if k.due_on else ""
    return f"KR #{k.id} {k.title}: {numbers}{due}"


def project_shape(g: Goal) -> str:
    if g.project_kind == "recurring":
        return f"recurring: {g.rhythm}" if g.rhythm else "recurring"
    if g.starts_on or g.ends_on:
        return f"{g.starts_on or '?'} → {g.ends_on or '?'}"
    return "dated"


# ---- the prompt ---------------------------------------------------------------------


def _one_line(text: str, cap: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= cap else flat[: cap - 1] + "…"


def _who(g: Goal, member: str) -> str:
    owner = f" — owner @{g.owner}" if g.owner else ""
    mine = " (yours)" if member and g.owner == member else ""
    return f"{mine}{owner}"


def prompt(top: Goal | None, member: str = "") -> str:
    """The plan section of an agent's SOUL.md ("" without a Vision). `member`: a team
    member's name (its own goals and projects first); "" = the Co-Founder."""
    if top is None:
        return ""
    lines = ["## The workspace Vision", f"Vision #{top.id}: {top.title}"]
    if top.why:
        lines.append(f"Why: {_one_line(top.why, 400)}")
    if top.strategy:
        lines.append(f"Strategy: {_one_line(top.strategy, 600)}")
    goals = [g for g in top.children if g.status == "active" and g.level == "goal"]

    def owns(g: Goal) -> bool:
        return bool(member) and (g.owner == member or any(p.owner == member for p in g.children))

    if member:
        goals = sorted(goals, key=lambda g: not owns(g))  # stable: owned first
    if goals:
        lines.append("Goals, their key results and projects:")
    for g in goals[:PROMPT_GOALS]:
        due = f", due {g.due_on}" if g.due_on else ""
        lines.append(f"- Goal #{g.id} {g.title}{_who(g, member)}{due}")
        lines += [f"  - {result_line(k)}" for k in g.results[:PROMPT_RESULTS]]
        projects = [p for p in g.children if p.status == "active"]
        if member:
            projects = sorted(projects, key=lambda p: p.owner != member)
        for p in projects[:PROMPT_PROJECTS]:
            lines.append(f"  - Project #{p.id} {p.title} ({project_shape(p)}){_who(p, member)}")
        if len(projects) > PROMPT_PROJECTS:
            lines.append(f"  - … and {len(projects) - PROMPT_PROJECTS} more projects")
        paused = [p for p in g.children if p.status == "paused"]
        for p in paused[:PROMPT_PROJECTS]:
            lines.append(
                f"  - Project #{p.id} {p.title}: paused, no work on it until the owner resumes it"
            )
    if len(goals) > PROMPT_GOALS:
        lines.append(f"- … and {len(goals) - PROMPT_GOALS} more goals (agos_goals status)")
    lines.append(
        "Work toward it. A card you create for a project starts its body with the line "
        f'"{CARD_HEAD}" and under it "Project #<id>: <title>" (for a goal: "Goal #<id>: '
        '<title>"). To change a goal, a key result or a project, propose it with '
        "agos_goals (action propose): the owner approves. The Vision and the strategy are "
        "the owner's own words: you may only suggest a change."
    )
    return "\n".join(lines)


# ---- the rollup ---------------------------------------------------------------------


def _bucket(status: str) -> str | None:
    if status == "done":
        return "done"
    if status == "blocked":
        return "blocked"
    if status == "archived":
        return None
    return "open"


def card_goals(
    cards: Mapping[str, tuple[str, str]], links: Iterable[tuple[str, str]]
) -> dict[str, tuple[int, bool]]:
    """Each card's goal: (goal id, inherited?) — its own '## Goal' line, else its
    nearest parent's (breadth first up Hermes's task_links). `cards`: id -> (status,
    body)."""
    parents: dict[str, list[str]] = {}
    for parent, child in links:
        parents.setdefault(str(child), []).append(str(parent))
    own = {cid: g for cid, (_s, body) in cards.items() if (g := card_goal(body)) is not None}
    out: dict[str, tuple[int, bool]] = {}
    for cid in cards:
        if cid in own:
            out[cid] = (own[cid], False)
            continue
        seen = {cid}
        layer = parents.get(cid, [])
        while layer:
            hit = next((own[p] for p in layer if p in own), None)
            if hit is not None:
                out[cid] = (hit, True)
                break
            nxt: list[str] = []
            for p in layer:
                if p not in seen:
                    seen.add(p)
                    nxt += parents.get(p, [])
            layer = [p for p in nxt if p not in seen]
    return out


def rollup(
    top: Goal | None,
    cards: Mapping[str, tuple[str, str]],
    links: Iterable[tuple[str, str]],
) -> dict[int, dict[str, int]]:
    """Per row: its cards and the cards of the rows below it, done / open / blocked."""
    counts: dict[int, dict[str, int]] = {
        g.id: {"done": 0, "open": 0, "blocked": 0} for g in walk(top)
    }
    if top is None:
        return counts
    up: dict[int, int | None] = {}
    for g in walk(top):
        for child in g.children:
            up[child.id] = g.id
    for cid, (goal_id, _inherited) in card_goals(cards, links).items():
        bucket = _bucket(cards[cid][0])
        if bucket is None or goal_id not in counts:
            continue
        walk_id: int | None = goal_id
        seen: set[int] = set()
        while walk_id is not None and walk_id not in seen:
            seen.add(walk_id)
            counts[walk_id][bucket] += 1
            walk_id = up.get(walk_id)
    return counts


# A row's next card: the first open one, running before review before blocked before
# ready / to do (anything else open after those), then the board's own order.
NEXT_RANK = {"running": 0, "review": 1, "blocked": 2, "ready": 3, "todo": 3}


def next_cards(
    top: Goal | None,
    tasks: Iterable[Mapping[str, Any]],
    links: Iterable[tuple[str, str]],
) -> dict[int, dict[str, str]]:
    """Per row: the next card of its own cards and the rows' below it (id, title,
    status), from the same board read as the rollup. `tasks` in board order."""
    if top is None:
        return {}
    listed = list(tasks)
    cards = {str(t["id"]): (str(t["status"]), str(t["body"])) for t in listed}
    up: dict[int, int | None] = {}
    rows = {g.id for g in walk(top)}
    for g in walk(top):
        for child in g.children:
            up[child.id] = g.id
    goal_of = card_goals(cards, links)
    best: dict[int, tuple[int, int]] = {}
    out: dict[int, dict[str, str]] = {}
    for order, t in enumerate(listed):
        cid, status = str(t["id"]), str(t["status"])
        found = goal_of.get(cid)
        if found is None or found[0] not in rows or _bucket(status) in (None, "done"):
            continue
        key = (NEXT_RANK.get(status, 4), order)
        walk_id: int | None = found[0]
        seen: set[int] = set()
        while walk_id is not None and walk_id not in seen:
            seen.add(walk_id)
            if walk_id not in best or key < best[walk_id]:
                best[walk_id] = key
                out[walk_id] = {"id": cid, "title": str(t.get("title") or ""), "status": status}
            walk_id = up.get(walk_id)
    return out


def rollup_lines(top: Goal | None, counts: Mapping[int, Mapping[str, int]]) -> list[str]:
    """The plan and its progress as short lines (the agents' agos_goals status)."""
    out = []
    for g in walk(top):
        c = counts.get(g.id, {})
        share = progress(g, counts)
        pct = f" {round(share * 100)}%" if share is not None else ""
        kind = {"vision": "Vision", "project": "Project"}.get(g.level, "Goal")
        indent = {"vision": "", "goal": "", "project": "  "}.get(g.level, "")
        extra = f" ({project_shape(g)})" if g.level == "project" else ""
        due = f", due {g.due_on}" if g.due_on else ""
        out.append(
            f"{indent}{kind} #{g.id} {g.title}{extra} [{g.status}]{pct}: {c.get('done', 0)} "
            f"done, {c.get('open', 0)} open, {c.get('blocked', 0)} blocked"
            + (f" — owner @{g.owner}" if g.owner else "")
            + due
        )
        out += [f"  - {result_line(k)}" for k in g.results]
    return out


def result_dict(k: KeyResult) -> dict[str, Any]:
    return {
        "id": k.id,
        "goalId": k.goal_id,
        "title": k.title,
        "start": k.start,
        "current": k.current,
        "target": k.target,
        "unit": k.unit,
        "dueOn": k.due_on,
        "source": k.source,
        "position": k.position,
        "progress": result_progress(k),
    }


def as_dict(g: Goal) -> dict[str, Any]:
    return {
        "id": g.id,
        "parentId": g.parent_id,
        "level": g.level,
        "title": g.title,
        "why": g.why,
        "measure": g.measure,
        "owner": g.owner,
        "status": g.status,
        "position": g.position,
        "strategy": g.strategy,
        "dueOn": g.due_on,
        "projectKind": g.project_kind,
        "startsOn": g.starts_on,
        "endsOn": g.ends_on,
        "rhythm": g.rhythm,
    }
