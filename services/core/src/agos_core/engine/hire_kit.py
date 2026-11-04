"""A hire's kit (Step 62): everything a new member needs to do its work well, as
pure rules (shape, cleaning, the words of its cards). actions/hire_kit.py does the
reading and writing.

A hire proposal's payload (engine/proposals.py, kind hire) may carry `kit`:

    {"tools":  [{"name": "Instagram", "why": "posts the reels",
                 "connector": "instagram", "key": "", "alternative": ""}],
     "skills": [{"name": "video-editing", "source": "library" | "find" | "write",
                 "why": "..."}],
     "docs":   [{"title": "Style guide", "path": "brand/style.md", "url": "",
                 "kind": "doc" | "example"}],
     "team":   {"works_with": ["script-writer"], "project": "Weekly reels"},
     "onboarding": {"task": "Edit this 30 s clip in our style",
                    "criteria": ["cuts on the beat", "our captions font"]}}

- tools: a named service or account the role needs. `connector`: the Hermes
  connector (Hermes's MCP catalog app name, Settings -> Connectors) when one
  exists; `key`: the name of its API key in Settings -> Keys when it is an API
  without a connector; neither: no API (the Co-Founder proposes an alternative,
  `alternative`, or a task for the owner).
- skills: `library` = the workspace has it (installed into the member on
  approve); `find` = to search (Hermes's skills hub, the Brain); `write` = to
  write (skill_manage), then try in Skill Studio.
- docs: a workspace file (`path`, relative to the workspace's files folder) or a
  link (`url`); files are copied into the member's own folder
  (team/<member>/docs or team/<member>/examples).
- team: who it works with (members' names) and the project / goal in words; its
  lead (`reports_to`) and the goal it serves (`goal_id`) stay the hire's own fields.
- onboarding: a small, role-shaped task the member does once it is ready,
  graded against `criteria` before real work starts.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SKILL_SOURCES = ("library", "find", "write")
DOC_KINDS = ("doc", "example")
MAX_ITEMS = 12
MAX_CRITERIA = 8
# The owner's choices kept per member (actions/hire_kit.py, member_readiness rows).
CHOICES = ("start_anyway", "not_needed", "skip_test", "passed", "failed")
# One onboarding test, then up to two re-runs after the Co-Founder's fix.
MAX_TRIES = 3
STATES = ("not_ready", "onboarding", "ready")

_SKILL = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_APP = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_MEMBER = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
ROUTES_FENCE = "agos-kit-routes"
ROUTE_PATHS = ("search", "write", "connect", "key", "script", "alternative", "you", "ask", "done")
_ROUTES_OPEN = re.compile(r"^[ \t]*```[ \t]*" + re.escape(ROUTES_FENCE) + r"[ \t]*$", re.M)


def _line(raw: Any, limit: int) -> str:
    return " ".join(str(raw or "").split())[:limit]


def _items(raw: Any) -> list[Any]:
    return list(raw)[:MAX_ITEMS] if isinstance(raw, list) else []


def _tool(raw: Any) -> dict[str, str] | None:
    item: dict[str, Any] = {"name": raw} if isinstance(raw, str) else raw
    if not isinstance(item, dict):
        return None
    name = _line(item.get("name"), 60)
    if not name:
        return None
    connector = str(item.get("connector") or "").strip().lower()
    key = str(item.get("key") or "").strip().upper()
    return {
        "name": name,
        "why": _line(item.get("why"), 300),
        "connector": connector if _APP.fullmatch(connector) else "",
        "key": key if _KEY.fullmatch(key) else "",
        "alternative": _line(item.get("alternative"), 300),
    }


def _skill(raw: Any) -> dict[str, str] | None:
    item: dict[str, Any] = {"name": raw} if isinstance(raw, str) else raw
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip().lower()
    if not name:
        return None
    source = str(item.get("source") or "library").strip().lower()
    return {
        "name": name[:64],
        "source": source if source in SKILL_SOURCES else "library",
        "why": _line(item.get("why"), 300),
    }


def _doc(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        text = raw.strip()
        item: dict[str, Any] = (
            {"url": text} if text.startswith(("http://", "https://")) else {"path": text}
        )
    elif isinstance(raw, dict):
        item = raw
    else:
        return None
    path = str(item.get("path") or "").strip().removeprefix("/workspace/").removeprefix("./")
    url = str(item.get("url") or "").strip()
    if not path and not url:
        return None
    kind = str(item.get("kind") or "doc").strip().lower()
    title = _line(item.get("title"), 120) or (path.rsplit("/", 1)[-1] if path else url[:120])
    return {
        "title": title,
        "path": path[:300],
        "url": url[:500],
        "kind": kind if kind in DOC_KINDS else "doc",
    }


def clean_kit(raw: Any) -> dict[str, Any]:
    """The kit AGOS keeps: each list typed and deduped (by name / path), at most
    MAX_ITEMS per list; anything it can't read is dropped."""
    kit = raw if isinstance(raw, dict) else {}
    tools: dict[str, dict[str, str]] = {}
    for t in (_tool(x) for x in _items(kit.get("tools"))):
        if t is not None:
            tools.setdefault(t["name"].lower(), t)
    skills: dict[str, dict[str, str]] = {}
    for s in (_skill(x) for x in _items(kit.get("skills"))):
        if s is not None:
            skills.setdefault(s["name"], s)
    docs: dict[str, dict[str, str]] = {}
    for d in (_doc(x) for x in _items(kit.get("docs"))):
        if d is not None:
            docs.setdefault(d["path"] or d["url"], d)
    team: dict[str, Any] = kit["team"] if isinstance(kit.get("team"), dict) else {}
    works: list[Any] = team["works_with"] if isinstance(team.get("works_with"), list) else []
    onboarding: dict[str, Any] = (
        kit["onboarding"] if isinstance(kit.get("onboarding"), dict) else {}
    )
    criteria: list[Any] = (
        onboarding["criteria"] if isinstance(onboarding.get("criteria"), list) else []
    )
    return {
        "tools": list(tools.values()),
        "skills": list(skills.values()),
        "docs": list(docs.values()),
        "team": {
            "works_with": list(
                dict.fromkeys(
                    n
                    for n in (str(w or "").strip().lstrip("@").lower() for w in works[:MAX_ITEMS])
                    if _MEMBER.fullmatch(n)
                )
            ),
            "project": _line(team.get("project"), 300),
        },
        "onboarding": {
            "task": str(onboarding.get("task") or "").strip()[:2000],
            "criteria": [c for c in (_line(x, 300) for x in criteria[:MAX_CRITERIA]) if c],
        },
    }


def is_empty(kit: dict[str, Any]) -> bool:
    return not (
        kit.get("tools")
        or kit.get("skills")
        or kit.get("docs")
        or (kit.get("onboarding") or {}).get("task")
    )


def kit_problems(kit: dict[str, Any]) -> list[str]:
    """What keeps a kit from being used as is (told the agent, shown the owner)."""
    out = []
    for s in kit.get("skills") or []:
        if not _SKILL.fullmatch(s["name"]):
            out.append(f"kit skill '{s['name']}': a skill name is lowercase-with-dashes")
    for d in kit.get("docs") or []:
        path = d.get("path") or ""
        if path and (path.startswith("/") or ".." in path.split("/") or "\\" in path):
            out.append(f"kit doc '{path}': a path inside the workspace's files (no .., no /)")
        url = d.get("url") or ""
        if url and not url.startswith(("https://", "http://")):
            out.append(f"kit doc '{url}': a link starts with https://")
    onboarding = kit.get("onboarding") or {}
    if onboarding.get("task") and not onboarding.get("criteria"):
        out.append("kit onboarding: give the criteria its test is graded on")
    return out


# Every new member comes with its whole kit: a hire missing one part is refused when
# it is proposed (told the agent, which sends it again) and when it is approved (the
# owner's edit took one out: told on the card). Its team context stays optional.
NO_KIT = (
    'kit is missing: every hire carries its full kit, {"tools": [...], "skills": '
    '[...], "docs": [...], "onboarding": {"task", "criteria"}} (your team-design '
    "skill says what goes in each); nothing is created without it"
)
KIT_PARTS: dict[str, str] = {
    "tools": (
        "kit.tools is empty: name each service or account the role uses, "
        '{"name": "Instagram", "why": ...} (or "key": its API key\'s name)'
    ),
    "docs": (
        'kit.docs is empty: give the files it follows and good examples, {"title", '
        '"path" (a workspace file) or "url", "kind": "doc" | "example"}'
    ),
    "onboarding.task": (
        "kit.onboarding.task is missing: one small real task in its role, done and "
        "graded before real work"
    ),
    "onboarding.criteria": (
        "kit.onboarding.criteria is empty: the lines a good answer to its onboarding task shows"
    ),
}
NO_SKILL = (
    "skills: give at least one skill this workspace's library has (in skills, or in "
    "kit.skills with source library); find / write ones come on top"
)


def kit_missing(kit: dict[str, Any] | None, library_skills: int) -> list[str]:
    """The parts a hire's kit lacks (a cleaned kit; None = no kit at all).
    `library_skills`: how many of its skills this workspace's library has."""
    if not isinstance(kit, dict) or is_empty(kit):
        return [NO_KIT]
    onboarding = kit.get("onboarding") or {}
    have = {
        "tools": bool(kit.get("tools")),
        "docs": bool(kit.get("docs")),
        "onboarding.task": bool(str(onboarding.get("task") or "").strip()),
        "onboarding.criteria": bool(onboarding.get("criteria")),
    }
    out = [KIT_PARTS[part] for part, ok in have.items() if not ok]
    if library_skills < 1:
        out.append(NO_SKILL)
    return out


# ---- the member's model, sized to the role ---------------------------------------------
#
# A hire may carry `model`: {"model": <an id from the catalog, or a family such as
# "haiku">, "effort": <one of that model's levels>, "why": <one line>}. Only the
# workspace's own provider (the one its Co-Founder runs on) and only the models
# Hermes's catalog lists for it (actions/hire_model.py reads it) are taken; a family
# means its newest version there. No model = the workspace's model.

_DATE = re.compile(r"-(\d{8})$")
# Claude's families, smallest first (the catalog has no size; the names say it).
FAMILIES = ("haiku", "sonnet", "opus")


def model_family(model_id: str) -> str:
    """claude-haiku-4-5 -> haiku ('' for a model with no family AGOS knows)."""
    found = re.match(r"claude-(haiku|sonnet|opus)\b", model_id or "")
    return found.group(1) if found else ""


def _version(model_id: str) -> tuple[int, ...]:
    """claude-opus-5-5 -> (5, 5): the numbers of an id (its date suffix last)."""
    date = _DATE.search(model_id)
    head = _DATE.sub("", model_id)
    nums = tuple(int(n) for n in re.findall(r"\d+", head))
    return (*nums, int(date.group(1)) if date else 0)


MODEL_KEYS = ("provider", "mode", "model", "effort")
NO_MODEL = (
    'model is missing: every hire names its model, {"model": <an exact id from the '
    "workspace's catalog (a family's version, not the family alone)>, \"effort\": <one of "
    "its levels>}, and model_why: one line on why that model and effort fit the work"
)
NO_MODEL_WHY = (
    "model_why is missing: say in its own field, in one line, why this model and effort "
    "fit the role's work (e.g. 'small repetitive work -> Haiku, low')"
)


def resolve_model(
    raw: Any,
    *,
    provider: str,
    label: str,
    mode: str,
    models: list[dict[str, Any]] | None,
    hire: bool = False,
) -> tuple[dict[str, str] | None, list[str]]:
    """The member's model as AGOS writes it ({provider, mode, model, effort}), or
    None (the workspace's model), and what is wrong with the one asked for.
    `models`: the catalog's models of the workspace's provider (None: unreadable).
    `hire`: a new member's model, whole: an exact version (a family alone is refused,
    with its versions), an effort, and nothing else in it (its why has its own field)."""
    if isinstance(raw, str):
        raw = {"model": raw}
    if hire:
        if not isinstance(raw, dict) or not any(str(v or "").strip() for v in raw.values()):
            return None, [NO_MODEL]
        extra = sorted(str(k) for k in raw if k not in MODEL_KEYS)
        if extra:
            return None, [
                f"model holds only model and effort (found {', '.join(extra)[:80]}): put "
                "the why in model_why, its own field"
            ]
        if not str(raw.get("model") or "").strip():
            return None, [NO_MODEL]
    if not isinstance(raw, dict) or not str(raw.get("model") or "").strip():
        return None, []
    from agos_core.engine.models import AGOS_ID

    wanted = str(raw.get("model") or "").strip()
    key = wanted.lower()
    asked = str(raw.get("provider") or "").strip().lower()
    if asked and AGOS_ID.get(asked, asked) != provider:
        return None, [
            f"model: a member runs on the workspace's provider ({label}); pick one of its "
            "models" + ("" if hire else ", or leave model out (the workspace's model)")
        ]
    if not models:
        return None, [
            f"model: Hermes didn't list {label}'s models just now; "
            + (
                "try again in a moment"
                if hire
                else "leave model out (the workspace's model) or try again"
            )
        ]
    ids = [str(m["id"]) for m in models]
    found = next((m for m in models if str(m["id"]) == wanted), None)
    if found is None:  # its name as the pickers show it ("Claude Haiku 4.5")
        found = next((m for m in models if str(m.get("label") or "").lower() == key), None)
    if found is None and key in FAMILIES:
        same = sorted(
            (m for m in models if model_family(str(m["id"])) == key),
            key=lambda m: _version(str(m["id"])),
            reverse=True,
        )
        if hire:
            return None, [
                f"model '{wanted[:40]}' is a family, not a version: pick one of its versions "
                + (", ".join(str(m["id"]) for m in same) or "(none listed: " + ", ".join(ids) + ")")
            ]
        found = same[0] if same else None
    if found is None:
        return None, [
            f"model '{wanted[:80]}' isn't one {label} offers this workspace: pick one of "
            + ", ".join(ids)
            + (" (only the id: the why goes in model_why)" if hire and " " in wanted else "")
        ]
    efforts = [str(e) for e in found.get("efforts") or []]
    given = str(raw.get("effort") or "").strip().lower()
    if hire and not given and efforts:
        return None, [
            f"model effort is missing: pick one of {', '.join(efforts) or 'low, medium, high'} "
            f"for {found['id']}"
        ]
    effort = given or str(found.get("defaultEffort") or "")
    if efforts and effort not in efforts:
        return None, [
            f"model effort '{effort[:20]}' isn't one {found['id']} takes: pick one of "
            + ", ".join(efforts)
        ]
    modes = [str(m) for m in found.get("modes") or []]
    return {
        "provider": provider,
        "mode": mode if mode in modes or not modes else modes[0],
        "model": str(found["id"]),
        "effort": effort or "medium",
    }, []


def model_line(model: dict[str, Any] | None, label: str = "") -> str:
    """'claude-haiku-4-5 · low' (the card, the Readiness item); '' for none."""
    if not model or not model.get("model"):
        return ""
    effort = str(model.get("effort") or "")
    shown = label or str(model["model"])
    return f"{shown} · {effort}" if effort and effort not in ("standard", "default") else shown


# ---- the readiness checklist's items -------------------------------------------------


def skill_item(name: str) -> str:
    return f"skill:{name}"


def tool_item(name: str) -> str:
    return f"tool:{name.lower()}"


def doc_item(doc: dict[str, str]) -> str:
    return f"doc:{doc.get('path') or doc.get('url')}"


def tool_path(tool: dict[str, str]) -> str:
    """How a tool reaches the member: a connector, an API key, or neither."""
    if tool.get("connector"):
        return "connector"
    return "key" if tool.get("key") else "none"


def doc_target(member: str, doc: dict[str, str]) -> str:
    """Where a doc lands, relative to the workspace's files folder."""
    name = (doc.get("path") or "").rstrip("/").rsplit("/", 1)[-1]
    return f"team/{member}/{'examples' if doc.get('kind') == 'example' else 'docs'}/{name}"


def missing_digest(items: list[str]) -> str:
    """What makes two 'Make it ready' asks the same ask (the card's key)."""
    return hashlib.sha256("\n".join(sorted(items)).encode()).hexdigest()[:10]


# ---- the member's SOUL section --------------------------------------------------------

TEAM_START = "<!-- agos:your-team -->"
TEAM_END = "<!-- /agos:your-team -->"


def team_section(
    *,
    member: str,
    lead: tuple[str, str] | None,
    peers: list[tuple[str, str, str]],
    project: str,
    goal: str,
    docs: list[dict[str, str]],
) -> str:
    """'Your team' in the member's SOUL.md: one marked section, rewritten with every
    SOUL write (so it follows the team). `lead`: (name, title), None = the
    Co-Founder; `peers`: (name, title, what it does)."""
    lines = ["## Your team"]
    lines.append(
        f"- Your lead: @{lead[0]} ({lead[1]})." if lead else "- Your lead: the Co-Founder."
    )
    if peers:
        lines.append("- You work with:")
        lines += [f"  - @{n} ({t}){': ' + s if s else ''}" for n, t, s in peers]
    if project or goal:
        lines.append(f"- What the team works on: {'; '.join(p for p in (project, goal) if p)}.")
    lines.append(
        f"- Your files: /workspace/team/{member}/ (docs/ to follow, examples/ of good work)."
    )
    links = [d for d in docs if d.get("url")]
    if links:
        lines.append("- References: " + "; ".join(f"{d['title']} ({d['url']})" for d in links))
    return f"{TEAM_START}\n" + "\n".join(lines) + f"\n{TEAM_END}"


# ---- the Co-Founder's card: make the member ready ------------------------------------


def gap_line(item: dict[str, Any]) -> str:
    """One missing item, as the Co-Founder reads it on its card."""
    return f"- `{item['id']}`: {item['label']} — {item['how']}"


def gap_body(member: str, title: str, lines: list[str]) -> str:
    """The 'Make <member> ready' card (exact words)."""
    return "\n".join(
        [
            f"@{member} ({title}) was hired, but it can't do its work well yet: some of "
            "what its kit lists is missing. Make it ready, item by item. AGOS shows the "
            "owner the same list (Hierarchy -> the member -> Readiness) and checks each "
            "item itself; nothing here is marked done by hand.",
            "",
            "Missing:",
            *lines,
            "",
            "How to resolve each kind:",
            "- A skill to find: search Hermes's skills hub (`hermes skills search <words>`) "
            "and the Brain (skills_list). Put the best match into this workspace's library "
            "(create_skill with its text, same name as listed) and try it once on a small "
            "example. AGOS gives it to the member as soon as the library has it.",
            "- A skill to write: write it with create_skill (exactly the name listed; the "
            "whole method in instructions), try it once on a small example, and say in "
            "your routes that the owner can test it in Skill Studio.",
            "- A tool with a connector: the owner connects it himself (his Inbox has a "
            "Connect button); tell him in one line what the member needs it for.",
            "- A tool with only an API: the owner adds its key in Settings -> Keys under "
            "the name listed. Once the key is there (agents see the name in their "
            "environment), you may write a small tool script for the member in "
            f"/workspace/team/{member}/tools/ that calls the API with it.",
            "- A tool with no API: propose an alternative (another tool that has a "
            "connector or an API, or a manual step), or a task for the owner.",
            "- A missing file: ask the owner for it with agos_ask_owner (kind ask: which "
            f"file, why the member needs it). Put what he gives in /workspace/team/{member}/"
            "docs/ (examples/ for an example).",
            "",
            "Never give the member other work meanwhile: it starts once it is ready.",
            "Then complete this card. Its result ends with ONE fenced block saying what "
            "you did or propose for each item:",
            f"```{ROUTES_FENCE}",
            '[{"item": "<the item as listed>", "path": "search | write | connect | key | '
            'script | alternative | you | ask | done", "text": "one line"}]',
            "```",
        ]
    )


def parse_routes(text: str) -> dict[str, dict[str, str]]:
    """The Co-Founder's routes from its card's result, by item ({} when none)."""
    found = _ROUTES_OPEN.search(text or "")
    if found is None:
        return {}
    try:
        raw, _ = json.JSONDecoder().raw_decode(text[found.end() :].lstrip())
    except ValueError:
        return {}
    out: dict[str, dict[str, str]] = {}
    for r in raw if isinstance(raw, list) else []:
        if not isinstance(r, dict) or not str(r.get("item") or "").strip():
            continue
        path = str(r.get("path") or "").strip().lower()
        out[str(r["item"]).strip().strip("`")[:200]] = {
            "path": path if path in ROUTE_PATHS else "",
            "text": _line(r.get("text"), 400),
        }
    return out


# ---- the onboarding test ---------------------------------------------------------------


def onboard_body(member: str, task: str, criteria: list[str], attempt: int) -> str:
    """The member's onboarding card (exact words)."""
    tried = f" (try {attempt} of {MAX_TRIES})" if attempt > 1 else ""
    return "\n".join(
        [
            f"Your onboarding test{tried}: one small piece of real work in this team's "
            "style, before your first real card. Use your skills and your files in "
            f"/workspace/team/{member}/ (docs/ to follow, examples/ of good work).",
            "",
            "## The task",
            task.strip(),
            "",
            "## What it is graded on",
            *[f"- {c}" for c in criteria],
            "",
            "Do it as you would for real. Complete this card with your output as the "
            "result (the text itself, or where the file is and what is in it): AGOS "
            "grades it against the list above.",
        ]
    )


def fix_body(member: str, attempt: int, notes: str, task: str) -> str:
    """The Co-Founder's card after a failed onboarding test (exact words)."""
    return "\n".join(
        [
            f"@{member}'s onboarding test failed (try {attempt} of {MAX_TRIES}). The "
            "grader's notes:",
            "",
            notes.strip() or "(no notes)",
            "",
            f"The task was: {task.strip()}",
            "",
            "Find what the member lacked and give it: a skill (create_skill or "
            "update_skill, then it is in the library and AGOS installs it), a doc or an "
            f"example in /workspace/team/{member}/, or a clearer role (update_agent "
            "add_instructions). Then complete this card with one line: what you added. "
            "AGOS runs the test again right after.",
        ]
    )


def grade_job(member: str, task: str, criteria: list[str], output: str) -> dict[str, str]:
    """What the Skill Studio grader (agos-grade) reads for one onboarding test."""
    return {
        "skill": f"onboarding of @{member}",
        "input": task[:6000],
        "output": output[:6000],
        "expected": "",
        "checklist": "\n".join(f"- {c}" for c in criteria)[:6000],
    }


# ---- a kit for a member already on the team (actions/member_kits.py) -------------------

KIT_STATES = ("none", "incomplete", "whole")


def kit_state(kit: dict[str, Any] | None, library_skills: int) -> str:
    """none (hired before kits) / incomplete (a part kit_missing names) / whole."""
    if not isinstance(kit, dict) or is_empty(kit):
        return "none"
    return "incomplete" if kit_missing(kit, library_skills) else "whole"


def suggest_body(
    *,
    member: str,
    title: str,
    role: str,
    skills: list[str],
    model: str,
    kit: dict[str, Any] | None,
    missing: list[str],
    cards: list[dict[str, str]],
    note: str = "",
) -> str:
    """The 'Suggest a kit for @x' card on the Co-Founder (exact words): what the
    member is and has done, then how to propose its kit."""
    lines = [
        f"The owner asks you for a WHOLE kit for @{member} ({title}), a member already on "
        "the team: "
        + (
            "it was hired before kits existed, so it has none."
            if not kit or is_empty(kit)
            else "its kit misses a part."
        ),
        "",
        "## The member as it is now",
        f"- Name: @{member}; job title: {title}",
        f"- Model: {model or 'the workspace' + chr(39) + 's'}",
        f"- Skills it loads: {', '.join(skills) if skills else 'none'}",
        "- Its role (its SOUL.md):",
        "",
        *[
            f"  > {ln}" if ln.strip() else "  >"
            for ln in (role.strip() or "(no role text)").splitlines()
        ],
        "",
    ]
    if kit and not is_empty(kit):
        lines += [
            "- Its kit now:",
            "",
            "```json",
            json.dumps(kit, ensure_ascii=False, indent=1),
            "```",
            "",
            "- What its kit lacks:",
            *[f"  - {m}" for m in missing],
            "",
        ]
    lines.append("- Its latest Kanban cards (what it has done):")
    lines += (
        [
            f"  - {c.get('id')} [{c.get('status')}] {c.get('title')}"
            + (f" — {c['result']}" if c.get("result") else "")
            for c in cards
        ]
        if cards
        else ["  - none yet"]
    )
    lines += [
        "",
        "## What to do",
        "1. Load your team-design skill: its kit section says what goes in each part.",
        "2. Read its role, its cards and the workspace's files (docs, examples) and the "
        "goal it serves (agos_goals, action status).",
        '3. Propose the kit with agos_propose, kind "kit", payload: member '
        f'("{member}"), kit (tools, skills, docs, team, onboarding: none of them empty, '
        "at least one skill this workspace's library has; keep what its kit already has "
        "that still fits), model (the exact version and effort its work needs) with "
        "model_why in its own field, why (one line: what its role and cards show it "
        "needs), source_card = this card's id. AGOS refuses a kit missing any of it and "
        "says what: fix it and propose again. ONE proposal; the owner edits, approves "
        "or rejects it in his Inbox.",
        "4. Change nothing of the member yourself (no update_agent, no save_kit): the "
        "owner's Approve writes the kit.",
        "5. Then complete this card with one line: what you proposed.",
    ]
    if note.strip():
        lines += ["", "## The owner's note (word for word)", "", note.strip()]
    return "\n".join(lines)


def match_app(name: str, catalog: dict[str, str]) -> str:
    """The catalog app a tool's name means ('' when none): its name or title."""
    wanted = name.strip().lower()
    slug = "-".join(wanted.replace("_", " ").split())
    for app, title in catalog.items():
        if wanted in (app, title.strip().lower()) or slug == app:
            return app
    for app in catalog:
        if app.replace("-", "") == slug.replace("-", "") or app.startswith(f"{slug}-"):
            return app
    return ""
