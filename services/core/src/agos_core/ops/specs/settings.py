"""The Settings service's Co-Founder kinds: the workspace's settings, Hermes's limits
and time limits, helper models, voice, the fallback chain (actions/settings_ops.py
binds them to the Co-Founder's page actions).

Each kind was a hand-written row of engine/cofounder_parity; declared here once, it
becomes the Co-Founder's kind, its read-vs-act row and its do / undo through the
registry (permission, workspace scope, audit row). Inputs keep the Co-Founder's own
loose fields (`CofounderFields`: its page action reads them as before).

Owns: these declarations and their input models. Must not: hold the steps (the
service's own page actions do).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import WORKSPACE
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = [
    "CHECK_UPDATES",
    "RUN_UPDATES",
    "SET_FALLBACK",
    "SET_HELPER_MODELS",
    "SET_HERMES_LIMITS",
    "SET_TIME_LIMITS",
    "SET_VOICE",
    "SET_WORKSPACE_SETTINGS",
    "SPECS",
    "CheckUpdates",
    "RunUpdates",
    "SetFallback",
    "SetHelperModels",
    "SetHermesLimits",
    "SetTimeLimits",
    "SetVoice",
    "SetWorkspaceSettings",
]


class SetWorkspaceSettings(CofounderFields):
    model: Any = None
    name: Any = None
    description: Any = None
    values: Any = None


SET_WORKSPACE_SETTINGS: OperationSpec[SetWorkspaceSettings] = OperationSpec(
    name="set_workspace_settings",
    input_model=SetWorkspaceSettings,
    audit_title="This workspace's settings",
    gate="undo",
    agent_tool=None,
    web_action="saveWorkspaceSettings",
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "model (its default model: the model id, or {provider, model, effort}), name, "
        "description, values (object: the page's other engine settings keys)"
    ),
    cofounder_structured=("values",),
)


class SetHermesLimits(CofounderFields):
    loop_on: Any = None
    same_error: Any = None
    same_tool_failing: Any = None
    no_progress: Any = None
    time_limit_minutes: Any = None
    members_at_once: Any = None


SET_HERMES_LIMITS: OperationSpec[SetHermesLimits] = OperationSpec(
    name="set_hermes_limits",
    input_model=SetHermesLimits,
    audit_title="Loop detector & limits",
    gate="undo",
    agent_tool=None,
    web_action="saveHermesLimits",
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "loop_on, same_error, same_tool_failing, no_progress, time_limit_minutes, "
        'members_at_once (each optional; "" = the engine\'s default)'
    ),
)


class SetTimeLimits(CofounderFields):
    values: Any


SET_TIME_LIMITS: OperationSpec[SetTimeLimits] = OperationSpec(
    name="set_time_limits",
    input_model=SetTimeLimits,
    audit_title="Time limits",
    gate="undo",
    agent_tool=None,
    web_action="saveHermesTimeLimits",
    cofounder_domain=WORKSPACE,
    cofounder_fields="values (object: key -> seconds)",
    cofounder_structured=("values",),
)


class SetHelperModels(CofounderFields):
    sets: Any = None
    unsets: Any = None
    picks: Any = None


SET_HELPER_MODELS: OperationSpec[SetHelperModels] = OperationSpec(
    name="set_helper_models",
    input_model=SetHelperModels,
    audit_title="Helper models",
    gate="owner",
    agent_tool=None,
    web_action="saveHermesHelperModels",
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "sets (object key -> value), unsets (keys), picks (object task -> {provider, model} | null)"
    ),
    cofounder_structured=("sets", "unsets", "picks"),
)


class SetVoice(CofounderFields):
    provider: Any
    model: Any = None


SET_VOICE: OperationSpec[SetVoice] = OperationSpec(
    name="set_voice",
    input_model=SetVoice,
    audit_title="Voice notes: {provider} {model}",
    gate="undo",
    agent_tool=None,
    web_action="saveHermesVoice",
    cofounder_domain=WORKSPACE,
    cofounder_fields="provider, model",
)


class SetFallback(CofounderFields):
    chain: Any


SET_FALLBACK: OperationSpec[SetFallback] = OperationSpec(
    name="set_fallback",
    input_model=SetFallback,
    audit_title="Fallback models",
    gate="undo",
    agent_tool=None,
    web_action="saveHermesFallback",
    cofounder_domain=WORKSPACE,
    cofounder_fields="chain ([{provider, model, base_url}], in order)",
    cofounder_structured=("chain",),
)


class CheckUpdates(CofounderFields):
    pass


CHECK_UPDATES: OperationSpec[CheckUpdates] = OperationSpec(
    name="check_updates",
    input_model=CheckUpdates,
    audit_title="Check for updates",
    gate="once",
    agent_tool=None,
    effect="read",
    web_action="checkUpdates",
    cofounder_domain=WORKSPACE,
    cofounder_fields="(no fields)",
)


class RunUpdates(CofounderFields):
    pass


RUN_UPDATES: OperationSpec[RunUpdates] = OperationSpec(
    name="run_updates",
    input_model=RunUpdates,
    audit_title="Install the update",
    gate="owner",
    agent_tool=None,
    web_action="runUpdates",
    cofounder_domain=WORKSPACE,
    cofounder_fields="(no fields)",
)

SPECS: tuple[OperationSpec[Any], ...] = (
    SET_WORKSPACE_SETTINGS,
    SET_HERMES_LIMITS,
    SET_TIME_LIMITS,
    SET_HELPER_MODELS,
    SET_VOICE,
    SET_FALLBACK,
    CHECK_UPDATES,
    RUN_UPDATES,
)
