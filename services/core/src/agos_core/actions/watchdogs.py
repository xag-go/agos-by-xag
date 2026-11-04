"""Task watchdogs (Step 48, F44): "Watch this tree" on a card with children.

The watch is a Hermes cron job in the workspace's root (the Co-Founder's profile),
every 30 minutes. Its prompt has the agent read the subtree from the board
(`hermes kanban show` / `list`), and, when nothing in the tree is running or
queued while open leaves remain, compute the stop fingerprint — the sorted open
leaf ids with their statuses, `id:status,id:status` — and report it with the
`agos_watchdog_observe` tool (the guard's plugin posts it to AGOS). AGOS keeps the
last fingerprint per watchdog (kanban_watchdogs) and answers:
- `seen`: the same stop as last time — nothing to do (one wake per stop);
- `act`: a new stop — the agent continues or reopens the leaves (`kanban unblock`,
  a comment with what to do next) or asks the owner with agos_ask_owner;
- `escalate`: the third act in a row with the same open leaves (no leaf finished
  meanwhile): AGOS has blocked the root card for the owner (needs_input) and the
  agent writes nothing more.
The fingerprint rule is AGOS's; what to do on a stop is the agent's (the prompt).
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Any

from agos_core.actions import automations as automation_actions
from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import watchdogs as watchdog_rows
from agos_core.db.activity import add_activity
from agos_core.db.records import Record
from agos_core.db.rows import now
from agos_core.engine.cron import CronError, JobSpec
from agos_core.engine.hermes import EngineError

log = logging.getLogger("agos.watchdogs")

SCHEDULE = "30m"
ACTS_BEFORE_OWNER = 3
JOB_NAME = "AGOS watchdog: {card}"
BLOCK_REASON = (
    "Watchdog: this tree stopped {n} times with the same open cards and no progress; it needs you."
)


class Watchdog(Record):
    id: int
    root_card: str
    acts: int
    fingerprint: str
    created_at: str
    observed_at: str | None = None
    acted_at: str | None = None
    escalated_at: str | None = None
    problem: str | None = None


def prompt_for(watchdog_id: int, root_card: str) -> str:
    return "\n".join(
        [
            f"This is the watchdog of card {root_card} and everything under it (watchdog {watchdog_id}).",
            "",
            f"1. Read the tree: `hermes kanban show {root_card}` and the cards under it (its"
            " children, their children). Leaves are the cards with no children.",
            "2. If any card in the tree is running, scheduled or in review, or no open leaf"
            " remains (every leaf done or archived), answer `Watchdog: moving.` and stop.",
            "3. The tree stopped. Compute the stop fingerprint: every OPEN leaf (todo, ready,"
            " blocked) as `<id>:<status>`, sorted by id, joined with commas. Call"
            f" `agos_watchdog_observe(watchdog_id={watchdog_id}, fingerprint=<that>)`.",
            "4. `seen`: the same stop as last time; answer `Watchdog: seen.` and stop.",
            "   `act`: a new stop. For each open leaf: a leaf blocked for a dependency that is"
            " done, or ready but not picked up, unblock it (`hermes kanban unblock <id>`) and"
            " comment what to do next; a leaf blocked for the owner stays (his Inbox has it),"
            " and so does a leaf assigned to `founder` (the owner's own task: never unblock,"
            " comment or reassign it);"
            " something only the owner can settle: ask once with agos_ask_owner, naming the"
            " leaves. Then answer with one line of what you did.",
            "   `escalate`: AGOS blocked the root card for the owner; answer"
            " `Watchdog: escalated.` and stop.",
            "Write nothing else, start no new work, and never comment a card twice for the"
            " same stop.",
        ]
    )


def _row(core: Core, workspace_id: str, watchdog_id: int) -> sqlite3.Row:
    found = watchdog_rows.by_id(core.db, workspace_id, watchdog_id)
    if found is None:
        raise NotFoundError("This watchdog")
    return found


def _view(row: sqlite3.Row, problem: str | None = None) -> Watchdog:
    return Watchdog(
        id=int(row["id"]),
        root_card=str(row["root_card"]),
        acts=int(row["acts"]),
        fingerprint=str(row["fingerprint"]),
        created_at=str(row["created_at"]),
        observed_at=row["observed_at"],
        acted_at=row["acted_at"],
        escalated_at=row["escalated_at"],
        problem=problem,
    )


def by_card(core: Core, workspace_id: str) -> dict[str, int]:
    """{root card: watchdog id} of the workspace (one query, for the board read)."""
    return {str(r["root_card"]): int(r["id"]) for r in watchdog_rows.roots(core.db, workspace_id)}


def list_all(core: Core, workspace_id: str) -> list[Watchdog]:
    require_workspace(core, workspace_id)
    return [_view(r) for r in watchdog_rows.of_workspace(core.db, workspace_id)]


def _spec(watchdog_id: int, root_card: str) -> JobSpec:
    return JobSpec(
        name=JOB_NAME.format(card=root_card),
        prompt=prompt_for(watchdog_id, root_card),
        schedule=SCHEDULE,
        model="",
        provider="",
        reasoning_effort=None,
        enabled=True,
    )


def watch(core: Core, workspace_id: str, root_card: str, *, on: bool) -> Watchdog | None:
    """Watch this tree (on): a row and a Hermes cron job in the Co-Founder's cron;
    off: both go. None when off."""
    from agos_core.actions import holds

    require_workspace(core, workspace_id)
    found = watchdog_rows.by_card(core.db, workspace_id, root_card)
    bridge = automation_actions.cron_bridge(core)
    if bridge is None or core.engine is None:
        raise ActionError("The engine is off, so the watchdog can't change now.", 409)
    home = core.engine.profile_home(workspace_id)
    if not on:
        if found is None:
            return None
        if found["hermes_job_id"]:
            with contextlib.suppress(CronError, EngineError, OSError):
                bridge.remove(home, str(found["hermes_job_id"]))
        watchdog_rows.remove(core.db, int(found["id"]))
        add_activity(core.db, workspace_id, kind="watchdog.off", text=f"Watch off: {root_card}")
        return None
    tree = holds.subtree(core, workspace_id, root_card)  # NotFound when not on the board
    if len(tree) < 2:
        raise ActionError("Watch a card that has cards under it.")
    if found is None:
        watchdog_rows.add(core.db, workspace_id, root_card, now())
        found = watchdog_rows.by_card(core.db, workspace_id, root_card)
    assert found is not None
    watchdog_id = int(found["id"])
    problem: str | None = None
    try:
        if not (home / "config.yaml").is_file():
            raise CronError("this workspace's agent isn't set up yet")
        spec = _spec(watchdog_id, root_card)
        jobs = {str(j["id"]): j for j in bridge.job_states(home)}
        job = jobs.get(str(found["hermes_job_id"] or ""))
        if job is None:
            job_id = str(bridge.create(home, spec)["id"])
            watchdog_rows.set_job(core.db, watchdog_id, job_id)
        add_activity(core.db, workspace_id, kind="watchdog.on", text=f"Watch on: {root_card}")
    except (CronError, EngineError, OSError, ValueError) as error:
        problem = f"Not watching yet: {error}"[:300]
        log.warning("watchdog %s/%s: %s", workspace_id, root_card, error)
    return _view(_row(core, workspace_id, watchdog_id), problem)


def _leaf_ids(fingerprint: str) -> frozenset[str]:
    return frozenset(p.split(":", 1)[0].strip() for p in fingerprint.split(",") if p.strip())


def observe(core: Core, workspace_id: str, watchdog_id: int, fingerprint: str) -> dict[str, Any]:
    """The job reports a stop: 'seen' for the same fingerprint as last time, 'act'
    for a new one, 'escalate' on the third act with the same open leaves (the root
    card is blocked for the owner here)."""
    from agos_core.actions import founder

    row = _row(core, workspace_id, watchdog_id)
    parts = [p.strip() for p in fingerprint.split(",") if p.strip()]
    # A leaf that is the Founder's own task (the owner, a person) waits for him, not
    # for the team: never a stop to act on, never a reason to escalate.
    his = {c["id"] for c in founder.open_cards(core, workspace_id)}
    kept = [p for p in parts if p.split(":", 1)[0].strip() not in his]
    at = now()
    if parts and not kept:
        watchdog_rows.seen(core.db, watchdog_id, at)
        return {"answer": "seen", "acts": int(row["acts"])}
    clean = ",".join(sorted(kept))[:4000]
    if clean == str(row["fingerprint"]):
        watchdog_rows.seen(core.db, watchdog_id, at)
        return {"answer": "seen", "acts": int(row["acts"])}
    same_leaves = bool(row["fingerprint"]) and _leaf_ids(clean) == _leaf_ids(
        str(row["fingerprint"])
    )
    acts = int(row["acts"]) + 1 if same_leaves else 1
    answer = "act"
    escalated = None
    if acts >= ACTS_BEFORE_OWNER:
        answer = "escalate"
        escalated = at
        _block_root(core, workspace_id, str(row["root_card"]), acts)
        acts = 0  # the owner has it now; a later stop starts the count again
    watchdog_rows.acted(
        core.db, watchdog_id, fingerprint=clean, acts=acts, at=at, escalated=escalated
    )
    add_activity(
        core.db,
        workspace_id,
        kind="watchdog.act" if answer == "act" else "watchdog.escalated",
        text=f"Watchdog on {row['root_card']}: {answer} ({clean[:120] or 'no open leaves'})",
    )
    return {"answer": answer, "acts": acts}


def _block_root(core: Core, workspace_id: str, root_card: str, acts: int) -> None:
    """The root card blocked for the owner (Hermes's own `kanban block --kind
    needs_input`, so it lands in his Inbox)."""
    from agos_core.actions.kanban_asks import _hermes_kanban

    _hermes_kanban(
        core,
        workspace_id,
        "block",
        root_card,
        "--kind",
        "needs_input",
        BLOCK_REASON.format(n=acts),
    )


def sweep(core: Core) -> None:
    """A watched tree that ended (its root done or archived, or gone from the
    board): the watch goes, job included. Run by the automation loop; it reads the
    board only for workspaces that have a watchdog."""
    from agos_core.actions import holds

    rows = watchdog_rows.every_root(core.db)
    for row in rows:
        workspace_id, root = str(row["workspace_id"]), str(row["root_card"])
        try:
            status = holds.subtree(core, workspace_id, root).get(root, "")
        except NotFoundError:
            status = "archived"
        except ActionError:
            continue  # the board can't be read now: nothing is guessed
        if status in ("done", "archived"):
            with contextlib.suppress(ActionError, NotFoundError):
                watch(core, workspace_id, root, on=False)
