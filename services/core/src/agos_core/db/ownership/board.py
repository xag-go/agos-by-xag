"""Ownership of AGOS's tables: the board: holds, labels, folders, status cards, reviews, pipelines.

Part of the registry's TABLES (merged in order by db/ownership/tables.py); same
rules as db/ownership/__init__.py.

Must not: hold key or file entries (keys.py, files.py), or another area's tables.
"""

from __future__ import annotations

from agos_core.db.ownership.base import CHANGED, ID, MADE, WS, Table, agos, cols

__all__ = [
    "TABLES",
]

TABLES: dict[str, Table] = {
    "kanban_holds": Table(
        agos(
            "a Pause or Cancel of a card and its descendants (one row per hold): which "
            "Hermes cards it moved (`kanban schedule` / `kanban archive`, through Hermes's "
            "CLI) and from what status, so Resume releases exactly those (`kanban unblock`) "
            "and nothing the owner changed meanwhile (actions/holds.py)",
            "H: hermes_cli/kanban_db.py schedule_task / archive_task (one card at a time, no "
            "record of what one operator action held)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            root_card="the card whose subtree was held",
            action="pause or cancel",
            held="JSON list of {card, was} the hold moved",
            created_at=MADE,
            released_at="when Resume released it (a pause)",
        ),
        writer="db/kanban_holds.py",
    ),
    "labels": Table(
        agos(
            "a workspace's labels, step 58: a name, a colour and the folder that groups "
            "them (folders = label groups). Which cards carry a label is a block in each "
            "card's Hermes body (engine/threads.py LABELS_BLOCK), so the board stays one "
            "read and Hermes keeps the card's side",
            "H: hermes_cli/kanban_db.py tasks (no label, tag or folder column; tenant is a "
            "namespace, not a label); Paperclip labels / issue_labels / folders",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            name="the label's name (unique in the workspace)",
            color="its colour name (the web's palette)",
            folder="the folder (label group) it is in; '' = none",
            created_at=MADE,
        ),
        writer="db/labels.py",
    ),
    "folders": Table(
        agos(
            "the owner's folders that group a workspace's automations, skills or projects "
            "on his pages (actions/folders.py): pure organization, one level, per kind. "
            "Hermes runs nothing differently and no file moves: a skill's category folder "
            "on disk is Hermes's own and stays as it is",
            "H: tools/skill_manager_tool.py (category = where the skill's files live, a "
            "move on disk); cron/jobs.py (no group or folder on a job)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            kind="automation | skill | project: which list the folder belongs to",
            name="the folder's name (unique per workspace and kind)",
            created_at=MADE,
        ),
    ),
    "folder_items": Table(
        agos(
            "which folder each automation, skill or project is in (one at most); the "
            "foreign keys drop the row when the item or the folder goes",
        ),
        cols(
            folder_id="the folder (folders.id)",
            automation_id="an automation in it (automations.id)",
            skill_id="a skill in it (library_items.id)",
            project_id="a project in it (goals.id, level project)",
        ),
    ),
    "status_cards": Table(
        agos(
            "a status card's definition, step 55: its title, its scope (the workspace, a "
            "goal, a project, a member, or the cards with some words) and its update policy; "
            "its time is its Hermes cron job's schedule (the Co-Founder's cron), its change "
            "detection Hermes's monitor state, its summary and revisions files in the "
            "workspace folder (status/<id>/summary.md, actions/status_cards.py)",
            "H: cron/jobs.py create_job (schedule, prompt, monitor_script: no scope, no "
            "summary document); cron/monitor.py monitor_state (only the last output's hash)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            title="the card's title",
            scope="workspace, goal, project, member or query",
            scope_ref="the goal / project id, the member's name or the words",
            policy="daily, weekly or manual (on demand: only Refresh now wakes its job)",
            refresh_asked_at=(
                "when the owner last asked Refresh now, until the Co-Founder writes; its "
                "monitor script prints it so Hermes sees a change and wakes the agent"
            ),
            created_at=MADE,
            updated_at=CHANGED,
        ),
        writer="db/status_cards.py",
    ),
    "card_doc_annotations": Table(
        agos(
            "the owner's passage comments on a card's document (a file in the workspace "
            "folder: cards/<card>/<key>.md, actions/card_docs.py) and where each one is "
            "after every revision (active / stale / orphaned, engine/card_docs.py reanchor)",
            "H: hermes_cli/kanban_db.py task_comments (a comment on a card, anchored in "
            "nothing); tools/file_tools.py (reads and writes files, no comment on a passage)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            card="the Hermes card the document belongs to",
            key="the document (its file name without .md)",
            revision="the document's revision the comment was made on",
            quote="the passage as it was then",
            prefix="the letters before it then",
            suffix="the letters after it then",
            pos_start="where the passage starts in the anchored revision",
            pos_end="where it ends there",
            body="the comment",
            author="who wrote it",
            anchor="active, stale or orphaned after the last revision",
            anchored_revision="the revision the positions are for",
            resolved_at="when the owner resolved it",
            created_at=MADE,
            updated_at=CHANGED,
        ),
        writer="db/card_doc_annotations.py",
    ),
    "artifact_reviews": Table(
        agos(
            "the owner's review of an artifact on the Artifacts page: a Hermes card "
            "attachment or a card document (approved / needs work, with a note)",
            "H: hermes_cli/kanban_db.py task_attachments (filename, stored_path, uploaded_by: "
            "no review state)",
        ),
        cols(
            workspace_id=WS,
            artifact="attachment:<card>:<id> or document:<card>:<key>",
            state="approved or needs_work",
            note="his words with it",
            updated_at=CHANGED,
        ),
        writer="db/artifact_reviews.py",
    ),
    "feedback_votes": Table(
        agos(
            "the owner's 👍 / 👎 on an agent's reply or on a document revision, with his "
            "note; each one is also said into the workspace's Hermes learning conversation "
            "(actions/learning.py), the row only shows the vote on the item",
            "H: hermes_state_messages.py (a message row has no rating); "
            "tools/checkpoint_manager.py (no rating on a file snapshot)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            kind="reply or revision",
            ref="<chat>:<message> or <card>:<key>:<revision>",
            vote="1 (👍) or -1 (👎)",
            note="his words with a 👎 (optional)",
            created_at=MADE,
        ),
        writer="db/feedback_votes.py",
    ),
    "pipeline_rules": Table(
        agos(
            "a workspace's pipeline rule, step 59: when a card moves to a status (or a "
            "review stage approves, or a plan is accepted) in a project or with a #label, "
            "do one thing (a follow-up card for a member with Hermes's idempotency key "
            "agos-pipe:<rule>:<card>, a comment, an assignment, an automation's Run now, a "
            "note to the owner); the card, its moves and what the rule made stay on Hermes's "
            "board (actions/pipelines.py)",
            "H: hermes_cli/kanban_workflow.py DEFAULT_WORKFLOW (columns and the manual move "
            "matrix only, no action on a move); hermes_cli/plugins.py VALID_HOOKS "
            "kanban_task_completed / on_kanban_task_updated (observers with no rule store)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            name="the rule's name as the owner wrote it",
            trigger="status, review_approved or plan_accepted",
            status="the Hermes column a status rule waits for",
            goal_id="only cards serving this goal or project (its '## Goal' line), or none",
            label="only cards with this #label in their title or text, or none",
            action="follow_up, comment, assign, run_automation or notify",
            member="the member a follow-up card or an assignment goes to",
            automation_id="the automation run_automation runs",
            text="the follow-up card's text, the comment, or the note",
            enabled="on or off",
            last_fired_at="when the rule last acted (shown on Settings → Pipelines)",
            last_outcome="what it did then, or why it couldn't",
            created_at=MADE,
            updated_at=CHANGED,
        ),
        writer="db/pipelines.py",
    ),
    "pipeline_seen": Table(
        agos(
            "the last move a card's pipeline rules acted on (its status, its last review "
            "approve marker, its last plan accept marker), compared and set in one write so "
            "a Kanban hook Hermes fires from two processes acts once",
            "H: hermes_cli/kanban_db.py _fire_task_hook (fired in whichever process "
            "committed, no delivery record); task_events (no per-observer cursor)",
        ),
        cols(
            workspace_id=WS,
            card="the Hermes card",
            kind="status, review or plan",
            mark="the status, or the marker comment, last acted on",
            seen_at=MADE,
        ),
        writer="db/pipelines.py",
    ),
    "card_services": Table(
        agos(
            "a dev server / preview a card's worker started with its agos_service tool, "
            "step 59: Hermes runs it as its own background process (terminal background, "
            "persist_on_release); AGOS keeps the card, the port its preview link points to, "
            "and the pid so Stop works after the worker's run ended",
            "H: tools/process_registry_checkpoint.py _write_checkpoint (processes.json: "
            "rewritten by whichever process of the profile writes last, no port, no card)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            card="the Hermes card whose worker started it",
            profile="the Hermes profile that runs it (the worker's)",
            process_id="Hermes's background process session id (proc_...)",
            pid="the process id Hermes gave",
            pid_scope="host or sandbox (Hermes's pid_scope)",
            started_mark="the pid's start time on this machine, so a reused pid is never stopped",
            command="the command as the worker gave it (secrets masked by Hermes's redact)",
            port="the port the preview link opens",
            label="the worker's short name for it",
            started_at=MADE,
            stopped_at="when it was stopped or found gone",
        ),
        writer="db/card_services.py",
    ),
    "member_readiness": Table(
        agos(
            "step 62: the owner's own choices on a new member's Readiness checklist (Start "
            "anyway, Not needed with his reason, Skip test) and each onboarding test's "
            "grade (passed / failed with the grader's notes, one row per test card). The "
            "kit itself is the member's Hermes profile fact (profile.yaml ui_meta.agos.kit) "
            "and every item's state is derived from real checks, never stored",
            "H: hermes_cli/profiles.py (a profile has no readiness or onboarding record); "
            "hermes_cli/kanban_db.py (a card has no grade); the grader agos-grade only "
            "answers (agos_guard/grade.py), it keeps nothing",
        ),
        cols(
            workspace_id=WS,
            member="the member's name (its profile a-<name>)",
            item="the checklist item (skill:<name>, tool:<name>, doc:<path>, member, "
            "onboarding) or onboard:<card> for a test's grade",
            choice="start_anyway / not_needed / skip_test (the owner's) or passed / failed "
            "(the grader's)",
            reason="the owner's reason, or the grader's notes",
            created_at=MADE,
        ),
    ),
}
