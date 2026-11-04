"""A workspace skill's versions, derived from Hermes's skill ledger (pure helpers).

Hermes's ledger (tools/skill_ledger.py) is the record of every skill mutation: one
entry per operation with the changed files' before / after blobs by content hash.
It keeps deltas, not whole snapshots, and it trims itself at `skills.ledger_max_bytes`
(then garbage-collects the blobs nothing references), so a version's full content
can't be read back from it forever. AGOS therefore keeps, per version, one
immutable snapshot file of the whole skill folder — `skill-version-<n>.json` under
`<root>/.agos-versions/<skill>/` (actions/skill_versions.py writes them) — derived
from the ledger when the version is first seen. The snapshots live beside Hermes's
own skills folder, never inside it: Hermes's skill scanner skips only a fixed list
of folder names (agent/skill_utils.py EXCLUDED_SKILL_DIRS), so a SKILL.md copy
under `skills/.agos-versions/` would be indexed as a shadow skill.

A version = one write: the ledger entries one skill_manage call made (a batch is
one entry per op, in one process, with the same actor and session). AGOS's own
writes record their exact entry ids; entries from elsewhere (the Co-Founder's
skill_manage tool, Hermes's curator) are grouped by actor, session and a short time
window. A change the ledger never saw (Hermes's hub install / update, a file copied
beside the skill) becomes an "observed" version from the folder itself.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

VERSIONS_DIR = ".agos-versions"  # <root>/.agos-versions/<skill>/skill-version-<n>.json
# Consecutive ledger entries of one actor and session within this many seconds are
# one write (a skill_manage batch runs its ops in one process, milliseconds apart).
BATCH_WINDOW_S = 5.0
# Hermes's ledger actors (tools/skill_ledger.py _VALID_ACTORS) as AGOS names them.
AUTHORS = {"user": "owner", "agent": "cofounder", "curator": "curator"}
# What a version's files are kept as: text when UTF-8, else bytes (base64).
TEXT, BYTES = "text", "b64"


@dataclass(frozen=True)
class Version:
    number: int
    at: str  # ISO time of the write (the first entry's, or the observation's)
    author: str  # owner / cofounder / curator / hub / outside / agos
    action: str  # create / edit / delete / restore / undo / install / update / observed
    summary: str
    entries: tuple[str, ...]  # the ledger entry ids this version is made of
    files: dict[str, bytes] = field(default_factory=dict, compare=False)  # rel path -> content

    @property
    def size(self) -> int:
        return sum(len(b) for b in self.files.values())

    @property
    def digest(self) -> str:
        return files_digest(self.files)

    def listed(self) -> dict[str, Any]:
        """What the Versions tab shows (no content)."""
        return {
            "number": self.number,
            "at": self.at,
            "author": self.author,
            "action": self.action,
            "summary": self.summary,
            "size": self.size,
            "files": sorted(self.files),
            "entries": list(self.entries),
        }


# ---- content ----------------------------------------------------------------------


def files_digest(files: dict[str, bytes]) -> str:
    """One hash of a whole folder state (paths and bytes), to tell two states apart."""
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(rel.encode("utf-8") + b"\0")
        h.update(hashlib.sha256(files[rel]).digest())
    return h.hexdigest()


# What Hermes's ledger leaves out of a skill snapshot (tools/skill_ledger.py
# TRANSIENT_DIRS): the folder is read the same way, so the two states compare.
TRANSIENT_DIRS = frozenset(
    {
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
    }
)


def read_folder(folder: Path | None) -> dict[str, bytes]:
    """Every regular file of a skill folder (no links), by POSIX path relative to
    it, read as Hermes's ledger snapshots it (transient folders left out)."""
    if folder is None or not folder.is_dir():
        return {}
    out: dict[str, bytes] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(folder)
        if any(part in TRANSIENT_DIRS for part in rel.parts[:-1]):
            continue
        try:
            out[rel.as_posix()] = path.read_bytes()
        except OSError:
            continue
    return out


def as_text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---- the snapshot files -----------------------------------------------------------


def store_dir(home: Path, skill: str) -> Path:
    return home / VERSIONS_DIR / skill


def version_file(home: Path, skill: str, number: int) -> Path:
    return store_dir(home, skill) / f"skill-version-{number}.json"


def encode(version: Version) -> str:
    files: dict[str, dict[str, str]] = {}
    for rel, data in sorted(version.files.items()):
        text = as_text(data)
        files[rel] = (
            {TEXT: text} if text is not None else {BYTES: base64.b64encode(data).decode("ascii")}
        )
    return json.dumps(
        {
            "version": version.number,
            "at": version.at,
            "author": version.author,
            "action": version.action,
            "summary": version.summary,
            "entries": list(version.entries),
            "files": files,
        },
        ensure_ascii=False,
        indent=1,
    )


def decode(text: str) -> Version:
    raw = json.loads(text)
    files: dict[str, bytes] = {}
    for rel, item in (raw.get("files") or {}).items():
        if not isinstance(item, dict):
            continue
        if TEXT in item:
            files[str(rel)] = str(item[TEXT]).encode("utf-8")
        elif BYTES in item:
            files[str(rel)] = base64.b64decode(str(item[BYTES]))
    return Version(
        number=int(raw["version"]),
        at=str(raw.get("at") or ""),
        author=str(raw.get("author") or ""),
        action=str(raw.get("action") or ""),
        summary=str(raw.get("summary") or ""),
        entries=tuple(str(e) for e in raw.get("entries") or []),
        files=files,
    )


def load_all(home: Path, skill: str) -> list[Version]:
    """The stored versions, oldest first (a file that can't be read is skipped)."""
    folder = store_dir(home, skill)
    if not folder.is_dir():
        return []
    out: list[Version] = []
    for path in folder.glob("skill-version-*.json"):
        try:
            out.append(decode(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            continue
    out.sort(key=lambda v: v.number)
    return out


def save_for(home: Path, skill: str, version: Version) -> Path:
    """Writes one version's snapshot (aside, then renamed: never half a file)."""
    path = version_file(home, skill, version.number)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(encode(version), encoding="utf-8")
    tmp.replace(path)
    return path


# ---- from the ledger ---------------------------------------------------------------


def _when(entry: dict[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(entry.get("ts") or "")).timestamp()
    except ValueError:
        return 0.0


def group_entries(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Ledger entries (oldest first) as writes: consecutive entries of one actor and
    session within BATCH_WINDOW_S of the group's first. A rollback's safety entry
    (`pre-rollback`) rides with its `rollback`."""
    groups: list[list[dict[str, Any]]] = []
    for entry in entries:
        if groups:
            head = groups[-1][0]
            same = (
                head.get("actor") == entry.get("actor")
                and _session(head) == _session(entry)
                and 0 <= _when(entry) - _when(head) <= BATCH_WINDOW_S
            )
            if same:
                groups[-1].append(entry)
                continue
        groups.append([entry])
    return groups


def _session(entry: dict[str, Any]) -> str:
    return str((entry.get("evidence") or {}).get("session_id") or "")


def _decode_side(side: Any) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for rel, b64 in (side or {}).items():
        out[str(rel)] = None if b64 is None else base64.b64decode(str(b64))
    return out


def apply_group(state: dict[str, bytes], group: list[dict[str, Any]]) -> dict[str, bytes]:
    """The folder after these entries: each entry's `after` files written, the
    files it had only in `before` removed (a blob Hermes no longer has leaves the
    file as it was)."""
    now = dict(state)
    for entry in group:
        before = _decode_side(entry.get("before"))
        after = _decode_side(entry.get("after"))
        for rel in before:
            if rel not in after:
                now.pop(rel, None)
        for rel, data in after.items():
            if data is not None:
                now[rel] = data
    return now


def before_group(state: dict[str, bytes], group: list[dict[str, Any]]) -> dict[str, bytes]:
    """The folder as the ledger says it was right before these entries: `state`
    with every touched file as the entries' `before` has it (absent = not there)."""
    was = dict(state)
    for entry in group:
        before = _decode_side(entry.get("before"))
        after = _decode_side(entry.get("after"))
        for rel in after:
            if rel not in before:
                was.pop(rel, None)
        for rel, data in before.items():
            if data is not None:
                was[rel] = data
    return was


def describe(group: list[dict[str, Any]]) -> tuple[str, str, str]:
    """(author, action, summary) of a write from its ledger entries."""
    head = group[0]
    actor = str(head.get("actor") or "")
    author = AUTHORS.get(actor, actor or "outside")
    actions = [str(e.get("action") or "") for e in group]
    if "rollback" in actions:
        return author, "undo", "undo (Hermes's ledger rollback)"
    if "delete" in actions or "archive" in actions or "purge" in actions:
        return author, "delete", "deleted"
    if "create" in actions:
        return author, "create", "created"
    touched = sorted({str(p) for e in group for p in (e.get("paths") or []) if p})
    files = ", ".join(touched[:4]) + (", …" if len(touched) > 4 else "")
    return author, "edit", f"edited {files}" if files else "edited"


def _iso(entry: dict[str, Any]) -> str:
    return str(entry.get("ts") or "")


def derive(
    stored: list[Version],
    history: list[dict[str, Any]],
    disk: dict[str, bytes],
    *,
    now: str,
    observed_author: str,
    observed_action: str,
    first_action: str = "",
) -> list[Version]:
    """The versions to add to `stored` (oldest first, numbered after it) from the
    ledger's entries for the skill (`history`, oldest first, each with its
    before/after file contents) and the folder as it is now (`disk`).

    Entries a stored version already names are skipped. A gap the ledger doesn't
    explain (the folder before a write differs from the last known state, or the
    folder now differs from the last version) is an observed version, by
    `observed_author` / `observed_action` (`first_action` when it is the skill's
    first version: an install, not an update)."""
    known = {e for v in stored for e in v.entries}
    state = dict(stored[-1].files) if stored else {}
    number = stored[-1].number if stored else 0
    out: list[Version] = []

    def observed(at: str, files: dict[str, bytes]) -> None:
        nonlocal number
        number += 1
        first = not (stored or out)
        summary = "as found in the skill folder" if first else "changed outside Hermes's skill tool"
        action = first_action if first and first_action else observed_action
        out.append(Version(number, at, observed_author, action, summary, (), files))

    fresh = [e for e in history if str(e.get("id") or "") not in known and "after" in e]
    for group in group_entries(fresh):
        was = before_group(state, group)
        if files_digest(was) != files_digest(state):
            observed(_iso(group[0]), was)
        state = apply_group(was, group)
        author, action, summary = describe(group)
        number += 1
        out.append(
            Version(
                number,
                _iso(group[0]),
                author,
                action,
                summary,
                tuple(str(e.get("id") or "") for e in group),
                state,
            )
        )
    if disk and files_digest(disk) != files_digest(state):
        observed(now, dict(disk))
    return out


# ---- diff and restore -----------------------------------------------------------------


def unified_diff(a: Version, b: Version) -> list[dict[str, str]]:
    """Per file, a unified diff from version a to version b (empty when equal; a
    one-line note for binary files)."""
    out: list[dict[str, str]] = []
    for rel in sorted(set(a.files) | set(b.files)):
        was, now = a.files.get(rel), b.files.get(rel)
        if was == now:
            continue
        was_text = as_text(was) if was is not None else ""
        now_text = as_text(now) if now is not None else ""
        if was_text is None or now_text is None:
            out.append({"path": rel, "diff": "Binary file differs."})
            continue
        lines = difflib.unified_diff(
            was_text.splitlines(keepends=True),
            now_text.splitlines(keepends=True),
            fromfile=f"v{a.number}/{rel}",
            tofile=f"v{b.number}/{rel}",
        )
        out.append({"path": rel, "diff": "".join(lines)})
    return out


def restore_plan(
    target: Version, disk: dict[str, bytes], allowed_dirs: tuple[str, ...]
) -> tuple[str | None, dict[str, str], list[str]]:
    """What Hermes's skill_manage must write to make the folder the version:
    (SKILL.md text when it differs, {file: text | "" to remove}, files skipped).
    Skipped: binary files and files outside the folders Hermes's skill tool writes
    (they stay as they are and are named in the answer)."""
    skipped: list[str] = []
    text: str | None = None
    want_md = target.files.get("SKILL.md")
    if want_md is not None and want_md != disk.get("SKILL.md"):
        text = as_text(want_md)
        if text is None:
            skipped.append("SKILL.md")
    files: dict[str, str] = {}
    for rel in sorted(set(target.files) | set(disk)):
        if rel == "SKILL.md":
            continue
        want, have = target.files.get(rel), disk.get(rel)
        if want == have:
            continue
        if rel.split("/", 1)[0] not in allowed_dirs or "/" not in rel:
            skipped.append(rel)
            continue
        if want is None:
            files[rel] = ""
            continue
        body = as_text(want)
        if body is None:
            skipped.append(rel)
            continue
        files[rel] = body
    return text, files, skipped
