"""Keys for a workspace's own tools and scripts (Workspace → Settings → Keys).

Hermes holds everything; AGOS only shows and controls it:

- The key itself: one line of the workspace ROOT's `.env`, written and removed by
  Hermes's own .env writer (H: hermes_cli/config.py `save_env_value` /
  `remove_env_value`), run in Hermes's runtime with HERMES_HOME = that root. The key
  travels on stdin only (never argv, never a log line, never an answer).
- Who gets it: its NAME in the root's `terminal.env_passthrough` (config.yaml,
  written with `hermes config set`). Hermes's docker backend then injects the
  value into every sandbox command and execute_code run of that profile, resolved
  through the profile's own secret scope (H: tools/env_passthrough.py
  `_load_config_passthrough`, tools/environments/remote_common.py
  `resolve_passthrough_env`, tools/environments/docker.py
  `_profile_scoped_passthrough`). Scripts read it as `$NAME` / `os.environ`.
- Hermes refuses to pass its own credentials into a sandbox, whatever the list says
  (H: tools/env_passthrough.py `_is_hermes_provider_credential` over
  tools/environments/local_env_policy.py `_is_provider_env_blocklisted` /
  `_is_hermes_internal_secret`). A tools copy of such a key gets its own name
  (`TOOLS_<NAME>`), so it never overwrites the root's own provider key either.

The variable name comes from what the owner types (the app's name), decided from
Hermes's own data (`pick`): Hermes's env-var catalog (H: hermes_cli/config_defaults.py
OPTIONAL_ENV_VARS) when it knows a key of that app, else `<APP>_API_KEY`; a name
Hermes calls its own credential becomes `TOOLS_<name>`.

A running gateway keeps the passthrough list it read first (per home, never
re-read: `_config_passthrough`) and the .env values it loaded at start in its
environment (nothing re-reads them: `reload_env` is the CLI's /reload only), so a
change restarts the root's gateway (actions/tool_keys.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Hermes's key: the names its sandbox backends pass into commands and code.
PASSTHROUGH = "terminal.env_passthrough"
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
TOOLS_PREFIX = "TOOLS_"
APP_MAX = 60
KEY_MAX = 4000
# Names never written here whatever Hermes says: Hermes's own and AGOS's own.
RESERVED_PREFIXES = ("HERMES_", "AGOS_", "TERMINAL_", "API_SERVER_", "GATEWAY_")
# Only this many trailing characters are ever shown, and only of a long value.
SHOWN = 4
SHOWN_MIN_LEN = 12

# Cheap real checks for apps whose key can be tried without cost. `{key}` is put in
# by Hermes's runtime (the value never leaves it); the answer is only a status code.
PROBES: dict[str, dict[str, Any]] = {
    "PIXABAY_API_KEY": {
        "url": "https://pixabay.com/api/?key={key}&q=test&per_page=3",
        "ok": [200],
        "refused": [400, 401, 403],
    },
    "OPENROUTER_API_KEY": {
        "url": "https://openrouter.ai/api/v1/key",
        "header": ["Authorization", "Bearer {key}"],
        "ok": [200],
        "refused": [401, 403],
    },
}

# Run in Hermes's runtime (HERMES_HOME = the workspace root) by
# HermesEngine.tool_keys. Job on argv[1] (names only), the key on stdin. Prints one
# AGOS-TOOLKEYS line that never holds a value.
SCRIPT = r"""
import json, logging, re, sys
logging.disable(logging.CRITICAL)
job = json.loads(sys.argv[1])
secret = sys.stdin.read().strip()
NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
out = {}
try:
    from hermes_cli.config import (
        OPTIONAL_ENV_VARS, env_write_refusal, load_env, remove_env_value, save_env_value)
    from tools.environments.local_env_policy import (
        _is_hermes_internal_secret, _is_provider_env_blocklisted)

    def own(name):
        meta = OPTIONAL_ENV_VARS.get(name) or {}
        return bool(_is_hermes_internal_secret(name) or _is_provider_env_blocklisted(name)
                    or meta.get("category") in ("provider", "messaging", "setting"))

    do = job["do"]
    if do == "facts":
        slug = str(job["slug"])
        rows = []
        for name, meta in OPTIONAL_ENV_VARS.items():
            if name == slug + "_API_KEY" or name.startswith(slug + "_"):
                rows.append({"name": name, "category": str(meta.get("category") or ""),
                             "url": str(meta.get("url") or ""),
                             "secret": bool(meta.get("password")), "own": own(name)})
        names = set(job.get("names") or []) | {r["name"] for r in rows}
        names |= {"TOOLS_" + n for n in list(names) if not n.startswith("TOOLS_")}
        out = {"catalog": rows, "own": {n: own(n) for n in sorted(names) if NAME.match(n)}}
    elif do == "share":
        # A member profile gets its root's tool keys: values on stdin (a JSON
        # object), names to drop on argv. Each written by Hermes's own writer.
        values = json.loads(secret or "{}")
        have = load_env()
        put, dropped = [], []
        for name, value in sorted(values.items()):
            if not NAME.match(name) or own(name) or env_write_refusal(name, "set"):
                continue
            if (have.get(name) or "").strip() != str(value).strip():
                save_env_value(name, str(value))
            put.append(name)
        for name in job.get("drop") or []:
            if NAME.match(name) and not own(name) and name in have:
                if not env_write_refusal(name, "remove"):
                    remove_env_value(name)
                    dropped.append(name)
        now = load_env()
        out = {"put": [n for n in put if (now.get(n) or "").strip()], "dropped": dropped}
    else:
        name = str(job["name"])
        if not NAME.match(name):
            raise ValueError("bad name")
        if do == "save":
            if own(name):
                out = {"refused": "own"}
            elif env_write_refusal(name, "set"):
                out = {"refused": "managed"}
            elif not secret:
                out = {"refused": "empty"}
            else:
                save_env_value(name, secret)
                out = {"saved": bool((load_env().get(name) or "").strip())}
        elif do == "remove":
            if own(name):
                out = {"refused": "own"}
            elif env_write_refusal(name, "remove"):
                out = {"refused": "managed"}
            else:
                remove_env_value(name)
                out = {"removed": name not in load_env()}
        elif do == "test":
            from tools.env_passthrough import is_env_passthrough
            from tools.environments.remote_common import resolve_passthrough_env
            value = (load_env().get(name) or "").strip()
            passed, _unset = resolve_passthrough_env()
            out = {"present": bool(value), "listed": bool(is_env_passthrough(name)),
                   "passed": bool((passed.get(name) or "").strip()), "own": own(name)}
            probe = job.get("probe")
            if probe and value:
                import urllib.error, urllib.parse, urllib.request
                url = probe["url"].replace("{key}", urllib.parse.quote(value, safe=""))
                request = urllib.request.Request(url, headers={"User-Agent": "AGOS key check"})
                if probe.get("header"):
                    request.add_header(probe["header"][0], probe["header"][1].replace("{key}", value))
                try:
                    with urllib.request.urlopen(request, timeout=20) as answer:
                        out["status"] = int(answer.status)
                except urllib.error.HTTPError as error:
                    out["status"] = int(error.code)
                except Exception as error:
                    out["status"] = None
                    out["unreached"] = type(error).__name__
        else:
            raise ValueError("unknown job")
except Exception as error:
    out = {"error": type(error).__name__}
print("AGOS-TOOLKEYS " + json.dumps(out))
"""


class NameProblem(ValueError):
    """The app's name gives no variable name AGOS may write (said to the owner)."""


@dataclass(frozen=True)
class Picked:
    name: str  # the variable Hermes holds the key under
    url: str  # where to get a key (Hermes's catalog), "" when Hermes doesn't say
    hermes_own: bool  # the plain name is Hermes's own credential: a TOOLS_ copy


def slug(app: str) -> str:
    """The app's name as a variable stem: upper case, anything else → `_`."""
    return re.sub(r"[^A-Z0-9]+", "_", app.strip().upper()).strip("_")


def clean_app(app: str) -> str:
    text = " ".join(app.split())
    if not text:
        raise NameProblem("Type the app's name, for example Pixabay.")
    if len(text) > APP_MAX:
        raise NameProblem(f"Keep the app's name to {APP_MAX} characters.")
    if not slug(text) or not slug(text)[0].isalpha():
        raise NameProblem("Start the app's name with a letter, for example Pixabay.")
    return text


def candidates(app: str) -> list[str]:
    """The names Hermes is asked about for this app (besides its catalog's)."""
    base = f"{slug(app)}_API_KEY"
    return [base, TOOLS_PREFIX + base]


def pick(app: str, facts: dict[str, Any]) -> Picked:
    """The variable for this app's key, from Hermes's answer (`facts`: its catalog
    rows starting with the app's stem, and whether each name is its own credential).

    1. Hermes's catalog has a secret of exactly that app (`<APP>_API_KEY`, else the
       only secret named `<APP>_…KEY/TOKEN/SECRET`): that name, with its link.
    2. Else `<APP>_API_KEY`.
    3. A name Hermes calls its own credential becomes `TOOLS_<name>`."""
    stem = slug(app)
    rows = [r for r in facts.get("catalog") or [] if isinstance(r, dict)]
    own: dict[str, bool] = {str(k): bool(v) for k, v in (facts.get("own") or {}).items()}
    exact = [r for r in rows if r.get("name") == f"{stem}_API_KEY"]
    loose = [
        r
        for r in rows
        if r.get("secret")
        and str(r.get("name", "")).startswith(f"{stem}_")
        and str(r.get("name", "")).endswith(("_KEY", "_TOKEN", "_SECRET"))
    ]
    match = exact[0] if exact else (loose[0] if len(loose) == 1 else None)
    base = str(match["name"]) if match else f"{stem}_API_KEY"
    url = str(match.get("url") or "") if match else ""
    if not NAME.match(base):
        raise NameProblem("This app's name is too long for a key name: use a shorter one.")
    hermes_own = own.get(base, True)  # fail closed: Hermes didn't say
    name = TOOLS_PREFIX + base if hermes_own else base
    if not NAME.match(name) or own.get(name, True):
        raise NameProblem("Hermes keeps a key of this name for itself: it can't be added here.")
    return Picked(name, url, hermes_own)


def probe_for(name: str) -> dict[str, Any] | None:
    base = name[len(TOOLS_PREFIX) :] if name.startswith(TOOLS_PREFIX) else name
    return PROBES.get(base)


def shown_end(value: str) -> str:
    """The last characters of a value, only when that gives little away."""
    value = value.strip()
    return value[-SHOWN:] if len(value) >= SHOWN_MIN_LEN else ""


def passthrough(config: dict[str, Any]) -> list[str]:
    """The names in a profile's `terminal.env_passthrough` (Hermes reads a list;
    anything else is no list)."""
    from agos_core.engine import config_file

    found = config_file.string_list(config_file.get(config, PASSTHROUGH))
    return [n.strip() for n in found or [] if isinstance(n, str) and n.strip()]
