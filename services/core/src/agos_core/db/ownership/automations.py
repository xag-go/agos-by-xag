"""Ownership of AGOS's tables: automations, revisions, templates, the library and Skill Studio.

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
    "automations": Table(
        agos(
            "the owner's automations: team plan steps, approval-first, notice, when he last "
            "ran it by hand, and the link to Hermes's cron job (which holds its name, "
            "schedule and on/off)",
            "H: cron/jobs.py:2206-2228 trigger_job stamps manual_run_at only for the next "
            "fire and :2368 clears it after the run (no history); no team plan",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            name=agos(
                "request buffer: the owner's name only while neither a Hermes job nor its "
                "Hermes webhook route holds it (a change Hermes refused, or no route yet); "
                "'' once the job's own name is it (db/automations.py forget_request) or, "
                "for an automation started by an event only, its route's description "
                "(actions/hooks.py held_by_route)",
                "H: cron/jobs.py:1813 create_job name (`hermes cron create/edit --name`); "
                "hermes_cli/webhook.py:213 route description",
            ),
            file=agos(
                "the path of its instructions file: a Kanban automation's brief (AGOS's "
                "team plan; Hermes's script gets a generated PLAN), or a one-agent job's "
                "only while Hermes's job doesn't hold them (dropped once it does, never "
                "rewritten unchanged). That file holds only the instructions (never the "
                "name, model or schedule); the generated playbooks view, which does copy "
                "the job's name, schedule and on/off, is another file (FILES "
                "playbooks/automations/{}.md)",
                "H: cron/jobs.py:1813 create_job prompt (a one-agent job's instructions)",
            ),
            schedule=agos(
                "request buffer: the owner's schedule only while Hermes refused it or the "
                "engine is off, then cleared (db/automations.py forget_request)",
                "H: cron/jobs.json schedule",
            ),
            model=agos(
                "the model of a team-plan run, which Hermes's job doesn't hold; for a "
                "one-agent job only a request buffer like schedule",
                "H: cron/jobs.json model",
            ),
            enabled=agos(
                "request buffer: on/off only while Hermes refused it; 0 once Hermes has it",
                "H: cron/jobs.json enabled",
            ),
            created_at=MADE,
            updated_at=CHANGED,
            hermes_job_id="the link: Hermes's cron job id",
            sync_error="why Hermes refused the last change",
            manual_at="when the owner last ran it by hand",
            agent=agos(
                "request buffer: the member while Hermes refused it",
                "H: `hermes -p <member> cron` (the job's profile)",
            ),
            steps="the team plan (Hermes has no step plan)",
            notice="the owner's notice text",
            check_first="ask the owner before it runs",
            variables=agos(
                "the automation's typed variables (JSON list of name, type, default, "
                "options), interpolated as {name} into its cards' titles and bodies and "
                "its job's prompt; Run now may give values (actions/automation_variables.py)",
                "H: cron/jobs.py create_job (a prompt is one text; no variables, no "
                "manual-run inputs); gateway/platforms/webhook.py _render_prompt (payload "
                "fields in a route prompt only, not in Kanban cards)",
            ),
            policy=agos(
                "what a trigger does while the last run's cards are still open: "
                "skip_if_active (Hermes's own overlap skip), coalesce_if_active (one "
                "comment on the open cards), always_enqueue (new cards after them); the "
                "script Hermes runs reads it from its plan (engine/automation_run.py)",
                "H: cron/scheduler.py (an overlapping job run is skipped; no policy per "
                "job, and nothing about the cards a run left on the Kanban)",
            ),
            ticket=agos(
                "the ticket on-ramp mapping (JSON: source linear|jira|asana|github, the "
                "member, the payload paths of id, title, body, link and 'closed'): one "
                "Kanban card per incoming issue with key agos-ticket:<source>:<id>, "
                "completed when the issue closes upstream (actions/ticket_presets.py)",
                "H: gateway/platforms/webhook.py (verifies Linear / GitHub / Svix HMAC and "
                "runs the route script; no card mapping)",
            ),
            catch_up=agos(
                "the owner's choice for a run missed while the server was off: NULL = run "
                "it once when AGOS is back, 'skip' (actions/catch_up.py)",
                "H: cron/jobs.py _fast_forward_missed_recurring reads one cron.catch_up_missed "
                "for the whole home (no per-job field, no age limit, and a slot that passed "
                "while the job was paused is kept due on resume_job)",
            ),
        ),
    ),
    "cron_catch_up": Table(
        agos(
            "what AGOS saw of each Hermes cron job of a workspace for the catch-up of "
            "missed runs (actions/catch_up.py): since when it was off and back on (a slot "
            "missed while off never runs) and the missed occurrence it caught up or "
            "skipped, so a core restart never runs it twice",
            "H: cron/jobs.py resume_job clears paused_at (no on/off history) and a skipped "
            "occurrence leaves only a metric (record_cron_missed), nothing per job",
        ),
        cols(
            workspace_id=WS,
            job_id="the Hermes cron job (its id in the profile's cron/jobs.json)",
            off_since="when AGOS first saw it paused or held (archive, account pause)",
            on_since="when AGOS saw it back on after that",
            missed_at="the occurrence last caught up or skipped",
            asked_at="when AGOS asked Hermes to run it (Run now)",
            state="waiting (Hermes's gateway not up yet), asked, or skipped",
        ),
    ),
    "automation_revisions": Table(
        agos(
            "an automation's revision history: one snapshot per save (name, instructions, "
            "schedule, who does it, steps, variables, policy, webhook lines) with who "
            "saved it and a one-line summary of what changed; Restore is a new save from "
            "a snapshot, recorded as 'restored from vN' (actions/automation_revisions.py)",
            "H: cron/jobs.py update_job (the job is overwritten in place; cron/jobs.json "
            "holds its current state only, cron/executions the runs, never the edits)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            automation_id="the automation it is a revision of",
            n="the revision number (v1, v2, ... per automation)",
            snapshot="JSON of the automation as saved",
            who="who saved it: owner or cofounder",
            summary="one line of what changed since the revision before",
            restored_from="the revision number this save restored, if it did",
            created_at=MADE,
        ),
    ),
    "agent_revisions": Table(
        agos(
            "a team member's revision history (Step 56, F08): one snapshot per change AGOS "
            "wrote (job title, what it's for, role text, the owner's notes, model, skills, "
            "rule files it reads, lead, on/off, heartbeat) with who made it and why; "
            "Restore is a new write through the team's path, recorded as 'restored from "
            "vN' (actions/agent_revisions.py). The member itself is its Hermes profile",
            "H: hermes_cli/config_backups.py (copies of config.yaml for Hermes's own "
            "`config set` undo: no SOUL.md, no profile.yaml, no who or why); "
            "hermes_cli/profiles.py:958 write_profile_meta overwrites in place",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            name="the member (its Hermes profile a-<name>)",
            n="the revision number (v1, v2, ... per member)",
            snapshot="JSON of the member as it was after the change",
            who="who made it: owner, cofounder, import, template, hermes (outside AGOS)",
            why="why, when the writer said (a card, an import, a restore)",
            summary="one line of what changed since the revision before",
            restored_from="the revision number this change restored, if it did",
            created_at=MADE,
        ),
    ),
    "template_installs": Table(
        agos(
            "which ready-made team (a catalog bundle shipped with AGOS, Step 56 F91) a "
            "workspace installed: the bundle's hash and what each of its members, skills "
            "and automations became there, so the Team page shows what drifted from it "
            "(actions/teams_catalog.py). The items themselves are Hermes's profiles, "
            "skills and cron jobs",
            "H: hermes_cli/profile_distribution.py read_manifest (one distribution per "
            "profile, its source and installed_at; no team of profiles, no drift)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            slug="the catalog team's folder name",
            title="its name when installed",
            content_hash="the bundle's hash when installed (engine/bundle.content_hash)",
            items="JSON: the template's member, skill and automation names -> what they "
            "are named here, and the lead the team went under",
            installed_at=MADE,
        ),
    ),
    "kanban_watchdogs": Table(
        agos(
            "a 'Watch this tree' on a Hermes card: the link to the Hermes cron job (Co-"
            "Founder profile, every 30 min) whose run reads the subtree and asks AGOS "
            "whether to act, the last stop fingerprint (sorted open leaf ids and their "
            "statuses) so one stop wakes the agent once, and how many wakes acted without "
            "a leaf finishing (3 → the root card is blocked for the owner) "
            "(actions/watchdogs.py)",
            "H: hermes_cli/kanban_db.py (tasks, task_links: no watch per subtree, no stop "
            "fingerprint); cron/jobs.py (a job, no memory between its runs)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            root_card="the card whose subtree is watched",
            hermes_job_id="the link: Hermes's cron job id",
            fingerprint="the last stop fingerprint the job observed",
            acts="wakes that acted since a leaf last finished",
            created_at=MADE,
            observed_at="when the job last reported a fingerprint",
            acted_at="when a wake last acted",
            escalated_at="when the root card was blocked for the owner",
        ),
    ),
    "library_items": Table(
        agos(
            "AGOS's library: id/name rows for tools and plugins, each workspace's own "
            "skills, agents and MCP servers, and the cross-workspace MCP templates "
            "(Hermes has no catalog shared across roots); skill and tool words are read "
            "from SKILL.md and Hermes's catalog",
            "H: hermes_cli/config.py:948 mcp_servers (per home only)",
        ),
        cols(
            id=ID,
            kind="skill, agent, mcp, plugin or tool",
            name="its name",
            title="an owner's or derived display name (empty when it equals the name)",
            summary="an MCP template's or agent's words (skills/tools: empty, read from Hermes)",
            definition=(
                "an MCP template's definition; a skill's hub identifier or hash, and its "
                "auto_update flag (follow its source nightly: actions/skill_updates.py; "
                "H: tools/skills_hub.py HubLockFile keeps the source, not the owner's wish)"
            ),
            source="created, web, machine, template…",
            created_at=MADE,
            updated_at=CHANGED,
            workspace_id=WS,
        ),
    ),
    # Skill Studio (step 46): the run itself is a Hermes Kanban card (its body holds
    # the rendered test and an `agos-skill-test` block); these rows are what Hermes
    # has no record for.
    "skill_test_inputs": Table(
        agos(
            "a workspace skill's saved test inputs (name, text, the expected output), for "
            "Skill Studio's test runs",
            "H: hermes_cli/kanban_db.py tasks (a card holds one run's text, no reusable "
            "input); tools/skill_linter.py (lints a skill's text, runs nothing)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            item_id="the skill's library row",
            name="the input's name",
            text="the input text rendered into the run's card",
            expected="the output expected (the grader compares; empty = none)",
            created_at=MADE,
        ),
    ),
    "skill_test_settings": Table(
        agos(
            "per skill: the run template ({skill}, {input} placeholders) and the grading "
            "checklist of Skill Studio",
            "H: hermes_cli/kanban_db.py tasks.skills (loads a skill on a card; no template "
            "or checklist for a skill test)",
        ),
        cols(
            item_id="the skill's library row",
            workspace_id=WS,
            template="the card's text with placeholders (empty = AGOS's default)",
            checklist="what a passing output must satisfy (the grader reads it; empty = none)",
            updated_at=CHANGED,
        ),
    ),
    "skill_test_runs": Table(
        agos(
            "one test run: the link to its Hermes card, the input as it was, the skill "
            "version pinned, the output read from the card and the grader's verdict",
            "H: hermes_cli/kanban_db.py tasks.result / latest_summary (the output lives "
            "there; nothing ties a card to a skill version or grades it)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            item_id="the skill's library row",
            input_id="the saved input it ran (NULL once that input is deleted)",
            input_name="the input's name at run time",
            input_text="the input text at run time (a re-run repeats it)",
            expected="the expected output at run time",
            checklist="the checklist at run time",
            version="the skill version pinned on the card",
            member="who ran it (cofounder or a member)",
            card="the Hermes Kanban card id",
            status="running / blocked / done / lost (the card's state as last read)",
            output="the card's result as read from Hermes's board",
            grade="pass / fail / error (the grader's verdict), NULL before grading",
            notes="the grader's notes",
            score="the grader's 0-1 score (Step 63: a candidate's against the current)",
            created_at=MADE,
            finished_at="when the card was seen finished",
            graded_at="when the grader answered",
        ),
    ),
    # Step 63: skills that grow. The skill itself stays Hermes's (its folder, its hub
    # lock and scan, its ledger); these rows are the request and the candidate before
    # either is a skill version.
    "skill_requests": Table(
        agos(
            "an agent's request for a hub skill it lacks (agos_skill_request): who asked, "
            "the source, why, its tests, what Hermes's scan said and where it stands "
            "(installing, testing, waiting for the owner, landed or not): the request log "
            "with its provenance",
            "H: tools/skills_hub.py HubLockFile (lock.json: provenance of an installed hub "
            "skill, no request, requester, tests or approval); hermes_cli/skills_hub.py "
            "do_install (installs at once, nothing waits for a test or a yes)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            member="who asked ('' = the Co-Founder)",
            name="the skill's name as Hermes's hub gives it",
            source="the hub identifier asked for",
            reason="why the agent needs it",
            tests="the requester's 1-2 test inputs with their expected answers (JSON)",
            criteria="the requester's checklist for every answer (optional)",
            status="installing / testing / approval / landed / refused / failed / rejected",
            item_id="the skill's library row once Hermes installed it",
            verdict="Hermes's scan verdict (safe / caution / forced)",
            scan="Hermes's scan report lines (verdict, decision, provenance)",
            scripts="1 when the skill carries scripts (the owner is asked)",
            forced="1 when the owner's yes made Hermes install it with --force",
            runs="its Skill Studio test runs (ids)",
            ask_id="its proposal in the owner's Inbox (kind 'skill')",
            note="what happened, in words",
            created_at=MADE,
            updated_at=CHANGED,
        ),
    ),
    "skill_candidates": Table(
        agos(
            "a skill's candidate version from the week's evidence (the Co-Founder's "
            "agos_skill_candidate): its text under test, the evidence it came from, its "
            "Skill Studio runs against the current version and the decision; promoted = "
            "written by Hermes's skill_manage as the next version",
            "H: tools/skill_manager_tool.py (every write is live, no draft); "
            "tools/write_approval (holds a write for a yes, no test gate)",
        ),
        cols(
            id=ID,
            workspace_id=WS,
            item_id="the skill's library row",
            name="the skill's name",
            batch="the ISO week of the review it came from (one Inbox note per week)",
            base_version="the version it was tested against",
            text="the candidate SKILL.md (Hermes writes it only when promoted)",
            why="the Co-Founder's one line",
            evidence="the evidence refs it came from (sessions, votes, cards, runs)",
            status="testing / promoted / discarded",
            runs="its test runs: candidate and current side by side (JSON)",
            score="the candidate's mean grader score",
            base_score="the current version's mean on the same inputs",
            version="the version it became",
            note="why it was promoted or discarded",
            created_at=MADE,
            decided_at="when it was decided",
        ),
    ),
}
