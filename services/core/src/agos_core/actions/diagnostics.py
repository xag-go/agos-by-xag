"""Diagnostics for a GitHub issue, and the deep health check.

`report(core)` is a short Markdown text the owner can paste into an issue
(`agos doctor --bundle`, Settings → Errors → Copy diagnostics). It holds versions,
health, free disk/memory, the backup and update state, the Labs switches, the
newest open errors and AGOS's environment, and nothing of the owner's own:

- no workspace, chat, card, file, member or person name, no message text;
- each error is its normalized line (error_issues.normalize: ids, numbers, paths and
  quoted values taken out), then `scrub`: e-mail addresses, web addresses, @handles, every name this AGOS knows (workspaces, chats, members,
  automations, folders...) and a capitalized name after words such as "workspace",
  "member" or "customer" become <name>; with its type, place and count, never the
  raw message or the traceback;
- the environment shows a value only for the names in `SHOWN`; every other
  `AGOS_*` name is `set`;
- the whole text goes through `system_log.redact` (keys and tokens) and has the
  core's internal token wiped.

`deep(app, core)` is `/health?deep=1`, read by `agos update`'s watch after an update
(deploy/agos `healthy`) and shown in this report: the database answers, the data
disk is not full, no background loop died. The watch rolls back only on the
database or a loop; a full disk alone is the ops watch's alert (a rollback needs
room). The dead-man and `agos status` use the plain `/health`.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from datetime import UTC, datetime
from typing import Any

from agos_core.actions import agos_update, error_issues, flags, hermes_update, isolation, ops_watch
from agos_core.actions.system_log import redact
from agos_core.config import HERMES_TESTED_VERSION
from agos_core.db import health
from agos_core.db import workspaces as workspaces_repo

ERRORS_SHOWN = 20
FULL = 0.02  # less free than this on the data disk = not healthy
SHOWN = frozenset(
    {
        "AGOS_ENGINE",
        "AGOS_PROFILE_PREFIX",
        "AGOS_STAGING",
        "AGOS_HOOKS_PORT",
        "AGOS_WEBHOOK_FIRST_PORT",
        "AGOS_EGRESS_NAME",
        "AGOS_SANDBOX_IMAGE",
        "AGOS_GATEWAY_SUPERVISOR",
        "AGOS_HOST_OS",
        "AGOS_REF",
    }
)


# Names AGOS itself holds: (table, column). Any of them in an error line is the owner's.
_NAMED = (
    ("workspaces", "name"),
    ("chats", "title"),
    ("automations", "name"),
    ("agent_versions", "title"),
    ("agent_versions", "name"),
    ("channel_connections", "name"),
    ("folders", "name"),
    ("goals", "title"),
    ("labels", "name"),
    ("library_items", "title"),
    ("message_attachments", "name"),
)
_PERSONAL = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "<email>"),
    (re.compile(r"\bhttps?://\S+", re.I), "<url>"),
    (re.compile(r"(?<![\w@])@\w{2,}"), "<handle>"),
    (
        re.compile(
            r"\b((?i:workspace|member|agent|chat|card|customer|client|contact|person|user|"
            r"owner|team|hire|named|called)s?\s+)[A-Z][\w'\u2019-]*(?:\s+[A-Z][\w'\u2019-]*)*"
        ),
        r"\1<name>",
    ),
)


def known_names(core: Any) -> list[str]:
    """Every name and title AGOS holds (longest first), for `scrub`."""
    values = health.distinct_values(core.db, _NAMED)
    found = {v.strip() for v in values if len(v.strip()) >= 3}
    return sorted(found, key=len, reverse=True)


def scrub(text: str, names: list[str]) -> str:
    """Takes the owner's names, people and addresses out of an (already normalized) line."""
    for name in names:
        text = re.sub(re.escape(name), "<name>", text, flags=re.I)
    for pattern, repl in _PERSONAL:
        text = pattern.sub(repl, text)
    return text


def _pin() -> str:
    try:
        return (agos_update.app_dir() / "deploy" / "hermes.pin").read_text().strip()
    except OSError:
        return "?"


def loops_alive(app: Any) -> bool:
    tasks = getattr(app.state, "loops", None) or []
    return all(not t.done() for t in tasks)


def deep(app: Any, core: Any) -> dict[str, bool]:
    try:
        database = health.answers(core.db)
    except Exception:  # noqa: BLE001 - any failure is "not healthy"
        database = False
    try:
        usage = shutil.disk_usage(core.layout.root)
        disk = usage.free / usage.total >= FULL if usage.total else True
    except OSError:
        disk = False
    loops = loops_alive(app)
    return {"ok": database and disk and loops, "database": database, "disk": disk, "loops": loops}


def _env() -> list[str]:
    out = []
    for name in sorted(os.environ):
        if not name.startswith("AGOS_"):
            continue
        shown = name in SHOWN or name.startswith("AGOS_FLAG_")
        out.append(f"{name}={os.environ[name]}" if shown else f"{name}=set")
    return out


def report(core: Any, health: dict[str, bool] | None = None) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    current = agos_update.current()
    lines = [
        "## AGOS diagnostics",
        "",
        f"- made: {now}",
        f"- AGOS: {error_issues.agos_version()} (commit {current.get('sha', '?')[:12]}, "
        f"{current.get('date', '?')})",
        f"- Hermes: tested {HERMES_TESTED_VERSION}, pin {_pin()[:12]}",
        f"- Python: {sys.version.split()[0]} on {platform.system()} {platform.release()} "
        f"({platform.machine()})",
        f"- engine: {'Hermes' if core.engine is not None else 'none'}",
        f"- staging copy: {'yes' if ops_watch.staging() else 'no'}",
        "",
        "### Health",
        "",
    ]
    if health is not None:
        lines += [f"- {k}: {'ok' if v else 'NOT OK'}" for k, v in health.items()]
    free = ops_watch.read_free(core)
    lines += [f"- free disk: {free['disk']:.0%}", f"- free memory: {free['ram']:.0%}"]
    workspaces = len(workspaces_repo.live_ids(core.db))
    lines += [f"- workspaces: {workspaces}", ""]
    lines += isolation.report_lines(core)
    lines += ["### Backups", ""]
    from agos_core.actions import backups

    status = backups.status(core)
    lines += [
        f"- password set: {'yes' if status.has_password else 'no'}",
        f"- schedule: {status.schedule}, keep {status.keep}, {len(status.files)} file(s)",
        f"- last backup: {status.last_backup_at or 'never'} "
        f"({'ok' if status.last_backup_ok else 'failed' if status.last_backup_ok is False else '-'})",
        f"- last restore test: {status.last_rehearsal_at or 'never'}",
        *[f"- warning: {w}" for w in status.warnings],
        "",
        "### Updates",
        "",
    ]
    state = agos_update.status(core).get("state") or {}
    lines.append(
        f"- AGOS update: {state.get('phase', 'none')}"
        f"{' (rolled back)' if state.get('rolled_back') else ''} "
        f"{state.get('from', '')[:12]} -> {state.get('to', '')[:12]}".rstrip(" ->")
    )
    hermes_state = hermes_update.status(core).get("state") or {}
    lines += [f"- Hermes update: {hermes_state.get('phase', 'none')}", "", "### Labs", ""]
    lines += [
        f"- {f.name}: {'on' if f.on else 'off'}{' (forced)' if f.forced else ''}"
        for f in flags.listed(core)
    ]
    lines += ["", f"### Errors (newest {ERRORS_SHOWN} open)", ""]
    issues = error_issues.listed(core.db, status="open")[:ERRORS_SHOWN]
    if not issues:
        lines.append("- none")
    names = known_names(core) if issues else []
    for issue in issues:
        what = scrub(error_issues.normalize(issue.message), names)
        lines.append(
            f"- #{issue.id} {issue.source} {issue.where}"
            f"{' ' + issue.error_type if issue.error_type else ''}: {what} "
            f"(x{issue.count}, last {issue.last_seen[:16]}, {issue.version})"
        )
    lines += ["", "### Environment", "", "```", *_env(), "```", ""]
    return redact("\n".join(lines), (core.internal_token,))
