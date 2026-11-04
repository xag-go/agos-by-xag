"""Automations of a workspace: what AGOS keeps of them.

Hermes's cron job holds an automation's schedule, on/off, next and last run and
its runs; Hermes's webhook route holds its webhook (address, secret, events,
on/off); its readable file holds the instructions (actions/automations.py puts
them together). Here: team steps, "check with me first", the link
to the Hermes job. Its runs are Hermes's (cron executions, Kanban cards). The
`schedule` and `agent` columns hold what the owner asked only until Hermes takes
it (read while `sync_error` says Hermes refused it; the agent also while no
one-agent Hermes job holds it). On/off is Hermes's job's `enabled` alone: AGOS
writes `enabled` only when Hermes didn't take his on/off (keep_request), and sets
it back to 0 once Hermes has it (forget_request). Who does a one-agent automation is the
profile whose Hermes cron holds its job; the file is the one
copy of the instructions.
"""

import sqlite3

from agos_core.db.records import (
    Automation,
    AutomationHook,
    AutomationStep,
    AutomationVariable,
    TicketMapping,
)
from agos_core.db.rows import dump_json, load_json, now
from agos_core.db.workspaces import model_of
from agos_core.domain.models import ModelSelection


def _checked_schedule(schedule: str) -> str:
    """The owner's request as Hermes's parser took it (actions.automations
    schedule_problem); only its shape here. "" = no schedule (a webhook only)."""
    if len(schedule) > 100 or any(c in schedule for c in "\r\n\0"):
        raise ValueError("not a schedule")
    return schedule


def from_row(row: sqlite3.Row, hook: AutomationHook | None = None) -> Automation:
    """AGOS's part only: schedule/on are the owner's request (until Hermes has it);
    `hook` is its Hermes webhook route (actions/hooks.py); the caller adds the rest."""
    return Automation(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        file=row["file"],
        instructions="",  # the file's (actions/automations.read_instructions)
        schedule=row["schedule"],
        # NULL: Hermes's job has it (read there); until then the workspace's model.
        model=ModelSelection.model_validate(load_json(row["model"]))
        if row["model"]
        else model_of(str(row["workspace_id"])),
        on=row["enabled"] == 1,
        last_run=None,
        problem=row["sync_error"],
        next_run_at=None,
        agent=row["agent"],
        steps=[AutomationStep.model_validate(s) for s in load_json(row["steps"] or "[]") or []],
        notice=row["notice"],
        hook=hook,
        check_first=bool(row["check_first"]),
        variables=[
            AutomationVariable.model_validate(v) for v in load_json(row["variables"] or "[]") or []
        ],
        policy=row["policy"] or "skip_if_active",
        ticket=TicketMapping.model_validate(load_json(row["ticket"])) if row["ticket"] else None,
        catch_up="skip" if row["catch_up"] == "skip" else "once",
    )


def rows(db: sqlite3.Connection, workspace_id: str) -> list[sqlite3.Row]:
    return list(
        db.execute("SELECT * FROM automations WHERE workspace_id = ? ORDER BY id", (workspace_id,))
    )


def row(db: sqlite3.Connection, workspace_id: str, automation_id: int) -> sqlite3.Row | None:
    found: sqlite3.Row | None = db.execute(
        "SELECT * FROM automations WHERE id = ? AND workspace_id = ?", (automation_id, workspace_id)
    ).fetchone()
    return found


def list_automations(
    db: sqlite3.Connection,
    workspace_id: str,
    hooks: dict[int, AutomationHook] | None = None,
) -> list[Automation]:
    """AGOS's part only (see from_row) with their webhooks; actions.automations.list_all
    adds Hermes's timing."""
    return [from_row(r, (hooks or {}).get(int(r["id"]))) for r in rows(db, workspace_id)]


def summary(report: str | None, error: str | None) -> str:
    """One line for the list: the error, else the report's first line."""
    text = (report or "").strip()
    return (error or (text.splitlines()[0] if text else ""))[:300]


def insert_automation(
    db: sqlite3.Connection,
    workspace_id: str,
    *,
    name: str,
    file: str,
    schedule: str,
    model: ModelSelection,
    agent: str | None = None,
    steps: list[dict[str, object]] | None = None,
    check_first: bool = False,
    variables: list[dict[str, object]] | None = None,
    policy: str = "skip_if_active",
    ticket: dict[str, object] | None = None,
) -> int:
    """A new automation. Its on/off goes straight to Hermes's job (sync_job's
    `want`); `enabled` is written only if Hermes doesn't take it (keep_request)."""
    at = now()
    cursor = db.execute(
        """INSERT INTO automations (workspace_id, name, file, schedule, model, enabled,
             created_at, updated_at, agent, steps, check_first, variables, policy, ticket)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            workspace_id,
            name,
            file,
            _checked_schedule(schedule),
            model.model_dump_json(),
            at,
            at,
            agent,
            dump_json(steps) if steps else None,
            int(check_first),
            dump_json(variables) if variables else None,
            policy,
            dump_json(ticket) if ticket else None,
        ),
    )
    return int(cursor.lastrowid or 0)


def update_automation(
    db: sqlite3.Connection,
    workspace_id: str,
    automation_id: int,
    *,
    name: str,
    schedule: str,
    model: ModelSelection,
    agent: str | None = None,
    steps: list[dict[str, object]] | None = None,
    check_first: bool = False,
    variables: list[dict[str, object]] | None = None,
    policy: str = "skip_if_active",
    ticket: dict[str, object] | None = None,
) -> bool:
    """Everything but the file name, which stays fixed once created. The
    instructions are in the file; schedule and the model are what the owner asks,
    until Hermes has them (see forget_request); on/off goes to Hermes directly."""
    return (
        db.execute(
            """UPDATE automations SET name = ?, schedule = ?, model = ?,
                 updated_at = ?, agent = ?, steps = ?, check_first = ?,
                 variables = ?, policy = ?, ticket = ?
               WHERE id = ? AND workspace_id = ?""",
            (
                name,
                _checked_schedule(schedule),
                model.model_dump_json(),
                now(),
                agent,
                dump_json(steps) if steps else None,
                int(check_first),
                dump_json(variables) if variables else None,
                policy,
                dump_json(ticket) if ticket else None,
                automation_id,
                workspace_id,
            ),
        ).rowcount
        > 0
    )


def delete_automation(db: sqlite3.Connection, workspace_id: str, automation_id: int) -> str | None:
    """Deletes the row and returns its file, for the caller to remove."""
    row = db.execute(
        "SELECT file FROM automations WHERE id = ? AND workspace_id = ?",
        (automation_id, workspace_id),
    ).fetchone()
    if not row:
        return None
    db.execute("DELETE FROM automations WHERE id = ?", (automation_id,))
    return str(row["file"])


# ---- the Hermes job and its runs --------------------------------------------------


def job_id(db: sqlite3.Connection, automation_id: int) -> str | None:
    row = db.execute(
        "SELECT hermes_job_id FROM automations WHERE id = ?", (automation_id,)
    ).fetchone()
    return str(row["hermes_job_id"]) if row and row["hermes_job_id"] else None


def set_job(
    db: sqlite3.Connection, automation_id: int, *, job: str | None, error: str | None
) -> None:
    db.execute(
        "UPDATE automations SET hermes_job_id = COALESCE(?, hermes_job_id), sync_error = ? WHERE id = ?",
        (job, error, automation_id),
    )


def clear_job(db: sqlite3.Connection, automation_id: int) -> None:
    db.execute("UPDATE automations SET hermes_job_id = NULL WHERE id = ?", (automation_id,))


def forget_request(
    db: sqlite3.Connection, automation_id: int, *, model: bool = False, name: bool = False
) -> None:
    """Hermes's job has the schedule now (and, for a one-agent job, the model; with
    `name`, the owner's name as the job's own name): AGOS keeps no copy of them.
    `enabled` and `name` can't be NULL: back to 0 / "", never read once Hermes has the
    job (only while sync_error says Hermes refused it)."""
    db.execute(
        "UPDATE automations SET schedule = '', enabled = 0 WHERE id = ?",
        (automation_id,),
    )
    if model:
        db.execute("UPDATE automations SET model = NULL WHERE id = ?", (automation_id,))
    if name:
        db.execute("UPDATE automations SET name = '' WHERE id = ?", (automation_id,))


def set_name(db: sqlite3.Connection, automation_id: int, name: str) -> None:
    """The owner's name held by AGOS while no Hermes job or route holds it (a
    route takes it from actions/hooks.py held_by_route), or a job Hermes refused."""
    db.execute("UPDATE automations SET name = ? WHERE id = ?", (name, automation_id))


def set_agent(db: sqlite3.Connection, automation_id: int, agent: str | None) -> None:
    """NULL once the agent's own Hermes cron holds the job (Hermes says who runs
    it); else the agent the owner picked, waiting for its profile (or the Co-Founder)."""
    db.execute("UPDATE automations SET agent = ? WHERE id = ?", (agent, automation_id))


def keep_request(
    db: sqlite3.Connection,
    automation_id: int,
    *,
    schedule: str,
    on: bool,
    agent: str | None,
    name: str | None = None,
) -> None:
    """Hermes didn't take a change: AGOS shows (and retries) this request until it does."""
    db.execute(
        "UPDATE automations SET schedule = ?, enabled = ?, agent = ? WHERE id = ?",
        (_checked_schedule(schedule), int(on), agent, automation_id),
    )
    if name:
        set_name(db, automation_id, name)


def set_catch_up(db: sqlite3.Connection, automation_id: int, catch_up: str) -> None:
    """A missed run: 'once' (NULL, the default) or 'skip' (actions/catch_up.py)."""
    db.execute(
        "UPDATE automations SET catch_up = ? WHERE id = ?",
        (None if catch_up == "once" else catch_up, automation_id),
    )


def set_manual_at(db: sqlite3.Connection, automation_id: int, at: str) -> None:
    """When the owner last started it by hand."""
    db.execute("UPDATE automations SET manual_at = ? WHERE id = ?", (at, automation_id))


def set_notice(db: sqlite3.Connection, automation_id: int, notice: str | None) -> None:
    """What the owner is told about it (None: nothing)."""
    db.execute("UPDATE automations SET notice = ? WHERE id = ?", (notice, automation_id))


def name_of_job(db: sqlite3.Connection, workspace_id: str, job_id: str) -> str:
    """The name of the workspace's automation that holds this Hermes job ("": none)."""
    found = db.execute(
        "SELECT name FROM automations WHERE workspace_id = ? AND hermes_job_id = ? LIMIT 1",
        (workspace_id, job_id),
    ).fetchone()
    return str(found["name"] or "") if found is not None else ""


def webhook_names(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every workspace's webhook automations (no Hermes job) that still keep a name."""
    return db.execute(
        "SELECT id, workspace_id, name FROM automations WHERE hermes_job_id IS NULL AND name != ''"
    ).fetchall()


def drop_webhook_name(
    db: sqlite3.Connection, workspace_id: str, automation_id: int, name: str
) -> None:
    """A webhook automation's name goes once its Hermes route holds it."""
    db.execute(
        """UPDATE automations SET name = '' WHERE id = ? AND workspace_id = ?
             AND hermes_job_id IS NULL AND name = ?""",
        (automation_id, workspace_id, name),
    )
