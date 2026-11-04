"""Connectors = apps with an account (Notion, Canva, Figma, Stripe…).

The list is Hermes's own approved catalog (`optional-mcps/`: vendor-hosted
HTTP MCP servers, OAuth or no login) plus AGOS_APPS. Each workspace connects
its OWN account to an app; nothing is shared between workspaces.

Where a login lives: that workspace's login folder (`agos-data/system/
connectors/w/<workspace>`). The login helper runs Hermes with a login profile
whose `mcp-tokens` links there, so Hermes writes its own token files in
`<folder>/mcp-tokens/`. Never the owner's ~/.hermes.

How the workspace uses it: its profile's `mcp-tokens` links to the same folder,
and `mcp_servers.<app>` is written only while the app is ON there. An app that
is off has no server entry, so the agent has no tool for it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

APP_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Server names AGOS writes for apps, so they never collide with library MCP names.
SERVER_PREFIX = "app-"
TOKEN_SUFFIXES = (".json", ".client.json", ".meta.json", ".cimd-off")


class AppError(ValueError):
    """The message is safe to show to the owner."""


@dataclass(frozen=True)
class CatalogApp:
    name: str
    description: str
    url: str
    auth: str  # "oauth" | "none"
    source: str = ""
    excluded_tools: list[str] = field(default_factory=list)
    # Why it can't be connected from AGOS yet (needs the owner's own developer app…).
    locked: str | None = None
    # The owner's own OAuth client, for servers that don't register one themselves
    # (Google's): Hermes skips registration and uses it (`oauth.client_id/secret`).
    oauth_client: tuple[str, str] | None = None


# Printed by the Hermes python; reads Hermes's parser so AGOS shows exactly its catalog.
_DUMP = """
import json
from hermes_cli.mcp_catalog import list_catalog
out = []
for e in list_catalog():
    out.append({
        "name": e.name, "description": e.description, "source": e.source,
        "transport": e.transport.type, "url": e.transport.url or "",
        "auth": e.auth.type, "env": [v.name for v in e.auth.env],
        "oauth": bool(e.auth.oauth),
        "headers": "${" in e.manifest_path.read_text(errors="replace"),
        "excluded": list(e.tools.default_excluded or []),
    })
print(json.dumps(out))
"""


def load_catalog(python: str, repo: Path, *, timeout: float = 60) -> list[CatalogApp]:
    off_loop("hermes apps catalog")
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [python, "-c", _DUMP],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=hermes_wait(timeout),
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/")},
        check=False,
    )
    hermes_contract.ran(done)
    if done.returncode != 0:
        raise AppError("Hermes's app catalog couldn't be read.")
    return parse_catalog(json.loads(done.stdout.strip().splitlines()[-1]))


def parse_catalog(rows: list[dict[str, Any]]) -> list[CatalogApp]:
    apps = []
    for row in rows:
        name = str(row.get("name") or "")
        if not APP_NAME.fullmatch(name):
            continue
        url = str(row.get("url") or "")
        locked = None
        if row.get("transport") != "http" or not url.startswith("https://"):
            locked = "Runs on this computer or a local address; not available."
        elif "${" in url or row.get("env") or row.get("oauth") or row.get("headers"):
            locked = "Needs your own developer app or key for it; not available yet."
        elif row.get("auth") not in ("oauth", "none"):
            locked = "Uses a login type AGOS doesn't support yet."
        apps.append(
            CatalogApp(
                name=name,
                description=" ".join(str(row.get("description") or "").split())[:300],
                url=url,
                auth=str(row.get("auth") or "none"),
                source=str(row.get("source") or "")[:300],
                excluded_tools=[str(t)[:120] for t in row.get("excluded") or []][:100],
                locked=locked,
            )
        )
    return sorted(apps, key=lambda a: a.name)


# Apps AGOS adds beside Hermes's catalog. They are vendor-hosted HTTP MCP servers
# with standard OAuth (discovery + registration), so Hermes logs in and runs them
# exactly like a catalog app.
COMPOSIO = CatalogApp(
    name="composio",
    description=(
        "One login to Composio, then 1000+ apps through it (Gmail, Slack, GitHub, "
        "HubSpot…). The agent finds the tool it needs; the first time it uses an app, "
        "Composio gives a link to approve that app. App logins are kept by Composio."
    ),
    url="https://connect.composio.dev/mcp",
    auth="oauth",
    source="https://docs.composio.dev/docs/composio-connect",
)
AGOS_APPS: tuple[CatalogApp, ...] = (COMPOSIO,)


def server_name(app: str) -> str:
    if not APP_NAME.fullmatch(app):
        raise AppError("Unknown app.")
    return SERVER_PREFIX + app


def server_entry(app: CatalogApp, allowed_tools: list[str] | None = None) -> dict[str, Any]:
    """`mcp_servers.app-<name>` in a workspace profile."""
    entry: dict[str, Any] = {"url": app.url}
    if app.auth == "oauth":
        entry["auth"] = "oauth"
    if app.oauth_client is not None:
        entry["oauth"] = {"client_id": app.oauth_client[0], "client_secret": app.oauth_client[1]}
    if allowed_tools:
        entry["tools"] = {"include": sorted(allowed_tools)}
    elif app.excluded_tools:
        entry["tools"] = {"exclude": list(app.excluded_tools)}
    return entry


def tokens_dir(connectors_home: Path) -> Path:
    return connectors_home / "mcp-tokens"


# Hermes's MCP OAuth token file of a server, under the connectors home.
MCP_LOGIN_FILE = "mcp-tokens/{}.json"


def has_login(connectors_home: Path, app: str) -> bool:
    return (connectors_home / MCP_LOGIN_FILE.format(server_name(app))).is_file()


def forget_login(connectors_home: Path, app: str) -> None:
    folder = tokens_dir(connectors_home)
    for suffix in TOKEN_SUFFIXES:
        (folder / f"{server_name(app)}{suffix}").unlink(missing_ok=True)


def link_tokens(profile_home: Path, login_home: Path) -> None:
    """profile/mcp-tokens -> this workspace's login folder.

    Sign-ins the profile already kept in a real folder (a library MCP signed in
    before any app was on) move into that folder first: same workspace, so
    nothing is shared and nothing is lost. A file that exists on both sides
    keeps the login folder's copy and the profile's stays where it was.

    Stays AGOS's: Hermes keeps MCP sign-ins only in `HERMES_HOME/mcp-tokens/`,
    with no setting to point it elsewhere (tools/mcp_oauth.py `_get_token_dir`),
    so the link is how one workspace's profiles share one sign-in."""
    target = tokens_dir(login_home)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    link = profile_home / "mcp-tokens"
    if link.is_symlink():
        if link.readlink() == target:
            return
        link.unlink()
    elif link.is_dir():
        left = []
        for item in link.iterdir():
            if item.is_file() and not (target / item.name).exists():
                item.replace(target / item.name)
            else:
                left.append(item)
        if left:
            raise AppError("This workspace's agent has app logins that clash; not replaced.")
        link.rmdir()
    elif link.exists():
        raise AppError("Unexpected file where the app logins go.")
    link.symlink_to(target, target_is_directory=True)
