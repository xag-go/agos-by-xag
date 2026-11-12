"""Every AGOS write of a Hermes home's .env goes through `rewrite`, under
Hermes's own .env lock.

Hermes writes the same file while it runs: a pairing approval adds the user to
TELEGRAM_ALLOWED_USERS (gateway/pairing.py `_write_allowlist_env`), the dashboard
and `hermes tools` save keys. All of those go through hermes_cli.config
`save_env_value` / `remove_env_value`, which hold Hermes's .env lock for the whole
read, change and write: `_env_write_lock` (hermes_cli/config.py:2578), an
exclusive flock on `<.env>.lock` (hermes_cli/auth.py `_file_lock`, `_kernel_lock`
at :592). AGOS takes that same lock, re-reads the file under it and replaces it
whole, so neither side can lose the other's lines.

No other AGOS module writes a Hermes .env (tests/test_hermes_writes_guard.py).
"""

import fcntl
import os
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT = 15.0  # Hermes's own wait for this lock (hermes_cli/config.py:2602)


def lock_path(env_file: Path) -> Path:
    """Hermes's .env lock file: `<.env>.lock` beside it."""
    return env_file.with_name(env_file.name + ".lock")


@contextmanager
def hermes_env_lock(env_file: Path, timeout: float = LOCK_TIMEOUT) -> Iterator[None]:
    """Holds Hermes's .env lock (the flock Hermes's save_env_value takes)."""
    path = lock_path(env_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"The engine's .env lock is busy ({env_file})") from None
                time.sleep(0.02)
        try:
            handle.truncate(0)  # who holds it, the way Hermes stamps it
            handle.write(f"{os.getpid()}\n")
            handle.flush()
            yield
        finally:
            handle.truncate(0)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _name(line: str) -> str:
    """The line as Hermes's .env reader sees its name (`export KEY=…` too)."""
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    return stripped


def rewrite(env_file: Path, drop: tuple[str, ...], add: Iterable[str]) -> None:
    """Keeps the lines that don't start with `drop`, adds `add` (mode 0600)."""
    added = list(add)
    with hermes_env_lock(env_file):
        lines = [
            line
            for line in (env_file.read_text().splitlines() if env_file.exists() else [])
            if not _name(line).startswith(drop)
        ]
        lines += added
        tmp = env_file.with_name(env_file.name + ".agos-tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.chmod(0o600)
        tmp.replace(env_file)
