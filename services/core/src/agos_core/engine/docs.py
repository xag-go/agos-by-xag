"""The Documentation of a workspace: the team's rules, one home per rule.

Three kinds of text, each with its own job (the owner's split):
- Agent (the employee): who it is, what it does and doesn't, its steps in short,
  its skills and tools, what it READS, who it hands work to, how it reports.
- Skill: HOW one job is done, in full detail (steps, templates, examples, checks).
- Documentation (the company rulebook): the facts and decisions (what each column
  means, who sets done, where the Sheets are, who each style is, the language).
  Short, because agents read it on every job.

Ask: "how is it done?" -> skill. "what is our rule or decision?" -> documentation.
"who does it and with what?" -> agent.

Files live in the workspace folder, /workspace/playbooks (README.md = the map,
CHANGES.md = the log of every rule change). This module is pure: parsing,
sections, checks, templates. Reading and writing is in actions/docs.py.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

FOLDER = "playbooks"
MAP = "README.md"
LOG = "CHANGES.md"
# Rule files are the top-level .md files; these two are the map and the log.
NOT_RULES = {MAP, LOG}
SHINGLE = 6  # words compared at a time
RUN = 12  # words in a row that make "the same rule written twice"

_HEADING = re.compile(r"^(#{2,3})\s+(\d+)[.)]?\s+(.*)$", re.MULTILINE)
_POINTER = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_./-]*\.md)[^\S\n]+sections?[^\S\n]+(\d+)", re.I)
_WORD = re.compile(r"\w+", re.UNICODE)
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---- sections ----------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    number: str
    title: str
    start: int
    end: int


def sections(text: str) -> list[Section]:
    """Numbered sections ("## 4. Tracker statuses"): the unit a pointer cites."""
    found = list(_HEADING.finditer(text))
    out = []
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.append(Section(m.group(2), m.group(3).strip(), m.start(), end))
    return out


def section_text(text: str, number: str) -> str | None:
    for s in sections(text):
        if s.number == str(number):
            return text[s.start : s.end].strip()
    return None


def changed_sections(before: str, after: str) -> list[str]:
    """Which numbered sections differ ("4. Tracker statuses"); the intro counts too."""

    def parts(text: str) -> dict[str, str]:
        found = sections(text)
        out = {"intro": text[: found[0].start] if found else text}
        for s in found:
            out[f"{s.number}. {s.title}"] = text[s.start : s.end]
        return out

    a, b = parts(before), parts(after)
    keys = list(dict.fromkeys([*a, *b]))
    return [k for k in keys if a.get(k, "").strip() != b.get(k, "").strip()]


# ---- the log ------------------------------------------------------------------------


def log_entry(path: str, who: str, why: str, changed: list[str], at: datetime | None = None) -> str:
    when = (at or datetime.now(UTC)).strftime("%Y-%m-%d")
    where = ", ".join(changed) if changed else "whole file"
    return (
        f"## {when} - {path}: {where}\n\n"
        f"Who: {who}\n"
        f"Why: {why.strip()}\n"
        f"What changed: {path} ({where}).\n"
    )


def add_to_log(log_text: str, entry: str) -> str:
    """Newest first: the entry goes before the first dated entry."""
    if not log_text.strip():
        return f"# Rule changes (newest first)\n\n{entry}"
    first = re.search(r"^## ", log_text, re.MULTILINE)
    if first is None:
        return log_text.rstrip() + "\n\n" + entry
    return log_text[: first.start()] + entry + "\n" + log_text[first.start() :]


# ---- checks -------------------------------------------------------------------------


@dataclass
class Finding:
    kind: str  # duplicate | pointer | orphan | language
    where: str  # file (or "agent X", "skill X", "automation X")
    detail: str
    other: str = ""  # the second place, for a duplicate


@dataclass
class Sources:
    """Everything the checks look at, as plain texts."""

    docs: dict[str, str]  # path under playbooks/ -> text
    agents: dict[str, str] = field(default_factory=dict)  # title -> instructions
    skills: dict[str, str] = field(default_factory=dict)
    automations: dict[str, str] = field(default_factory=dict)
    reads: dict[str, list[str]] = field(default_factory=dict)  # agent title -> files
    other_files: set[str] = field(default_factory=set)  # .md names elsewhere in /workspace
    latin_only: bool = False


def fingerprint(src: Sources) -> str:
    """Everything the checks look at as one hash, in its order (the findings follow
    it): the same texts, names and setting give the same findings."""
    digest = hashlib.sha256()

    def add(text: str) -> None:
        data = text.encode("utf-8", "surrogatepass")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    for part in (src.docs, src.agents, src.skills, src.automations):
        add(str(len(part)))
        for name, text in part.items():
            add(name)
            add(text)
    add(str(len(src.reads)))
    for name, files in src.reads.items():
        add(name)
        add(str(len(files)))
        for file in files:
            add(file)
    add(str(len(src.other_files)))
    for name in sorted(src.other_files):
        add(name)
    add("latin" if src.latin_only else "any")
    return digest.hexdigest()


def rule_files(docs: dict[str, str]) -> dict[str, str]:
    return {
        p: t for p, t in docs.items() if "/" not in p and p.endswith(".md") and p not in NOT_RULES
    }


def _words(text: str) -> list[str]:
    # Paths and file names aren't rules: "research/yyyy-mm-dd-style-x.md" is dropped.
    clean = re.sub(r"\S*[/_.]\S*\.(md|txt|json|py|csv)\S*|/workspace\S*", " ", text.lower())
    return _WORD.findall(clean)


def _shingles(text: str, words: list[str] | None = None) -> dict[int, int]:
    """Each run of SHINGLE words -> where it starts (first time). `words`: the
    text already split by _words."""
    words = _words(text) if words is None else words
    out: dict[int, int] = {}
    for i in range(len(words) - SHINGLE + 1):
        out.setdefault(hash(" ".join(words[i : i + SHINGLE])), i)
    return out


@dataclass
class _Parsed:
    """Each text's words and shingles, worked out once per check: every agent,
    skill and automation is compared with the rule files again, and splitting
    the rule files anew for each of them was most of the Documentation page's
    time (0.2 s of a page of 21 texts)."""

    words: dict[str, list[str]] = field(default_factory=dict)
    shingles: dict[str, dict[int, int]] = field(default_factory=dict)

    def words_of(self, text: str) -> list[str]:
        found = self.words.get(text)
        if found is None:
            found = self.words[text] = _words(text)
        return found

    def shingles_of(self, text: str) -> dict[int, int]:
        found = self.shingles.get(text)
        if found is None:
            found = self.shingles[text] = _shingles(text, self.words_of(text))
        return found


def _duplicates(
    named: dict[str, str], seen_pairs: set[tuple[str, str]], parsed: _Parsed | None = None
) -> list[Finding]:
    """The same passage (RUN words or more in a row) in two places. Phrases found
    in 3+ places are the shared skeleton ("This file is the one home of..."), not
    a rule written twice. `parsed`: the texts already split by this check."""
    parsed = parsed if parsed is not None else _Parsed()
    shingles = {name: parsed.shingles_of(text) for name, text in named.items()}
    count: dict[int, int] = {}
    for sh in shingles.values():
        for key in sh:
            count[key] = count.get(key, 0) + 1
    names = list(named)
    found: list[Finding] = []
    for a_i, a in enumerate(names):
        words_a = parsed.words_of(named[a])
        for b in names[a_i + 1 :]:
            if (a, b) in seen_pairs or (b, a) in seen_pairs:
                continue
            common = {k for k in shingles[a] if k in shingles[b] and count[k] == 2}
            if not common:
                continue
            starts = sorted(shingles[a][k] for k in common)
            # The longest stretch of shared runs, in words.
            best, run_start, prev, best_start = 0, starts[0], starts[0], starts[0]
            for st in starts[1:]:
                if st != prev + 1:
                    if prev - run_start > best:
                        best, best_start = prev - run_start, run_start
                    run_start = st
                prev = st
            if prev - run_start > best:
                best, best_start = prev - run_start, run_start
            length = best + SHINGLE
            if length < RUN:
                continue
            seen_pairs.add((a, b))
            sample = " ".join(words_a[best_start : best_start + min(length, 16)])
            found.append(
                Finding(
                    "duplicate",
                    b,
                    f"The same passage ({length} words) is written in two places: “{sample}…”",
                    a,
                )
            )
    return found


def check(src: Sources) -> list[Finding]:
    findings: list[Finding] = []
    rules = rule_files(src.docs)
    # 1. The same rule (9+ words in a row) in two rule files, or restated in an
    #    agent text / skill / automation instead of pointing to its file.
    seen: set[tuple[str, str]] = set()
    parsed = _Parsed()
    findings += _duplicates(rules, seen, parsed)
    for kind, texts in (
        ("agent", src.agents),
        ("skill", src.skills),
        ("automation", src.automations),
    ):
        for name, text in texts.items():
            findings += [
                f
                for f in _duplicates({**rules, f"{kind} {name}": text}, seen, parsed)
                if f.where == f"{kind} {name}" or f.other == f"{kind} {name}"
            ]
    # 2. Every "file.md section N" cited exists.
    # CHANGES.md is the history: an old entry may cite a section that has moved since.
    places = {p: t for p, t in src.docs.items() if p != LOG}
    places.update({f"agent {n}": t for n, t in src.agents.items()})
    places.update({f"skill {n}": t for n, t in src.skills.items()})
    places.update({f"automation {n}": t for n, t in src.automations.items()})
    by_name = {p.rsplit("/", 1)[-1]: t for p, t in src.docs.items()}
    for where, text in places.items():
        for m in _POINTER.finditer(text):
            name, number = m.group(1).rsplit("/", 1)[-1], m.group(2)
            target = by_name.get(name)
            if target is None:
                if name not in src.other_files:
                    findings.append(
                        Finding(
                            "pointer", where, f"Points to {name} section {number}: no such file."
                        )
                    )
                continue
            if section_text(target, number) is None and sections(target):
                findings.append(
                    Finding(
                        "pointer",
                        where,
                        f"Points to {name} section {number}: that section doesn't exist.",
                    )
                )
    # The same pointer cited twice in one place is one finding.
    unique: list[Finding] = []
    for f in findings:
        if not any(
            (u.kind, u.where, u.detail, u.other) == (f.kind, f.where, f.detail, f.other)
            for u in unique
        ):
            unique.append(f)
    findings = unique
    # 3. Every rule file is read by someone (an agent's reads, or an automation / agent
    #    / skill that points to it).
    mentioned = " ".join([*src.agents.values(), *src.skills.values(), *src.automations.values()])
    read = {f for files in src.reads.values() for f in files}
    for path in rules:
        if path not in read and path not in mentioned:
            findings.append(Finding("orphan", path, "No agent or automation reads this file."))
    # 4. The workspace's language rule (e.g. Latin letters only).
    if src.latin_only:
        for where, text in places.items():
            if _ARABIC.search(text):
                findings.append(
                    Finding(
                        "language",
                        where,
                        "Arabic letters here; this workspace uses Latin letters only.",
                    )
                )
    return findings


# ---- a new workspace's documentation ------------------------------------------------


def template(workspace_name: str) -> dict[str, str]:
    """README (the map), team, flow and CHANGES, ready to fill in."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return {
        MAP: f"""# {workspace_name}: the team's rules

Every rule of the team lives in ONE of these files, and only there. Agent texts say
who the agent is and point here for the rules; skills say how a job is done. To change
a rule: change it here (one place); CHANGES.md gets a line with why.

| File | What it is the one home of | Who reads it |
|---|---|---|
| `team.md` | the team, the board, files and folders, language, facts, reporting, tools and rights | every agent, before every task |
| `flow.md` | where things live, what each status or trigger does, how each automation runs | every agent, and every automation |
| `CHANGES.md` | the log of every rule change (date, what, why) | whoever changes a rule |
""",
        "team.md": f"""# {workspace_name}: the team

## 1. The team
Who does what (one line per agent, its job title and its job).

## 2. Files and folders
Where the work is kept in /workspace.

## 3. Language
The language and alphabet of the work and of the reports.

## 4. Reporting
How each agent reports what it did.

## 5. Tools and rights
Which tools and connectors each agent may use, and what it may change.
""",
        "flow.md": f"""# {workspace_name}: the flow

## 1. Where everything lives
Sheets, Drive, boards, apps.

## 2. What each status does
For each status or column: who acts, what happens next.

## 3. Automations
What starts each automation and its steps.
""",
        LOG: f"""# Rule changes (newest first)

Every change to a rule gets a line here: date, what changed, why.

## {today} - Documentation created

Why: every workspace keeps its rules in one place.
""",
    }


def agent_block(always: list[tuple[str, str]], on_demand: list[str]) -> str:
    """What an agent gets on every job: its required rules in full, and the files
    it opens itself when the work needs them."""
    parts: list[str] = []
    if always:
        parts.append(
            "## The team's rules you follow (from /workspace/playbooks; they win over "
            "anything else. If a rule seems wrong, say so, don't work around it)"
        )
        for label, text in always:
            parts.append(f"### {label}\n\n{text.strip()}")
    if on_demand:
        parts.append(
            "## Rules you open yourself when the work needs them\n\n"
            + "\n".join(f"- /workspace/{FOLDER}/{p}" for p in on_demand)
        )
    return "\n\n".join(parts)
