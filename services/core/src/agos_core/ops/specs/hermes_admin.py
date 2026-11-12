"""The Co-Founder's kinds for the engine's own settings and stores: one setting, held-back
writes, key pools, Health and the secrets check (actions/cofounder_hermes.py runs them).
"""

from __future__ import annotations

from typing import Any

from agos_core.engine.cofounder_kind import CHAT
from agos_core.ops.spec import CofounderFields, OperationSpec

__all__ = ["SPECS"]


class ChangeHermesSetting(CofounderFields):
    key: Any


CHANGE_HERMES_SETTING: OperationSpec[ChangeHermesSetting] = OperationSpec(
    name="change_hermes_setting",
    input_model=ChangeHermesSetting,
    audit_title="Engine setting {key} → {value}",
    gate="undo",
    agent_tool=None,
    web_action="saveHermesSetting",
    cofounder_domain=CHAT,
)


class ResetHermesSetting(CofounderFields):
    key: Any


RESET_HERMES_SETTING: OperationSpec[ResetHermesSetting] = OperationSpec(
    name="reset_hermes_setting",
    input_model=ResetHermesSetting,
    audit_title="Engine setting {key} back to its default",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class ShowHermesSetting(CofounderFields):
    key: Any


SHOW_HERMES_SETTING: OperationSpec[ShowHermesSetting] = OperationSpec(
    name="show_hermes_setting",
    input_model=ShowHermesSetting,
    audit_title="Engine setting {key}",
    gate="once",
    agent_tool=None,
    effect="read",
    cofounder_domain=CHAT,
)


class ApproveHeldWrite(CofounderFields):
    id: Any


APPROVE_HELD_WRITE: OperationSpec[ApproveHeldWrite] = OperationSpec(
    name="approve_held_write",
    input_model=ApproveHeldWrite,
    audit_title="Approve held-back write {id}",
    gate="owner",
    agent_tool=None,
    cofounder_domain=CHAT,
    undo_after_yes=True,
)


class RejectHeldWrite(CofounderFields):
    id: Any


REJECT_HELD_WRITE: OperationSpec[RejectHeldWrite] = OperationSpec(
    name="reject_held_write",
    input_model=RejectHeldWrite,
    audit_title="Reject held-back write {id}",
    gate="undo",
    agent_tool=None,
    cofounder_domain=CHAT,
)


class ListHeldWrites(CofounderFields):
    pass


LIST_HELD_WRITES: OperationSpec[ListHeldWrites] = OperationSpec(
    name="list_held_writes",
    input_model=ListHeldWrites,
    audit_title="Memory changes in the Inbox",
    gate="once",
    agent_tool=None,
    effect="read",
    cofounder_domain=CHAT,
)


class AddPoolKey(CofounderFields):
    provider: Any
    key: Any


ADD_POOL_KEY: OperationSpec[AddPoolKey] = OperationSpec(
    name="add_pool_key",
    input_model=AddPoolKey,
    audit_title="Add a key to the {provider} pool",
    gate="undo",
    agent_tool=None,
    web_action="addPoolKey",
    cofounder_domain=CHAT,
)


class RemovePoolKey(CofounderFields):
    provider: Any
    label: Any


REMOVE_POOL_KEY: OperationSpec[RemovePoolKey] = OperationSpec(
    name="remove_pool_key",
    input_model=RemovePoolKey,
    audit_title="Remove key “{label}” from the {provider} pool",
    gate="undo",
    agent_tool=None,
    web_action="removePoolKey",
    cofounder_domain=CHAT,
)


class MovePoolKey(CofounderFields):
    provider: Any
    label: Any
    position: Any


MOVE_POOL_KEY: OperationSpec[MovePoolKey] = OperationSpec(
    name="move_pool_key",
    input_model=MovePoolKey,
    audit_title="Move key “{label}” to place {position} in the {provider} pool",
    gate="undo",
    agent_tool=None,
    web_action="movePoolKey",
    cofounder_domain=CHAT,
)


class SetPoolStrategy(CofounderFields):
    provider: Any
    strategy: Any


SET_POOL_STRATEGY: OperationSpec[SetPoolStrategy] = OperationSpec(
    name="set_pool_strategy",
    input_model=SetPoolStrategy,
    audit_title="{provider} pool: pick keys by {strategy}",
    gate="undo",
    agent_tool=None,
    web_action="setPoolStrategy",
    cofounder_domain=CHAT,
)


class ListPoolKeys(CofounderFields):
    pass


LIST_POOL_KEYS: OperationSpec[ListPoolKeys] = OperationSpec(
    name="list_pool_keys",
    input_model=ListPoolKeys,
    audit_title="Keys per provider (the engine's pools)",
    gate="once",
    agent_tool=None,
    effect="read",
    cofounder_domain=CHAT,
)


class HermesHealth(CofounderFields):
    pass


HERMES_HEALTH: OperationSpec[HermesHealth] = OperationSpec(
    name="hermes_health",
    input_model=HermesHealth,
    audit_title="Engine checks (Status and Full check)",
    gate="once",
    agent_tool=None,
    effect="read",
    web_action="runHermesHealth",
    cofounder_domain=CHAT,
)


class SecretsCheck(CofounderFields):
    pass


SECRETS_CHECK: OperationSpec[SecretsCheck] = OperationSpec(
    name="secrets_check",
    input_model=SecretsCheck,
    audit_title="Secrets check (keys in chats and logs, file permissions)",
    gate="once",
    agent_tool=None,
    effect="read",
    web_action="runSecretsCheck",
    cofounder_domain=CHAT,
)


SPECS: tuple[OperationSpec[Any], ...] = (
    CHANGE_HERMES_SETTING,
    RESET_HERMES_SETTING,
    SHOW_HERMES_SETTING,
    APPROVE_HELD_WRITE,
    REJECT_HELD_WRITE,
    LIST_HELD_WRITES,
    ADD_POOL_KEY,
    REMOVE_POOL_KEY,
    MOVE_POOL_KEY,
    SET_POOL_STRATEGY,
    LIST_POOL_KEYS,
    HERMES_HEALTH,
    SECRETS_CHECK,
)
