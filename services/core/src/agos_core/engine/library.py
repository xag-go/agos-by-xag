"""The library (Settings → Tools / Plugins / Connectors; each workspace's own
skills, agents and MCP servers) and what each workspace turns on.

The rules for what reaches a Hermes profile: checked MCP definitions and their
`mcp_servers` entries, skills, agents. What a workspace has on (on/off, allowed
tools, credentials) lives in its own Hermes config (actions/hermes_config.py).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

Kind = Literal["skill", "agent", "mcp", "plugin", "tool"]
KINDS: tuple[Kind, ...] = ("skill", "agent", "mcp", "plugin", "tool")

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SKILLS_DIR_NAME = "agos-library"  # inside each profile's skills/ folder
MCP_ENV_PREFIX = "AGOS_MCP_"


class LibraryError(ValueError):
    """Shown to the owner as-is."""


def check_name(name: str) -> str:
    if not NAME.fullmatch(name):
        raise LibraryError("Use lowercase letters, digits and dashes for the name (max 63).")
    return name


# ---- skills ----------------------------------------------------------------------

log = logging.getLogger("agos.library")
_FRONTMATTER = re.compile(r"\A---\n(?P<head>.*?)\n---\n?(?P<body>.*)\Z", re.DOTALL)


# Hermes's own frontmatter reader (engine/skill_frontmatter.py), set when the core
# starts with Hermes. Without an engine (demo, unit tests) the plain reader below.
_hermes_reader: Callable[[list[str]], list[tuple[dict[str, str], str]]] | None = None


def use_hermes_reader(
    reader: Callable[[list[str]], list[tuple[dict[str, str], str]]] | None,
) -> None:
    global _hermes_reader
    _hermes_reader = reader


def has_frontmatter(text: str) -> bool:
    return bool(_FRONTMATTER.match(text.replace("\r\n", "\n").removeprefix("\ufeff")))


def parse_skill(text: str) -> tuple[dict[str, str], str]:
    """(frontmatter, body) of a SKILL.md, as Hermes reads it."""
    return parse_skills([text])[0]


def parse_skills(texts: list[str]) -> list[tuple[dict[str, str], str]]:
    """Many SKILL.md texts in one Hermes call. A text without a --- block is refused."""
    clean = [t.replace("\r\n", "\n").removeprefix("\ufeff") for t in texts]
    for text in clean:
        if not _FRONTMATTER.match(text):
            raise LibraryError(
                "SKILL.md must start with a --- frontmatter block (name, description)."
            )
    if _hermes_reader is not None:
        try:
            return _hermes_reader(clean)
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            log.warning("Hermes could not read SKILL.md frontmatter: %s", error)
    return [_plain(text) for text in clean]


def _plain(text: str) -> tuple[dict[str, str], str]:
    """No Hermes here (demo, unit tests): `key: value` lines."""
    match = _FRONTMATTER.match(text)
    assert match is not None
    head: dict[str, str] = {}
    for line in match["head"].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        key, sep, value = line.partition(":")
        if sep:
            head[key.strip()] = value.strip().strip('"').strip("'")
    return head, match["body"]


def check_skill(text: str) -> tuple[str, str]:
    """(name, description) of a valid SKILL.md."""
    head, body = parse_skill(text)
    name = check_name(head.get("name", ""))
    description = head.get("description", "").strip()
    if not description:
        raise LibraryError("The frontmatter needs a description (when to use the skill).")
    if not body.strip():
        raise LibraryError("The skill has no instructions after the frontmatter.")
    return name, description


def readable_title(name: str) -> str:
    """'ideas-generator' -> 'Ideas Generator' (when no display name is given)."""
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[-_\s]+", name) if w)


def skill_template(name: str, description: str, body: str) -> str:
    return f"---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n{body.strip()}\n"


# ---- MCP ---------------------------------------------------------------------------

_BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
]


def _private(host: str) -> bool | None:
    """Whether the host is on this computer or a private network; None when its
    name can't be resolved now (then it is refused too: a name that resolves only
    later could point at 127.0.0.1, where each workspace's local MCP servers are)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return None
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if any(address in net for net in _BLOCKED_NETS):
            return True
    return False


def check_mcp(definition: dict[str, Any], *, resolve: bool = True) -> dict[str, Any]:
    """An MCP server definition, cleaned. Remote = an HTTP URL. Local = a command
    that speaks MCP over stdio; it never runs on this machine: each workspace
    that turns it on runs it in its own container (engine/mcp_runner.py)."""
    transport = str(definition.get("transport") or "http")
    if transport in ("command", "stdio"):
        command = str(definition.get("command") or "").strip()
        if not command or "\n" in command:
            raise LibraryError("Give the command that starts the server (one line).")
        from agos_core.engine.mcp_runner import check_command

        try:
            check_command(command)
        except ValueError as error:
            raise LibraryError(str(error)) from error
        env_key = str(definition.get("env_key") or "").strip()
        if env_key and not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", env_key):
            raise LibraryError("The key's variable name looks wrong (e.g. GITHUB_TOKEN).")
        return {"transport": "command", "command": command, "env_key": env_key}
    if transport != "http":
        raise LibraryError("Unknown kind of MCP server.")
    url = str(definition.get("url") or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise LibraryError("Give the server's URL (https://…).")
    if parts.username or parts.password:
        raise LibraryError("Don't put credentials in the URL; add them per workspace.")
    host = parts.hostname.lower()
    if host in ("localhost", "host.docker.internal") or host.endswith(".local"):
        raise LibraryError("Servers on this computer or the local network aren't allowed.")
    if resolve:
        private = _private(host)
        if private is None:
            raise LibraryError(
                f"AGOS can't find the server {host} (check the URL, or try again when "
                "this machine is online): it isn't added."
            )
        if private:
            raise LibraryError("Servers on this computer or the local network aren't allowed.")
    header = str(definition.get("auth_header") or "").strip()
    if header and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", header):
        raise LibraryError("The credential header name looks wrong (e.g. Authorization).")
    scheme = str(definition.get("auth_scheme") or "").strip()
    if scheme and not re.fullmatch(r"[A-Za-z]{1,20}", scheme):
        raise LibraryError("The credential prefix looks wrong (e.g. Bearer).")
    return {"transport": "http", "url": url, "auth_header": header, "auth_scheme": scheme}


def is_local(definition: dict[str, Any]) -> bool:
    return str(definition.get("transport") or "http") in ("command", "stdio")


def auth_of(definition: dict[str, Any]) -> tuple[str, str]:
    """(header, prefix) a workspace key is sent with. No header set = the MCP
    standard, `Authorization: Bearer <key>`."""
    header = str(definition.get("auth_header") or "").strip()
    if not header:
        return "Authorization", "Bearer"
    return header, str(definition.get("auth_scheme") or "").strip()


def env_name(name: str) -> str:
    return MCP_ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", name.upper())


def mcp_entry(
    name: str, definition: dict[str, Any], *, has_secret: bool, allowed_tools: list[str]
) -> dict[str, Any]:
    """What goes under `mcp_servers.<name>` in the profile's config. The secret
    itself stays in the profile's .env and is referenced as ${AGOS_MCP_…}.
    A local server's `url` is its container's address (set by the caller); its
    key lives in that container, never in Hermes."""
    entry: dict[str, Any] = {"url": definition["url"]}
    if has_secret and is_local(definition):
        has_secret = False
    if has_secret:
        header, scheme = auth_of(definition)
        prefix = f"{scheme} " if scheme else ""
        entry["headers"] = {header: f"{prefix}${{{env_name(name)}}}"}
    if allowed_tools:
        entry["tools"] = {"include": allowed_tools}
    return entry


# ---- agents -------------------------------------------------------------------------


def check_agent(definition: dict[str, Any]) -> dict[str, Any]:
    instructions = str(definition.get("instructions") or "").strip()
    if not instructions:
        raise LibraryError("Write the agent's role instructions.")
    model = definition.get("model")
    return {
        "instructions": instructions,
        "model": model if isinstance(model, dict) else None,
        "skills": [check_name(s) for s in definition.get("skills") or []],
        "tools": [str(t)[:64] for t in definition.get("tools") or []][:50],
        # Who it reports to in the team (the org chart): "" = the Co-Founder (the
        # workspace's own Hermes), else another member's name (a sub-manager).
        "reports_to": reports_to(definition.get("reports_to")),
        # The Documentation it follows: given in full on every job ("always"), or
        # opened by itself when the work needs it ("demand").
        "reads": [
            {
                "path": str(r.get("path")).strip().strip("/")[:200],
                "section": str(r.get("section") or "").strip()[:20],
                "mode": "demand" if r.get("mode") == "demand" else "always",
            }
            for r in definition.get("reads") or []
            if isinstance(r, dict) and str(r.get("path") or "").strip()
        ],
    }


def reports_to(value: Any) -> str:
    """A member's lead as written in its profile: "" (the Co-Founder) or a name."""
    name = str(value or "").strip().lower().lstrip("@")
    # "manager": the name before step 44, still in old definitions
    return "" if name in ("", "cofounder", "manager", "none") else name[:63]


INSTRUCTIONS_START = "<!-- agos:instructions -->"
INSTRUCTIONS_END = "<!-- /agos:instructions -->"
LOCAL_START = "<!-- agos:local -->"
LOCAL_END = "<!-- /agos:local -->"


def agent_instructions(title: str, definition: dict[str, Any], local: str) -> str:
    """The member's role in its SOUL.md (its one home): the owner's role text and his
    notes for it in this workspace, each between markers so they read back as written."""
    text = str(definition.get("instructions") or "").strip()
    parts = [
        f"## Acting as the agent “{title}”",
        f"{INSTRUCTIONS_START}\n{text}\n{INSTRUCTIONS_END}" if text else "",
    ]
    if local.strip():
        parts.append(f"For this workspace:\n{LOCAL_START}\n{local.strip()}\n{LOCAL_END}")
    return "\n\n".join(p for p in parts if p)


def _between(text: str, start: str, end: str) -> str | None:
    at = text.find(start)
    stop = text.find(end, at + 1) if at >= 0 else -1
    if at < 0 or stop < 0:
        return None
    return text[at + len(start) : stop].strip()


def soul_role(soul: str) -> tuple[str | None, str]:
    """(role text, the owner's notes) as a member's SOUL.md has them (None: no role
    block in it)."""
    return (
        _between(soul, INSTRUCTIONS_START, INSTRUCTIONS_END),
        _between(soul, LOCAL_START, LOCAL_END) or "",
    )


# ---- writing into a profile ----------------------------------------------------------


@dataclass(frozen=True)
class Enabled:
    kind: Kind
    name: str
    definition: dict[str, Any]
    allowed_tools: list[str]
    secret: str | None


# The old per-folder provenance file of the shared library (gone: each workspace's
# row keeps where its skill came from). Only named so the move drops it.
SOURCES_FILE = ".agos-sources.json"


# ---- a workspace's skills in Hermes: ONE folder, read by its whole team -------------
#
# A workspace's skills live in its root's (its Co-Founder's) local skill folder
# <root>/skills/agos-library/<name>: the Co-Founder reads and changes them as its own
# local skills (Hermes's skill_manage), and every member profile of the workspace
# reads that same folder through its `skills.external_dirs` (read-only for them).
# A skill turned off in the workspace is in each profile's `skills.disabled`.


def copies_dir(profile_home: Path) -> Path:
    """The workspace's skill folder in its root (a Hermes local skill folder)."""
    return profile_home / "skills" / SKILLS_DIR_NAME


def archive_skill(profile_home: Path, name: str, *, archive: Callable[[str], None]) -> None:
    """The workspace's skill goes, the Hermes way: `archive(skill)` runs `hermes
    curator archive <skill>` in its root, which moves it to `skills/.archive/`
    (recoverable with `curator restore`, recorded in the curator's ledger;
    hermes_cli/curator.py _cmd_archive, tools/skill_usage.py archive_skill).
    Raises LibraryError when Hermes kept it (it says why)."""
    folder = copies_dir(profile_home) / name
    if not (folder / "SKILL.md").is_file():
        return
    try:  # Hermes finds a skill by its frontmatter name
        skill = str(parse_skill((folder / "SKILL.md").read_text())[0].get("name") or name)
    except LibraryError:
        skill = name
    try:
        archive(skill)
    except Exception as error:
        raise LibraryError(f"The engine kept this skill: {error}"[:300]) from error
    if folder.exists():
        raise LibraryError("The engine kept this skill (curator archive).")


def write_mcp_env(profile_home: Path, secrets_by_name: dict[str, str]) -> None:
    """Replaces the AGOS_MCP_* lines of the profile's .env (0600)."""
    from agos_core.engine import envfile

    lines = []
    for name, value in sorted(secrets_by_name.items()):
        if "\n" in value or "\r" in value:
            raise LibraryError("A credential can't contain line breaks.")
        lines.append(f"{env_name(name)}={value}")
    envfile.rewrite(profile_home / ".env", (MCP_ENV_PREFIX,), lines)
