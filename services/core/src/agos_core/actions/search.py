"""Workspace-wide search (Step 55, Paperclip F32): one read over everything a
workspace holds, each type read where it lives, with an excerpt around the words.

Where each type is read (never another workspace's: every source is the
workspace's own Hermes root, folder or rows):

- card / comment / artifact: Hermes's own board database (`kanban.db` of the
  workspace's root: tasks, task_comments, task_attachments), read only, one
  connection for the three (Hermes has no index over them; a scan of a few
  thousand rows takes milliseconds);
- chat: Hermes's own full-text index of the workspace's conversations (state.db
  messages_fts, through db/chats.py search_chats);
- document: the workspace folder's files: the Documentation (playbooks/), each
  card's documents (cards/<card>/<key>.md) and each status card's summary
  (status/<id>/summary.md);
- agent: the team's Hermes profiles (title, what it is for, its role text);
- goal: AGOS's plan rows (the Vision, goals, projects, key results);
- skill: the workspace's skill folder in its root (each SKILL.md).

Nothing is copied into an index: the files' texts are only held in this
process's memory while the file is unchanged (its size and mtime), like
engine/read_cache.py, so a second search does not read every document again.

Excerpts (Paperclip's company-search-extract.ts): ~180 letters around the first
match, whitespace folded, with "…" where cut, and the [start, end) of every
matched word inside it so the page can highlight them.
"""

from __future__ import annotations

import contextlib
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agos_core.actions.workspaces import require_workspace
from agos_core.context import Core
from agos_core.db import goals as goals_repo
from agos_core.db import key_results as key_results_repo
from agos_core.hermes_gateway import kanban_rows

TYPES = ("card", "comment", "document", "artifact", "agent", "goal", "skill", "chat")
EXCERPT = 180
PER_TYPE = 25
MAX_TEXT = 400_000  # letters of one file searched (a bigger file: its start)
MAX_TERMS = 6


@dataclass
class Hit:
    type: str
    id: str
    title: str
    body: str  # the text the excerpt is cut from (cut only for the hits shown)
    words: list[str]
    href: str
    where: str = ""
    at: float = 0.0  # unix seconds, 0 = unknown
    score: int = 0

    def as_dict(self) -> dict[str, Any]:
        shown, marks = excerpt(self.body, self.words)
        if not shown or not marks:
            shown, marks = excerpt(self.title, self.words) if self.title else (shown, marks)
        return {
            "type": self.type,
            "id": self.id,
            "title": self.title,
            "excerpt": shown,
            "marks": [list(m) for m in marks],
            "href": self.href,
            "where": self.where,
            "at": self.at,
        }


@dataclass
class Found:
    hits: list[Hit] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


# ---- words, matching, excerpts --------------------------------------------------------------


def terms(query: str) -> list[str]:
    """The words searched (each must be in the item, any case): a quoted phrase
    counts as one word."""
    out: list[str] = []
    for phrase, word in re.findall(r'"([^"]+)"|(\S+)', query.lower()):
        term = " ".join((phrase or word).split()).strip(".,;:!?()[]{}'\"")
        if term and term not in out:
            out.append(term)
    return out[:MAX_TERMS]


def _fold(text: str) -> str:
    return " ".join(text.split())


def matches(text: str, words: list[str]) -> bool:
    low = text.lower()
    return bool(words) and all(w in low for w in words)


def excerpt(text: str, words: list[str], size: int = EXCERPT) -> tuple[str, list[tuple[int, int]]]:
    """~`size` letters around the first matched word, with each word's place in it."""
    flat = _fold(text[:MAX_TEXT])
    low = flat.lower()
    starts = [i for i in (low.find(w) for w in words) if i >= 0]
    first = min(starts) if starts else 0
    if len(flat) <= size:
        start, end = 0, len(flat)
    else:
        start = max(0, first - size // 3)
        end = min(len(flat), start + size)
        start = max(0, end - size)
        # Cut at a word's edge.
        if start > 0:
            space = flat.find(" ", start, first if first > start else start + 20)
            start = space + 1 if space >= 0 else start
        if end < len(flat):
            space = flat.rfind(" ", max(first + 1, end - 20), end)
            end = space if space > first else end
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    shown = prefix + flat[start:end] + suffix
    marks: list[tuple[int, int]] = []
    view = shown.lower()
    for w in words:
        at = view.find(w)
        while at >= 0:
            marks.append((at, at + len(w)))
            at = view.find(w, at + max(len(w), 1))
    marks.sort()
    merged: list[tuple[int, int]] = []
    for a, b in marks:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return shown, merged


def _score(title: str, body: str, words: list[str]) -> int:
    t, b = title.lower(), body.lower()
    phrase = " ".join(words)
    return (
        sum(3 for w in words if w in t)
        + sum(1 for w in words if w in b)
        + (4 if len(words) > 1 and phrase in t else 0)
        + (2 if len(words) > 1 and phrase in b else 0)
    )


def _hit(
    kind: str,
    item: str,
    title: str,
    body: str,
    words: list[str],
    href: str,
    *,
    where: str = "",
    at: float = 0.0,
) -> Hit:
    return Hit(kind, item, title, body, words, href, where, at, _score(title, body, words))


# ---- the files' texts, held while unchanged -------------------------------------------------

_TEXTS: dict[str, tuple[int, int, str]] = {}
_LISTS: dict[str, tuple[int, list[tuple[str, bool]]]] = {}
_LOCK = threading.Lock()
_MAX_HELD = 50_000


def _text(path: Path) -> str | None:
    """The file's text, read again only when its size or time changed."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = str(path)
    held = _TEXTS.get(key)
    if held is not None and held[0] == stat.st_size and held[1] == stat.st_mtime_ns:
        return held[2]
    try:
        with path.open("rb") as handle:
            text = handle.read(MAX_TEXT * 4).decode("utf-8", "replace")
    except OSError:
        return None
    with _LOCK:
        if len(_TEXTS) >= _MAX_HELD:
            _TEXTS.clear()
        _TEXTS[key] = (stat.st_size, stat.st_mtime_ns, text)
    return text


def _listing(folder: Path) -> list[tuple[str, bool]]:
    """(name, is a folder) of a folder's entries, listed again only when it changed."""
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        return []
    key = str(folder)
    held = _LISTS.get(key)
    if held is not None and held[0] == stamp:
        return held[1]
    try:
        with os.scandir(folder) as entries:
            found = sorted((e.name, e.is_dir(follow_symlinks=False)) for e in entries)
    except OSError:
        return []
    with _LOCK:
        if len(_LISTS) >= _MAX_HELD:
            _LISTS.clear()
        _LISTS[key] = (stamp, found)
    return found


def _markdown(base: Path, skip_top: tuple[str, ...] = ()) -> list[tuple[str, Path]]:
    """Every .md / .txt file under `base` (relative path, file), hidden folders and
    the top folders in `skip_top` left out."""
    out: list[tuple[str, Path]] = []
    stack = [(base, "")]
    while stack:
        folder, rel = stack.pop()
        for name, is_dir in _listing(folder):
            if name.startswith("."):
                continue
            path = f"{rel}/{name}" if rel else name
            if is_dir:
                if not (rel == "" and name in skip_top):
                    stack.append((folder / name, path))
            elif name.endswith((".md", ".txt")):
                out.append((path, folder / name))
    return out


# ---- each type ------------------------------------------------------------------------------


def _board(core: Core, ws: str) -> kanban_rows.Board | None:
    from agos_core.actions import agent_profiles

    if core.engine is None:
        return None
    path = agent_profiles.board_db(core, ws)
    if not path.is_file():
        return None
    try:
        return kanban_rows.open_board(path)
    except sqlite3.Error:
        return None


def _clean_body(body: str) -> str:
    from agos_core.actions.kanban_board import without_pins
    from agos_core.engine import goals as goal_rules
    from agos_core.engine import reviews as review_rules

    return goal_rules.without_card_goal(without_pins(review_rules.without_policy(body)))


def _who(core: Core, ws: str) -> Any:
    """Who a board author is (the owner, the Co-Founder, a member's title)."""
    from agos_core.actions import kanban_board

    members = kanban_board._members(core, ws)
    cofounder = core.engine.hermes_name(ws) if core.engine else ""
    return lambda author: kanban_board._creator(str(author or ""), members, cofounder)


def _board_hits(core: Core, ws: str, words: list[str], wanted: set[str], found: Found) -> None:
    board = _board(core, ws)
    if board is None:
        return
    base = f"/w/{ws}/kanban?card="
    with contextlib.closing(board):
        if "card" in wanted and (have := board.columns("tasks")):
            try:
                rows = board.card_hits(words, have)
            except sqlite3.Error:
                rows = []
            found.counts["card"] = len(rows)
            for i, title, body, result, status, made in rows:
                text = "\n".join(
                    t for t in (_clean_body(str(body or "")), str(result or "")) if t.strip()
                )
                found.hits.append(
                    _hit(
                        "card",
                        str(i),
                        str(title or ""),
                        text,
                        words,
                        base + str(i),
                        where=f"Card {i} · {status or ''}".strip(" ·"),
                        at=float(made or 0),
                    )
                )
        if "comment" in wanted and board.columns("task_comments"):
            try:
                rows = board.comment_hits(words)
            except sqlite3.Error:
                rows = []
            found.counts["comment"] = len(rows)
            who = _who(core, ws) if rows else None
            for i, card, author, body, made, title in rows:
                found.hits.append(
                    _hit(
                        "comment",
                        f"{card}:{i}",
                        f"Comment on “{title or card}”",
                        str(body or ""),
                        words,
                        base + str(card),
                        where=f"Card {card} · {who(author) if who else author}",
                        at=float(made or 0),
                    )
                )
        if "artifact" in wanted and board.columns("task_attachments"):
            try:
                rows = board.attachment_hits(words)
            except sqlite3.Error:
                rows = []
            found.counts["artifact"] = found.counts.get("artifact", 0) + len(rows)
            for i, card, name, made, title in rows:
                found.hits.append(
                    _hit(
                        "artifact",
                        f"attachment:{card}:{i}",
                        str(name or ""),
                        str(name or ""),
                        words,
                        base + str(card),
                        where=f"File of card {card} “{title or ''}”",
                        at=float(made or 0),
                    )
                )


def _document_hits(core: Core, ws: str, words: list[str], found: Found) -> None:
    from agos_core.actions import docs, status_cards
    from agos_core.engine import card_docs as card_rules
    from agos_core.storage.layout import workspace_paths

    files = workspace_paths(core.layout, ws).files
    n = 0
    # The Documentation (the team's rules).
    for rel, path in _markdown(docs.folder(core, ws), ("skills", "agents", "automations")):
        text = _text(path)
        if text is None or not matches(f"{rel}\n{text}", words):
            continue
        n += 1
        found.hits.append(
            _hit(
                "document",
                f"doc:{rel}",
                rel,
                text,
                words,
                f"/w/{ws}/docs?f={rel}",
                where="Documentation",
                at=_mtime(path),
            )
        )
    # Each card's documents: cards/<card>/<key>.md (not their revisions).
    cards = files / card_rules.FOLDER
    for card, is_dir in _listing(cards):
        if not is_dir or card.startswith("."):
            continue
        for name, sub in _listing(cards / card):
            key = card_rules.clean_key(name) if not sub else None
            if key is None:
                continue
            text = _text(cards / card / name)
            if text is None or not matches(f"{key}\n{text}", words):
                continue
            n += 1
            found.hits.append(
                _hit(
                    "document",
                    f"card-doc:{card}:{key}",
                    key,
                    text,
                    words,
                    f"/w/{ws}/kanban?card={card}&doc={key}",
                    where=f"Document of card {card}",
                    at=_mtime(cards / card / name),
                )
            )
    # Each status card's summary (the Co-Founder's words).
    titles = status_cards.titles(core, ws)
    folder = files / status_cards.FOLDER
    for item, is_dir in _listing(folder):
        if not is_dir or not item.isdigit() or int(item) not in titles:
            continue
        path = folder / item / status_cards.SUMMARY
        text = _text(path)
        title = titles[int(item)]
        if text is None or not matches(f"{title}\n{text}", words):
            continue
        n += 1
        found.hits.append(
            _hit(
                "document",
                f"status:{item}",
                title,
                text,
                words,
                f"/w/{ws}/status#card-{item}",
                where="Status card",
                at=_mtime(path),
            )
        )
    found.counts["document"] = n


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _agent_hits(core: Core, ws: str, words: list[str], found: Found) -> None:
    from agos_core.actions import team

    if core.engine is None:
        return
    n = 0
    for a in team.members(core, ws):
        text = "\n".join((a.name, a.title, a.summary, a.instructions))
        if not matches(text, words):
            continue
        n += 1
        body = "\n".join((a.summary, a.instructions))
        found.hits.append(
            _hit(
                "agent",
                a.name,
                a.title or a.name,
                body if matches(body, words) else text,
                words,
                f"/w/{ws}/hierarchy",
                where=f"@{a.name}" + ("" if a.on else " (off the team)"),
            )
        )
    found.counts["agent"] = n


_LEVEL = {"vision": "Vision", "goal": "Goal", "project": "Project"}


def _goal_hits(core: Core, ws: str, words: list[str], found: Found) -> None:
    n = 0
    plan = goals_repo.rows(core.db, ws)
    for r in plan:
        keys = r.keys()
        body = "\n".join(
            str(r[c] or "") for c in ("why", "strategy", "rhythm", "measure") if c in keys
        )
        title = str(r["title"] or "")
        if not matches(f"{title}\n{body}", words):
            continue
        n += 1
        level = str(r["level"] or "goal") if "level" in keys else "goal"
        found.hits.append(
            _hit(
                "goal",
                f"goal:{r['id']}",
                title,
                body,
                words,
                f"/w/{ws}/vision#goal-{r['id']}",
                where=_LEVEL.get(level, "Goal"),
            )
        )
    goal_titles = {int(g["id"]): g["title"] for g in plan}
    for r in sorted(key_results_repo.rows(core.db, ws), key=lambda k: int(k["id"])):
        if int(r["goal_id"]) not in goal_titles:
            continue
        title = str(r["title"] or "")
        body = f"{r['source'] or ''}\n{r['unit'] or ''}"
        if not matches(f"{title}\n{body}", words):
            continue
        n += 1
        found.hits.append(
            _hit(
                "goal",
                f"kr:{r['id']}",
                title,
                body,
                words,
                f"/w/{ws}/vision#goal-{r['goal_id']}",
                where=f"Key result of “{goal_titles[int(r['goal_id'])]}”",
            )
        )
    found.counts["goal"] = n


def _skill_hits(core: Core, ws: str, words: list[str], found: Found) -> None:
    from agos_core.actions import workspace_skills

    base = workspace_skills.folder(core, ws)
    n = 0
    for r in workspace_skills.shown(core, ws):
        name = str(r["name"])
        text = _text(base / name / "SKILL.md") if base is not None else None
        whole = f"{name}\n{text or ''}"
        if not matches(whole, words):
            continue
        n += 1
        found.hits.append(
            _hit(
                "skill",
                f"skill:{r['id']}",
                name,
                text or name,
                words,
                f"/w/{ws}/settings/capabilities/skills/{r['id']}",
                where="Skill",
            )
        )
    found.counts["skill"] = n


def _chat_hits(core: Core, ws: str, query: str, words: list[str], found: Found) -> None:
    from agos_core.db import chats as chats_repo

    rows = chats_repo.search_chats(core.db, ws, query)
    n = 0
    for h in rows:
        body = str(h["body"] or "")
        if not matches(body, words):
            continue  # Hermes matched a word's start (prefix search): not every word
        n += 1
        found.hits.append(
            _hit(
                "chat",
                f"chat:{h['chatId']}:{h['messageId']}",
                str(h["chatTitle"] or "Chat"),
                body,
                words,
                f"/w/{ws}/sessions?chat={h['chatId']}",
                where="You" if h["from"] == "owner" else "Agent's answer",
            )
        )
    found.counts["chat"] = n


# ---- the search -----------------------------------------------------------------------------


def search(
    core: Core,
    workspace_id: str,
    query: str,
    types: list[str] | None = None,
    *,
    per_type: int = PER_TYPE,
) -> dict[str, Any]:
    """Every type's matches (the best `per_type` of each, best first then newest),
    how many each type has, and how long the search took (ms)."""
    require_workspace(core, workspace_id)
    started = time.perf_counter()
    words = terms(query)
    wanted = {t for t in (types or TYPES) if t in TYPES} or set(TYPES)
    found = Found(counts={t: 0 for t in TYPES})
    if words:
        if wanted & {"card", "comment", "artifact"}:
            _board_hits(core, workspace_id, words, wanted, found)
        if "document" in wanted:
            _document_hits(core, workspace_id, words, found)
        if "agent" in wanted:
            _agent_hits(core, workspace_id, words, found)
        if "goal" in wanted:
            _goal_hits(core, workspace_id, words, found)
        if "skill" in wanted:
            _skill_hits(core, workspace_id, words, found)
        if "chat" in wanted:
            _chat_hits(core, workspace_id, query, words, found)
    by_type: dict[str, list[Hit]] = {}
    for h in found.hits:
        by_type.setdefault(h.type, []).append(h)
    kept: list[Hit] = []
    for t in TYPES:
        mine = sorted(by_type.get(t, []), key=lambda h: (-h.score, -h.at, h.id))
        kept += mine[:per_type]
    kept.sort(key=lambda h: (-h.score, TYPES.index(h.type), -h.at, h.id))
    return {
        "query": query,
        "terms": words,
        "results": [h.as_dict() for h in kept],
        "counts": {t: found.counts.get(t, 0) for t in TYPES},
        "tookMs": round((time.perf_counter() - started) * 1000, 1),
    }


def for_agent(core: Core, workspace_id: str, query: str, types: list[str] | None) -> str:
    """`agos_search` as the agents read it: one short line per match."""
    answer = search(core, workspace_id, query, types, per_type=8)
    if not answer["terms"]:
        return "Give the words to search for."
    lines = [f"Search “{query}” in this workspace:"]
    for r in answer["results"][:30]:
        place = f" ({r['where']})" if r["where"] else ""
        lines.append(f"- [{r['type']}] {r['title']}{place}: {r['excerpt']} -> {r['id']}")
    if len(lines) == 1:
        lines.append("Nothing found.")
    counts = ", ".join(f"{t} {n}" for t, n in answer["counts"].items() if n)
    if counts:
        lines.append(f"Matches per type: {counts}.")
    return "\n".join(lines)
