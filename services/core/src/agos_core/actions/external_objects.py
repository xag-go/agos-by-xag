"""Links to outside objects shown as live chips (Step 59, F58).

A card's text or a comment that links a GitHub pull request or issue, a Linear
issue or a Jira issue shows that link as a chip with the object's live title and
state (open / merged / closed / draft, the ticket's status). The state is read by
the core with the workspace's OWN keys (Settings → Keys: GITHUB_TOKEN, LINEAR_API_KEY,
JIRA_EMAIL + JIRA_API_TOKEN, each also under Hermes's TOOLS_ name; a public GitHub
repository needs none), kept a short while in memory, never written back. A link
AGOS doesn't know stays a plain link.
"""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agos_core.context import Core

log = logging.getLogger("agos.external_objects")

MAX_LINKS = 20
TTL_S = 120.0  # a state is this fresh at most
FAILED_TTL_S = 30.0
TIMEOUT_S = 4.0

GITHUB = re.compile(
    r"^https://github\.com/([\w.-]+)/([\w.-]+)/(pull|issues)/(\d{1,9})(?:[/?#].*)?$"
)
LINEAR = re.compile(r"^https://linear\.app/[\w-]+/issue/([A-Z][A-Z0-9]{0,9}-\d{1,9})(?:[/?#].*)?$")
JIRA = re.compile(
    r"^https://([a-z0-9][a-z0-9-]{0,62})\.atlassian\.net/browse/([A-Z][A-Z0-9_]{0,19}-\d{1,9})"
    r"(?:[/?#].*)?$"
)

KEY_NAMES = {
    "github": ("GITHUB_TOKEN", "GH_TOKEN"),
    "linear": ("LINEAR_API_KEY",),
    "jira_email": ("JIRA_EMAIL", "JIRA_USER_EMAIL"),
    "jira_token": ("JIRA_API_TOKEN", "JIRA_TOKEN"),
}

_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def _get_json(
    method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None = None
) -> tuple[int, Any]:
    """One HTTP call (tests replace it). (status, JSON or None)."""
    import httpx

    try:
        response = httpx.request(method, url, headers=headers, json=body, timeout=TIMEOUT_S)
    except httpx.HTTPError as error:
        log.info("external object %s: %s", url, type(error).__name__)
        return 0, None
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


def kind_of(url: str) -> tuple[str, tuple[str, ...]] | None:
    """(provider, its parts) of a link AGOS knows; None for any other link."""
    if m := GITHUB.match(url):
        return ("github_pr" if m.group(3) == "pull" else "github_issue"), m.groups()
    if m := LINEAR.match(url):
        return "linear", m.groups()
    if m := JIRA.match(url):
        return "jira", m.groups()
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _key(values: dict[str, str], what: str) -> str:
    for name in KEY_NAMES[what]:
        for candidate in (name, "TOOLS_" + name):
            if values.get(candidate, "").strip():
                return values[candidate].strip()
    return ""


def _github(parts: tuple[str, ...], pull: bool, keys: dict[str, str]) -> dict[str, Any]:
    owner, repo, _, number = parts
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "AGOS"}
    token = _key(keys, "github")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    path = "pulls" if pull else "issues"
    status, data = _get_json(
        "GET", f"https://api.github.com/repos/{owner}/{repo}/{path}/{number}", headers
    )
    if status != 200 or not isinstance(data, dict):
        return {"ok": False, "why": "private" if status in (401, 403, 404) else "unreached"}
    state = str(data.get("state") or "")
    if pull and data.get("merged_at"):
        state = "merged"
    elif pull and data.get("draft") and state == "open":
        state = "draft"
    elif not pull and state == "closed" and data.get("state_reason") == "not_planned":
        state = "not_planned"
    return {
        "ok": True,
        "key": f"{owner}/{repo}#{number}",
        "title": str(data.get("title") or "")[:200],
        "state": state,
        "stateLabel": state.replace("_", " "),
        "done": state in ("merged", "closed", "not_planned"),
    }


_LINEAR_QUERY = "query($id: String!) { issue(id: $id) { identifier title state { name type } } }"


def _linear(parts: tuple[str, ...], keys: dict[str, str]) -> dict[str, Any]:
    token = _key(keys, "linear")
    if not token:
        return {"ok": False, "key": parts[0], "why": "no_key"}
    status, data = _get_json(
        "POST",
        "https://api.linear.app/graphql",
        {"Authorization": token, "Content-Type": "application/json", "User-Agent": "AGOS"},
        {"query": _LINEAR_QUERY, "variables": {"id": parts[0]}},
    )
    issue = ((data or {}).get("data") or {}).get("issue") if isinstance(data, dict) else None
    if status != 200 or not isinstance(issue, dict):
        return {"ok": False, "key": parts[0], "why": "unreached"}
    state = _dict(issue.get("state"))
    kind = str(state.get("type") or "")
    return {
        "ok": True,
        "key": str(issue.get("identifier") or parts[0]),
        "title": str(issue.get("title") or "")[:200],
        "state": kind or "unknown",
        "stateLabel": str(state.get("name") or kind),
        "done": kind in ("completed", "canceled"),
    }


def _jira(parts: tuple[str, ...], keys: dict[str, str]) -> dict[str, Any]:
    site, issue_key = parts
    email, token = _key(keys, "jira_email"), _key(keys, "jira_token")
    if not (email and token):
        return {"ok": False, "key": issue_key, "why": "no_key"}
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    status, data = _get_json(
        "GET",
        f"https://{site}.atlassian.net/rest/api/3/issue/{issue_key}?fields=summary,status",
        {"Authorization": f"Basic {auth}", "Accept": "application/json", "User-Agent": "AGOS"},
    )
    fields = data.get("fields") if isinstance(data, dict) else None
    if status != 200 or not isinstance(fields, dict):
        return {
            "ok": False,
            "key": issue_key,
            "why": "private" if status in (401, 403, 404) else "unreached",
        }
    found = _dict(fields.get("status"))
    category = _dict(found.get("statusCategory"))
    bucket = str(category.get("key") or "")
    return {
        "ok": True,
        "key": issue_key,
        "title": str(fields.get("summary") or "")[:200],
        "state": {"new": "todo", "indeterminate": "in_progress", "done": "done"}.get(
            bucket, bucket
        ),
        "stateLabel": str(found.get("name") or bucket),
        "done": bucket == "done",
    }


def _resolve_one(url: str, keys: Callable[[], dict[str, str]]) -> dict[str, Any] | None:
    found = kind_of(url)
    if found is None:
        return None
    kind, parts = found
    if kind.startswith("github"):
        shown = _github(parts, kind == "github_pr", keys())
    elif kind == "linear":
        shown = _linear(parts, keys())
    else:
        shown = _jira(parts, keys())
    return {"url": url, "kind": kind, **shown}


def _workspace_keys(core: Core, workspace_id: str) -> dict[str, str]:
    from agos_core.actions import tool_keys

    if core.engine is None:
        return {}
    try:
        return tool_keys.root_values(core, workspace_id)
    except (OSError, ValueError) as error:
        log.info("workspace keys not read: %s", error)
        return {}


def resolve(core: Core, workspace_id: str, urls: list[str]) -> list[dict[str, Any]]:
    """The chips for these links (known kinds only, in the order given)."""
    wanted = list(dict.fromkeys(u.strip() for u in urls if u.strip()))[:MAX_LINKS]
    known = [u for u in wanted if kind_of(u) is not None]
    out: dict[str, dict[str, Any]] = {}
    at = time.monotonic()
    missing: list[str] = []
    with _lock:
        for url in known:
            held = _cache.get((workspace_id, url))
            if held is not None and held[0] > at:
                out[url] = held[1]
            else:
                missing.append(url)
    if missing:
        keys_once: dict[str, dict[str, str]] = {}

        def keys() -> dict[str, str]:
            if "k" not in keys_once:
                keys_once["k"] = _workspace_keys(core, workspace_id)
            return keys_once["k"]

        keys()  # read once, before the threads
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as pool:
            for url, shown in zip(
                missing, pool.map(lambda u: _resolve_one(u, keys), missing), strict=True
            ):
                if shown is None:
                    continue
                out[url] = shown
                with _lock:
                    ttl = TTL_S if shown.get("ok") else FAILED_TTL_S
                    _cache[(workspace_id, url)] = (time.monotonic() + ttl, shown)
                    if len(_cache) > 2000:
                        _cache.clear()
    return [out[u] for u in known if u in out]
