"""Problems of AGOS itself (a loop that crashed, a sandbox that couldn't start, a
channel that can't send...) are kept for the workspace Log, not only in a log file
the owner never opens.

Every warning or error of AGOS's own loggers ("agos.*", and "agos_core.*" for the
modules that log under their own name) lands in `system_log`, with where it
happened (the logger) and the cause (the message + the exception type). The
workspace is the one the record names (`extra={"agos_workspace": ...}`, an API
route's), else the one the message names; otherwise it's a system entry shown in
every workspace's Log. Secrets are wiped before storing.

Each ERROR is also counted on its issue for Settings → Errors (error_issues.py),
with its traceback (wiped the same way); a new issue, one that came back or a
spike is told to the owner (error_alerts.py).
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import threading
import traceback
from collections.abc import Callable
from typing import Any

from agos_core.db import system_log as log_rows
from agos_core.db.rows import now

KEEP = 5000  # rows kept; older ones are dropped
LOGGERS = ("agos", "agos_core")

_SECRETS = (
    re.compile(r"bot\d{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"\d{8,}:AA[A-Za-z0-9_-]{30,}"),
    re.compile(r"whsec_[A-Za-z0-9]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}"),
    re.compile(r"nsec1[0-9a-z]+"),
    re.compile(r"(/hooks/)[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key)(\W{1,3})[^\s,;\"']{6,}"),
)


def redact(text: str, extra: tuple[str, ...] = ()) -> str:
    for secret in extra:
        if secret:
            text = text.replace(secret, "[hidden]")
    for pattern in _SECRETS:
        text = pattern.sub(
            lambda m: (
                m.group(0)  # wiped already (the web app wipes its reports first)
                if m.group(0).endswith("[hidden]")
                else (
                    m.group(1)
                    + (m.group(2) if m.lastindex and m.lastindex > 1 else "")
                    + "[hidden]"
                )
                if m.lastindex
                else "[hidden]"
            ),
            text,
        )
    return text


class DbLogHandler(logging.Handler):
    """Writes AGOS's warnings and errors into `system_log`."""

    def __init__(
        self,
        db: sqlite3.Connection,
        workspaces: set[str],
        hidden: tuple[str, ...],
        alert: Callable[[int, str], None] | None = None,
    ):
        super().__init__(level=logging.WARNING)
        self.db = db
        self.workspaces = workspaces
        self.hidden = hidden
        self.alert = alert
        self.db_lock = threading.RLock()
        self.count = 0
        self.inside = threading.local()

    def workspace_of(self, text: str) -> str | None:
        # Warnings are rare: re-read the workspaces so a new one is known.
        with contextlib.suppress(sqlite3.Error):
            self.workspaces = log_rows.workspace_ids(self.db)
        for ws in sorted(self.workspaces, key=len, reverse=True):
            if re.search(rf"(?<![\w-]){re.escape(ws)}(?![\w-])", text):
                return ws
        return None

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(self.inside, "on", False):
            return  # a log line written while this one is stored (never loops)
        self.inside.on = True
        try:
            self._store(record)
        except Exception:  # noqa: BLE001 - a log must never break the app
            self.handleError(record)
        finally:
            self.inside.on = False

    def _store(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        text = message
        error = record.exc_info[1] if record.exc_info else None
        if error is not None:
            text += f" — {type(error).__name__}: {error}"
        text = redact(text, self.hidden)[:4000]
        level = "error" if record.levelno >= logging.ERROR else "warn"
        with self.db_lock:
            named = getattr(record, "agos_workspace", None)
            workspace = (
                named
                if isinstance(named, str) and named in self._known()
                else self.workspace_of(text)
            )
            if not getattr(record, "agos_issue_only", False):
                log_rows.add(
                    self.db,
                    workspace,
                    level,
                    getattr(record, "agos_log_source", record.name),
                    text,
                    now(),
                )
                self.count += 1
                if self.count % 200 == 0:
                    log_rows.keep_last(self.db, KEEP)
            if record.levelno >= logging.ERROR:
                said = f"{message} — {error}" if error is not None else message
                self._count_issue(record, redact(said, self.hidden), error, workspace)

    def _known(self) -> set[str]:
        with contextlib.suppress(sqlite3.Error):
            self.workspaces = log_rows.workspace_ids(self.db)
        return self.workspaces

    def _count_issue(
        self,
        record: logging.LogRecord,
        text: str,
        error: BaseException | None,
        workspace: str | None,
    ) -> None:
        from agos_core.actions import error_issues

        # The web app's and Hermes's errors come with their own type, frames and
        # traceback (api/errors.py, hermes_errors.py); AGOS's own from the exception.
        trace = str(getattr(record, "agos_trace", "") or "")
        if error is not None:
            trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        frames = [str(f) for f in getattr(record, "agos_frames", None) or []]
        frames = frames or error_issues.frames_of(error.__traceback__ if error else None)
        if not frames:  # no exception: where the line was logged
            frames = [f"{record.module}:{record.funcName}"]
        source = getattr(record, "agos_source", "core")
        named_type = str(getattr(record, "agos_type", "") or "")
        issue_id, alert = error_issues.record(
            self.db,
            source=source if source in error_issues.SOURCES else "core",
            where=str(getattr(record, "agos_where", "") or record.name),
            error_type=type(error).__name__ if error is not None else named_type,
            message=text,
            frames=frames,
            trace=redact(trace, self.hidden),
            route=str(getattr(record, "agos_route", "") or ""),
            workspace_id=workspace,
            request_id=str(getattr(record, "agos_request", "") or ""),
            at=getattr(record, "agos_at", None),
        )
        quiet = getattr(record, "agos_quiet", False)
        if alert is not None and self.alert is not None and not quiet:
            self.alert(issue_id, alert)


def install(core: Any, alert: Callable[[int, str], None] | None = None) -> DbLogHandler:
    """Attach the handler to the "agos" and "agos_core" loggers (idempotent)."""
    workspaces = log_rows.workspace_ids(core.db)
    hidden: tuple[str, ...] = ()
    token = getattr(core, "internal_token", None)
    if isinstance(token, str):
        hidden = (token,)
    handler = DbLogHandler(core.db, workspaces, hidden, alert)
    for name in LOGGERS:
        logger = logging.getLogger(name)
        for old in list(logger.handlers):
            if isinstance(old, DbLogHandler):
                logger.removeHandler(old)
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.WARNING:
            logger.setLevel(logging.INFO)
    return handler


def uninstall(handler: DbLogHandler) -> None:
    for name in LOGGERS:
        logging.getLogger(name).removeHandler(handler)
