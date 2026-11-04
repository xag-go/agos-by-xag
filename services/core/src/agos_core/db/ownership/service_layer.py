"""Ownership of the Service Layer's own tables (migration 146,
db/schema_service_layer.py) and reliability's (migration 147, db/schema_reliability.py): part of the registry's TABLES (db/ownership/tables.py).
Same rules as db/ownership/__init__.py.

Must not: hold another area's table or a key.
"""

from __future__ import annotations

from agos_core.db.ownership.base import ID, MADE, WS, Table, agos, cols

__all__ = ["TABLES"]

_NO_RUNS = (
    "H: hermes_cli has no record of an AGOS operation, its actor or its idempotency key; "
    "Hermes's own sessions are chats, not owner actions"
)

TABLES: dict[str, Table] = {
    "op_runs": Table(
        agos(
            "one run of an AGOS operation (agos_core/ops): the audit row of who did "
            "what, and its idempotency key so a retry returns the first result",
            _NO_RUNS,
        ),
        cols(
            id=ID,
            operation="the operation's name",
            workspace_id=WS,
            actor="owner, cofounder or agent:<member>",
            title="its audit title",
            idempotency_key="the caller's key (a retry or double click sends the same)",
            status="running | done | failed | undone",
            result="what it returned (JSON), given back to a retry",
            error="why it failed",
            created_at=MADE,
            finished_at="when it ended",
        ),
    ),
    "sagas": Table(
        agos(
            "the journal of a multi-step change touching Hermes (agos_core/saga.py), "
            "so a half-done change is visible and a later sync can finish it",
            "H: Hermes's own steps (profile create, gateway install) keep no journal "
            "of the AGOS change they are part of",
        ),
        cols(
            id=ID,
            name="which change (workspace.create, ...)",
            workspace_id=WS,
            status="running | done | needs_attention | compensated | compensation_failed",
            data="what a later sync needs to finish it (JSON)",
            error="why it stopped",
            started_at=MADE,
            finished_at="when it ended",
        ),
    ),
    "saga_steps": Table(
        agos("one step of a saga and how it went"),
        cols(
            id=ID,
            saga_id="its saga",
            seq="its place in the saga",
            name="the step",
            status="done | failed | compensated | compensation_failed",
            error="why it failed",
            at="when",
        ),
    ),
    "outbox": Table(
        agos(
            "notifications (phone push, ...) written inside the change and delivered "
            "after it by one loop with retry (agos_core/outbox)",
            "H: Hermes delivers its own messages; AGOS's own notifications to the "
            "owner's devices have no queue in Hermes",
        ),
        cols(
            id=ID,
            channel="how it goes out (push, ...)",
            workspace_id=WS,
            payload="what is sent (JSON)",
            dedupe_key="one row per notification",
            status="pending | sending | sent | failed",
            attempts="tries so far",
            next_at="when it is tried next",
            last_error="why the last try failed",
            created_at=MADE,
            sent_at="when it went out",
        ),
    ),
    "jobs": Table(
        agos(
            "AGOS's own background work as durable rows (agos_core/jobs): claimed with a "
            "lease, retried with backoff, dead-lettered into Settings → Errors",
            "H: Hermes's cron runs agent jobs; AGOS's own chores (retention, idle round, "
            "probes) have no queue in Hermes",
        ),
        cols(
            id=ID,
            kind="which work (retention.daily, idle.round, ...)",
            workspace_id=WS,
            payload="what the work needs (JSON)",
            dedupe_key="one waiting job per kind and key",
            status="pending | running | done | dead",
            attempts="tries so far",
            max_attempts="tries before it is a dead letter",
            run_at="when it is due",
            lease_until="when a worker that took it gives it back",
            last_error="why the last try failed",
            created_at=MADE,
            finished_at="when it ended",
        ),
    ),
    "slo_samples": Table(
        agos(
            "the measured SLIs (docs/compliance/sre.md) for scripts/slo.py's monthly report",
            "H: Hermes keeps no page, health or due-vs-start timings of AGOS",
        ),
        cols(
            id=ID,
            sli="page | first_output | automation_delay | health",
            workspace_id=WS,
            subject="what was measured (a page, a turn, an automation)",
            value_ms="how long, in ms",
            ok="1 when it answered",
            once_key="recorded at most once (one turn, one run)",
            at="when",
        ),
    ),
}
