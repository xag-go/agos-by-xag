"""The Portability service's Co-Founder kinds: a workspace's export and import (a
bundle .zip) (actions/portability_ops.py binds them to the Co-Founder's page
actions).

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
    "EXPORT_BUNDLE",
    "IMPORT_BUNDLE",
    "SPECS",
    "ExportBundle",
    "ImportBundle",
]


class ImportBundle(CofounderFields):
    path: Any
    inputs: Any = None
    later: Any = None
    strategies: Any = None


IMPORT_BUNDLE: OperationSpec[ImportBundle] = OperationSpec(
    name="import_bundle",
    input_model=ImportBundle,
    audit_title="Import the bundle {path}",
    gate="owner",
    agent_tool=None,
    web_action="importBundle",
    cofounder_domain=WORKSPACE,
    cofounder_fields="path (a .zip in the workspace), inputs (object), later (input names), strategies",
    cofounder_structured=("inputs", "later", "strategies"),
)


class ExportBundle(CofounderFields):
    path: Any = None


EXPORT_BUNDLE: OperationSpec[ExportBundle] = OperationSpec(
    name="export_bundle",
    input_model=ExportBundle,
    audit_title="Export this workspace as a bundle",
    gate="once",
    agent_tool=None,
    cofounder_domain=WORKSPACE,
    cofounder_fields=(
        "path (where the .zip goes in the workspace; leave out = "
        "exports/agos-<id>.zip). The same zip as Settings → Export / Import: team, "
        "skills, docs, automations, no secrets"
    ),
)

SPECS: tuple[OperationSpec[Any], ...] = (
    IMPORT_BUNDLE,
    EXPORT_BUNDLE,
)
