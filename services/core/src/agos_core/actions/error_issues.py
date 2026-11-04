"""Settings → Errors: AGOS's own errors grouped into issues (the System Log, grouped).

Every ERROR that reaches the System Log (core loggers `agos.*` / `agos_core.*`,
an unhandled error in an API route, a page of the web app that broke, or an ERROR
line in a workspace's Hermes `errors.log`) is also counted on one row per issue:

- the issue is its *fingerprint*: where it came from (core | web | hermes), the
  error's type, its message with numbers, ids, paths and quoted values taken out,
  and the top frames of its traceback (module:function, no line numbers, so a
  release that moves code keeps the same issue). One row per fingerprint per
  workspace (none = the installation itself);
- the row keeps how often it happened, when first and last, the AGOS version it
  was first and last seen on, the last request id and route, and the last
  traceback (secrets wiped by `system_log.redact`, 8 KB at most);
- the owner marks an issue fixed (Settings → Errors, or the Co-Founder's
  `mark_error_fixed`); when it happens again it is open again and *came back*.

A new issue, one that came back, or one that suddenly happens many times
(`SPIKE` within an hour) is told to the owner by `error_alerts` the way his
Notifications setting says (event `agos.error`).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import re
import sqlite3
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Literal

from agos_core.db.connection import transaction
from agos_core.db.records import Record
from agos_core.db.rows import now

Source = Literal["core", "web", "hermes"]
Alert = Literal["new", "back", "spike"]
SOURCES: tuple[Source, ...] = ("core", "web", "hermes")

KEEP = 1000  # issues kept (the ones seen longest ago go first)
TRACE_MAX = 8000
MESSAGE_MAX = 1000
SPIKE = 25  # this many in one hour is a spike (told once per SPIKE_QUIET)
SPIKE_QUIET = timedelta(hours=6)
FRAMES = 3

_REPO = Path(__file__).resolve().parents[5]

_NORMALIZE = (
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<id>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.I), "<hex>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"(?:[A-Za-z]:)?(?:/[\w.@+-]+){2,}/?"), "<path>"),
    (re.compile(r"'[^']*'|\"[^\"]*\"|“[^”]*”"), "<v>"),
    (re.compile(r"\d+(?:\.\d+)?"), "<n>"),
)


class ErrorIssue(Record):
    id: int
    source: Source
    where: str  # the logger, or the page / route of the web
    error_type: str
    message: str
    route: str
    workspace_id: str | None
    count: int
    first_seen: str
    last_seen: str
    first_version: str
    version: str
    request_id: str
    status: Literal["open", "fixed"]
    fixed_at: str | None
    came_back: bool
    trace: str


class ErrorIssues(Record):
    issues: list[ErrorIssue]
    version: str


def _head_sha(repo: Path) -> str:
    """The checkout's HEAD commit, read from git's own files (no git process: the
    core starts processes only through hermes_gateway, ADR 0024); "" when unknown.
    Follows a worktree's `.git` file, a symbolic ref and packed refs."""
    git = repo / ".git"
    with contextlib.suppress(OSError, ValueError):
        if git.is_file():
            line = git.read_text(encoding="utf-8").strip()
            if not line.startswith("gitdir:"):
                return ""
            git = (repo / line.removeprefix("gitdir:").strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if re.fullmatch(r"[0-9a-f]{40}", head) else ""
        ref = head.removeprefix("ref:").strip()
        common = git
        with contextlib.suppress(OSError):
            common = (git / (git / "commondir").read_text(encoding="utf-8").strip()).resolve()
        for base in (git, common):
            with contextlib.suppress(OSError):
                found = (base / ref).read_text(encoding="utf-8").strip()
                if re.fullmatch(r"[0-9a-f]{40}", found):
                    return found
        with contextlib.suppress(OSError):
            for line in (common / "packed-refs").read_text(encoding="utf-8").splitlines():
                sha, _, name = line.partition(" ")
                if name.strip() == ref and re.fullmatch(r"[0-9a-f]{40}", sha):
                    return sha
    return ""


@functools.cache
def agos_version() -> str:
    """The release AGOS runs: the VERSION file and the git commit ("0.1.0 · 33e135a")."""
    version = ""
    with contextlib.suppress(OSError):
        version = (_REPO / "VERSION").read_text(encoding="utf-8").strip()
    sha = _head_sha(_REPO)[:7]
    return " · ".join(p for p in (version, sha) if p) or "unknown"


def normalize(message: str) -> str:
    """The message without what changes from one time to the next."""
    text = message.strip().splitlines()[0] if message.strip() else ""
    for pattern, repl in _NORMALIZE:
        text = pattern.sub(repl, text)
    return " ".join(text.split())[:300]


def frames_of(tb: TracebackType | None) -> list[str]:
    """The innermost frames of AGOS's own code (module:function), else of any code."""
    if tb is None:
        return []
    found = traceback.extract_tb(tb)
    ours = [f for f in found if "agos_core" in f.filename] or list(found)
    out: list[str] = []
    for frame in reversed(ours[-FRAMES:]):
        module = Path(frame.filename).stem
        out.append(f"{module}:{frame.name}")
    return out


def fingerprint(source: str, error_type: str, message: str, frames: list[str]) -> str:
    key = "\n".join([source, error_type, normalize(message), *frames[:FRAMES]])
    # A grouping key, not security (usedforsecurity=False); a new hash re-keys stored issues.
    # nosemgrep: python.lang.security.insecure-hash-algorithms.insecure-hash-algorithm-sha1
    return hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:20]


def _hour(at: datetime) -> str:
    return at.replace(minute=0, second=0, microsecond=0).isoformat()


def record(
    db: sqlite3.Connection,
    *,
    source: Source,
    where: str,
    error_type: str,
    message: str,
    frames: list[str],
    trace: str = "",
    route: str = "",
    workspace_id: str | None = None,
    request_id: str = "",
    at: datetime | None = None,
) -> tuple[int, Alert | None]:
    """Counts one error on its issue: (the issue's id, what to tell the owner)."""
    moment = at or datetime.now(UTC)
    stamp = now() if at is None else moment.astimezone(UTC).isoformat(timespec="milliseconds")
    stamp = stamp.replace("+00:00", "Z")
    hour = _hour(moment.astimezone(UTC))
    version = agos_version()
    key = fingerprint(source, error_type, message, frames)
    message = message[:MESSAGE_MAX]
    trace = trace[-TRACE_MAX:]
    with transaction(db):
        row = db.execute(
            """SELECT id, status, hour_start, hour_count, spike_told_at FROM error_issues
               WHERE fingerprint = ? AND COALESCE(workspace_id, '') = ?""",
            (key, workspace_id or ""),
        ).fetchone()
        if row is None:
            cursor = db.execute(
                """INSERT INTO error_issues (fingerprint, workspace_id, source, where_from,
                     error_type, message, route, trace, count, first_seen, last_seen,
                     first_version, version, request_id, hour_start, hour_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    key,
                    workspace_id,
                    source,
                    where[:200],
                    error_type[:200],
                    message,
                    route[:300],
                    trace,
                    stamp,
                    stamp,
                    version,
                    version,
                    request_id,
                    hour,
                ),
            )
            issue_id = int(cursor.lastrowid or 0)
            if issue_id % 100 == 0:
                _prune(db)
            return issue_id, "new"
        issue_id = int(row["id"])
        came_back = row["status"] == "fixed"
        hour_count = int(row["hour_count"]) + 1 if row["hour_start"] == hour else 1
        alert: Alert | None = "back" if came_back else None
        told = row["spike_told_at"]
        quiet = told is not None and moment - _when(str(told)) < SPIKE_QUIET
        if alert is None and hour_count >= SPIKE and not quiet:
            alert = "spike"
        db.execute(
            """UPDATE error_issues SET count = count + 1, last_seen = ?, version = ?,
                 message = ?, route = CASE WHEN ? = '' THEN route ELSE ? END,
                 trace = CASE WHEN ? = '' THEN trace ELSE ? END,
                 request_id = CASE WHEN ? = '' THEN request_id ELSE ? END,
                 hour_start = ?, hour_count = ?,
                 status = 'open', fixed_at = NULL,
                 came_back = CASE WHEN ? THEN 1 ELSE came_back END,
                 spike_told_at = CASE WHEN ? THEN ? ELSE spike_told_at END
               WHERE id = ?""",
            (
                stamp,
                version,
                message,
                route,
                route[:300],
                trace,
                trace,
                request_id,
                request_id,
                hour,
                hour_count,
                came_back,
                alert == "spike",
                stamp,
                issue_id,
            ),
        )
        return issue_id, alert


def _when(stamp: str) -> datetime:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _prune(db: sqlite3.Connection) -> None:
    db.execute(
        """DELETE FROM error_issues WHERE id IN (
             SELECT id FROM error_issues ORDER BY last_seen DESC LIMIT -1 OFFSET ?)""",
        (KEEP,),
    )


def _issue(row: sqlite3.Row) -> ErrorIssue:
    return ErrorIssue(
        id=int(row["id"]),
        source=row["source"],
        where=str(row["where_from"]),
        error_type=str(row["error_type"]),
        message=str(row["message"]),
        route=str(row["route"]),
        workspace_id=row["workspace_id"],
        count=int(row["count"]),
        first_seen=str(row["first_seen"]),
        last_seen=str(row["last_seen"]),
        first_version=str(row["first_version"]),
        version=str(row["version"]),
        request_id=str(row["request_id"]),
        status=row["status"],
        fixed_at=row["fixed_at"],
        came_back=bool(row["came_back"]),
        trace=str(row["trace"]),
    )


def get(db: sqlite3.Connection, issue_id: int) -> ErrorIssue | None:
    row = db.execute("SELECT * FROM error_issues WHERE id = ?", (issue_id,)).fetchone()
    return _issue(row) if row is not None else None


def listed(
    db: sqlite3.Connection,
    *,
    workspace_id: str | None = None,
    source: str | None = None,
    status: str = "open",
    limit: int = 500,
) -> list[ErrorIssue]:
    """The issues, the latest first. `workspace_id` "-" = only the installation's own."""
    sql = "SELECT * FROM error_issues WHERE 1 = 1"
    args: list[object] = []
    if workspace_id == "-":
        sql += " AND workspace_id IS NULL"
    elif workspace_id:
        sql += " AND workspace_id = ?"
        args.append(workspace_id)
    if source:
        sql += " AND source = ?"
        args.append(source)
    if status in ("open", "fixed"):
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY last_seen DESC, id DESC LIMIT ?"
    args.append(max(1, min(limit, 1000)))
    return [_issue(r) for r in db.execute(sql, args).fetchall()]


def set_status(
    db: sqlite3.Connection,
    issue_id: int,
    status: Literal["open", "fixed"],
    *,
    workspace_id: str | None,
) -> str:
    """Marks an issue fixed or open again; returns its status before (for Undo).
    `workspace_id`: only an issue of that workspace or of AGOS itself (the Co-Founder's
    action and its Undo); None for any (the owner's Settings → Errors, every workspace's)."""
    from agos_core.actions.errors import ActionError

    row = db.execute(
        """SELECT status FROM error_issues
           WHERE id = ? AND (? IS NULL OR workspace_id IS NULL OR workspace_id = ?)""",
        (issue_id, workspace_id, workspace_id),
    ).fetchone()
    if row is None:
        raise ActionError("There is no such error.", 404)
    before = str(row["status"])
    db.execute(
        """UPDATE error_issues SET status = ?, fixed_at = CASE WHEN ? = 'fixed' THEN ? END,
             came_back = CASE WHEN ? = 'fixed' THEN 0 ELSE came_back END
           WHERE id = ? AND (? IS NULL OR workspace_id IS NULL OR workspace_id = ?)""",
        (status, status, now(), status, issue_id, workspace_id, workspace_id),
    )
    return before
