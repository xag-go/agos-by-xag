"""What a workspace has on lives in its own Hermes config (ADR 0020 root).

A workspace's MCP servers and apps, Hermes's tools, its own skills and the plugins
it uses are its root's Hermes settings (the Co-Founder's profile, the root's default):
- MCP servers and apps → `mcp_servers` (Hermes's own `enabled` switch and
  `tools.include` filter; the key in the root's .env, referenced as ${AGOS_MCP_…});
- tools → `platform_toolsets.agos` (and the other platforms) holds the ones the owner
  turned on, `agent.disabled_toolsets` the ones off (Hermes applies it last);
- its skills → off = the root's `skills.disabled`;
- plugins → `plugins.enabled`.
AGOS reads them there and changes them there with `hermes config set`; it keeps no
copy. A member profile gets the root's settings copied in (Hermes profiles inherit
nothing from each other: hermes_cli/profiles.py has no config inheritance).

A Hermes `mcp_servers` entry is an open mapping (hermes_cli/config.py
`_OPEN_DICT_TOP_LEVEL_KEYS`; the MCP client reads only its own keys), so AGOS keeps
what Hermes has no key for under `agos`: a local server's command (it runs in the
workspace's own container, engine/mcp_runner.py, never on this machine), the header
a key is sent with, and which Google apps the one Google server serves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agos_core.context import Core
from agos_core.engine import config_file
from agos_core.engine import library as lib

AGOS = "agos"  # AGOS's own facts inside a Hermes mcp_servers entry
GOOGLE_APPS = "apps"  # agos.apps of `app-google`: the Google apps it serves
NOUS_TOOLSET = "connections"  # Nous hosted apps are this Hermes toolset
PLATFORM = "platform_toolsets.agos"  # the owner's tool switches (AGOS's own chats)


@dataclass
class Here:
    """What one workspace has on, as its root's Hermes config says."""

    tools: set[str] = field(default_factory=set)  # optional toolsets on
    skills: set[str] = field(default_factory=set)  # its own skills on
    plugins: set[str] = field(default_factory=set)  # plugin names on
    mcp: dict[str, dict[str, Any]] = field(default_factory=dict)  # its own servers
    apps: set[str] = field(default_factory=set)  # apps on ("nous" = Nous apps)
    keys: dict[str, str] = field(default_factory=dict)  # MCP keys, by server name


def root_home(core: Core, workspace_id: str) -> Path | None:
    if core.engine is None:
        return None
    return core.engine.profile_home(workspace_id)


def has_root(core: Core, workspace_id: str) -> bool:
    home = root_home(core, workspace_id)
    return home is not None and (home / "config.yaml").is_file()


def config(core: Core, workspace_id: str) -> dict[str, Any]:
    home = root_home(core, workspace_id)
    return config_file.read(home) if home is not None else {}


# ---- an MCP server: Hermes's entry <-> AGOS's definition -----------------------------


def entry_of(
    name: str,
    definition: dict[str, Any],
    *,
    on: bool,
    allowed_tools: list[str],
    has_key: bool,
    url: str | None = None,
) -> dict[str, Any]:
    """The `mcp_servers.<name>` entry for a server AGOS checked (lib.check_mcp)."""
    local = lib.is_local(definition)
    entry = lib.mcp_entry(
        name,
        {**definition, "url": url if url is not None else definition.get("url", "")},
        has_secret=has_key,
        allowed_tools=allowed_tools,
    )
    entry["enabled"] = bool(on)
    if local:
        entry[AGOS] = {
            "command": str(definition.get("command") or ""),
            "env_key": str(definition.get("env_key") or ""),
        }
    else:
        extra = {
            k: str(definition.get(k) or "")
            for k in ("auth_header", "auth_scheme")
            if definition.get(k)
        }
        if extra:
            entry[AGOS] = extra
    return entry


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def agos_part(entry: dict[str, Any]) -> dict[str, Any]:
    return _mapping(entry.get(AGOS))


def definition_of(entry: dict[str, Any]) -> dict[str, Any]:
    """AGOS's definition of a server from its Hermes entry."""
    mine = agos_part(entry)
    if mine.get("command"):
        return {
            "transport": "command",
            "command": str(mine["command"]),
            "env_key": str(mine.get("env_key") or ""),
        }
    header, scheme = str(mine.get("auth_header") or ""), str(mine.get("auth_scheme") or "")
    headers = _mapping(entry.get("headers"))
    if not header and headers:
        first, value = next(iter(headers.items()))
        header = str(first)
        prefix = str(value).split("${", 1)[0].strip()
        scheme = prefix if " " not in prefix else ""
    return {
        "transport": "http",
        "url": str(entry.get("url") or ""),
        "auth_header": header,
        "auth_scheme": scheme,
    }


def is_on(entry: dict[str, Any]) -> bool:
    """Hermes's own reading of `enabled` (tools/mcp_tool_common.mcp_server_enabled)."""
    value = entry.get("enabled", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return value is None or bool(value)


def allowed_tools(entry: dict[str, Any]) -> list[str]:
    include = _mapping(entry.get("tools")).get("include")
    return [str(t) for t in include] if isinstance(include, list) else []


# ---- reading -------------------------------------------------------------------------


def here(core: Core, workspace_id: str) -> Here:
    return from_hermes(core, workspace_id)


def _library_names(
    core: Core, kind: str, workspace_id: str | None = None
) -> dict[str, dict[str, Any]]:
    from agos_core.db import library as repo

    return {
        str(r["name"]): repo.definition(r) for r in repo.list_items(core.db, kind, workspace_id)
    }


def plugin_name(name: str, definition: dict[str, Any]) -> str:
    return str(definition.get("plugin") or name)


def from_hermes(core: Core, workspace_id: str) -> Here:
    from agos_core.engine import hermes_tools

    cfg = config(core, workspace_id)
    optional = hermes_tools.optional()
    platform = config_file.string_list(config_file.get(cfg, PLATFORM))
    disabled = set(config_file.string_list(config_file.get(cfg, "agent.disabled_toolsets")) or [])
    if platform is None:
        # AGOS never set this root up: every tool it may give is on.
        tools = set(optional)
    else:
        # The owner's switch is the platform list; a toolset Hermes added since
        # (in neither list) is on, like every tool he never turned off.
        tools = {t for t in optional if t in platform or t not in disabled}
    skills_off = set(config_file.string_list(config_file.get(cfg, "skills.disabled")) or [])
    plugins = set(config_file.string_list(config_file.get(cfg, "plugins.enabled")) or [])
    library_skills = set(_library_names(core, "skill", workspace_id))  # its own
    if platform is None:
        # Never set up by AGOS: none of its skills is on yet, every tool is.
        skills_off |= library_skills
    servers = config_file.get(cfg, "mcp_servers") or {}
    mcp: dict[str, dict[str, Any]] = {}
    apps: set[str] = set()
    from agos_core.engine.apps import SERVER_PREFIX

    for name, entry in servers.items() if isinstance(servers, dict) else []:
        if not isinstance(entry, dict):
            continue
        name = str(name)
        if name.startswith(SERVER_PREFIX):
            app = name[len(SERVER_PREFIX) :]
            listed = agos_part(entry).get(GOOGLE_APPS)
            if isinstance(listed, list):
                apps |= {str(a) for a in listed}
            else:
                apps.add(app)
            continue
        mcp[name] = entry
    if NOUS_TOOLSET in (platform or []):
        from agos_core.actions.apps import NOUS_APP

        apps.add(NOUS_APP)
    env = config_file.read_env(root_home(core, workspace_id) or Path("/nonexistent"))
    keys = {name: env[lib.env_name(name)] for name in mcp if env.get(lib.env_name(name))}
    return Here(
        tools=tools,
        skills={n for n in library_skills if n not in skills_off},
        plugins={p for p in plugins if p != "agos-guard"},
        mcp=mcp,
        apps=apps,
        keys=keys,
    )
