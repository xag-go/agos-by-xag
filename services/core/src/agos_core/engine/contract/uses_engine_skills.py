"""Hermes contract entries: helper scripts: held memory / skill writes, their Undo, skill versions, search.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _GIST,
    _HELD,
    _LEARNED,
    _NEW_SKILL,
    _POOLS,
    _RVA,
    _SEARCH,
    _SETTINGS,
    _SKILLS_OWN,
    _STATUS,
    _VERSIONS,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # Read vs act: a memory / skill write after an untrusted read is held in Hermes's
    # own pending store (hermes_plugin/agos_guard/taint.py held_write; its stage_write
    # is pinned below with the Undo).
    _u("tools.write_approval", "current_origin", "function", "guard", _RVA),
    _u("tools.write_approval", "skill_gist", "function", "guard", _RVA, pos=2, kw=_GIST),
    # Where the held writes and the skill ledger live, so AGOS asks Hermes again only
    # when they changed (engine/hermes.py _held_stamp, _ledger_stamp).
    _u(
        "tools.write_approval",
        "_pending_path",
        "text",
        "engine",
        _HELD + ", asked from Hermes again when its queue changed",
        text='get_hermes_home() / "pending" / subsystem / f"{pending_id}.json"',
    ),
    _u(
        "tools.write_approval",
        "_pending_files",
        "text",
        "engine",
        _HELD + ", asked from Hermes again when its queue changed",
        text='list(d.glob("*.json"))',
    ),
    _u(
        "tools.skill_ledger",
        "ledger_path",
        "text",
        "engine",
        "what the agents learned, asked from Hermes again when its ledger changed",
        text='_skills_dir() / ".curator_ledger.jsonl"',
    ),
    _u(
        "tools.skill_ledger",
        "_skills_dir",
        "text",
        "engine",
        "what the agents learned, asked from Hermes again when its ledger changed",
        text='get_hermes_home() / "skills"',
    ),
    _u(
        "tools.skill_ledger",
        "blobs_dir",
        "text",
        "engine",
        "what the agents learned, asked from Hermes again when its ledger changed",
        text='get_hermes_home() / ".curator_backups" / "blobs"',
    ),
    _u(
        "hermes_cli.write_approval_commands", "_matched_entries", "function", "engine", _HELD, pos=1
    ),
    _u(
        "hermes_cli.write_approval_commands",
        "handle_pending_subcommand",
        "function",
        "engine",
        _HELD,
        pos=2,
        kw="memory_store",
    ),
    _u("tools.memory_tool", "load_on_disk_store", "function", "engine", _HELD),
    _u("tools.memory_tool", "apply_memory_pending", "function", "engine", _HELD, pos=2),
    # A Co-Founder card's Undo of its approve / reject (engine/hermes.py _UNDO_PENDING):
    # a rejected write held again, an approved memory write taken back under
    # Hermes's own memory-file lock.
    _u(
        "tools.write_approval",
        "stage_write",
        "function",
        "engine",
        _HELD + " (Undo)",
        pos=2,
        kw="summary origin",
    ),
    # One approved change: Hermes's own public inverse op (engine.memory_undo_ops);
    # _mutate only for a batch's snapshot.
    _u("tools.memory_tool_store", "MemoryStore.add", "method", "engine", _HELD + " (Undo)", pos=2),
    _u(
        "tools.memory_tool_store",
        "MemoryStore.replace",
        "method",
        "engine",
        _HELD + " (Undo)",
        pos=3,
        kw="matched_entry",
    ),
    _u(
        "tools.memory_tool_store",
        "MemoryStore.remove",
        "method",
        "engine",
        _HELD + " (Undo)",
        pos=2,
        kw="matched_entry",
    ),
    _u(
        "tools.memory_tool_store",
        "MemoryStore._mutate",
        "method",
        "engine",
        _HELD + " (Undo)",
        pos=2,
        kw="skip_drift",
    ),
    # An approved skill write's Undo (engine/hermes.py _SKILL_LEDGER / _UNDO_PENDING):
    # the ledger entries the approval's replay made, rolled back newest first.
    _u("tools.skill_ledger", "", "module", "engine", _HELD + " (skill Undo)"),
    _u(
        "tools.skill_ledger",
        "list_entries",
        "function",
        "engine",
        _HELD + " (skill Undo)",
        pos=1,
        kw="limit",
    ),
    _u(
        "tools.skill_ledger", "rollback_entry", "function", "engine", _HELD + " (skill Undo)", pos=1
    ),
    # The owner's and the Co-Founder's skill writes (engine/hermes.py _SKILL_MANAGE /
    # _SKILL_ROLLBACK / _SKILL_CHANGES, actions/skill_writes.py): Hermes's own
    # skill_manage replayed past the agents' write_approval gate (the public
    # function its /skills approve uses), the ledger actor, and "What I learned".
    _u(
        "tools.skill_manager_tool",
        "apply_skill_pending",
        "function",
        "engine",
        _SKILLS_OWN,
        pos=1,
    ),
    # The checks Hermes's own create makes first, run before AGOS writes a new skill
    # anywhere (engine/hermes.py _SKILL_CHECK; a missing one is skipped and told).
    _u("tools.skill_manager_tool", "_validate_name", "function", "engine", _NEW_SKILL, pos=1),
    _u(
        "tools.skill_manager_tool",
        "_validate_frontmatter",
        "function",
        "engine",
        _NEW_SKILL,
        pos=1,
        kw="new_skill",
    ),
    _u(
        "tools.skill_manager_tool",
        "_validate_content_size",
        "function",
        "engine",
        _NEW_SKILL,
        pos=1,
        kw="label",
    ),
    _u("tools.skill_manager_tool", "_validate_file_path", "function", "engine", _NEW_SKILL, pos=1),
    _u("tools.skill_manager_tool", "MAX_SKILL_FILE_BYTES", "constant", "engine", _NEW_SKILL),
    _u("tools.skill_ledger", "set_ledger_actor", "function", "engine", _SKILLS_OWN, pos=1),
    _u("tools.skill_ledger", "reset_ledger_actor", "function", "engine", _SKILLS_OWN, pos=1),
    _u("tools.skill_ledger", "read_blob", "function", "engine", _LEARNED, pos=1),
    # A skill's versions (engine/hermes.py _SKILL_HISTORY, engine/skill_versions.py):
    # the ledger keeps deltas and trims itself, so AGOS snapshots each version once;
    # Hermes's skill scanner skips a fixed list of folders, so the snapshots live
    # beside skills/, not in it.
    _u("tools.skill_ledger", "_delta", "function", "engine", _VERSIONS, pos=2),
    _u("tools.skill_ledger", "_maintain_size", "function", "engine", _VERSIONS),
    _u("tools.skill_ledger", "gc_blobs", "function", "engine", _VERSIONS),
    _u("agent.skill_utils", "EXCLUDED_SKILL_DIRS", "constant", "engine", _VERSIONS),
    # His decisions (actions/learning.py decisions): the learning conversation's
    # sessions by their key, then their messages through Hermes's own index.
    _u(
        "hermes_state_common",
        "sessions.session_key",
        "text",
        "engine",
        _LEARNED + " (his decisions: the learning conversation's sessions)",
        text="    user_id TEXT,\n    session_key TEXT,\n    chat_id TEXT,",
    ),
    _u(
        "hermes_state_common",
        "idx_messages_session_id",
        "text",
        "engine",
        _LEARNED + " (his decisions: their messages by session, never a walk of all)",
        text="CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id, id);",
    ),
    # Search (step 55) reads Hermes's own stores where they are: its board's tables
    # (read only, one connection) and its full-text index of the conversations.
    *[
        _u("hermes_cli.kanban_db", f"schema.{table}", "text", "kanban", _SEARCH, text=said)
        for table, said in (
            (
                "tasks",
                "CREATE TABLE IF NOT EXISTS tasks (\n    id                   TEXT PRIMARY KEY,",
            ),
            ("task_comments", "CREATE TABLE IF NOT EXISTS task_comments (\n    id         INTEGER"),
            ("task_attachments", "CREATE TABLE IF NOT EXISTS task_attachments (\n    id"),
            (
                "task_runs",
                "CREATE TABLE IF NOT EXISTS task_runs (\n    id                  INTEGER",
            ),
        )
    ],
    _u(
        "hermes_state_common",
        "messages_fts",
        "text",
        "engine",
        _SEARCH,
        text="CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(",
    ),
    # A status card's job is a Hermes monitor job (cron/monitor.py): its monitor
    # script runs first and an unchanged output suppresses the agent's run.
    _u(
        "hermes_cli.subcommands.cron",
        "cron_create.monitor_script",
        "text",
        "engine",
        _STATUS,
        text='cron_create.add_argument("--monitor-script", dest="monitor_script",',
    ),
    _u(
        "hermes_cli.subcommands.cron",
        "cron_edit.monitor_script",
        "text",
        "engine",
        _STATUS,
        text='cron_edit.add_argument("--monitor-script", dest="monitor_script",',
    ),
    _u(
        "cron.scheduler",
        "_apply_monitor_gate.unchanged",
        "text",
        "engine",
        _STATUS,
        text="monitor output unchanged — suppressing agent run",
    ),
    _u("cron.monitor", "check_monitor", "text", "engine", _STATUS, text='"last_changed_at":'),
    _u("hermes_cli.web_routers.ops", "", "module", "engine", _POOLS),
    _u("hermes_cli.web_routers.ops", "list_credential_pool", "function", "engine", _POOLS),
    _u(
        "hermes_cli.web_routers.ops",
        "remove_credential_pool_entry",
        "function",
        "engine",
        _POOLS,
        pos=2,
    ),
    _u("agent.credential_pool", "get_pool_strategy", "function", "engine", _POOLS, pos=1),
    _u("agent.credential_pool", "SUPPORTED_POOL_STRATEGIES", "constant", "engine", _POOLS),
    _u("agent.credential_pool", "AUTH_TYPE_API_KEY", "constant", "engine", _POOLS),
    _u(
        "agent.credential_persistence",
        "fingerprint_secret_value",
        "function",
        "engine",
        _POOLS + " (the one-time move of hand-added copies)",
        pos=1,
    ),
    _u("gateway.config", "load_gateway_config", "function", "engine", _SETTINGS + " (.env in use)"),
)
