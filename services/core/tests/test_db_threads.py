"""The shared connection is used from the event loop and worker threads at once."""

import sqlite3
import threading
import time

from agos_core.db.connection import open_database


def test_many_threads_reading_and_writing_at_once() -> None:
    db = open_database(":memory:")
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(200):
        db.execute("INSERT INTO t (v) VALUES (?)", (f"v{i}",))
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            for _ in range(150):
                rows = [r["v"] for r in db.execute("SELECT v FROM t ORDER BY id")]
                assert len(rows) >= 200
                assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] >= 200
                new = db.execute("INSERT INTO t (v) VALUES (?)", (f"w{n}",)).lastrowid
                assert new
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert db.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 200 + 8 * 150


def test_closing_waits_for_a_running_statement() -> None:
    """When the app stopped, it closed the connection while a worker thread was
    stepping a statement: the whole process crashed (segfault)."""
    db = open_database(":memory:")
    db.execute("CREATE TABLE t (v INTEGER)")
    errors: list[BaseException] = []

    def write() -> None:
        try:
            while True:
                db.execute("INSERT INTO t VALUES (1)")
                db.execute("SELECT COUNT(*) FROM t").fetchone()
        except sqlite3.ProgrammingError:
            return  # closed: a clean error, not a crash
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=write) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    db.close()
    for t in threads:
        t.join(5)
    assert errors == []
