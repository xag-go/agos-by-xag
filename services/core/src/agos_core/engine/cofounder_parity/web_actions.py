"""Every server action of the web app (apps/web/src/features/**/(actions|*-actions).ts)
mapped to the Co-Founder's way of doing it (DO) or marked a read (READS); the
owner-only exceptions are engine/cofounder_owner_only.py. tests/test_cofounder_parity.py
fails on a web action these tables don't know.

Owns: the web-action map. Must not: define kinds (cofounder_parity/catalog.py).
"""

from __future__ import annotations

from agos_core.ops import catalog
from agos_core.ops.specs import SPECS

__all__ = ["DO", "READS"]

# ---- every web server action -> how the Co-Founder does it -----------------------------
# "do:<kind>" = an agos_action kind (the old ones in engine/cofounder_actions.py ACTIONS,
# the new ones in catalog.py); "tool:<name>" = one of AGOS's own Hermes tools (agos_guard);
# "hermes:<name>" = one of Hermes's own tools.

DO: dict[str, str] = {
    # automations (setup/actions.ts, pipelines/actions.ts)
    # team (workers, search palette)
    "suggestHires": "tool:agos_propose",
    # library and skills
    # (a NEW agent from it is the owner's own hire, /hires: the Co-Founder's is
    # hire_agent, always a card he approves; never create_agent)
    "setConnector": "tool:agos_capability",
    "setWorkspaceApp": "tool:agos_capability",
    # board, cards, reviews, documents, status cards
    "createCard": "hermes:kanban_create",
    "commentOnCard": "hermes:kanban_comment",
    "attachToCard": "hermes:kanban_attach",
    "setCardLabels": "tool:agos_label",
    # folders (folders/actions.ts)
    "decideReview": "tool:agos_review",
    "stopCardService": "tool:agos_service",
    "saveCardDoc": "tool:agos_card_document",
    # vision (goals keep their approval: agos_goals propose)
    "saveVision": "tool:agos_goals",
    "addGoal": "tool:agos_goals",
    "changeItem": "tool:agos_goals",
    "deleteItem": "tool:agos_goals",
    "addProject": "tool:agos_goals",
    "addResult": "tool:agos_goals",
    "changeResult": "tool:agos_goals",
    "deleteResult": "tool:agos_goals",
    # work hours (workspaces/work-hours-actions.ts)
    # docs, agents' history
    # owner rules and the Brain
    # keys, apps
    "connectApp": "tool:agos_capability",
    # channels
    # templates, artifacts
    # settings, Hermes
    "saveMemory": "hermes:memory",
    **catalog.web_do(SPECS),  # the registry's kinds (ops/specs), as declared
}

# Read-only server actions: nothing changes, nothing for the Co-Founder to do (it reads
# the same through its tools, files and AGOS's search).
READS: frozenset[str] = frozenset(
    {
        "readSkillVersions",
        "readRemoteAccess",
        "readSkillVersionDiff",
        "readSkillTests",
        "revisionText",
        "versionDiff",
        "statusRevision",
        "notesRevision",
        "agentRevisions",
        "listTemplates",
        "previewBundle",
        "paletteData",
        "paletteSearch",
        "searchChats",
        "hermesCommands",
        "scheduleText",
        "telegramPlaces",
        "readinessOf",
        "openCardDoc",
        "resolveLinks",
        "explainHeld",
        "callbackUrl",
        "composioToolkits",
        "composioAccounts",
        "composioAuthSetup",
        "githubTokenStatus",
        "mcpSignInStatus",
        "searchWeb",
        "inspectSkill",
        "testMcp",
        "toolKeyName",
        "botRestart",
        "pushKey",
    }
)
