"""Opening the database: WAL, foreign keys, migrations, nestable transactions."""

import contextlib
import itertools
import logging
import re
import sqlite3
import struct
import threading
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from agos_core.db import hermes_switches
from agos_core.db.migrations import MIGRATIONS as MIGRATIONS

_savepoints = itertools.count(1)


class NewerDatabaseError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("the database was created by a newer version of AGOS; update the app")


@contextlib.contextmanager
def transaction(db: sqlite3.Connection) -> Iterator[None]:
    """All of it or none of it. Inside another transaction it becomes a savepoint,
    so repository functions can be combined freely.

    On the shared connection the transaction is this thread's alone until it ends:
    the event loop and worker threads use one connection, so another thread's
    statement (or its own transaction, which saw `in_transaction` and became a
    savepoint) would otherwise land inside this one and be committed or rolled
    back with it — a room event taken while another thread's transaction rolled
    back was lost, with the room's cursor already past it."""
    lock: contextlib.AbstractContextManager[Any] = (
        db._lock if isinstance(db, SharedConnection) else contextlib.nullcontext()
    )
    with lock:
        if db.in_transaction:
            name = f"sp_{next(_savepoints)}"
            db.execute(f"SAVEPOINT {name}")
            try:
                yield
            except BaseException:
                db.execute(f"ROLLBACK TO {name}")
                db.execute(f"RELEASE {name}")
                raise
            db.execute(f"RELEASE {name}")
            return
        db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            db.execute("ROLLBACK")
            raise
        db.execute("COMMIT")


class _Rows:
    """A statement's result, read completely while the connection was ours."""

    def __init__(self, cursor: sqlite3.Cursor, rows: list[Any]) -> None:
        self.lastrowid = cursor.lastrowid
        self.rowcount = cursor.rowcount
        self.description = cursor.description
        self._rows = rows
        self._at = 0

    def fetchone(self) -> Any:
        if self._at >= len(self._rows):
            return None
        row = self._rows[self._at]
        self._at += 1
        return row

    def fetchall(self) -> list[Any]:
        rest = self._rows[self._at :]
        self._at = len(self._rows)
        return rest

    def fetchmany(self, size: int = 1) -> list[Any]:
        rest = self._rows[self._at : self._at + size]
        self._at += len(rest)
        return rest

    def __iter__(self) -> Iterator[Any]:
        while (row := self.fetchone()) is not None:
            yield row

    def close(self) -> None:
        self._rows = []


log = logging.getLogger(__name__)

WAIT_TOLD_S = 0.25  # a wait for the shared connection longer than this is told in the log
TELL_EVERY_S = 30.0  # at most one such line (with the holder's stack) this often


def _stack_of(ident: int | None) -> str:
    """Where thread `ident` is right now (Python's faulthandler writes every thread's
    stack; this one's part is kept)."""
    import faulthandler
    import tempfile

    if ident is None:
        return "(unknown)"
    with tempfile.TemporaryFile("w+") as out:
        faulthandler.dump_traceback(out, all_threads=True)
        out.seek(0)
        dumped = out.read()
    mark = f"0x{ident:0{2 * struct.calcsize('P')}x}"
    for part in dumped.split("\n\n"):
        if mark in part.splitlines()[0] if part.strip() else False:
            return part.strip()
    return "(unknown)"


class _TimedLock:
    """The shared connection's lock (re-entrant), with long waits told in the log.

    The event loop and every thread share one connection: while one thread holds it
    (a long statement, a transaction with slow work inside), every page and gateway
    call waits. A wait longer than WAIT_TOLD_S names the thread that held it and
    where it was at that moment, so a 12-122 s stall says who caused it. The line is
    written after the lock is given back (a log handler may write to the database)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._holder: int | None = None
        self._depth = 0
        self._told_at = 0.0
        self._tell: str | None = None

    def __enter__(self) -> "_TimedLock":
        if not self._lock.acquire(timeout=WAIT_TOLD_S):
            started = time.monotonic() - WAIT_TOLD_S
            tell = started - self._told_at >= TELL_EVERY_S
            holder = self._holder
            where = _stack_of(holder) if tell else ""
            name = next((t.name for t in threading.enumerate() if t.ident == holder), "?")
            self._lock.acquire()
            if tell:
                self._told_at = time.monotonic()
                self._tell = (
                    f"db: waited {time.monotonic() - started:.2f}s for the shared connection; "
                    f"thread {name} held it, at:\n{where}"
                )
        if self._depth == 0:
            self._holder = threading.get_ident()
        self._depth += 1
        return self

    def __exit__(self, *_exc: object) -> None:
        self._depth -= 1
        tell = None
        if self._depth == 0:
            self._holder = None
            tell, self._tell = self._tell, None
        self._lock.release()
        if tell is not None:
            log.warning("%s", tell.rstrip())


class SharedConnection(sqlite3.Connection):
    """One connection used by the event loop and worker threads: one statement at a
    time, each read to the end before the next ("bad parameter or other API misuse"
    came from two threads stepping statements on it at once)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._lock = _TimedLock()

    def execute(self, sql: str, parameters: Any = (), /) -> Any:
        with self._lock, hermes_switches.statement():
            try:
                cursor = super().execute(sql, parameters)
            except OverflowError as error:  # a number past SQLite's 64-bit INTEGER
                raise ValueError("a number in the request is too large") from error
            return _Rows(cursor, cursor.fetchall() if cursor.description else [])

    def executemany(self, sql: str, parameters: Iterable[Any], /) -> Any:
        with self._lock:
            cursor = super().executemany(sql, parameters)
            return _Rows(cursor, [])

    def executescript(self, sql_script: str, /) -> Any:
        with self._lock:
            return super().executescript(sql_script)

    def close(self) -> None:
        # A worker thread may still be inside execute() when the app stops:
        # closing under it crashed the process (segfault). Wait for it first.
        with self._lock:
            super().close()


FOREIGN_KEYS_OFF = "-- agos: foreign-keys-off"
# "-- agos: ensure-column <table>.<column> <type>": added first when it's missing
# (a migration that was changed after it shipped left some databases without it).
_ENSURE = re.compile(r"^\s*-- agos: ensure-column (\w+)\.(\w+) (\w+)\s*$", re.M)


def _ensure_columns(db: sqlite3.Connection, sql: str) -> None:
    for table, column, kind in _ENSURE.findall(sql):
        have = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


# ``-- agos: rename-table old new``: the rename happens once (a table already renamed,
# or never there, is left alone), so a migration that renames can run again (step 32's
# old-copies test replays the tail of the list).
_RENAME = re.compile(r"^\s*-- agos: rename-table (\w+) (\w+)\s*$", re.M)


def _rename_tables(db: sqlite3.Connection, sql: str) -> None:
    for old, new in _RENAME.findall(sql):
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if old in names and new not in names:
            db.execute(f"ALTER TABLE {old} RENAME TO {new}")


class MigrationError(RuntimeError):
    """A migration would leave broken links between tables: nothing was changed."""


def _migrate(db: sqlite3.Connection, data_root: Path | None = None) -> None:
    from agos_core.db import leftovers, logins_gone, old_board, old_copies

    current: int = db.execute("PRAGMA user_version").fetchone()[0]
    if current > len(MIGRATIONS):
        raise NewerDatabaseError
    for index, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        # A table rebuild (SQLite's own recipe) runs with foreign keys off, so
        # dropping the old copy never cascades; every link is checked before commit.
        rebuild = FOREIGN_KEYS_OFF in sql
        if rebuild:
            db.execute("PRAGMA foreign_keys = OFF")
        try:
            with transaction(db):
                _ensure_columns(db, sql)
                _rename_tables(db, sql)
                if old_board.MARK in sql:
                    old_board.archive(db, data_root)
                if old_board.HISTORY_MARK in sql:
                    old_board.archive_history(db, data_root)
                if leftovers.MARK in sql:
                    leftovers.archive(db, data_root)
                if old_copies.MARK in sql:
                    old_copies.move(db, data_root)
                if logins_gone.MARK in sql:
                    logins_gone.keep_owner_name(db)
                # executescript would commit; run statement by statement instead.
                for statement in _split(sql):
                    db.execute(statement)
                if rebuild and db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise MigrationError(f"migration {index} would break links between tables")
                db.execute(f"PRAGMA user_version = {index}")
        finally:
            if rebuild:
                db.execute("PRAGMA foreign_keys = ON")


def _split(script: str) -> list[str]:
    """Splits a migration into statements; triggers (BEGIN…END) stay whole."""
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if buffer.strip():
                statements.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def open_read_only(file: Path, *, timeout: float = 30) -> sqlite3.Connection:
    """A read-only connection of its own to one of AGOS's database files (or a copy),
    for checks that must never block the core's writers (db/health.py)."""
    return sqlite3.connect(f"file:{file}?mode=ro", uri=True, timeout=timeout)


def open_database(file: Path | str) -> sqlite3.Connection:
    """Opens, creates or upgrades the database. ":memory:" is accepted for tests.
    The file is created private to the owner's user."""
    if file != ":memory:":
        path = Path(file)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)
    db = sqlite3.connect(
        file, isolation_level=None, check_same_thread=False, factory=SharedConnection
    )
    db.row_factory = sqlite3.Row
    from agos_core.db import hermes_text

    hermes_text.install(db)  # functions older migrations' views name
    from agos_core.db import hermes_switches

    hermes_switches.install(db)  # Hermes's own on/off switches (agos_bot_on)
    for pragma in (
        "journal_mode = WAL",
        "foreign_keys = ON",
        "busy_timeout = 5000",
        "synchronous = NORMAL",
    ):
        db.execute(f"PRAGMA {pragma}")
    # The data folder (system/agos.db lives in it): where a migration may keep files.
    _migrate(db, Path(file).resolve().parent.parent if file != ":memory:" else None)
    return db
