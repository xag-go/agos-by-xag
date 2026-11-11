"""Every server action of the web app (apps/web/src/features/**/(actions|*-actions).ts)
mapped to the Co-Founder's way of doing it (DO) or marked a read (READS); the
owner-only exceptions are engine/cofounder_owner_only.py. tests/test_cofounder_parity.py
fails on a web action these tables don't know.

Owns: the web-action map. Must not: define kinds (cofounder_parity/catalog.py).
"""

from __future__ import annotations

from agos_core.engine.cofounder_parity.prefs import PREFS_DO
from agos_core.ops import catalog
from agos_core.ops.specs import SPECS

__all__ = ["DO", "READS"]

# ---- every web server action -> how the Co-Founder does it -----------------------------
# "do:<kind>" = an agos_action kind (the old ones in engine/cofounder_actions.py ACTIONS,
# the new ones in catalog.py); "tool:<name>" = one of AGOS's own Hermes tools (agos_guard);
# "hermes:<name>" = one of Hermes's own tools.

DO: dict[str, str] = {
    # automations (setup/actions.ts, pipelines/actions.ts)
    "saveAutomation": "do:update_automation",
    "toggleAutomation": "do:pause_automation",
    "deleteAutomation": "do:delete_automation",
    "runAutomationNow": "do:run_automation",
    "setCofounderHeartbeat": "do:set_heartbeat",
    "saveHook": "do:update_automation",
    # team (workers, search palette)
    "setReportsTo": "do:update_agent",
    "suggestHires": "tool:agos_propose",
    "finishFounderTask": "do:founder_done",
    "askToHire": "do:hire_agent",
    "suggestKits": "do:suggest_member_kit",
    # library and skills
    # (a NEW agent from it is the owner's own hire, /hires: the Co-Founder's is
    # hire_agent, always a card he approves; never create_agent)
    "saveLibraryItem": "do:update_skill",
    "setConnector": "tool:agos_capability",
    "setWorkspaceApp": "tool:agos_capability",
    # board, cards, reviews, documents, status cards
    "createCard": "hermes:kanban_create",
    "commentOnCard": "hermes:kanban_comment",
    "attachToCard": "hermes:kanban_attach",
    "assignCard": "do:assign_card",
    "actOnCard": "do:card_action",
    "estimateCard": "do:estimate_card",
    "setCardGoal": "do:set_card_goal",
    "setCardLabels": "tool:agos_label",
    "bulkCards": "do:bulk_cards",
    "watchCard": "do:watch_card",
    "saveBoardView": "do:save_board_view",
    "deleteBoardView": "do:delete_board_view",
    "createLabel": "do:create_label",
    "updateLabel": "do:update_label",
    "deleteLabel": "do:delete_label",
    "renameLabelFolder": "do:rename_label_folder",
    # folders (folders/actions.ts)
    "createFolder": "do:create_folder",
    "renameFolder": "do:rename_folder",
    "deleteFolder": "do:delete_folder",
    "moveToFolder": "do:move_to_folder",
    "decideReview": "tool:agos_review",
    "setReviewRules": "do:set_card_review",
    "saveReviewSettings": "do:save_review_settings",
    "stopCardService": "tool:agos_service",
    "saveCardDoc": "tool:agos_card_document",
    "restoreCardDoc": "do:restore_card_doc",
    "resolveAnnotation": "do:resolve_doc_comment",
    "holdSubtree": "do:hold_cards",
    "resumeHold": "do:resume_hold",
    "addStatusCard": "do:create_status_card",
    "saveStatusCard": "do:update_status_card",
    "deleteStatusCard": "do:delete_status_card",
    "refreshStatusCard": "do:refresh_status_card",
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
    "saveWorkHours": "do:set_work_hours",
    "setStayOnToday": "do:stay_on_today",
    "wakeNow": "do:wake_now",
    # docs, agents' history
    "saveDoc": "do:update_doc",
    "newDoc": "do:update_doc",
    "deleteDoc": "do:delete_doc",
    "restoreVersion": "do:restore_doc_version",
    "setLatinOnly": "do:set_latin_only",
    # owner rules and the Brain
    "addOwnerRule": "do:add_owner_rule",
    "editOwnerRule": "do:edit_owner_rule",
    "deleteOwnerRule": "do:delete_owner_rule",
    "addMethod": "do:add_method",
    "editMethod": "do:edit_method",
    "deleteMethod": "do:delete_method",
    "setMethodHere": "do:set_method_here",
    # keys, apps
    "connectApp": "tool:agos_capability",
    "addPoolKey": "do:add_pool_key",
    "removePoolKey": "do:remove_pool_key",
    "movePoolKey": "do:move_pool_key",
    "setPoolStrategy": "do:set_pool_strategy",
    # channels
    "setTeamGroup": "do:set_team_group",
    "setBotReactions": "do:set_bot_reactions",
    "addAddress": "do:add_chat_address",
    "removeAddress": "do:remove_chat_address",
    "approvePerson": "do:approve_person",
    "removePerson": "do:remove_person",
    # templates, artifacts
    "reviewArtifact": "do:review_artifact",
    "promoteArtifact": "do:promote_artifact",
    # settings, Hermes
    **PREFS_DO,
    "runHermesHealth": "do:hermes_health",
    "runSecretsCheck": "do:secrets_check",
    "setBackupSchedule": "do:set_backup_schedule",
    "runBackup": "do:run_backup",
    "rehearseRestore": "do:rehearse_restore",
    "undoLearned": "do:undo_learned",
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
