"""Owner-facing copy from the core never names the engine.

Spec docs/specs/2026-11-04-no-engine-name.md (section 5): every owner-visible
text the core produces — setting titles/descriptions/hints it writes or serves,
"Set by AGOS" reasons, ActionError messages and hints, activity labels,
inbox/proposal texts, notification and report texts — explains what happens
without the word "Hermes".

Scope: the modules listed in MODULES (the owner-copy sources swept for the
spec), not the whole tree. Developer-facing text is out of scope and skipped
by the scan itself:
- docstrings and comments (comments never reach the AST),
- log lines (string arguments of ``log.debug/info/warning/error/...`` calls),
- identifiers (``HermesEngine``, ``saveHermesSetting``: no word boundary, so
  the ``\\bHermes\\b`` pattern never matches them).

Only exception (the spec's one): the "Import from Hermes" features keep the
name, because there the owner's own Hermes install genuinely is the source.
Each kept text is listed in ALLOWED below, per file, verbatim.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agos_core"

# \bHermes\b: the word itself ("Hermes's", "a Hermes root"), never identifiers
# (HermesEngine, saveHermesSetting have word characters around it).
WORD = re.compile(r"\bHermes\b")

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}

# The owner-copy sources swept for the spec. A module belongs here when its
# string literals include owner-visible text (errors, hints, titles,
# descriptions, notifications, report lines). The sibling lanes' modules are
# integrated and scanned too: the updates modules (actions/agos_update.py,
# actions/hermes_update.py, actions/skill_updates.py, actions/updates.py,
# engine/hermes_update.py), the health modules (actions/hermes_health.py,
# api/settings_health.py), the errors modules (actions/errors.py,
# actions/error_alerts.py, actions/error_issues.py, actions/hermes_errors.py,
# engine/mcp_errors.py, api/errors.py, api/error_bodies.py). Not listed on
# purpose: engine/identity.py — it composes the agents' own prompt, which is
# agent-facing and names the engine by design (it carries the 'Never say
# "Hermes" to the owner' rule); its one owner-visible error is worded without
# the name and pinned by test_identity.py.
MODULES = [
    # actions/: ActionError messages, hints, audit and notification texts
    "actions/access.py",
    "actions/agos_update.py",
    "actions/artifacts.py",
    "actions/autonomy.py",
    "actions/backups.py",
    "actions/browse.py",
    "actions/capabilities.py",
    "actions/card_services.py",
    "actions/cofounder_hermes.py",
    "actions/contract_alert.py",
    "actions/diagnostics.py",
    "actions/error_alerts.py",
    "actions/error_issues.py",
    "actions/errors.py",
    "actions/heartbeat.py",
    "actions/held_writes.py",
    "actions/hermes_errors.py",
    "actions/hermes_fallback.py",
    "actions/hermes_health.py",
    "actions/hermes_helper_models.py",
    "actions/hermes_limits.py",
    "actions/hermes_managed.py",
    "actions/hermes_settings.py",
    "actions/hermes_time_limits.py",
    "actions/hermes_update.py",
    "actions/hermes_voice.py",
    "actions/holds.py",
    "actions/identity.py",
    "actions/key_pools.py",
    "actions/memory_plugin.py",
    "actions/ongoing.py",
    "actions/owner_gate.py",
    "actions/owner_time.py",
    "actions/rhythm.py",
    "actions/secrets_check.py",
    "actions/security_events.py",
    "actions/skill_requests.py",
    "actions/skill_tests.py",
    "actions/skill_updates.py",
    "actions/skill_writes.py",
    "actions/team.py",
    "actions/telegram_people.py",
    "actions/threads.py",
    "actions/tool_keys.py",
    "actions/tool_search.py",
    "actions/tool_services.py",
    "actions/trusted_apps.py",
    "actions/updates.py",
    "actions/vision_notes.py",
    "actions/workspaces.py",
    # actions/services/: the service layer's owner-facing errors and texts
    "actions/services/automation/cron.py",
    "actions/services/automation/jobs.py",
    "actions/services/automation/owner.py",
    "actions/services/board/card_bulk.py",
    "actions/services/board/card_writes.py",
    "actions/services/board/kanban_cli.py",
    "actions/services/channel/bot_setup.py",
    "actions/services/channel/connections.py",
    "actions/services/channel/topics.py",
    "actions/services/chat/gateway_turns.py",
    "actions/services/chat/history.py",
    "actions/services/chat/room_turns.py",
    "actions/services/cofounder/settings_actions.py",
    "actions/services/cofounder/skill_kinds.py",
    "actions/services/connector/nous_apps.py",
    "actions/services/connector/workspace_apps.py",
    "actions/services/hire/onboarding.py",
    "actions/services/hire/readiness.py",
    "actions/services/library/catalog.py",
    "actions/services/library/github_token.py",
    "actions/services/library/growth_candidates.py",
    "actions/services/library/lifecycle.py",
    "actions/services/library/mcp_test.py",
    "actions/services/library/skills_hub.py",
    "actions/services/library/sources.py",
    "actions/services/portability/export.py",
    "actions/services/proposals/hiring.py",
    "actions/services/settings/hermes_policy.py",
    "actions/services/settings/hermes_rows.py",
    "actions/services/settings/hermes_targets.py",
    "actions/services/settings/hermes_writes.py",
    "actions/services/settings/model_catalog.py",
    "actions/services/settings/model_keys.py",
    "actions/services/settings/model_logins.py",
    "actions/services/system/workspace_log.py",
    # engine/: errors and the setting catalog texts the core serves
    "engine/apps.py",
    "engine/automation_run.py",
    "engine/backup.py",
    "engine/cron.py",
    "engine/envfile.py",
    "engine/github_token.py",
    "engine/hermes_redact.py",
    "engine/hermes_reports.py",
    "engine/hermes_tools.py",
    "engine/hermes_update.py",
    "engine/library.py",
    "engine/mcp_errors.py",
    "engine/models.py",
    "engine/owner_choices.py",
    "engine/provider_keys.py",
    "engine/provider_login.py",
    "engine/rules.py",
    "engine/skill_frontmatter.py",
    "engine/skill_versions.py",
    "engine/sources.py",
    "engine/telegram_setup.py",
    "engine/threads.py",
    "engine/time_limits.py",
    "engine/tool_keys.py",
    "engine/settings_schema/env.py",
    "engine/settings_schema/extras.py",
    "engine/settings_schema/fields.py",
    "engine/settings_schema/groups.py",
    "engine/settings_schema/read_cache.py",
    "engine/hermes/commands.py",
    "engine/hermes/gateway_run.py",
    "engine/hermes/gateway_unit.py",
    "engine/hermes/profiles.py",
    "engine/hermes/sessions.py",
    "engine/hermes/tools.py",
    "engine/hermes/webhooks.py",
    # api/: response texts and error bodies the web shows as-is
    "api/agos_update.py",
    "api/error_bodies.py",
    "api/errors.py",
    "api/hermes_update.py",
    "api/settings_health.py",
    "api/updates.py",
    # hermes_gateway/: the gateway's owner-visible failure texts
    "hermes_gateway/chat_sessions.py",
    "hermes_gateway/errors.py",
]

# The spec's only exception: "Import from Hermes" texts keep the name.
ALLOWED: dict[str, list[str]] = {
    # Library → Import from Hermes (skills read from the machine's own install)
    "engine/sources.py": ["That skill isn't in this machine's Hermes skills."],
    # Connectors / Capabilities → Import from Hermes (the owner's Nous apps)
    "actions/services/connector/workspace_apps.py": [
        "Apps connected to your Nous account in Hermes."
    ],
}


def _skipped_ids(tree: ast.AST) -> set[int]:
    """Constants the scan ignores: docstrings, log-call arguments, and regex
    patterns handed to ``re.compile`` (they parse the engine's own output —
    e.g. its version banner — and are never shown to the owner)."""
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                skip.add(id(body[0].value))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and (
                node.func.attr in LOG_METHODS
                or (
                    node.func.attr == "compile"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re"
                )
            )
        ):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    skip.add(id(sub))
    return skip


def _offenders(rel: str) -> list[str]:
    path = SRC / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = _skipped_ids(tree)
    allowed = ALLOWED.get(rel, [])
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
            and WORD.search(node.value)
            and not any(a in node.value for a in allowed)
        ):
            shown = node.value.replace("\n", "\\n")[:120]
            out.append(f"{rel}:{node.lineno}: {shown}")
    return out


def test_modules_exist() -> None:
    missing = [rel for rel in MODULES if not (SRC / rel).is_file()]
    assert not missing, f"owner-copy modules moved: {missing}"


def test_allowlist_is_in_scanned_modules() -> None:
    stale = [rel for rel in ALLOWED if rel not in MODULES]
    assert not stale, f"ALLOWED entries outside MODULES: {stale}"


def test_owner_copy_never_names_the_engine() -> None:
    found: list[str] = []
    for rel in MODULES:
        found.extend(_offenders(rel))
    assert not found, (
        f"{len(found)} owner-facing string(s) name the engine "
        f"(reword without 'Hermes', spec 2026-11-04-no-engine-name):\n" + "\n".join(found)
    )
