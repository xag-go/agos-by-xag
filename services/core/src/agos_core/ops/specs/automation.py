"""The Automation service's Co-Founder kinds: card-move rules, heartbeats, an
automation's revisions and catch-up, scheduled jobs, the webhook address, watched
trees (actions/automation_ops.py binds them to the Co-Founder's page actions).

Each kind was a hand-written row of engine/cofounder_parity; declared here once, it
becomes the Co-Founder's kind, its read-vs-act row and its do / undo through the
registry (permission, workspace scope, audit row). Inputs keep the Co-Founder's own
loose fields (`CofounderFields`: its page action reads them as before).

Owns: these declarations and their input models. Must not: hold the steps (the
service's own page actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import AUTOMATIONS
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = [
    "AUTOMATION_COST",
    "DELETE_PIPELINE_RULE",
    "REMOVE_SCHEDULED_JOB",
    "RESTORE_AUTOMATION_REVISION",
    "SAVE_PIPELINE_RULE",
    "SET_AUTOMATION_CATCH_UP",
    "SET_HEARTBEAT",
    "SET_HOOKS_ADDRESS",
    "SPECS",
    "WATCH_TREE",
    "AutomationCost",
    "DeletePipelineRule",
    "RemoveScheduledJob",
    "RestoreAutomationRevision",
    "SavePipelineRule",
    "SetAutomationCatchUp",
    "SetHeartbeat",
    "SetHooksAddress",
    "WatchTree",
]


class SavePipelineRule(CofounderFields):
    rule: Any = None
    name: Any = None
    trigger: Any = None
    status: Any = None
    goal_id: Any = None
    label: Any = None
    action: Any = None
    member: Any = None
    automation: Any = None
    text: Any = None
    enabled: Any = None


SAVE_PIPELINE_RULE: OperationSpec[SavePipelineRule] = OperationSpec(
    name="save_pipeline_rule",
    input_model=SavePipelineRule,
    audit_title="Rule “{name}{rule}”",
    gate="undo",
    web_action="savePipelineRule",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields=(
        "rule (its number or name; leave out = a new rule), name, trigger (status | "
        "review_approved | plan_accepted), status (the column, for trigger status), "
        "goal_id, label, action (follow_up | comment | assign | run_automation | "
        "notify), member, automation (its name, for run_automation), text, enabled "
        "(false = paused)"
    ),
)


class DeletePipelineRule(CofounderFields):
    rule: Any


DELETE_PIPELINE_RULE: OperationSpec[DeletePipelineRule] = OperationSpec(
    name="delete_pipeline_rule",
    input_model=DeletePipelineRule,
    audit_title="Delete rule “{rule}”",
    gate="undo",
    web_action="deletePipelineRule",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields="rule",
)


class SetHeartbeat(CofounderFields):
    agent: Any
    on: Any = None
    interval: Any = None


SET_HEARTBEAT: OperationSpec[SetHeartbeat] = OperationSpec(
    name="set_heartbeat",
    input_model=SetHeartbeat,
    audit_title="Heartbeat of {agent}: {on} {interval}",
    gate="undo",
    web_action="setHeartbeat",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields=(
        "agent (a member's ID, or cofounder = you), on (true/false), interval (15m | "
        "1h | 4h | daily; not needed to turn it off)"
    ),
)


class RestoreAutomationRevision(CofounderFields):
    automation: Any
    revision: Any


RESTORE_AUTOMATION_REVISION: OperationSpec[RestoreAutomationRevision] = OperationSpec(
    name="restore_automation_revision",
    input_model=RestoreAutomationRevision,
    audit_title="Automation “{automation}” back to v{revision}",
    gate="undo",
    web_action="restoreRevision",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields="automation (its name), revision (the number from its History)",
)


class SetAutomationCatchUp(CofounderFields):
    automation: Any
    catch_up: Any


SET_AUTOMATION_CATCH_UP: OperationSpec[SetAutomationCatchUp] = OperationSpec(
    name="set_automation_catch_up",
    input_model=SetAutomationCatchUp,
    audit_title="Automation “{automation}”: a missed run → {catch_up}",
    gate="undo",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields=(
        "automation (its name), catch_up (once = a run missed while the server was off "
        "runs once when AGOS is back, the default | skip = it is skipped)"
    ),
)


class RemoveScheduledJob(CofounderFields):
    job: Any


REMOVE_SCHEDULED_JOB: OperationSpec[RemoveScheduledJob] = OperationSpec(
    name="remove_scheduled_job",
    input_model=RemoveScheduledJob,
    audit_title="Stop the scheduled job {job}",
    gate="owner",
    web_action="removeScheduled",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields="job (Hermes's job id, from Ongoing)",
)


class SetHooksAddress(CofounderFields):
    url: Any = None


SET_HOOKS_ADDRESS: OperationSpec[SetHooksAddress] = OperationSpec(
    name="set_hooks_address",
    input_model=SetHooksAddress,
    audit_title="Webhook public address: {url}",
    gate="undo",
    web_action="saveHooksAddress",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields='url (https://..., "" = none)',
)


class WatchTree(CofounderFields):
    card: Any
    on: Any = None


WATCH_TREE: OperationSpec[WatchTree] = OperationSpec(
    name="watch_tree",
    input_model=WatchTree,
    audit_title="Watch the card tree {card}: {on}",
    gate="undo",
    web_action="watchTree",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields="card, on (true/false)",
)


class AutomationCost(CofounderFields):
    automation: Any = None
    run: Any = None


AUTOMATION_COST: OperationSpec[AutomationCost] = OperationSpec(
    name="automation_cost",
    input_model=AutomationCost,
    audit_title="What “{automation}” cost",
    gate="once",
    effect="read",
    cofounder_domain=AUTOMATIONS,
    cofounder_fields=(
        "automation (its name or number; leave out = every automation), run (a run id "
        "from its Runs: that run step by step: who worked, who was skipped and why, how "
        "long, tokens and cost). Read only: what its runs cost this month and last month "
        "(UTC), as counted by the engine; an unpriced cost is said as unknown"
    ),
)


SPECS: tuple[OperationSpec[Any], ...] = (
    SAVE_PIPELINE_RULE,
    DELETE_PIPELINE_RULE,
    SET_HEARTBEAT,
    RESTORE_AUTOMATION_REVISION,
    SET_AUTOMATION_CATCH_UP,
    REMOVE_SCHEDULED_JOB,
    SET_HOOKS_ADDRESS,
    WATCH_TREE,
    AUTOMATION_COST,
)
