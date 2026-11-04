"""The owner's one Google login, for the Google MCP server Hermes runs.

Drive, Sheets and Docs are one open-source MCP server (workspace-mcp, see
actions/apps.py) run by each workspace's Hermes in that workspace's MCP container.
- The owner's OAuth client (a "Web application" made once in his Google Cloud
  project) is `<connectors home>/google/client.json`.
- Connect = the normal OAuth web flow (PKCE + state) back to AGOS's
  `/connectors/callback`; the login is `<connectors home>/google/token.json` (0600).
- The login goes into the MCP container only (never the agent's sandbox); the server
  refreshes it there. Disconnecting revokes it at Google.

Only the standard library is used (urllib), so nothing new is installed.

Why this is not Hermes's (checked in Hermes's source, Phase 7):
- `hermes mcp login` (tools/mcp_oauth*.py) signs Hermes itself in to a remote
  MCP server that speaks MCP OAuth 2.1: it discovers the authorization server from
  the server's protected-resource metadata, registers by CIMD or dynamic client
  registration, and keeps the token per home (`<root>/mcp-tokens/`), sent as a
  Bearer to that server. workspace-mcp here is not such a server: it holds the
  Google login itself (single-user credentials file) and calls Google with it;
  Google offers neither CIMD nor dynamic registration. Moving would mean running
  workspace-mcp in its OAuth 2.1 mode and one Google sign-in per workspace root
  instead of the owner's one login, and the live token wouldn't carry over.
- Hermes's google-workspace skill (`scripts/setup.py`) is a token for its own
  gws/google_api scripts (`<home>/google_token.json`, Gmail/Calendar scopes,
  copy-the-code-from-localhost:1 flow), not for this MCP server.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APP = "google"
TITLE = "Google (Drive, Docs, Sheets)"
DESCRIPTION = "Your Google Drive files, Google Docs and Google Sheets."
SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
TIMEOUT_S = 60


class GoogleError(ValueError):
    """The message is safe to show to the owner and to the agent."""


# ---- files ------------------------------------------------------------------------------


def folder(connectors_home: Path) -> Path:
    path = connectors_home / "google"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Client:
    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...]


def load_client(connectors_home: Path) -> Client | None:
    """The owner's OAuth client, or None when it isn't there (or isn't usable)."""
    try:
        data = json.loads((connectors_home / "google" / "client.json").read_text())
    except (OSError, ValueError):
        return None
    body = data.get("web") or data.get("installed") or {}
    client_id = str(body.get("client_id") or "")
    secret = str(body.get("client_secret") or "")
    if not client_id or not secret:
        return None
    uris = tuple(str(u) for u in body.get("redirect_uris") or [] if isinstance(u, str))
    return Client(client_id, secret, uris)


def _write_private(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(data, handle)
    tmp.chmod(0o600)
    tmp.replace(path)


def token_file(connectors_home: Path) -> Path:
    return folder(connectors_home) / "token.json"


def load_token(connectors_home: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(token_file(connectors_home).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("refresh_token") else None


def has_login(connectors_home: Path) -> bool:
    return load_token(connectors_home) is not None


def account(connectors_home: Path) -> str | None:
    token = load_token(connectors_home)
    return str(token.get("email") or "") or None if token else None


def forget(connectors_home: Path) -> None:
    """Deletes the login. Also asks Google to cancel it (best effort)."""
    token = load_token(connectors_home)
    if token:
        with contextlib.suppress(OSError, urllib.error.URLError, ValueError):
            _post_form(REVOKE_URL, {"token": str(token["refresh_token"])})
    token_file(connectors_home).unlink(missing_ok=True)


# ---- login ------------------------------------------------------------------------------


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def pick_redirect(client: Client, wanted: str) -> str:
    """Google only returns to an address saved in the client. Use the one AGOS
    is open on when it is saved there, else the first saved one."""
    if wanted in client.redirect_uris:
        return wanted
    for uri in client.redirect_uris:
        if uri.endswith("/connectors/callback"):
            return uri
    raise GoogleError("Add this address to the Google client's Authorized redirect URIs: " + wanted)


def login_url(client: Client, redirect_uri: str, state: str, challenge: str) -> str:
    query = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(query)


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - fixed https Google URLs
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            body: dict[str, Any] = json.loads(response.read() or b"{}")
            return body
    except urllib.error.HTTPError as error:
        try:
            detail = json.loads(error.read() or b"{}")
        except ValueError:
            detail = {}
        raise GoogleError(
            str(detail.get("error_description") or detail.get("error") or f"HTTP {error.code}")
        ) from error


def _email_from(id_token: str) -> str | None:
    """The id_token came straight from Google's token endpoint over TLS, so its
    payload is read without checking the signature (used only as a label)."""
    try:
        part = id_token.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    email = payload.get("email")
    return str(email) if email else None


def finish_login(
    connectors_home: Path, client: Client, code: str, redirect_uri: str, verifier: str
) -> dict[str, Any]:
    body = _post_form(
        TOKEN_URL,
        {
            "code": code,
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )
    if not body.get("refresh_token"):
        raise GoogleError("Google gave no lasting access; connect again.")
    granted = set(str(body.get("scope") or "").split())
    missing = [s.rsplit("/", 1)[-1] for s in SCOPES[2:] if s not in granted]
    if missing:
        raise GoogleError(
            "Google access was given without: "
            + ", ".join(missing)
            + ". Connect again and tick every box."
        )
    token = {
        "refresh_token": body["refresh_token"],
        "access_token": body.get("access_token"),
        "expires_at": time.time() + float(body.get("expires_in") or 0),
        "scope": body.get("scope"),
        "email": _email_from(str(body.get("id_token") or "")),
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_private(token_file(connectors_home), token)
    return token
