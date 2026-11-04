"""Keys in what the owner writes and in what Hermes kept, as Hermes's own masking
sees them (agent/redact.py redact_sensitive_text; ADR 0023).

Runs only inside Hermes's runtime: in the gateway (bridge.pre_gateway_dispatch masks
his Telegram message before Hermes keeps it), and as a plain file AGOS runs with
Hermes's Python (engine/owner_keys.py: `keys.py serve` masks his web chat messages,
`keys.py scan <root>` is the Secrets check on Settings → Health). So: the standard
library and Hermes only, no AGOS import, no package-relative import.

What a key is stays Hermes's answer: the text changes under
redact_sensitive_text(force=True) with Hermes's default URL handling (a link he pastes
for the agent keeps its query; known key shapes inside a URL are still masked). One
thing Hermes masks is put back: a phone number (+212…) is not a key, and the owner
gives his agents numbers on purpose.

Where the text changed, the original token there is the key. Only its kind (the
head Hermes's own mask shows, e.g. "sk-or-", or the name it was assigned to) and its
last 4 characters ever leave this file, never the value.
"""

from __future__ import annotations

import contextlib
import json
import re
import sqlite3
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NOTE = "[AGOS hid a key in this message. Keys go in Settings → Keys, never in chat.]"

# Where a token ends (a key never holds these).
_EDGES = frozenset(" \t\r\n\"'`<>()[]{},;=")
_PHONE = re.compile(r"\+[1-9]\d{6,14}")
_NAME_BEFORE = re.compile(r"([A-Za-z_][A-Za-z0-9_.-]{1,60})[\"']?\s*[:=]\s*[\"']?$")
_TELEGRAM = re.compile(r"\d{6,}:\*+")
# Hermes's marks are short ("...", "***", "[REDACTED PRIVATE KEY]", "+212****5678"):
# the texts agree again at most this far into `after`, on a stretch this long.
_MARK_MAX = 64
_ANCHOR = 8
# The columns of Hermes's messages a key can sit in (state.db; H: hermes_state_common.py).
COLUMNS = ("content", "tool_calls", "api_content")
MAX_LISTED = 200  # findings listed per root; the rest only counted
LOG_CHUNK = 200  # log lines asked together; a chunk Hermes changes is asked line by line


def _hermes() -> Callable[[str], str]:
    from agent.redact import redact_sensitive_text  # type: ignore[import-not-found]

    def one(text: str) -> str:
        return str(redact_sensitive_text(text, force=True))

    return one


def _resync(before: str, after: str, i: int, j: int) -> tuple[int, int]:
    """Where the two texts agree again after Hermes's mark at after[j:]: the first
    stretch of `after` behind a short mark that is found in `before` (str.find, so
    a long tool output is not compared letter by letter)."""
    for skip in range(_MARK_MAX + 1):
        mark = after[j : j + skip]
        if mark.count("[") > mark.count("]") or mark.count("«") > mark.count("»"):
            continue  # inside Hermes's [REDACTED …] / «redacted…» mark
        anchor = after[j + skip : j + skip + _ANCHOR]
        if not anchor:
            return len(before), len(after)
        if len(anchor) < _ANCHOR:
            at = len(before) - len(anchor)
            if at >= i and before.endswith(anchor):
                return at, j + skip
            continue
        at = before.find(anchor, i)
        if at >= 0:
            return at, j + skip
    return len(before), len(after)


def _regions(before: str, after: str) -> Iterator[tuple[int, int, int, int]]:
    """Each place Hermes's masking changed (before[i1:i2] -> after[j1:j2]). Hermes
    only replaces stretches by short marks, in order, so the texts are walked once."""
    i = j = 0
    while i < len(before) and j < len(after):
        if before[i] == after[j]:
            i += 1
            j += 1
            continue
        i2, j2 = _resync(before, after, i, j)
        yield i, i2, j, j2
        i, j = i2, j2
    if i < len(before) or j < len(after):
        yield i, len(before), j, len(after)


def _token_start(text: str, i: int) -> int:
    while i > 0 and text[i - 1] not in _EDGES:
        i -= 1
    return i


def _token_end(text: str, i: int) -> int:
    while i < len(text) and text[i] not in _EDGES:
        i += 1
    return i


def _kind(before: str, i1: int, shown: str) -> str:
    """What kind of key, from what Hermes's own mask shows (never the value)."""
    if "PRIVATE KEY" in shown:
        return "private key"
    if "..." in shown:
        head = before[_token_start(before, i1) : i1] + shown.split("...", 1)[0]
        head = re.split(r"[\s=:\"'`(),;\[\]{}<>.]", head)[-1][:12]
        cut = max(head.rfind("-"), head.rfind("_"))
        head = head[: cut + 1] if cut > 0 else head[:4]
        return f"{head}… key" if head else "key"
    lead = before[_token_start(before, i1) : i1]
    if _TELEGRAM.fullmatch(lead + shown):
        return "bot token"
    if "://" in lead:
        return "password in a link"
    name = _NAME_BEFORE.search(before[max(0, i1 - 80) : i1])
    return f"{name.group(1)} value" if name else "secret"


def _last4(secret: str) -> str:
    lines = [ln for ln in secret.splitlines() if not ln.strip().startswith("-----")]
    chars = [c for c in "".join(lines) if c.isalnum()]
    return "".join(chars[-4:])


def hide(text: str, mask: Callable[[str], str] | None = None) -> tuple[str, list[dict[str, str]]]:
    """(the text with its keys masked by Hermes, [{kind, last4}] of each key)."""
    if not text:
        return text, []
    after = (mask or _hermes())(text)
    if after == text:
        return text, []
    out: list[str] = []
    found: list[dict[str, str]] = []
    at = 0
    for i1, i2, j1, j2 in _regions(text, after):
        out.append(text[at:i1])
        shown = after[j1:j2]
        start, end = _token_start(text, i1), _token_end(text, i2)
        if set(shown) <= {"*"} and _PHONE.fullmatch(text[start:end]):
            out.append(text[i1:i2])  # a phone number: not a key, kept as he wrote it
        else:
            out.append(shown)
            # Hermes's mask keeps the key's last characters after its "...".
            tail = text[i2 : _token_end(text, i2)] if shown.endswith("...") else ""
            found.append({"kind": _kind(text, i1, shown), "last4": _last4(text[i1:i2] + tail)})
        at = i2
    out.append(text[at:])
    return "".join(out), found


def owner_text(
    text: str, *, command: bool = False, mask: Callable[[str], str] | None = None
) -> str | None:
    """His message with its keys masked, and the note that tells the agent (so it
    tells him); None when there was nothing to hide. A /command gets no note: its
    arguments are Hermes's to parse."""
    masked, found = hide(text, mask)
    if not found:
        return None
    return masked if command else f"{masked}\n\n{NOTE}"


# ---- the Secrets check ----------------------------------------------------------------


def _at(stamp: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(stamp), UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _homes(root: str) -> list[tuple[str, Path]]:
    """(profile as Hermes names it, home) of the root and its members."""
    out = [("default", Path(root))]
    with contextlib.suppress(OSError):
        for home in sorted((Path(root) / "profiles").iterdir()):
            if home.is_dir() and not home.is_symlink():
                out.append((home.name, home))
    return out


def scan_db(
    path: Path, profile: str, mask: Callable[[str], str]
) -> tuple[list[dict[str, Any]], int]:
    """Hermes's messages that hold a key (read-only), and how many there are."""
    found: list[dict[str, Any]] = []
    total = 0
    with contextlib.closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        have = {str(r[1]) for r in db.execute("PRAGMA table_info(messages)")}
        columns = [c for c in COLUMNS if c in have]
        if not columns:
            return [], 0
        info = {str(r[1]) for r in db.execute("PRAGMA table_info(sessions)")}
        title = "s.title" if "title" in info else "NULL"
        picked = ", ".join(f"m.{c}" for c in columns)
        rows = db.execute(
            f"""SELECT m.id, m.role, m.timestamp, {picked}, s.source, {title} AS title
                  FROM messages m LEFT JOIN sessions s ON s.id = m.session_id
                 ORDER BY m.id"""
        )
        for row in rows:
            for column in columns:
                text = row[column]
                if not isinstance(text, str) or not text:
                    continue
                _masked, keys = hide(text, mask)
                for key in keys:
                    total += 1
                    if len(found) < MAX_LISTED:
                        found.append(
                            {
                                "profile": profile,
                                "session": str(row["title"] or ""),
                                "source": str(row["source"] or ""),
                                "role": str(row["role"] or ""),
                                "at": _at(row["timestamp"]),
                                "column": column,
                                **key,
                            }
                        )
    return found, total


def scan_log(path: Path, mask: Callable[[str], str]) -> tuple[int, list[dict[str, str]]]:
    """(lines of this log that hold a key, the keys' kind + last 4)."""
    count = 0
    keys: list[dict[str, str]] = []

    def chunk(lines: list[str]) -> None:
        nonlocal count
        joined = "".join(lines)
        if mask(joined) == joined:
            return
        for line in lines:
            _masked, found = hide(line, mask)
            if found:
                count += 1
                keys.extend(k for k in found if k not in keys and len(keys) < 20)

    with path.open(encoding="utf-8", errors="replace") as f:
        lines: list[str] = []
        for line in f:
            lines.append(line)
            if len(lines) >= LOG_CHUNK:
                chunk(lines)
                lines = []
        if lines:
            chunk(lines)
    return count, keys


def _logs(root: str) -> Iterator[Path]:
    for _profile, home in _homes(root):
        with contextlib.suppress(OSError):
            for path in sorted((home / "logs").iterdir()):
                if re.fullmatch(r".+\.log(\.\d+)?", path.name) and path.is_file():
                    yield path


def scan(root: str, mask: Callable[[str], str] | None = None) -> dict[str, Any]:
    """One Hermes root: keys in its chat history (every profile's state.db) and in its
    logs. Reads only; never prints a value."""
    one = mask or _hermes()
    chats: list[dict[str, Any]] = []
    total = 0
    errors: list[str] = []
    for profile, home in _homes(root):
        path = home / "state.db"
        if not path.is_file():
            continue
        try:
            got, n = scan_db(path, profile, one)
        except sqlite3.Error as error:
            errors.append(f"{profile}: chat history not read ({error})")
            continue
        chats.extend(got[: max(0, MAX_LISTED - len(chats))])
        total += n
    logs: list[dict[str, Any]] = []
    for path in _logs(root):
        try:
            count, keys = scan_log(path, one)
        except OSError as error:
            errors.append(f"{path.relative_to(root)}: not read ({error.strerror})")
            continue
        if count:
            logs.append({"file": str(path.relative_to(root)), "count": count, "keys": keys})
    return {"chats": chats, "chats_total": total, "logs": logs, "errors": errors}


def serve() -> None:
    """AGOS's helper: one JSON list of texts per line in, [[masked, keys], …] out."""
    one = _hermes()
    for line in sys.stdin:
        texts = json.loads(line)
        sys.stdout.write(json.dumps([list(hide(str(t), one)) for t in texts]) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if sys.argv[1:2] == ["serve"]:
        serve()
    elif sys.argv[1:2] == ["scan"] and len(sys.argv) == 3:
        sys.stdout.write("AGOS-KEYS " + json.dumps(scan(sys.argv[2])) + "\n")
    else:
        raise SystemExit("usage: keys.py serve | scan <root>")
