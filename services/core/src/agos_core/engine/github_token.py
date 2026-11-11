"""The GitHub token Hermes's Skills Hub reads (Settings → Tools).

Hermes's hub reads GitHub's REST API: with no token GitHub allows 60 requests an
hour per server, and one skill install uses several, so a few installs in one hour
run out. Hermes has its own variable for this, `GITHUB_TOKEN` ("GitHub token for
Skills Hub" in hermes_cli/config_defaults.py), read from its `.env`.

Everything here is Hermes's own code run with Hermes's Python:
- save / remove: `hermes_cli.config.save_env_value` / `remove_env_value` (Hermes's
  .env lock); the token goes on stdin, never argv, never logged.
- status: `tools.skills_hub_github.GitHubAuth` + `GitHubSource` (the hub's own auth and
  GitHub client: which credential it picks, GitHub's limit for it, a refused token).

Only the two Hermes homes that run the library's hub commands get it: the shared
home (`hermes skills search/inspect`) and the library's own home (`install`,
`check`, `update`). Workspaces never do (general_sync skips GITHUB_* names), so
each stays closed off.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agos_core.config import EngineConfig
from agos_core.engine import hermes_contract
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.models import hermes_python
from agos_core.engine.waits import hermes_wait

NAME = "GITHUB_TOKEN"

_SAVE = """
import sys
from hermes_cli.config import save_env_value
token = sys.stdin.read().strip()
if not token:
    sys.exit(2)
save_env_value(sys.argv[1], token)
print("ok")
"""

_REMOVE = """
import sys
from hermes_cli.config import remove_env_value
remove_env_value(sys.argv[1])
print("ok")
"""

# What the hub's own auth says, through the hub's own GitHub client (GitHubSource:
# its auth headers, retries and its 401 handling that drops a refused token).
_STATUS = """
import json, sys
from hermes_cli.env_loader import load_hermes_dotenv
load_hermes_dotenv()  # what every `hermes skills ...` command loads first
from hermes_cli.config import get_env_value
out = {"saved": bool(get_env_value(sys.argv[1])), "method": "anonymous",
       "limit": None, "remaining": None, "reset": None, "rejected": False, "error": None}
try:
    from tools.skills_hub_github import GitHubAuth, GitHubSource
    auth = GitHubAuth()
    out["method"] = auth.auth_method()
    resp = GitHubSource(auth)._github_get("https://api.github.com/rate_limit", max_retries=1)
    out["rejected"] = bool(auth.rejected)
    out["method"] = auth.auth_method()
    if resp is None:
        out["error"] = "GitHub didn't answer."
    elif resp.status_code == 200:
        core = resp.json().get("resources", {}).get("core", {})
        out["limit"], out["remaining"], out["reset"] = (
            core.get("limit"), core.get("remaining"), core.get("reset"))
    else:
        out["error"] = f"GitHub answered {resp.status_code}."
except Exception as exc:
    out["error"] = type(exc).__name__
sys.stdout.write(json.dumps(out))
"""


class TokenProblem(ValueError):
    """Something the owner can fix (a wrong or refused token)."""


@dataclass(frozen=True)
class TokenStatus:
    saved: bool
    method: str  # Hermes's GitHubAuth: pat, gh-cli, github-app or anonymous
    limit: int | None
    remaining: int | None
    reset: int | None  # unix time the hour restarts
    rejected: bool
    error: str | None


def clean_token(token: str) -> str:
    token = token.strip()
    if not token or len(token) > 400 or not re.fullmatch(r"[A-Za-z0-9_\-]+", token):
        raise TokenProblem("Paste the token exactly as GitHub shows it, with no spaces.")
    return token


class GithubToken:
    def __init__(self, engine: EngineConfig, library_home: Path) -> None:
        self.engine = engine
        self.library_home = library_home

    def homes(self) -> list[Path]:
        """The shared home (search, inspect) and the library's own (install, update)."""
        return [self.engine.hermes_home, self.library_home]

    def _run(self, script: str, home: Path, stdin: str = "", timeout: float = 60) -> str:
        home.mkdir(parents=True, exist_ok=True)
        env = {
            "HOME": str(self.engine.host_home),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HERMES_HOME": str(home),
            **self.engine.runtime_env(),
        }
        off_loop("hermes github token")
        result = subprocess.run(  # noqa: S603 - fixed argv; the token goes on stdin
            [hermes_python(self.engine), "-c", script, NAME],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=env,
            check=False,
        )
        hermes_contract.ran(result)
        if result.returncode != 0:
            raise RuntimeError("The engine did not take the change.")
        return result.stdout

    def save(self, token: str) -> TokenStatus:
        """Saves it in both homes, then asks Hermes's hub auth whether GitHub takes
        it. A refused token is removed again, so a typo never shadows the 60/hour."""
        token = clean_token(token)
        for home in self.homes():
            self._run(_SAVE, home, stdin=token)
        status = self.status()
        if status.rejected:
            self.remove()
            raise TokenProblem("GitHub refused this token. Check it and paste it again.")
        return status

    def remove(self) -> None:
        for home in self.homes():
            self._run(_REMOVE, home)

    def status(self) -> TokenStatus:
        raw = self._run(_STATUS, self.library_home, timeout=40)
        data = json.loads(raw or "{}")
        return TokenStatus(
            saved=bool(data.get("saved")),
            method=str(data.get("method") or "anonymous"),
            limit=_int(data.get("limit")),
            remaining=_int(data.get("remaining")),
            reset=_int(data.get("reset")),
            rejected=bool(data.get("rejected")),
            error=str(data["error"]) if data.get("error") else None,
        )


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
