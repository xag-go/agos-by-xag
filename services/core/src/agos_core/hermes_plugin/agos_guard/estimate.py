"""`hermes agos-estimate <card>`: Hermes's own Kanban estimate for a card (its
dashboard's "Estimate effort": a rough token / complexity read by the auxiliary
model), printed as JSON for AGOS's Board."""

from __future__ import annotations

import contextlib
import json
from typing import Any


def setup(parser: Any) -> None:
    parser.add_argument("card", help="Kanban card id")


def handle(args: Any) -> int:
    try:
        from hermes_cli import kanban_db  # type: ignore[import-not-found]
        from hermes_cli.kanban_db_connect import (  # type: ignore[import-not-found]
            connect_closing,
        )
        from plugins.kanban.dashboard.plugin_api import (  # type: ignore[import-not-found]
            _run_estimate,
        )

        with connect_closing() as conn:
            task = kanban_db.get_task(conn, str(args.card))
        if task is None:
            print(json.dumps({"ok": False, "reason": "no such card"}))
            return 0
        print(json.dumps(_run_estimate(task.title, task.body, task_id=task.id)))
    except Exception as error:  # noqa: BLE001 — AGOS shows the reason
        with contextlib.suppress(Exception):
            from . import bridge

            bridge._broken(
                bridge._name_of(error, "plugins.kanban.dashboard.plugin_api._run_estimate"), error
            )
        print(json.dumps({"ok": False, "reason": f"{type(error).__name__}: {error}"[:300]}))
    return 0
