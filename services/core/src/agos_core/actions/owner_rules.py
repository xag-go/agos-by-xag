"""The owner's rules for every workspace (shared lessons), as Hermes keeps them.

Most of what the owner teaches belongs to ONE project (its feedback, memory and
playbooks stay there). A few things are about him, not a project: his language,
how he wants to be asked, how he likes reports. Those are his rules set in AGOS, so
a lesson learned in one project helps all of them, with nothing of a project's own
work carried over.

Where they live: entries of the shared Hermes home's USER.md (the one General
Settings writes, `engine.settings.hermes_home`), marked as his rules. That is the
one place AGOS reads and edits them. AGOS keeps no table of them; only which
workspace proposed one is kept beside it (`owner-rules.json` in AGOS's data, never
read by an agent), like the Brain's origins.

How every agent gets them: one system-prompt section of the agos-guard plugin,
Hermes's own place for a plugin's context (H: hermes_cli/plugins.py
`register_system_prompt_section`, rendered into every new session's prompt, cron
and Kanban runs included: H: agent/system_prompt.py `build_system_prompt_parts`).
The plugin asks AGOS for them (`/hermes-bridge/<ws>/owner-rules`) when a session
starts. So they are no longer copied into each root's and member's USER.md, where
Hermes's own memory tool could edit or drop them. Hermes caps a section at 4,000
characters and skips a longer one whole, and caps all sections at 8,000 (H:
hermes_cli/plugins_dispatch.py `MAX_SYSTEM_PROMPT_SECTION_CHARS`,
`MAX_SYSTEM_PROMPT_SECTIONS_TOTAL_CHARS`), so the plugin has two sections and his
rules are split between them, whole rules each (`section_parts`). Only when they
are longer than that are the sections empty and the rules written into every
USER.md as before, so none is ever lost. `sync_profile` puts each profile in the
right state; it runs for every profile at AGOS's start (the one-time clean-up of
the old copies).

A rule is added by the owner (Settings → My rules) or proposed by a workspace's
Co-Founder with an `add_owner_rule` card, which always waits for his Approve: it
reaches every project. A workspace's own rules win on its project.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.rows import now

log = logging.getLogger("agos.owner_rules")

MARK = "[The owner's rule for every workspace, set in AGOS] "
ENTRY_DELIMITER = "\n§\n"  # Hermes's memory files (tools/memory_tool_store.py)
_lock = threading.Lock()


def rule_id(text: str) -> int:
    """A rule's id: from its text (48 bits, safe as a number in the web app)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def _shared(core: Core) -> Path:
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    return core.engine.settings.hermes_home


def _entries(home: Path) -> list[str]:
    path = home / "memories" / "USER.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [
        e[len(MARK) :].strip()
        for e in text.split(ENTRY_DELIMITER)
        if e.startswith(MARK) and e[len(MARK) :].strip()
    ]


def texts(core: Core) -> list[str]:
    """His rules, in order, as the shared Hermes home's USER.md has them."""
    if core.engine is None:
        return []
    return _entries(_shared(core))


def _origins_file(core: Core) -> Path:
    return core.layout.root / "owner-rules.json"


def _origins(core: Core) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_origins_file(core).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_origins(core: Core, data: dict[str, dict[str, Any]]) -> None:
    path = _origins_file(core)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".owner-rules.json.agos")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def list_rules(core: Core) -> list[dict[str, Any]]:
    origins = _origins(core)
    out = []
    for text in texts(core):
        found = origins.get(str(rule_id(text))) or {}
        out.append(
            {
                "id": rule_id(text),
                "text": text,
                "fromWorkspace": found.get("from") or None,
                "createdAt": str(found.get("at") or ""),
            }
        )
    return out


def _clean(text: str) -> str:
    from agos_core.engine.identity import clean

    # One Hermes memory entry: its delimiter can't be inside it.
    value = clean(str(text or "").replace("\n§\n", "\n"))
    if not value:
        raise ActionError("Write the rule.")
    return value


def _save(core: Core, rules: list[str]) -> None:
    write_user_profile(_shared(core), rules)


def add(core: Core, text: str, *, from_workspace: str | None = None) -> int:
    value = _clean(text)
    with _lock:
        rules = texts(core)
        for have in rules:
            if have.lower() == value.lower():
                return rule_id(have)
        _save(core, [*rules, value])
        origins = _origins(core)
        origins[str(rule_id(value))] = {
            "from": from_workspace,
            "at": now(),
            # Stays with the rule through edits (its id is its text's): an Undo of
            # the card that added it finds it even after the owner changed it.
            "key": secrets.token_hex(8),
        }
        _save_origins(core, origins)
    _spread(core)
    return rule_id(value)


def edit(core: Core, rule_id_: int, text: str) -> str:
    """Returns the text before (for Undo)."""
    value = _clean(text)
    with _lock:
        rules = texts(core)
        found = next((i for i, t in enumerate(rules) if rule_id(t) == rule_id_), None)
        if found is None:
            raise NotFoundError("This rule")
        before = rules[found]
        rules[found] = value
        _save(core, rules)
        origins = _origins(core)
        kept = origins.pop(str(rule_id_), None)
        if kept is not None:
            origins[str(rule_id(value))] = kept
            _save_origins(core, origins)
    _spread(core)
    return before


def delete(core: Core, rule_id_: int) -> None:
    with _lock:
        rules = texts(core)
        left = [t for t in rules if rule_id(t) != rule_id_]
        if left == rules:
            return
        _save(core, left)
        origins = _origins(core)
        if origins.pop(str(rule_id_), None) is not None:
            _save_origins(core, origins)
    _spread(core)


def key_of(core: Core, rule_id_: int) -> str:
    return str((_origins(core).get(str(rule_id_)) or {}).get("key") or "")


def delete_by_key(core: Core, key: str, fallback_id: int) -> None:
    """Undo of an add: the rule it added, as it is now (edited or not)."""
    found = next(
        (int(i) for i, o in _origins(core).items() if key and (o or {}).get("key") == key),
        fallback_id,
    )
    delete(core, found)


def write_user_profile(home: Path, rules: list[str]) -> bool:
    """His rules as entries of the profile's USER.md (Hermes's user profile), under
    Hermes's own memory-file lock. What Hermes learned about him there is kept."""
    import fcntl

    path = home / "memories" / "USER.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            own = [e for e in text.split(ENTRY_DELIMITER) if e.strip() and not e.startswith(MARK)]
            entries = [MARK + r for r in rules] + own
            new = ENTRY_DELIMITER.join(entries)
            if new == text:
                return False
            tmp = path.with_name(f".{path.name}.agos")
            tmp.write_text(new, encoding="utf-8")
            tmp.chmod(0o600)
            tmp.replace(path)
            return True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


# Hermes's caps for a plugin's sections (H: hermes_cli/plugins_dispatch.py): one
# section at most 4,000 characters (MAX_SYSTEM_PROMPT_SECTION_CHARS, a longer one is
# skipped whole), all of a session's sections at most 8,000 as rendered
# (MAX_SYSTEM_PROMPT_SECTIONS_TOTAL_CHARS, counted by render_system_prompt_sections
# over format_system_prompt_section's heading + length marker, and the container's
# start/end markers). The plugin registers two sections, so his rules can take
# about 8,000 characters; only beyond that do they go into every USER.md.
SECTION_ID = "agos.owner-rules"
SECTION_IDS = (SECTION_ID, SECTION_ID + ".2")
SECTION_MAX = 4_000
TOTAL_MAX = 8_000
_START, _END = "<!-- hermes-plugin-sections:start -->", "<!-- hermes-plugin-sections:end -->"
_HEAD = (
    "The owner's rules for every workspace (set by him in AGOS; they apply here "
    "unless this workspace's own rules say otherwise):"
)
_MORE = "The owner's rules for every workspace (continued):"


def _rendered(section_id: str, text: str) -> int:
    """One section's size as Hermes counts it (format_system_prompt_section)."""
    return len(
        f"## Plugin Context: {section_id}\n<!-- hermes-plugin-section-chars:{len(text)} -->\n\n{text}"
    )


def section_parts(rules: list[str]) -> list[str]:
    """The plugin sections' texts for these rules, in order, whole rules only: []
    when there are none, or when they don't fit Hermes's caps (then they are in
    every USER.md instead)."""
    if not rules:
        return []
    parts: list[list[str]] = [[]]
    for rule in rules:
        line = f"- {rule}"
        head = _HEAD if len(parts) == 1 else _MORE
        if len("\n".join([head, *parts[-1], line])) <= SECTION_MAX:
            parts[-1].append(line)
            continue
        if not parts[-1] or len(parts) == len(SECTION_IDS):
            return []
        parts.append([line])
        if len("\n".join([_MORE, line])) > SECTION_MAX:
            return []
    texts = ["\n".join([_HEAD if n == 0 else _MORE, *p]) for n, p in enumerate(parts)]
    total = len(_START) + len(_END) + 2
    total += sum(
        _rendered(i, t) + (2 if n else 0)
        for n, (i, t) in enumerate(zip(SECTION_IDS, texts, strict=False))
    )
    return texts if total <= TOTAL_MAX else []


def section_text(rules: list[str]) -> str:
    """The first plugin section's text ("" when the sections don't carry them)."""
    parts = section_parts(rules)
    return parts[0] if parts else ""


def in_user_md(rules: list[str]) -> list[str]:
    """What each root's and member's USER.md carries of his rules: nothing while
    the plugin sections carry them."""
    return [] if section_parts(rules) else rules


def sync_profile(core: Core, home: Path) -> None:
    """One root's or member's USER.md: no copy of his rules while the plugin
    section carries them (an old copy is taken out), else the copies."""
    if core.engine is not None and home.resolve() == _shared(core).resolve():
        return
    write_user_profile(home, in_user_md(texts(core)))


def _spread(core: Core) -> None:
    """Every workspace gets them from its next session or run (prompt cache kept)."""
    from agos_core.actions.engine import write_all_identities

    write_all_identities(core)
