"""Hermes contract entries: Kanban: the bridge's board hooks, tokens.py, estimate.py.

Part of `engine/hermes_contract.CONTRACT` (assembled in order by
`engine/contract/entries.py`); see engine/hermes_contract.py for what an entry means.

Must not: hold another area's entries (each uses_*.py has one), or check them (tree.py).
"""

from __future__ import annotations

from agos_core.engine.contract.base import (
    _CARD,
    _DONE,
    _EST,
    _GRADE,
    _KAN,
    _ORGANIZE,
    _THREADS,
    _TOK,
    Use,
    _u,
)

__all__ = [
    "USES",
]

USES: tuple[Use, ...] = (
    # ---- kanban: bridge.py hooks, tokens.py, estimate.py ----
    _u("hermes_cli.kanban_db", "get_task", "function", "kanban", _KAN + "; " + _EST, pos=2),
    _u("hermes_cli.kanban_db", "child_ids", "function", "kanban", _KAN, pos=2),
    _u("hermes_cli.kanban_db", "_append_event", "function", "kanban", _TOK, pos=4, kw="run_id"),
    *[
        _u("hermes_cli.kanban_db", f"Task.{a}", "attr", "kanban", _KAN + "; " + _EST)
        for a in ("id", "title", "body", "idempotency_key")
    ],
    _u("hermes_cli.kanban_db_connect", "connect", "function", "kanban", _KAN, kw="board"),
    _u("hermes_cli.kanban_db_connect", "connect_closing", "function", "kanban", _TOK + "; " + _EST),
    # A card's page read from the board database the way `hermes kanban show --json`
    # and `hermes kanban attachments --json` read it (engine/hermes_board.py): its
    # queries, their order, its conversions, the board it resolves, the event names
    # the CLI renames first. tests/test_kanban_direct_live.py compares with the CLI.
    *[
        _u("hermes_cli.kanban_db", name, "text", "kanban", _CARD, text=said)
        for name, said in (
            ("get_task", 'conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()'),
            (
                "_task_rows",
                'f"SELECT * FROM {table} WHERE task_id = ? ORDER BY {order}", (task_id,)',
            ),
            ("list_comments", '_task_rows(conn, "task_comments", task_id, "created_at ASC")'),
            ("list_events", '_task_rows(conn, "task_events", task_id, "created_at ASC, id ASC")'),
            (
                "list_attachments",
                '_task_rows(conn, "task_attachments", task_id, "created_at ASC, id ASC")',
            ),
            ("_linked_ids", 'f"SELECT {want} FROM task_links WHERE {where} = ? ORDER BY {want}"'),
            ("parent_ids", 'return _linked_ids(conn, "parent_id", "child_id", task_id)'),
            ("child_ids", 'return _linked_ids(conn, "child_id", "parent_id", task_id)'),
            (
                "latest_summary",
                "\"WHERE task_id = ? AND summary IS NOT NULL AND summary != '' \"\n"
                '        "ORDER BY COALESCE(ended_at, started_at) DESC, id DESC LIMIT 1", (task_id,),',
            ),
            (
                "Task.from_row",
                "**{col: _to_epoch(g(col)) for col in _TASK_EPOCH_COLUMNS},",
            ),
            (
                "_TASK_EPOCH_COLUMNS",
                '_TASK_EPOCH_COLUMNS = ("created_at", "started_at", "completed_at",',
            ),
            (
                "_TASK_EMPTY_IS_NULL_COLUMNS",
                '_TASK_EMPTY_IS_NULL_COLUMNS = (\n    "model_override",',
            ),
            (
                "Comment.from_row",
                'body=_lossy_text(r["body"]), created_at=_to_epoch(r["created_at"]) or 0,',
            ),
            (
                "Event.from_row",
                'payload=_json_or(_lossy_text(row["payload"])), created_at=_to_epoch(row["created_at"]) or 0,',
            ),
            (
                "Attachment.from_row",
                'size=r["size"] or 0, uploaded_by=r["uploaded_by"], created_at=_to_epoch(r["created_at"]) or 0,',
            ),
            ("kanban_db_path", 'board, ("kanban.db",), "kanban.db")'),
            ("_board_path", ".joinpath(*default_parts)"),
            ("current_board_path", '/ "kanban" / "current"'),
        )
    ],
    _u(
        "hermes_constants",
        "get_default_hermes_root",
        "text",
        "kanban",
        _CARD,
        text='result = env_path.parent.parent if env_path.parent.name == "profiles" else env_path',
    ),
    _u("hermes_cli.kanban_db", "_to_epoch", "function", "kanban", _CARD, pos=1),
    _u("hermes_cli.kanban_db", "_lossy_text", "function", "kanban", _CARD, pos=1),
    _u("hermes_cli.kanban_db", "_json_or", "function", "kanban", _CARD, pos=1),
    _u("hermes_cli.kanban_db", "_row_get", "function", "kanban", _CARD, pos=2),
    _u(
        "hermes_cli.kanban_db_connect",
        "_migrate_add_optional_columns",
        "text",
        "kanban",
        _CARD,
        text='("ready", "promoted"),',
    ),
    _u(
        "hermes_cli.kanban",
        "_cmd_show",
        "text",
        "kanban",
        _CARD,
        text='"task": _task_to_dict(task), "latest_summary": latest_summary, "parents": parents, "children": children,',
    ),
    _u(
        "hermes_cli.kanban",
        "_cmd_attachments",
        "text",
        "kanban",
        _CARD,
        text="if _json_out(args, [_obj_dict(a, _ATTACHMENT_FIELDS) for a in atts], ascii=True):",
    ),
    _u(
        "hermes_cli.kanban_output",
        "_ATTACHMENT_FIELDS",
        "text",
        "kanban",
        _CARD,
        text='_ATTACHMENT_FIELDS = ("id", "filename", "content_type", "size", "uploaded_by", "stored_path", "created_at")',
    ),
    # Mark done (actions/services/board/card_text.py done_needs_summary, complete_args): the cards
    # Hermes refuses to complete without words (its empty-completion gate), the flags
    # his words go with, and where Hermes prints why it refused (engine/hermes.py
    # refusal_line).
    *[
        _u(module, name, "text", "kanban", _DONE, text=said)
        for module, name, said in (
            (
                "hermes_cli.kanban_db",
                "_gate_empty_completion",
                '    if row["status"] == "review":\n        return\n    stored = row["result"]\n'
                "    if _substantive_text(result) or _substantive_text(summary)"
                " or _substantive_text(stored):\n",
            ),
            (
                "hermes_cli.kanban_db",
                "_substantive_text",
                "return bool(value is not None and str(value).strip())",
            ),
            (
                "hermes_cli.kanban_parser",
                "complete",
                '_cmd("complete", [\n'
                '        _arg("task_ids", nargs="+", help="One or more task ids (only --result'
                ' applies to all of them)"),\n'
                '        _arg("--result", help="Result summary"),\n'
                '        _arg("--summary",',
            ),
            ("hermes_cli.kanban_output", "_err", "print(msg, file=sys.stderr)"),
        )
    ],
    _u("hermes_cli.kanban_db_notify", "list_notify_subs", "function", "kanban", _KAN, pos=2),
    _u(
        "hermes_cli.kanban_db_notify",
        "add_notify_sub",
        "function",
        "kanban",
        _KAN,
        pos=1,
        kw="task_id platform chat_id thread_id user_id chat_type notifier_profile delivery_mode delivery_metadata",
    ),
    _u(
        "hermes_cli.kanban_db_notify",
        "remove_notify_sub",
        "function",
        "kanban",
        _KAN,
        pos=1,
        kw="task_id platform chat_id thread_id",
    ),
    # Step 58: the agos-guard's threads.py. Hermes's kanban_comment answers with the
    # comment's id (AGOS reads it back by id); `hermes agos-bulk` writes through
    # Hermes's own assign_task / edit_task; a mention subscribes the member with
    # `notify-subscribe --delivery-mode wake`, and its card read lists the
    # kanban_notify_subs rows.
    _u(
        "tools.kanban_tools",
        "_handle_comment",
        "text",
        "kanban",
        _THREADS,
        text="return _ok(task_id=tid, comment_id=cid)",
    ),
    _u("hermes_cli.kanban_db", "edit_task", "function", "kanban", _THREADS, pos=2, kw="body"),
    _u(
        "hermes_cli.kanban_parser",
        "notify-subscribe",
        "text",
        "kanban",
        _THREADS,
        text='_arg("--delivery-mode", choices=kbn._NOTIFY_DELIVERY_MODES,',
    ),
    _u(
        "hermes_cli.kanban_db",
        "kanban_notify_subs",
        "text",
        "kanban",
        _THREADS,
        text="CREATE TABLE IF NOT EXISTS kanban_notify_subs (",
    ),
    _u(
        "tools.kanban_tools",
        "inject_new_comments_from_env",
        "text",
        "kanban",
        _THREADS + " (a running worker hears a comment from Hermes itself)",
        text='fresh = [c for c in rows if (c.author or "").strip() != own and (c.body or "").strip()]',
    ),
    _u(
        "plugins.kanban.dashboard.plugin_api",
        "_run_estimate",
        "function",
        "kanban",
        _EST,
        pos=2,
        kw="task_id",
    ),
    # Skill Studio's grader (agos_guard/grade.py): Hermes's own auxiliary client on its
    # `review` task, the way its Kanban estimate calls it.
    _u(
        "agent.auxiliary_client",
        "call_llm",
        "function",
        "kanban",
        _GRADE,
        kw="task messages temperature max_tokens timeout",
    ),
    _u(
        "hermes_cli.config_defaults",
        "DEFAULT_CONFIG",
        "constant",
        "kanban",
        _GRADE,
        text='"review": {"provider": "auto"',
    ),
    # Step 60, the Vision notes' Organize (actions/vision_notes.py _ask_cofounder): the
    # flags of Hermes's one-shot query AGOS passes.
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.query",
        "text",
        "engine",
        _ORGANIZE,
        text='_query_group.add_argument("-q", "--query"',
    ),
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.quiet",
        "text",
        "engine",
        _ORGANIZE,
        text="Only output the final response and session info.",
    ),
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.source",
        "text",
        "engine",
        _ORGANIZE,
        text='add("--source", default=None,',
    ),
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.run_budget",
        "text",
        "engine",
        _ORGANIZE,
        text='add("--run-budget", type=float',
    ),
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.max_turns",
        "text",
        "engine",
        _ORGANIZE,
        text='add("--max-turns", type=int',
    ),
    _u(
        "hermes_cli._parser",
        "_build_chat_parser.toolsets",
        "text",
        "engine",
        _ORGANIZE,
        text='add("-t", "--toolsets", default=SUPPRESS',
    ),
    _u(
        "toolsets",
        "TOOLSETS.todo",
        "text",
        "engine",
        _ORGANIZE,
        text='"todo": _ts(',
    ),
)
