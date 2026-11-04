"""The Settings, Automation, Library, Vision and Team pages' routers and services keep
to the service layer (ARCHITECTURE.md §10): the routers reach the database and
Hermes only through actions, the services never import a router, and the services
listed below hold no SQL of their own (it lives in their tables' repositories, db/).

The layer ratchet (scripts/layer_ratchet.py) counts the whole core; this pins the
modules already moved, so one of them can't slide back while the totals still fall.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

# Routers of these pages: no db (beyond the view models), engine, gateway, storage.
ROUTERS = [
    "api/apps.py",
    "api/automations.py",
    "api/capabilities.py",
    "api/connections.py",
    "api/founder.py",
    "api/library.py",
    "api/models.py",
    "api/office.py",
    "api/portability.py",
    "api/preferences.py",
    "api/routines.py",
    "api/settings_account.py",
    "api/settings_facts.py",
    "api/settings_health.py",
    "api/settings_hermes_all.py",
    "api/settings_hermes_limits.py",
    "api/settings_hermes_models.py",
    "api/skill_growth.py",
    "api/skill_studio.py",
    "api/tool_keys.py",
    "api/vision.py",
    "api/workers.py",
    "api/workspaces.py",
]
_BELOW_ACTIONS = ("db", "engine", "hermes_gateway", "storage", "security")
_DTO = {"agos_core.db.records"}

# Services that may not import a router.
SERVICES = [
    "actions/services/automation",
    "actions/services/cofounder",
    "actions/services/connector",
    "actions/services/hire",
    "actions/services/library",
    "actions/services/portability",
    "actions/services/proposals",
    "actions/services/settings",
    "actions/services/team",
    "actions/services/vision",
    "actions/services/workspace",
]


def _files(entries: list[str]) -> list[Path]:
    out: list[Path] = []
    for entry in entries:
        path = SRC / entry
        out += sorted(path.glob("*.py")) if path.is_dir() else [path]
    return out


def _imported(path: Path) -> list[tuple[int, str]]:
    """Every agos_core module this file imports (absolute imports; any depth)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found += [(node.lineno, f"{node.module}.{a.name}") for a in node.names]
    return [(n, m) for n, m in found if m.startswith("agos_core.")]


def _below(module: str) -> bool:
    parts = module.split(".")
    if len(parts) < 3 or parts[1] not in _BELOW_ACTIONS:
        return False
    return not any(module == d or module.startswith(d + ".") for d in _DTO)


def test_these_routers_reach_the_database_and_hermes_only_through_actions() -> None:
    hits = [
        f"{p.relative_to(SRC)}:{n} {m}"
        for p in _files(ROUTERS)
        for n, m in _imported(p)
        if _below(m)
    ]
    assert not hits, "a router reaches below actions:\n" + "\n".join(hits)


def test_these_services_never_import_a_router() -> None:
    hits = [
        f"{p.relative_to(SRC)}:{n} {m}"
        for p in _files(SERVICES)
        for n, m in _imported(p)
        if m.startswith("agos_core.api.")
    ]
    assert not hits, "a service imports a router:\n" + "\n".join(hits)


# Services whose tables have their repository (db/<table>.py): no SQL of their own.
SQL_FREE = [
    "actions/agent_profiles.py",
    "actions/artifacts.py",
    "actions/capabilities.py",
    "actions/composio.py",
    "actions/feedback.py",
    "actions/founder.py",
    "actions/hermes_fallback.py",
    "actions/hire_model.py",
    "actions/hire_review.py",
    "actions/hooks.py",
    "actions/mcp_tools.py",
    "actions/member_kits.py",
    "actions/member_profiles_gone.py",
    "actions/services/automation/jobs.py",
    "actions/services/automation/owner.py",
    "actions/services/automation/sync_loop.py",
    "actions/services/cofounder/action_cards.py",
    "actions/services/cofounder/agent_tools.py",
    "actions/services/cofounder/connection_actions.py",
    "actions/services/cofounder/folder_actions.py",
    "actions/services/cofounder/skill_kinds.py",
    "actions/services/cofounder/snapshots.py",
    "actions/services/cofounder/team_actions.py",
    "actions/services/connector",
    "actions/services/hire/kit_lifecycle.py",
    "actions/services/hire/kit_rules.py",
    "actions/services/hire/onboarding.py",
    "actions/services/hire/readiness.py",
    "actions/services/library/growth_candidates.py",
    "actions/services/library/growth_evidence.py",
    "actions/services/library/sharing.py",
    "actions/services/library/workspace_state.py",
    "actions/services/portability/export.py",
    "actions/services/portability/import_steps.py",
    "actions/services/proposals",
    "actions/services/proposals/proposal_states.py",
    "actions/services/settings",
    "actions/services/vision/plan_board.py",
    "actions/services/vision/plan_edits.py",
    "actions/services/vision/plan_rows.py",
    "actions/services/workspace",
    "actions/skill_requests.py",
    "actions/skills_move.py",
    "actions/team.py",
    "actions/teams_catalog.py",
    "actions/tool_keys.py",
    "actions/tool_services.py",
    "actions/vision_notes.py",
]


def _sql_calls(path: Path) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "executemany", "executescript")
    ]


def test_these_services_hold_no_sql_of_their_own() -> None:
    hits = [f"{p.relative_to(SRC)}:{n}" for p in _files(SQL_FREE) for n in _sql_calls(p)]
    assert not hits, "SQL outside its table's repository (db/):\n" + "\n".join(hits)
