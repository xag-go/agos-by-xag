"""The consent gate: an agent never edits its own instruction files by itself.

Its SOUL.md, config.yaml, AGENTS.md and profile.yaml (the profile home Hermes runs
it in) change only through an `instructions` proposal the owner approved in AGOS.
The approval leaves a token in the profile home (`agos-consent.json`, written by
AGOS: actions/proposals.py consent):

    {"tokens": [{"card", "target", "sha256", "approved_at", "consumed"}]}

A write_file whose content's SHA-256 is the token's goes through once (the token
is marked consumed before the write runs); every other way to the file (patch,
a terminal redirect or sed, skill_manage reaching out of its folder) is refused
with the way to do it. The check is string work on the call; the token file is
read only when the call really targets one of those files. Owner edits through
AGOS (core-side writes) never pass through this hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

CONSENT_FILE = "agos-consent.json"
PROTECTED = ("SOUL.md", "config.yaml", "AGENTS.md", "profile.yaml")
# Names that are the agent's own wherever they are written from (not generic).
OWN_NAMES = ("SOUL.md", "AGENTS.md")
_WRITES = re.compile(
    r"(>|\bsed\s+-i|\btee\b|\bmv\b|\bcp\b|\btruncate\b|\bperl\s+-i|\brm\b|\bdd\b"
    r"|open\([^)]*['\"][wa]|\.write_text\(|\.write_bytes\()"
)
PROPOSE = (
    "Blocked: {name} is one of your own instruction files; you don't change it yourself. "
    'Propose the change with your agos_propose tool, kind "instructions" (payload: '
    "target, a unified diff, the SHA-256 of the whole new file, a summary): AGOS puts the "
    "agos-proposal card in the owner's Inbox, and once he approves write the exact "
    "content with write_file."
)


def target_of(tool: str, args: dict[str, Any], home: Path) -> str | None:
    """The protected file this call would change, or None (string work only)."""
    if tool in ("write_file", "patch"):
        return _path_target(str(args.get("path") or args.get("file_path") or ""), home)
    if tool == "skill_manage":
        for key in ("file_path", "path"):
            raw = str(args.get(key) or "")
            if ".." in raw and raw.replace("\\", "/").rsplit("/", 1)[-1] in PROTECTED:
                return raw.replace("\\", "/").rsplit("/", 1)[-1]
        return None
    if tool in ("terminal", "execute_code", "process"):
        text = str(args.get("command") or args.get("code") or "")
        if not text or not _WRITES.search(text):
            return None
        for name in PROTECTED:
            if name not in text:
                continue
            if name in OWN_NAMES:
                return name
            for root in (str(home), "$HERMES_HOME", "${HERMES_HOME}", "~"):
                if f"{root}/{name}" in text:
                    return name
        return None
    return None


def _path_target(raw: str, home: Path) -> str | None:
    if not raw:
        return None
    clean = raw.strip().replace("\\", "/")
    name = clean.rsplit("/", 1)[-1]
    if name not in PROTECTED:
        return None
    if "/" not in clean:
        return name  # a bare name: its own, wherever the cwd is
    try:
        where = Path(clean).expanduser()
        if not where.is_absolute():
            return name if name in OWN_NAMES else None
        return name if where.resolve() == (home / name).resolve() else None
    except (OSError, RuntimeError):
        return None


def _load(home: Path) -> dict[str, Any]:
    try:
        data = json.loads((home / CONSENT_FILE).read_text())
    except (OSError, ValueError):
        return {"tokens": []}
    tokens = data.get("tokens") if isinstance(data, dict) else None
    return {"tokens": [t for t in (tokens or []) if isinstance(t, dict)]}


def _save(home: Path, data: dict[str, Any]) -> None:
    target = home / CONSENT_FILE
    tmp = target.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle, sort_keys=True)
    tmp.replace(target)


def consume(home: Path, name: str, content: str) -> bool:
    """True when an unconsumed token for this file and this exact content exists;
    it is marked consumed now (one write per approval)."""
    if not (home / CONSENT_FILE).is_file():
        return False
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    data = _load(home)
    for token in data["tokens"]:
        if (
            token.get("target") == name
            and str(token.get("sha256") or "").lower() == digest
            and not token.get("consumed")
        ):
            token["consumed"] = True
            _save(home, data)
            return True
    return False


def gate(tool: str, args: dict[str, Any], home: Path | None) -> dict[str, str] | None:
    """None = not an instruction-file write, or the one approved write; else the
    refusal."""
    if home is None:
        return None
    name = target_of(tool, args, home)
    if name is None:
        return None
    if tool == "write_file" and consume(home, name, str(args.get("content") or "")):
        return None
    if tool == "write_file" and (home / CONSENT_FILE).is_file():
        message = (
            f"Blocked: this content is not what the owner approved for {name} (its SHA-256 "
            "differs, or the approval was used already). Write exactly the proposed content, "
            "or propose again."
        )
        return {"action": "block", "message": message}
    return {"action": "block", "message": PROPOSE.format(name=name)}
