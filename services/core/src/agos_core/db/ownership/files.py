"""The ownership registry's files outside the database: FILES (AGOS's own), CODE
(program files, not data) and HERMES_FILES (Hermes's own). db/ownership/ re-exports
them next to TABLES and KEYS; the rule and the classes are in its docstring.

Must not: hold table or key entries (tables.py, keys.py).
"""

from __future__ import annotations

from agos_core.db.ownership.base import Owned, agos, move

__all__ = [
    "CODE",
    "FILES",
    "HERMES_FILES",
]

# ---- files outside the database ---------------------------------------------------
# Every file name the code names (tests/ownership_scan.py file_names: a literal or an
# f-string, `{}` for its variable parts) is in exactly one of these two lists, so a
# new file that would copy Hermes data outside agos.db fails test_ownership.py until
# it is written here with a reason, like a new table.
#
# FILES: AGOS's own files (product or control data Hermes has no place for), with
# the same AGOS_ONLY / MOVE_ONCE classes as the tables.
_BUNDLE = (
    "a file of a workspace bundle (Step 56, engine/bundle.py): never kept by AGOS on "
    "disk, the export is a download made in memory, the ready-made teams ship with "
    "the code (agos_core/catalog/teams)"
)
FILES: dict[str, Owned] = {
    "agos.db": agos("AGOS's database (this registry's TABLES and KEYS)"),
    "master.key": agos("the key AGOS's secrets in agos.db are sealed with"),
    "internal.token": agos("the token AGOS's web and the plugin use to reach the core"),
    "hook-secrets.json": agos(
        "a webhook signing secret AGOS made while saving its automation, sealed with "
        "AGOS's key until the owner shows it once in the webhook's dialog "
        "(actions/hook_secrets.py); Hermes keeps the route's secret itself",
        "H: hermes_cli/webhook.py keeps the secret in the route, with no shown-once state",
    ),
    "read-vs-act.json": agos(
        "which Hermes sessions, scheduled jobs and cards read untrusted content (read vs "
        "act, actions/read_vs_act.py), so a core restart forgets no mark; Hermes has no "
        "notion of untrusted input to keep",
        "H: tools/approval.py keeps approvals per session, never what a session read",
    ),
    "deadman.json": agos(
        "where the dead-man timer (deploy/agos-deadman.py) tells the owner the core is down "
        "without the core: the path of the bot's Hermes .env and his chat id, never the "
        "token itself",
        "H: the bot token stays in the root's .env (TELEGRAM_BOT_TOKEN), read at alert time",
    ),
    "remote-access.json": agos(
        "Settings → Access → Use AGOS from other devices: the machine's Tailscale "
        "address and the Tailscale logins let in; beside the internal token so the "
        "web's access check reads it on every request (apps/web/src/server/access.ts)"
    ),
    "agos-update.json": agos(
        "the running (or last) AGOS update's progress, written by `agos update` "
        "(deploy/agos) and read by actions/agos_update.py, so the Update AGOS card "
        "follows it across the restart"
    ),
    "hook-routes.json": agos(
        "the relay's map from a public webhook address to the workspace gateway that "
        "has the route (one public port for every root)",
        "H: gateway/platforms/webhook.py routes within one gateway only",
    ),
    "origins.json": agos(
        "which workspace proposed each Brain method (a shared skill); beside the skills "
        "folder, never read by an agent",
        "H: agent/skill_utils.py (SKILL.md frontmatter has no proposing workspace)",
    ),
    "owner-rules.json": agos(
        "which workspace proposed each of the owner's rules (the rules themselves are "
        "entries of the shared home's USER.md)",
        "H: tools/memory_tool.py (memory entries carry no origin)",
    ),
    ".agos-general.json": agos(
        "General settings' ledger in each Hermes home: which .env keys General wrote "
        "there, so removing one from General removes it only where General put it",
        "H: hermes_cli/config.py save_env_value (no record of who wrote a key)",
    ),
    ".agos-config.lock": agos(
        "an empty lock file in each Hermes home (engine/hermes.py HOME_LOCK): AGOS's "
        "config-writing Hermes commands and the e2e rig take it so two writes on one "
        "home never run at once; holds no data",
        "H: hermes_cli/config.py set_config_value -> atomic_config_replace (no "
        "cross-process lock on config.yaml)",
    ),
    "{}.deliveries": agos(
        "the webhook deliveries an automation's Hermes script already took (its "
        "dedupe), beside the script in the workspace's Hermes home",
        "H: gateway/platforms/webhook.py (its dedupe is per-process memory)",
    ),
    "agos-kanban-allowed.json": agos(
        "the plugin's control file: the card actions the owner allowed or denied for a "
        "Kanban worker (his answers to a card ask)",
        "H: hermes_cli/config_defaults.py approvals.single_query_mode (workers deny)",
    ),
    "agos-consent.json": agos(
        "the plugin's control file: the owner's consent tokens for an agent's change to "
        "its own instruction files (SOUL.md, config.yaml): card, target, sha256 of the "
        "approved content, consumed once the guard let that exact write through",
        "H: agent/system_prompt.py (SOUL.md is read, never gated); tools/approval.py gates "
        "commands per session, not a file's content",
    ),
    "automations/{}.md": agos(
        "an automation's instructions file (instructions only): a Kanban automation's "
        "brief (AGOS's team plan), or a one-agent job's only until Hermes's job holds "
        "them (services/automation/instructions.py drop_file)",
        "H: cron/jobs.py create_job prompt (holds a one-agent job's instructions)",
    ),
    "automations/{}-{}.md": agos("the same, when its name's file was taken"),
    "playbooks/automations/{}.md": agos(
        "a GENERATED read-only COPY for the agents (team_files): the Hermes job's name, "
        "schedule and on/off with AGOS's team plan and brief, never read back. It must "
        "exist because Hermes's cronjob list shows only a 100-character prompt preview "
        "and nothing of the team plan; rewritten only when a source changed "
        "(team_files.fingerprint)",
        "H: tools/cronjob_job_args.py:488 prompt_preview; cron/jobs.py:1813 create_job",
    ),
    "playbooks/agents/{}.md": agos(
        "a GENERATED read-only COPY for the agents (team_files) of each member's Hermes "
        "profile (display name, description, skills.auto_load, SOUL.md role), never "
        "read back. It must exist because the Co-Founder edits a member's role by exact "
        "text and no Hermes tool shows another profile's SOUL.md (mounting Hermes's "
        "profile folders into a sandbox is not allowed); rewritten only when a source "
        "changed (team_files.fingerprint)",
        "H: hermes_cli/profiles.py:916 profile meta; tools/delegate_tool_progress.py:199 "
        "(SOUL.md is skipped)",
    ),
    "team.md": agos("the team's documentation (AGOS's Docs, playbooks/)"),
    "flow.md": agos("the team's documentation (AGOS's Docs, playbooks/)"),
    "README.md": agos("the team's documentation (AGOS's Docs, playbooks/)"),
    "CHANGES.md": agos(
        "the team's documentation (AGOS's Docs, playbooks/); and, beside a card "
        "document's revision files (cards/<card>/.revisions/<key>/), one line per "
        "revision: who, why, when (actions/card_docs.py)"
    ),
    "v{}.md": agos(
        "a card document's revision as written (cards/<card>/.revisions/<key>/v<N>.md): "
        "every save keeps one, restore writes a new one (actions/card_docs.py)",
        "H: tools/checkpoint_manager.py (snapshots of the agent's own edits per working "
        "dir only, not a document's history anyone can read)",
    ),
    ".agos-written.json": move(
        "the old playbooks/ manifest, removed once (team_files.adopt)",
        "nothing: playbooks.written.<ws> keeps the hashes",
    ),
    ".agos-sources.json": move(
        "the old shared library's per-folder provenance (own versions' base hashes), "
        "removed once (actions/skills_move.py)",
        "nothing: each workspace's skill row keeps its source, hub identifier and hash",
    ),
    ".agos-tool-keys.json": agos(
        "which tool-key names in a member profile's .env and passthrough are AGOS's "
        "copies of its root's Keys (actions/tool_keys.py share), so only those are removed",
        "H: tools/env_passthrough.py (a passthrough list has no record of who added a name)",
    ),
    "agos-bridge.json": agos(
        "the plugin's control file in each home: where AGOS's core is and which "
        "workspace the home is (written by AGOS, read by agos_guard)"
    ),
    "agos-bridge-sent.json": agos("the plugin's record of outbox items it delivered"),
    "agos-bridge-sessions.json": move(
        "the plugin's old copy of Hermes's session index (Telegram chat → session key), "
        "removed once by the plugin at gateway start (bridge.drop_old_keys_file); the "
        "map is memory only now and Hermes's index answers after a restart",
        "H: gateway/session.py:1300 SessionStore.list_sessions (entry origin = chat); "
        "gateway/session_persistence.py:482 sessions.json",
    ),
    "agos-guard.json": agos("the plugin's Autonomy rules (the owner's Do/Ask/Never table)"),
    "agos-gateway.log": agos("the output of a gateway AGOS starts itself (test supervisor)"),
    "tools-install.log": agos("the output of a tool service install AGOS ran"),
    "client.json": agos(
        "AGOS's own Google OAuth client (connectors home)",
        "H: skills/productivity/google-workspace/scripts/google_api.py (keeps its own)",
    ),
    "token.json": agos("a workspace's Google login made with AGOS's own client"),
    "manifest.json": agos("an encrypted backup's file list and hashes"),
    "old-board-{}.json": agos("the old board's history, archived once in the workspace"),
    "{}-{}.json": agos("the same archive, when that day's name was taken"),
    "launchers.json": agos("migrate_root's record of the old launchers it replaced"),
    "report.json": agos("migrate_root's checklist of a moved workspace"),
    "report-check.json": agos("migrate_root's checklist, run again"),
    "rows.json": agos("migrate_root's copy of the rows it changed (its undo)"),
    ".{}.{}.tmp": agos(
        "agos-guard.json written aside then renamed over it (actions/autonomy.py), so "
        "the plugin never reads half a file; gone at once"
    ),
    "agos-automation-{}.py": agos(
        "the script an automation's Hermes cron job runs (engine/cron.py "
        "fire_script_name): engine/automation_run.py plus AGOS's team PLAN, which "
        "Hermes's job has no field for; rewritten only when it changed",
        "H: cron/jobs.py:1813 create_job script (Hermes runs a script AGOS wrote)",
    ),
    "agos-status-{}.py": agos(
        "a status card's monitor script in the root's Hermes scripts folder "
        "(actions/status_cards.py script_text): Hermes's cron runs it before each tick of "
        "the card's job and wakes the Co-Founder only when its output (the scope's facts, "
        "asked from AGOS's bridge) changed; rewritten only when it changed",
        "H: cron/monitor.py check_monitor (runs a monitor_script AGOS wrote)",
    ),
    "summary.md": agos(
        "a status card's summary, the Co-Founder's words, in the workspace folder "
        "(status/<id>/summary.md); every save is a revision (.revisions/summary/v<N>.md "
        "and CHANGES.md, like a card's documents)",
        "H: cron/jobs.py (a job's outputs are its runs' files, no revised document)",
    ),
    "notes.md": agos(
        "the owner's free Vision notes, his own words, in the workspace folder "
        "(vision/notes.md, actions/vision_notes.py); every save is a revision "
        "(.revisions/notes/v<N>.md and CHANGES.md, like a card's documents)",
        "H: tools/memory_tool.py (the agent's own notes; nothing keeps the owner's "
        "revised document)",
    ),
    "organized.json": agos(
        "the last Organize of the Vision notes (vision/organized.json): the notes "
        "revision and the Co-Founder's answer, so the goals it found are proposed once "
        "a Vision exists (actions/vision_notes.py)",
        "H: hermes_cli/cli_single_query.py (a one-shot query keeps only its session)",
    ),
    "agos-hook-{}.py": agos(
        "the same script for an automation's Hermes webhook route (one delivery each)",
        "H: hermes_cli/webhook.py:213 route (runs a script per delivery)",
    ),
    "skill-version-{}.json": agos(
        "one immutable snapshot of a workspace skill's version (every file's content, "
        "who wrote it, when, the ledger entry ids), under <root>/.agos-versions/<skill>/ "
        "(engine/skill_versions.py): Hermes's ledger keeps per-mutation deltas and trims "
        "itself, so a version's whole content can't be read back from it forever; kept "
        "beside skills/, never in it (Hermes's scanner would index a SKILL.md copy)",
        "H: tools/skill_ledger.py _delta, _maintain_size, gc_blobs (deltas, 5 MB cap); "
        "agent/skill_utils.py EXCLUDED_SKILL_DIRS (a fixed list, no hidden-folder rule)",
    ),
    "agos-skill-review.py": agos(
        "the weekly skill review job's monitor script in the root's Hermes scripts folder "
        "(actions/skill_growth.py script_text): Hermes's cron runs it before each tick and "
        "wakes the Co-Founder only when the week's evidence (asked from AGOS's bridge) "
        "changed; rewritten only when it changed",
        "H: cron/monitor.py check_monitor (runs a monitor_script AGOS wrote)",
    ),
    "agos-skill-updates.py": agos(
        "the no-agent script of a workspace's skill auto-update job in the root's Hermes "
        "scripts folder (Hermes's cron runs it nightly: `hermes skills update` per flagged "
        "skill; actions/skill_updates.py); rewritten when the flagged skills change",
        "H: cron/jobs.py:1813 create_job script / no_agent",
    ),
    "agos-digest.py": agos(
        "the digest's no-agent script in the root's Hermes scripts folder (the Hermes "
        "cron job runs it; actions/digest.py)",
        "H: cron/jobs.py:1813 create_job script / no_agent",
    ),
    "agos-runtime.conf": agos(
        "the systemd drop-in AGOS adds to Hermes's gateway unit: Hermes's runtime dir, "
        "HERMES_MANAGED_DIR (never persisted by Hermes) and the Landlock wall around "
        "the gateway (its ExecStart behind engine/wall.py, with the root's allow-list; "
        "rewritten from the root's own terminal.docker_volumes when its folders change), "
        "plus the cage (engine/cage.py bwrap prefix, KillMode=control-group) when the "
        "sandbox broker is on",
        "H: hermes_cli/managed_scope.py:45-59 (HERMES_MANAGED_DIR is per process)",
    ),
    "agos-sandboxd.service": agos(
        "the sandbox broker's own systemd user unit (engine/cage.py unit_text, installed "
        "by engine/sandbox_broker.py ensure): one daemon serving every workspace's "
        "filtered Docker socket, outside the gateways' walls and cages (ADR 0025 step 4)",
    ),
    "cage.ok": agos(
        "<data>/system/cage.ok (engine/sandbox_broker.py marker): written once bwrap made "
        "its sandbox on this machine, holding only the machine id, so AGOS_SANDBOXD=auto "
        "refuses rather than uncages on a later doubt (a restored backup proves nothing "
        "on another machine)",
    ),
    "config.json": agos(
        "<data>/sandboxd/docker-config/<profile>/config.json (engine/cage.py "
        "write_docker_config): the workspace's docker CLI config, bound read-only over the "
        "gateway's ~/.docker in its cage; the host's ~/.docker/config.json settings plus "
        "currentContext 'agos', so a docker CLI without DOCKER_HOST (Hermes's sandboxed "
        "browser) still lands on the filtered socket. Rewritten on each cage build",
    ),
    "meta.json": agos(
        "<data>/sandboxd/docker-config/<profile>/contexts/meta/<sha256('agos')>/meta.json "
        "(engine/cage.py write_docker_config): the docker CLI context 'agos' whose endpoint "
        "is the workspace's own agos-sandboxd socket",
    ),
    "events.jsonl": agos(
        "the broker's security log beside its policies (<data>/hermes/../sandboxd/): one "
        "JSON line per refused Docker call (engine/sandboxd.py event); append-only, "
        "mirrored to the journal",
    ),
    "{}.policy.json": agos(
        "a workspace's sandbox policy in the broker's policies folder (engine/cage.py "
        "write_policy, named after the root's profile): the labels, image, network and "
        "bind folders its gateway may ask Docker for; rewritten on apply, re-read by "
        "agos-sandboxd per request",
    ),
    ".policy.json": agos(
        "the same policy files' suffix (engine/sandboxd.py POLICY_SUFFIX): the broker "
        "serves exactly the *.policy.json files, nothing else in the folder",
    ),
    "cofounder-actions-before-step32.json": agos(
        "in the backups folder (outside AGOS's data): the skill and role copies old "
        "Co-Founder cards kept for their Undo, moved out of agos.db once (cofounder_actions."
        "move_snapshots); kept, never deleted. Nothing reads it back: every card since "
        "keeps Hermes's skill-ledger ids instead",
        "H: tools/skill_ledger.py record_mutation / rollback_entry (the Undo since)",
    ),
    "manager-actions-before-step32.json": agos(
        "the same file's name before step 44 (the Manager is the Co-Founder): "
        "actions/cofounder_move.py gives it the new name at start, once; nothing else "
        "names it",
        "H: tools/skill_ledger.py record_mutation / rollback_entry (the Undo since)",
    ),
    "app-settings-orphans-{}.json": agos(
        "in the backups folder's old-copies-<date>/: settings keys of workspaces and "
        "chats that no longer exist, with their values, moved out of app_settings at "
        "start (db/orphan_keys.sweep; old purges left them behind). Kept, never read "
        "back"
    ),
    "shared.zip": agos(
        "in the backups folder's hermes-upgrade-<stamp>/: `hermes backup` of the shared "
        "home, written before a Hermes update moves anything (engine/hermes_update."
        "backup_roots; `hermes import` restores it, docs/hermes-upgrade.md section 3)"
    ),
    "root-{}.zip": agos(
        "beside shared.zip: `hermes backup` of each workspace root before the update, "
        "named after the root (engine/hermes_update.backup_roots)"
    ),
    ".{}.tmp": agos("that file written aside then renamed over it; gone at once"),
    "agos-{}.zip": agos(
        "a workspace's export (Settings → Export): the readable bundle, made in memory "
        "and sent as a download, never kept on disk (actions/portability.py)",
        "H: hermes_cli/profiles.py export_profile (one profile as a tar.gz with its "
        "memories and sessions; no team, no automations, not readable)",
    ),
    "TEAM.md": agos(_BUNDLE + ": the team and its org chart"),
    "settings.yaml": agos(_BUNDLE + ": the workspace's settings and env_requires (names only)"),
    "vision.md": agos(_BUNDLE + ": the Vision, goals, key results, projects"),
    "cofounder/SOUL.md": agos(_BUNDLE + ": the owner's identity text for the Co-Founder"),
    "agents/{}/SOUL.md": agos(_BUNDLE + ": a member's role text (its Hermes SOUL.md part)"),
    "agents/{}/agent.yaml": agos(_BUNDLE + ": a member's title, lead, model, skills…"),
    "skills/{}/SKILL.md": agos(_BUNDLE + ": a workspace skill (Hermes's SKILL.md format)"),
    "automations/{}.yaml": agos(_BUNDLE + ": an automation (Hermes cron job + AGOS's row)"),
    "icon.png": agos(
        "a workspace's icon, the picture on its tile in the web app's rail (one of "
        "icon.png / icon.jpg / icon.webp / icon.svg, by what the bytes are), beside its "
        "chat attachments in `files/.agos` (storage/workspace_icon.py); AGOS "
        "presentation data, never read by an agent",
        "H: hermes_cli/profiles.py:916 read_profile_meta, :958 write_profile_meta "
        "(a profile has description, display_name and previous_names; no picture)",
    ),
    "icon.jpg": agos("the same icon, a JPEG", "H: hermes_cli/profiles.py:916 (no picture)"),
    "icon.webp": agos("the same icon, a WebP", "H: hermes_cli/profiles.py:916 (no picture)"),
    "icon.svg": agos(
        "the same icon, an SVG (refused with a <script>; served fenced by a CSP)",
        "H: hermes_cli/profiles.py:916 (no picture)",
    ),
}

# CODE: program files the code names, not data: AGOS's own modules it runs, mounts or
# reads beside itself (each must exist in agos_core), or Hermes's source files the
# upgrade checker reads (evidence `H:`).
CODE: dict[str, str] = {
    "automation_run.py": "engine/automation_run.py (copied into the automation scripts)",
    "connect_helper.py": "engine/connect_helper.py (run for a connector sign-in)",
    "egress_proxy.py": "engine/egress_proxy.py (mounted read-only into the proxy)",
    "keys.py": "hermes_plugin/agos_guard/keys.py (run in Hermes's runtime: masking, Secrets check)",
    "__init__.py": "H: hermes_cli/__init__.py (a package's module, read by hermes_contract)",
    "plugins.py": "H: hermes_cli/plugins.py (checked by hermes_contract)",
}

# HERMES_FILES: Hermes's own files, named by AGOS only to read them, to point Hermes
# at them, or to write them with Hermes's own code (never a copy). The evidence says
# where Hermes keeps each.
HERMES_FILES: dict[str, str] = {
    "uv.lock": "H: pm/environments.py ACTIVATION_INPUTS (dependency data, not a lock: the wall keeps it read-only)",
    "config.yaml": "H: hermes_cli/config.py load_config (written with hermes config set)",
    "profile.yaml": "H: hermes_cli/profiles.py:916 read_profile_meta / write_profile_meta",
    "SOUL.md": "H: agent/system_prompt.py (the profile's identity)",
    "AGENTS.md": (
        "H: agent/prompt_builder.py (a context file Hermes reads into the prompt; the guard "
        "only refuses an agent's own write to it)"
    ),
    "USER.md": "H: tools/memory_tool.py (user memory)",
    "MEMORY.md": "H: tools/memory_tool.py (agent memory)",
    "memories/USER.md": "H: tools/memory_tool.py (user memory)",
    "memories/MEMORY.md": "H: tools/memory_tool.py (agent memory)",
    "SKILL.md": "H: agent/skill_utils.py (a skill's file)",
    "lock.json": (
        "H: tools/skills_hub.py HubLockFile (skills/.hub/lock.json, the hub's provenance;"
        " actions/skills_move.py carries the old library's entries into each root once,"
        " in Hermes's own format)"
    ),
    ".curator_ledger.jsonl": (
        "H: tools/skill_ledger.py ledger_path (Hermes's skill ledger: read only by its own"
        " list_entries in its runtime; AGOS stamps the file to know when to ask again)"
    ),
    "auth.json": "H: hermes_cli/auth.py (logins and credential pool)",
    "auth.lock": "H: agent/file_safety.py",
    ".credentials.json": (
        "H: agent/anthropic_credentials.py:351 (Claude Code's login file Hermes reads; AGOS"
        " only names it to keep it out of backups and to check its mode, ADR 0023)"
    ),
    "vault.key": (
        "H: agent/vault_store.py:201 (the key of Hermes's vault; AGOS only keeps it out of"
        " backups, engine/backup.py, ADR 0023)"
    ),
    "models_dev_cache.json": (
        "H: agent/models_dev.py:216 _get_cache_path (models.dev's provider/model list its"
        " picker reads; AGOS only stamps it, read-only, to ask the model catalog again)"
    ),
    "provider_models_cache.json": (
        "H: hermes_cli/models.py:1949 _provider_models_cache_path (each authed provider's"
        " /v1/models list its picker reads; AGOS only stamps it, read-only, to ask the"
        " model catalog again)"
    ),
    "state.db": "H: hermes_state_common.py (sessions and messages)",
    "sessions.json": "H: gateway/session_persistence.py:482 (the gateway's session index)",
    "shared-state.db": "H: gateway/hosted_rooms_common.py (hosted rooms)",
    "kanban.db": "H: hermes_cli/kanban_db.py (the board)",
    "jobs.json": "H: cron/jobs.py (cron jobs)",
    "executions.db": "H: hermes_cli/web_routers/cron.py (cron runs)",
    "webhook_subscriptions.json": "H: hermes_cli/webhook.py (webhook routes)",
    "channel_directory.json": "H: gateway/channel_directory.py",
    "channel_aliases.json": "H: gateway/channel_directory.py (its alias overlay)",
    "gateway_state.json": "H: gateway/status.py",
    "gateway.pid": "H: gateway/status.py",
    "gateway.lock": "H: gateway/status.py",
    "processes.json": "H: tools/process_registry.py",
    ".drain_request.json": "H: gateway/drain_control.py (a quiet stop's request)",
    "sandbox.json": "H: tools/bot_desktop/sandbox_host.py",
    "errors.log": "H: hermes_logging.py",
    "plugin.yaml": "H: hermes_cli/plugins.py (a plugin's manifest)",
    "memory_store.db": "H: hermes_cli/backup.py:1069 (the Holographic memory store)",
    "telegram-approved.json": "H: gateway/pairing.py (Telegram's approved users)",
    "telegram-pending.json": "H: gateway/pairing.py (Telegram's pending pairing codes)",
    "hermes-gateway-{}.service": "H: hermes_cli/gateway.py:2310 get_service_name (its unit)",
    "hermes/hermes-backup.zip": (
        "H: hermes_cli/subcommands/backup.py (written by `hermes backup` inside AGOS's "
        "encrypted backup; AGOS only strips the login files from it)"
    ),
    "hermes/roots/{}.zip": (
        "H: hermes_cli/subcommands/backup.py (`hermes backup` of one workspace root, "
        "inside AGOS's encrypted backup; login files stripped)"
    ),
    ".client.json": "H: tools/mcp_oauth.py (Hermes's MCP OAuth token files)",
    ".meta.json": "H: tools/mcp_oauth.py (Hermes's MCP OAuth token files)",
    "mcp-tokens/{}.json": "H: tools/mcp_oauth.py:233 _get_token_dir, :413 (<server>.json tokens)",
}
