"""The Connector service's Co-Founder kinds: tool keys (remove / test only: a key is
the owner's to paste) and apps (actions/connector_ops.py binds them to the Co-
Founder's page actions).

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
    "DISCONNECT_APP",
    "REMOVE_TOOL_KEY",
    "SPECS",
    "TEST_TOOL_KEY",
    "DisconnectApp",
    "RemoveToolKey",
    "TestToolKey",
]


class RemoveToolKey(CofounderFields):
    name: Any


REMOVE_TOOL_KEY: OperationSpec[RemoveToolKey] = OperationSpec(
    name="remove_tool_key",
    input_model=RemoveToolKey,
    audit_title="Remove the key {name}",
    gate="owner",
    agent_tool=None,
    web_action="removeToolKey",
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "name (the key's variable). You never add or replace a key: ask the owner "
        "(agos_ask_owner) to paste it in Settings → Keys"
    ),
)


class TestToolKey(CofounderFields):
    name: Any


TEST_TOOL_KEY: OperationSpec[TestToolKey] = OperationSpec(
    name="test_tool_key",
    input_model=TestToolKey,
    audit_title="Test the key {name}",
    gate="once",
    agent_tool=None,
    effect="work",
    web_action="testToolKey",
    cofounder_domain=WORKSPACE,
    cofounder_fields="name",
)


class DisconnectApp(CofounderFields):
    app: Any


DISCONNECT_APP: OperationSpec[DisconnectApp] = OperationSpec(
    name="disconnect_app",
    input_model=DisconnectApp,
    audit_title="Log out of {app} here",
    gate="owner",
    agent_tool=None,
    web_action="disconnectApp",
    cofounder_domain=WORKSPACE,
    cofounder_fields="app",
)

SPECS: tuple[OperationSpec[Any], ...] = (
    REMOVE_TOOL_KEY,
    TEST_TOOL_KEY,
    DISCONNECT_APP,
)
