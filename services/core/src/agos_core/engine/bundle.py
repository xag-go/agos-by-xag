"""A workspace bundle: a readable folder (or zip) of markdown and YAML, as rules on
text alone (no files, no database). Step 56, F90 / F91.

    TEAM.md                  the team: frontmatter (machine part) + a readable org chart
    settings.yaml            the workspace's name, model choice (no key), review
                             defaults, connectors it uses, and `env_requires`: every
                             key the importer is asked for (never a value)
    cofounder/SOUL.md        the owner's identity text for the Co-Founder
    agents/<name>/SOUL.md    a member's role text, exactly as its Hermes SOUL.md says it
    agents/<name>/agent.yaml its title, what it's for, lead, model, skills, rule files
                             it reads, on/off, heartbeat, the owner's notes
    skills/<name>/SKILL.md   a workspace skill (+ its other text files)
    automations/<slug>.yaml  an automation (who does it, schedule, steps, variables…)
    vision.md                the Vision, goals with key results, projects

`env_requires` entries have the shape of Hermes's own profile distributions
(hermes_cli/profile_distribution.py EnvRequirement: name, description, required,
default), plus AGOS's `kind` (tool_key / connector) and `app`. A bundle holds no
secret: the exporter keeps only named fields, runs Hermes's own masking over every
text and turns any known key value into `${NAME}` (an input).
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

import yaml

SCHEMA = "agos/bundle-v1"
TEAM_FILE = "TEAM.md"
SETTINGS_FILE = "settings.yaml"
VISION_FILE = "vision.md"
COFOUNDER_SOUL = "cofounder/SOUL.md"
AGENT_SOUL = "agents/{}/SOUL.md"
AGENT_FILE = "agents/{}/agent.yaml"
SKILL_FILE = "skills/{}/SKILL.md"
AUTOMATION_FILE = "automations/{}.yaml"

MAX_FILES = 2000
MAX_BYTES = 20_000_000
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_FRONT = re.compile(r"\A---\n(?P<head>.*?)\n---\n?(?P<body>.*)\Z", re.S)
STRATEGIES = ("skip", "rename", "replace")
# What a bundle never carries (the fidelity report says it every time).
NOT_CARRIED = (
    "chat history, sessions and the agents' memory",
    "Kanban cards and their history",
    "Telegram bots and member topics (set them up in Settings → Channels)",
    "provider logins and API keys (each key is asked for as an input)",
    "connector sign-ins (each connector is listed to sign in again)",
)


class BundleError(ValueError):
    """A bundle AGOS can't read (the message is safe to show)."""


@dataclass
class Agent:
    name: str
    title: str
    summary: str = ""
    instructions: str = ""
    notes: str = ""
    reports_to: str = ""
    model: dict[str, Any] | None = None
    skills: list[str] = field(default_factory=list)
    reads: list[dict[str, str]] = field(default_factory=list)
    on: bool = True
    heartbeat: str = ""


@dataclass
class Skill:
    name: str
    text: str
    files: dict[str, str] = field(default_factory=dict)


@dataclass
class Parsed:
    """A bundle as AGOS reads it."""

    meta: dict[str, Any]
    settings: dict[str, Any]
    agents: list[Agent]
    skills: list[Skill]
    automations: list[dict[str, Any]]
    vision: dict[str, Any] | None
    cofounder: str
    inputs: list[dict[str, Any]]

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or "")

    @property
    def slug(self) -> str:
        return str(self.meta.get("slug") or "")


# ---- small text helpers ------------------------------------------------------------


def frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """(YAML head, body) of a markdown file with a `---` frontmatter."""
    found = _FRONT.match(text.replace("\r\n", "\n"))
    if found is None:
        return {}, text
    try:
        head = yaml.safe_load(found["head"])
    except yaml.YAMLError as error:
        raise BundleError(f"Its frontmatter isn't YAML: {error}") from error
    return (head if isinstance(head, dict) else {}), found["body"]


def _dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def with_front(head: dict[str, Any], body: str) -> str:
    return f"---\n{_dump(head)}---\n\n{body.strip()}\n"


def _yaml(files: dict[str, str], path: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(files[path])
    except yaml.YAMLError as error:
        raise BundleError(f"{path} isn't YAML: {error}") from error
    if not isinstance(data, dict):
        raise BundleError(f"{path} must be a mapping.")
    return data


def slug(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-")
    return out or "item"


def content_hash(files: dict[str, str]) -> str:
    """The bundle's identity: every path and text, in order (drift is measured
    against the hash a workspace installed)."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode() + b"\0" + files[path].encode() + b"\0")
    return digest.hexdigest()


# ---- zip -----------------------------------------------------------------------------


def to_zip(files: dict[str, str], top: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.writestr(f"{top}/{path}", files[path])
    return out.getvalue()


def _safe(path: str) -> str:
    raw = path.replace("\\", "/")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or raw.startswith("/") or ":" in parts[0] or ".." in parts:
        raise BundleError(f"A file in the bundle has an unsafe path: {path}")
    return "/".join(parts)


def from_zip(data: bytes) -> dict[str, str]:
    """The bundle's text files (one top folder, if any, is dropped). Fails closed
    on anything that isn't a small UTF-8 text tree."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise BundleError("That file isn't a zip bundle.") from error
    entries = [i for i in archive.infolist() if not i.is_dir()]
    if len(entries) > MAX_FILES:
        raise BundleError(f"The bundle has more than {MAX_FILES} files.")
    if sum(i.file_size for i in entries) > MAX_BYTES:
        raise BundleError("The bundle is too big (20 MB of text at most).")
    raw: dict[str, str] = {}
    for info in entries:
        path = _safe(info.filename)
        if path.startswith("__MACOSX/") or path.rsplit("/", 1)[-1] == ".DS_Store":
            continue
        try:
            raw[path] = archive.read(info).decode("utf-8")
        except UnicodeDecodeError as error:
            raise BundleError(f"{path} isn't a text file.") from error
    tops = {p.split("/", 1)[0] for p in raw}
    if TEAM_FILE not in raw and len(tops) == 1:
        top = tops.pop() + "/"
        raw = {p[len(top) :]: v for p, v in raw.items() if p.startswith(top)}
    if TEAM_FILE not in raw:
        raise BundleError("This isn't an AGOS bundle: TEAM.md is missing.")
    return raw


# ---- reading -------------------------------------------------------------------------


def _str_list(value: Any) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


def _agent(files: dict[str, str], name: str) -> Agent:
    if not NAME.fullmatch(name):
        raise BundleError(f"agents/{name}: a member's name is lowercase-with-dashes.")
    data = _yaml(files, AGENT_FILE.format(name))
    model = data.get("model")
    reads = data.get("reads")
    return Agent(
        name=name,
        title=str(data.get("title") or "").strip()[:64],
        summary=str(data.get("summary") or "").strip(),
        instructions=files.get(AGENT_SOUL.format(name), "").strip(),
        notes=str(data.get("notes") or "").strip(),
        reports_to=str(data.get("reports_to") or "").strip().lstrip("@").lower(),
        model=model if isinstance(model, dict) and model.get("model") else None,
        skills=_str_list(data.get("skills")),
        reads=[
            {str(k): str(v) for k, v in r.items()}
            for r in (reads if isinstance(reads, list) else [])
            if isinstance(r, dict)
        ],
        on=data.get("on", True) is not False,
        heartbeat=str(data.get("heartbeat") or ""),
    )


def _skill(files: dict[str, str], name: str) -> Skill:
    if not NAME.fullmatch(name):
        raise BundleError(f"skills/{name}: a skill's name is lowercase-with-dashes.")
    base = f"skills/{name}/"
    extra = {
        p[len(base) :]: v
        for p, v in files.items()
        if p.startswith(base) and p != SKILL_FILE.format(name)
    }
    return Skill(name=name, text=files[SKILL_FILE.format(name)], files=extra)


def _inputs(settings: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for entry in settings.get("env_requires") or []:
        if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
            raise BundleError("settings.yaml: each env_requires entry needs a name.")
        out.append(
            {
                "name": str(entry["name"]).strip(),
                "description": str(entry.get("description") or ""),
                "required": bool(entry.get("required", True)),
                "kind": str(entry.get("kind") or "tool_key"),
                "app": str(entry.get("app") or entry["name"]),
            }
        )
    return out


def parse(files: dict[str, str]) -> Parsed:
    """The bundle as data. Raises BundleError with what is wrong."""
    if TEAM_FILE not in files:
        raise BundleError("This isn't an AGOS bundle: TEAM.md is missing.")
    meta, _body = frontmatter(files[TEAM_FILE])
    if str(meta.get("schema") or "") != SCHEMA:
        raise BundleError(f"TEAM.md: schema must be {SCHEMA}.")
    settings = _yaml(files, SETTINGS_FILE) if SETTINGS_FILE in files else {}
    names = sorted(
        {p.split("/")[1] for p in files if p.startswith("agents/") and p.count("/") >= 2}
    )
    agents = [_agent(files, n) for n in names if AGENT_FILE.format(n) in files]
    skill_names = sorted(
        {p.split("/")[1] for p in files if p.startswith("skills/") and p.endswith("/SKILL.md")}
    )
    skills = [_skill(files, n) for n in skill_names if SKILL_FILE.format(n) in files]
    automations = []
    for path in sorted(p for p in files if p.startswith("automations/") and p.endswith(".yaml")):
        data = _yaml(files, path)
        if not str(data.get("name") or "").strip():
            raise BundleError(f"{path}: an automation needs a name.")
        automations.append({**data, "slug": path[len("automations/") : -len(".yaml")]})
    vision = None
    if VISION_FILE in files:
        head, _vbody = frontmatter(files[VISION_FILE])
        vision = head if head.get("vision") or head.get("goals") else None
    return Parsed(
        meta=meta,
        settings=settings,
        agents=agents,
        skills=skills,
        automations=automations,
        vision=vision,
        cofounder=files.get(COFOUNDER_SOUL, "").strip(),
        inputs=_inputs(settings),
    )


def leads_first(agents: list[Agent]) -> list[Agent]:
    """The members in an order where each lead comes before its reports (a lead
    outside the bundle, or a loop, counts as the top)."""
    by_name = {a.name: a for a in agents}
    out: list[Agent] = []
    seen: set[str] = set()

    def visit(agent: Agent, path: set[str]) -> None:
        if agent.name in seen:
            return
        boss = by_name.get(agent.reports_to)
        if boss is not None and boss.name not in path:
            visit(boss, path | {agent.name})
        seen.add(agent.name)
        out.append(agent)

    for agent in agents:
        visit(agent, {agent.name})
    return out


def free_name(name: str, taken: set[str]) -> str:
    """`name`, or name-2, name-3… when it is taken (a rename on import)."""
    if name not in taken:
        return name
    n = 2
    while f"{name[:58]}-{n}" in taken:
        n += 1
    return f"{name[:58]}-{n}"


# ---- writing -------------------------------------------------------------------------


def agent_files(agent: Agent) -> dict[str, str]:
    data: dict[str, Any] = {
        "name": agent.name,
        "title": agent.title,
        "summary": agent.summary,
        "reports_to": agent.reports_to,
        "model": agent.model,
        "skills": list(agent.skills),
        "reads": [dict(r) for r in agent.reads],
        "on": agent.on,
        "heartbeat": agent.heartbeat,
        "notes": agent.notes,
    }
    return {
        AGENT_SOUL.format(agent.name): agent.instructions.strip() + "\n",
        AGENT_FILE.format(agent.name): _dump(data),
    }


def _tree_lines(agents: list[Agent]) -> list[str]:
    kids: dict[str, list[Agent]] = {}
    names = {a.name for a in agents}
    for agent in agents:
        kids.setdefault(agent.reports_to if agent.reports_to in names else "", []).append(agent)
    lines: list[str] = []

    def walk(boss: str, depth: int) -> None:
        for agent in sorted(kids.get(boss, []), key=lambda a: a.title.lower()):
            lead = f"@{agent.reports_to}" if agent.reports_to else "the Co-Founder"
            about = f" — {agent.summary}" if agent.summary else ""
            lines.append(
                f"{'  ' * depth}- **{agent.title}** (@{agent.name}), reports to {lead}{about}"
            )
            walk(agent.name, depth + 1)

    walk("", 0)
    return lines


def team_md(meta: dict[str, Any], parsed_agents: list[Agent], extra: dict[str, list[str]]) -> str:
    """TEAM.md: the frontmatter (what the importer reads) and a page a person reads."""
    head = {"schema": SCHEMA, **{k: v for k, v in meta.items() if k != "schema"}}
    head["members"] = [a.name for a in leads_first(parsed_agents)]
    lines = [f"# {meta.get('name') or 'Team'}", ""]
    if meta.get("description"):
        lines += [str(meta["description"]).strip(), ""]
    lines += ["## Team", ""]
    lines += _tree_lines(parsed_agents) or ["- (no members: the Co-Founder alone)"]
    for title, items in extra.items():
        if items:
            lines += ["", f"## {title}", "", *items]
    return with_front(head, "\n".join(lines))


def vision_md(vision: dict[str, Any]) -> str:
    top = vision.get("vision") or {}
    lines = [f"# Vision: {top.get('title') or ''}".rstrip(), ""]
    if top.get("why"):
        lines += [str(top["why"]), ""]
    if top.get("strategy"):
        lines += ["## Strategy", "", str(top["strategy"]), ""]
    for goal in vision.get("goals") or []:
        lines += [f"## Goal: {goal.get('title')}", ""]
        if goal.get("why"):
            lines += [str(goal["why"]), ""]
        for kr in goal.get("key_results") or []:
            target = kr.get("target")
            lines.append(
                f"- KR: {kr.get('title')} ({kr.get('current')} → {target if target is not None else '?'}"
                f"{' ' + str(kr['unit']) if kr.get('unit') else ''})"
            )
        for project in goal.get("projects") or []:
            lines.append(f"- Project: {project.get('title')}")
        lines.append("")
    return with_front(vision, "\n".join(lines))
