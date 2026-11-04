"""Review stages and plan-first on a Kanban card: pure rules (Step 52, F25 / F26).

Hermes's board is the engine of a review: its `review` column, the reviewer as the
card's assignee (the dispatcher wakes that profile on the card, hermes_cli/
kanban_db_dispatch.py review lane), request_changes / reopen_review back to the
implementer, comments. Hermes has one reviewer per handoff and no list of stages,
no round cap and no plan to accept first; those few things live on the card itself:

- the card's own policy: an `agos-review` block in its Hermes body (engine/
  card_blocks.py), any field left out = the workspace's default (app_settings
  `review.<workspace>`, actions/reviews.py):

      ```agos-review
      {"stages": ["lead", "cofounder", "owner"], "cap": 3, "plan": true, "planReviewer": "owner"}
      ```

  a stage is `lead` (the implementer's reports_to, resolved when the card reaches
  it; the Co-Founder's lead is the owner), `cofounder`, `owner` or a member's name;
- every step taken: a marker comment on the card (Hermes's own comments), read
  back to know where the card stands:

      [agos-review <card> r<round> s<stage>: submit|approve|changes|stuck|reset|pass] <words>
      [agos-plan <card> v<revision>: ready|accept|changes] <words>

  (Hermes's `reopen-review --reason` writes its comment as "CHANGES REQUESTED:
  <reason>", so a marker may follow that prefix.)

The owner's stage is the card in Hermes's `review` column assigned to `owner`: a
name no profile has, so Hermes's dispatcher never starts it (kanban_db_dispatch.py
_dispatch_lane_task, skipped_nonspawnable) and it waits for him.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agos_core.engine import card_blocks

FENCE = "agos-review"
OWNER = "owner"  # the owner's stage: the reviewer name on the card (no profile has it)
STAGE_WORDS = ("lead", "cofounder", "owner")
MAX_STAGES = 6
CAP_RANGE = (1, 20)
DEFAULTS: dict[str, Any] = {"stages": [], "cap": 3, "planFirst": False, "planReviewer": OWNER}
PLAN_KEY = "plan"  # the card document the plan is written in (actions/card_docs.py)
STUCK = "waiting for the owner: stuck in review after {n} rounds"
MAX_TASKS = 20
# A proposal's or a question's card (engine/proposals.py, engine/questions.py): the
# owner decides it; the workspace's review defaults never apply to it.
OWN_ASK_CARDS = ("agos-proposal", "agos-question")

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_REVIEW = re.compile(
    r"^(?:CHANGES REQUESTED: )?\[agos-review (?P<card>[A-Za-z0-9_-]+) r(?P<round>\d+) "
    r"s(?P<stage>\d+): (?P<verb>[a-z]+)\][ \t]*(?P<rest>.*)",
    re.S,
)
_PLAN = re.compile(
    r"^(?:CHANGES REQUESTED: )?\[agos-plan (?P<card>[A-Za-z0-9_-]+) v(?P<rev>\d+): "
    r"(?P<verb>[a-z]+)\][ \t]*(?P<rest>.*)",
    re.S,
)
_BY = re.compile(r"^by (?P<who>[A-Za-z0-9_-]+)\.")
REVIEW_VERBS = ("submit", "approve", "changes", "stuck", "reset", "pass")
PLAN_VERBS = ("ready", "accept", "changes")
ROUND_VERBS = ("changes", "stuck")  # each one counts a review round


# ---- the policy ---------------------------------------------------------------------------


def clean_stage(value: Any) -> str | None:
    text = str(value or "").strip().lower().lstrip("@")
    if text in ("co-founder", "co_founder"):
        text = "cofounder"
    if text in STAGE_WORDS or _NAME.fullmatch(text):
        return text
    return None


def clean_stages(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = [s for s in (clean_stage(v) for v in raw) if s]
    return out[:MAX_STAGES]


def clean_cap(raw: Any, default: int = 3) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return min(max(n, CAP_RANGE[0]), CAP_RANGE[1])


def clean_defaults(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "stages": clean_stages(data.get("stages")),
        "cap": clean_cap(data.get("cap"), DEFAULTS["cap"]),
        "planFirst": bool(data.get("planFirst")),
        "planReviewer": clean_stage(data.get("planReviewer")) or OWNER,
    }


@dataclass(frozen=True)
class Policy:
    stages: list[str]
    cap: int
    plan: bool
    plan_reviewer: str
    own: bool  # the card's body sets it (else the workspace's defaults)


def card_block(body: str) -> dict[str, Any]:
    return card_blocks.read_block(body, FENCE) or {}


def policy(body: str, defaults: dict[str, Any], *, has_children: bool = False) -> Policy:
    """The card's review policy: its body's block over the workspace's defaults.
    `planFirst` (the workspace's 'plan first for big cards') asks a plan of cards
    that have children; a card's own `plan` says yes or no for itself."""
    block = card_block(body)
    base = clean_defaults(defaults)
    if not block and any(f"```{fence}" in (body or "") for fence in OWN_ASK_CARDS):
        base = clean_defaults({})  # AGOS's own ask cards: no review of their own
    stages = clean_stages(block["stages"]) if "stages" in block else list(base["stages"])
    plan = bool(block["plan"]) if "plan" in block else bool(base["planFirst"] and has_children)
    return Policy(
        stages=stages,
        cap=clean_cap(block.get("cap"), base["cap"]) if "cap" in block else base["cap"],
        plan=plan,
        plan_reviewer=clean_stage(block.get("planReviewer")) or base["planReviewer"],
        own=bool(block),
    )


def with_policy(body: str, data: dict[str, Any]) -> str:
    """The body with its `agos-review` block set to `data` (none when empty)."""
    rest = card_blocks.strip_block(body, FENCE)
    clean: dict[str, Any] = {}
    if "stages" in data:
        clean["stages"] = clean_stages(data["stages"])
    if data.get("cap") is not None:
        clean["cap"] = clean_cap(data["cap"])
    if data.get("plan") is not None:
        clean["plan"] = bool(data["plan"])
    if data.get("planReviewer"):
        clean["planReviewer"] = clean_stage(data["planReviewer"]) or OWNER
    return card_blocks.with_block(rest, FENCE, clean) if clean else rest


def without_policy(body: str) -> str:
    return card_blocks.strip_block(body, FENCE)


# ---- the markers ----------------------------------------------------------------------------


def review_marker(card: str, round_: int, stage: int, verb: str) -> str:
    return f"[agos-review {card} r{round_} s{stage}: {verb}]"


def plan_marker(card: str, revision: int, verb: str) -> str:
    return f"[agos-plan {card} v{revision}: {verb}]"


@dataclass(frozen=True)
class Mark:
    kind: str  # review | plan
    verb: str
    number: int  # the stage (1-based) of a review mark, the revision of a plan mark
    round: int
    rest: str
    author: str
    at: int


def read_mark(card: str, body: str, author: str = "", at: int = 0) -> Mark | None:
    text = body.strip()
    found = _REVIEW.match(text)
    if found and found["card"] == card and found["verb"] in REVIEW_VERBS:
        return Mark(
            "review",
            found["verb"],
            int(found["stage"]),
            int(found["round"]),
            found["rest"].strip(),
            author,
            at,
        )
    found = _PLAN.match(text)
    if found and found["card"] == card and found["verb"] in PLAN_VERBS:
        return Mark("plan", found["verb"], int(found["rev"]), 0, found["rest"].strip(), author, at)
    return None


def marks(card: str, comments: list[dict[str, Any]]) -> list[Mark]:
    out = []
    for c in comments:
        if not isinstance(c, dict):
            continue
        m = read_mark(
            card,
            str(c.get("body") or ""),
            str(c.get("author") or ""),
            int(c.get("created_at") or 0),
        )
        if m is not None:
            out.append(m)
    return out


# ---- where a card stands ------------------------------------------------------------------


@dataclass
class State:
    phase: str = "work"  # work | review | stuck | done
    approved: set[int] = field(default_factory=set)  # 1-based stages approved in this pass
    rounds: int = 0  # requests for changes so far (the round is rounds + 1)
    since_reset: int = 0  # the ones counted against the cap
    implementer: str = ""  # who handed it to review (the latest submit)
    plan: str = "none"  # none | needed | waiting | changes | accepted
    plan_revision: int = 0
    notes: list[dict[str, Any]] = field(default_factory=list)
    passed: bool = False  # the owner let it through from stuck (every stage done)

    @property
    def round(self) -> int:
        return self.rounds + 1


def derive(card: str, pol: Policy, comments: list[dict[str, Any]]) -> State:
    state = State(plan="needed" if pol.plan else "none")
    for m in marks(card, comments):
        if m.kind == "plan":
            state.plan_revision = max(state.plan_revision, m.number)
            state.plan = {"ready": "waiting", "accept": "accepted", "changes": "changes"}[m.verb]
            by = _BY.match(m.rest)
            if m.verb == "ready" and by:
                state.implementer = by["who"]
            if m.verb != "ready" or m.rest:
                state.notes.append(_note(m))
            continue
        if m.verb == "submit":
            state.phase = "review"
            by = _BY.match(m.rest)
            if by:
                state.implementer = by["who"]
        elif m.verb == "approve":
            state.approved.add(m.number)
        elif m.verb in ROUND_VERBS:
            state.rounds += 1
            state.since_reset += 1
            state.phase = "stuck" if m.verb == "stuck" else "work"
        elif m.verb == "reset":
            state.since_reset = 0
            state.phase = "work"
        elif m.verb == "pass":
            state.passed = True
            state.phase = "done"
        if m.verb != "submit" or m.rest:
            state.notes.append(_note(m))
    return state


def _note(m: Mark) -> dict[str, Any]:
    return {
        "kind": m.kind,
        "verb": m.verb,
        "stage": m.number if m.kind == "review" else 0,
        "revision": m.number if m.kind == "plan" else 0,
        "round": m.round,
        "author": m.author,
        "text": _BY.sub("", m.rest).strip() if m.verb in ("submit", "ready") else m.rest,
        "at": m.at,
    }


def current_stage(state: State, reviewers: list[str], implementer: str) -> int:
    """The 1-based stage the card waits for (0 = none left). A stage is skipped
    when its reviewer is the implementer (no self-review) or a reviewer who already
    approved it in this pass (the same person twice)."""
    if state.passed:
        return 0
    done_by = {reviewers[i - 1] for i in state.approved if 0 < i <= len(reviewers)}
    for i, who in enumerate(reviewers, start=1):
        if i in state.approved:
            continue
        if not who or who == implementer or who in done_by:
            continue
        return i
    return 0


def skipped(state: State, reviewers: list[str], implementer: str) -> set[int]:
    """The stages `current_stage` passes over (same rules)."""
    done_by = {reviewers[i - 1] for i in state.approved if 0 < i <= len(reviewers)}
    return {
        i
        for i, who in enumerate(reviewers, start=1)
        if i not in state.approved and (not who or who == implementer or who in done_by)
    }


def next_stage(state: State, reviewers: list[str], implementer: str, after: int) -> int:
    """The stage after `after` is approved (0 = none: the card is done)."""
    ahead = State(
        phase=state.phase,
        approved={*state.approved, after},
        rounds=state.rounds,
        since_reset=state.since_reset,
        implementer=state.implementer,
    )
    return current_stage(ahead, reviewers, implementer)


# ---- the plan's tasks ---------------------------------------------------------------------

_TASKS = re.compile(r"^#{1,6}[ \t]+tasks[ \t]*$", re.I | re.M)
_HEADING = re.compile(r"^#{1,6}[ \t]+\S", re.M)
_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?(?P<text>.+?)[ \t]*$")
_MENTION = re.compile(r"(?<![\w@])@(?P<name>[a-z0-9][a-z0-9-]{0,63})\b")


def plan_tasks(text: str) -> list[dict[str, str]]:
    """The lines of the plan's '## Tasks' section: {title, member} each (member: the
    first @mention, "" = the card's own implementer)."""
    found = _TASKS.search(text or "")
    if found is None:
        return []
    rest = text[found.end() :]
    stop = _HEADING.search(rest)
    section = rest[: stop.start()] if stop else rest
    out: list[dict[str, str]] = []
    for line in section.splitlines():
        item = _ITEM.match(line)
        if item is None:
            continue
        words = item["text"]
        mention = _MENTION.search(words)
        title = " ".join(_MENTION.sub("", words).split()).strip(" -:")
        if title:
            out.append({"title": title[:200], "member": mention["name"] if mention else ""})
        if len(out) >= MAX_TASKS:
            break
    return out


def task_key(card: str, revision: int, n: int) -> str:
    """Hermes's idempotency key of the plan's n-th task card (a replay is the same card)."""
    return f"agos-plan:{card}:{revision}:{n}"
