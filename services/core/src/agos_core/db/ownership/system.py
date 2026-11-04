"""Ownership of AGOS's tables: connectors, docs, logs, the Co-Founder's actions, goals, the inbox.

Part of the registry's TABLES (merged in order by db/ownership/tables.py); same
rules as db/ownership/__init__.py.

Must not: hold key or file entries (keys.py, files.py), or another area's tables.
"""

from __future__ import annotations

from agos_core.db.ownership.base import CHANGED, CHAT, ID, MADE, WS, Table, agos, cols

__all__ = [
    "TABLES",
]

TABLES: dict[str, Table] = {
    "connector_notes": Table(
        agos("the owner's notes on a connector in a workspace"),
        cols(workspace_id=WS, item_id="the library item", notes="his notes", updated_at=CHANGED),
    ),
    "workspace_app_logins": Table(
        agos(
            "Google/Composio sign-ins per workspace (Hermes connectors are Nous-account "
            "wide, which breaks 'no sharing between workspaces')",
            "H: website/docs/user-guide/features/tool-gateway.md:124-142",
        ),
        cols(
            workspace_id=WS,
            app="the app",
            status="connected or error",
            tools="the tools AGOS's own probe found (its own sign-in flow)",
            error="the last error",
            connected_at="when it was connected",
            updated_at=CHANGED,
            via="login or key",
            session="the Composio session",
        ),
    ),
    "doc_settings": Table(
        agos("the owner's per-workspace document setting"),
        cols(workspace_id=WS, latin_only="write documents in Latin script only"),
    ),
    "doc_versions": Table(
        agos(
            "versions of the workspace's documents (the Office view), the owner's edits too",
            "H: tools/checkpoint_manager.py (snapshots of the agent's own file edits per "
            "working dir only)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            path="the document",
            body="that version's text",
            hash="its hash",
            author="who wrote it",
            why="why it changed",
            created_at=MADE,
        ),
    ),
    "agent_versions": Table(
        agos(
            "history of a member's identity (Hermes keeps no SOUL.md history)",
            "H: hermes_cli/web_routers/profiles.py:1018 (overwrites SOUL.md)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            name="the member",
            title="its title then",
            summary="its summary then",
            definition="its identity then",
            event="changed or deleted",
            created_at=MADE,
        ),
    ),
    "activity": Table(
        agos("AGOS's own audit trail shown to the owner"),
        cols(id=ID, workspace_id=WS, kind="what happened", text="the line", created_at=MADE),
    ),
    "system_log": Table(
        agos("AGOS's own errors (Hermes's are its own logs, read by the Log)"),
        cols(
            id=ID,
            workspace_id=WS,
            level="level",
            source="which AGOS part",
            text="the line",
            created_at=MADE,
        ),
    ),
    "error_issues": Table(
        agos(
            "AGOS's own errors grouped into issues for Settings → Errors (the System Log, "
            "counted per fingerprint; Hermes's own errors.log stays Hermes's, only counted)",
            "Hermes keeps its errors as log lines (<home>/logs/errors.log, hermes logs "
            "errors); it has no issue list, no count and no fixed mark",
        ),
        cols(
            id=ID,
            fingerprint="the issue: source + error type + normalized message + top frames",
            workspace_id=WS,
            source="core | web | hermes",
            where_from="the logger, or the web page kind",
            error_type="the error's type",
            message="the last message, secrets wiped",
            route="the API route or web page it happened on",
            trace="the last traceback, secrets wiped",
            count="how many times",
            first_seen="when first",
            last_seen="when last",
            first_version="the AGOS version it was first seen on",
            version="the AGOS version it was last seen on",
            request_id="the last request's reference (shown in the error answer)",
            status="open | fixed (the owner's mark)",
            fixed_at="when the owner marked it fixed",
            came_back="it happened again after being marked fixed",
            hour_start="the hour the spike count is for",
            hour_count="how many times in that hour (a spike alert)",
            spike_told_at="when the owner was last told of a spike",
        ),
    ),
    "cofounder_actions": Table(
        agos("changes the Co-Founder proposed to AGOS itself, waiting for the owner"),
        cols(
            id=ID,
            workspace_id=WS,
            chat_id=CHAT,
            turn_id="the turn that proposed it",
            action="the action",
            title="its title",
            payload=(
                "its details; a pool key travels sealed only until the action is done, "
                "declined or undone, then Hermes's managed .env holds it (migration 121)"
            ),
            status="proposed … undone",
            error="why it failed",
            result=(
                "what it did and the least its Undo needs: a skill change's Hermes "
                "skill-ledger ids (Undo = Hermes's rollback_entry), a member role's "
                "agent_versions id, an automation change's touched fields (a delete: the "
                "whole job; Hermes's cron keeps no history or trash, H: cron/jobs.py "
                "update_job / remove_job), a Hermes setting's per-profile values before "
                "(Hermes's config keeps no history), an approved memory write's entries "
                "before/after (Hermes's memory keeps no history); a removed key stays "
                "sealed only until its Undo settles. Older copies moved once "
                "(cofounder_actions.move_snapshots)"
            ),
            created_at=MADE,
            decided_at="when the owner decided",
            task_id="the AGOS item it is about",
        ),
    ),
    "capability_requests": Table(
        agos("an agent asking the owner for an app, skill, member or tool (AGOS's control plane)"),
        cols(
            id=ID,
            workspace_id=WS,
            chat_id=CHAT,
            turn_id="the turn that asked",
            kind="app, skill, agent, mcp or tool",
            name="what it asks for",
            title="shown title",
            turn_on="on or off",
            reason="the agent's reason",
            status="proposed … failed",
            error="why it failed",
            flow_id="the sign-in flow",
            created_at=MADE,
            decided_at="when the owner decided",
        ),
    ),
    "kanban_asks": Table(
        agos(
            "a card's 'Ask me' waiting for the owner, an agent's proposal (a hire, "
            "a change to its own instructions, a plan) waiting for his approve / revise / "
            "reject, and an agent's typed question (ask, confirm, checkbox, choice, "
            "verdicts, suggest_tasks) waiting for his answer, on top of Hermes's "
            "needs_input block; the card body holds the proposal or question too "
            "(Hermes-side), the row keeps the owner's stable button keys, the round and "
            "what Undo needs",
            "H: hermes_cli/kanban_db.py:110 kanban_block needs_input (no decision record, "
            "no payload typing, no Undo)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            card="the Hermes Kanban card",
            member="the member asking",
            action="what it wants to do",
            label="shown label",
            detail="details",
            status="waiting, allowed or denied (an ask); approved, revised, rejected or "
            "undone (a proposal); answered (a question)",
            created_at=MADE,
            decided_at="when the owner decided",
            kind="ask (an Autonomy ask), hire, instructions, plan, goal, skill or kit (a proposal), "
            "question",
            payload="the proposal's or question's payload as read from the card's "
            "agos-proposal / agos-question block (so the Inbox renders it without reading "
            "the board)",
            round="the proposal round (a revise asks for the next round, a new card)",
            note="the owner's revise note",
            result="what the approve did (the hired member's id, a kit's member and what it had "
            "before) for Undo; a question's answer",
        ),
        writer="db/kanban_asks.py",
    ),
    "app_settings": Table(
        agos("AGOS's own settings, one row per key in KEYS below"),
        cols(key="a key listed in KEYS", value="its JSON value", updated_at=CHANGED),
    ),
    "push_subscriptions": Table(
        agos(
            "the browsers (the owner's phone) that asked for the installed AGOS app's own "
            "notifications (actions/web_push.py); a browser's Web Push address is AGOS's UI, "
            "Hermes reaches the owner through its own chat platforms",
            "H: gateway/platforms/ (Telegram and the other chat platforms; no browser push)",
        ),
        cols(
            id=ID,
            endpoint="the browser's push service address (unique per subscription)",
            p256dh="the browser's public key for the push payload",
            auth="the browser's push auth secret",
            label="which device it is (shown to the owner)",
            created_at=MADE,
            seen_at="when that browser last subscribed again",
        ),
    ),
    "goals": Table(
        agos(
            "the workspace goal (title, why, success measure; parent_id NULL, one per "
            "workspace) and its sub-goals (owner member, active / paused / done / dropped, parent "
            "goal): AGOS's plan, written into every profile's SOUL.md as one marked "
            "section (actions/goals.py); a card's link to a sub-goal is its Hermes body's "
            "'## Goal' line, never a row",
            "H: hermes_cli/projects_db.py:28 projects (per-profile name, description, "
            "folders: no status, owner, parent or measure); hermes_cli/goals.py:1 (one "
            "session's Ralph-loop objective, not a workspace plan); hermes_cli/"
            "kanban_db.py:804 tasks (no goal column)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            parent_id="the goal it serves (NULL = the workspace goal itself)",
            title="what the goal is",
            why="why it matters",
            measure="how the owner knows it is reached (the workspace goal)",
            owner="the team member that owns a sub-goal ('' = none)",
            status="active, paused, done or dropped",
            position="the owner's order among its siblings",
            created_at=MADE,
            updated_at=CHANGED,
            level=(
                "vision (the row with no parent: the owner's sentence), goal (under the "
                "Vision) or project (under a goal), step 53"
            ),
            strategy="the Vision's strategy: how the workspace gets there (the owner's text)",
            due_on="a goal's due date (YYYY-MM-DD, '' = none)",
            project_kind="a project: dated (start / end) or recurring (a rhythm)",
            starts_on="a dated project's start (YYYY-MM-DD)",
            ends_on="a dated project's end (YYYY-MM-DD)",
            rhythm="a recurring project's rhythm, in the owner's words ('4 reels a week')",
        ),
    ),
    "key_results": Table(
        agos(
            "a goal's key results, step 53: numbers (start, current, target, unit, due "
            "date) the Vision page draws as progress bars and the agents read in their "
            "SOUL.md goal section; the Co-Founder proposes a new current value with its "
            "source (an Inbox proposal), the owner approves; a row each so a proposal "
            "names one",
            "H: hermes_cli/projects_db.py:28 projects (per-profile name, description, "
            "folders: no metric or target); hermes_cli/goals.py:1 (one session's "
            "Ralph-loop objective, no number); hermes_cli/kanban_db.py:804 tasks (no "
            "target value)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            goal_id="the goal it measures (goals.id)",
            title="what is measured",
            start_value="where the number started",
            current="the number now",
            target="the number that means done (NULL = not set yet)",
            unit="its unit (followers, MAD, %)",
            due_on="when the target is due (YYYY-MM-DD, '' = the goal's)",
            source="where the current number came from last (the owner, a report)",
            position="the owner's order",
            created_at=MADE,
            updated_at=CHANGED,
        ),
    ),
    "inbox_notes": Table(
        agos(
            "a note AGOS itself leaves in the owner's Inbox about the team (a lead removed: "
            "its reports now report to the Co-Founder); read and dismissed like every "
            "Inbox item (inbox_marks key note:<id>)",
            "H: hermes_cli/profiles.py delete_profile (no record of who reported to the "
            "deleted profile); hermes_cli/kanban_db.py (no note that isn't a card)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            kind="what the note is about (lead_removed; recap, weekly: the Co-Founder's posts)",
            title="the note's line",
            detail="its details",
            created_at=MADE,
        ),
        writer="db/inbox.py",
    ),
    "inbox_marks": Table(
        agos(
            "what the owner marked in his Inbox: read, or dismissed (hidden until the item "
            "changes). Every Inbox item is derived on read from Hermes's board (blocked "
            "cards, their events and links) and AGOS's asks; only his marks persist, by "
            "the item's key (actions/inbox.py), like Paperclip's inbox_dismissals",
            "H: hermes_cli/kanban_db.py (tasks, task_events, task_links: no read or dismiss "
            "state per human; the dashboard shows every blocked card every time)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            key="the Inbox item's key (ask:<id> for an ask or question, card:<card>:<stamp> "
            "for a derived blocked-card item, chain:<lead>:<why> for a stalled team, "
            "note:<id> for an AGOS note)",
            mark="read or dismissed",
            created_at=MADE,
        ),
        writer="db/inbox.py",
    ),
}
