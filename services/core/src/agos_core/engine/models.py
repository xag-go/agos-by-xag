"""What models the owner can pick, read from Hermes (never a hard-coded list).

Hermes already knows which providers are logged in (subscriptions and keys, in
its root auth store) and their live model lists. agos-core asks it through the
Hermes venv, caches the answer a few minutes, and maps it to AGOS's catalog.
No secret ever leaves Hermes: only provider slugs, model ids and the kind of
credential (subscription or API key).
"""

import hashlib
import json
import logging
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import agos_core.engine.hermes as _hermes_engine
from agos_core.config import EngineConfig
from agos_core.domain.models import ModelSelection
from agos_core.engine import hermes_contract, read_cache
from agos_core.engine.loop_guard import off_loop
from agos_core.engine.waits import hermes_wait

Mode = Literal["cli", "api"]

# AGOS's stored provider id per Hermes slug (the reverse is hermes_slug). These ids
# are what chats, cards, automations and workspace defaults store in their
# ModelSelection (`provider` + `mode`, "cli" = subscription), so they never follow a
# Hermes rename: Claude is Hermes's `anthropic`, OpenAI is two Hermes providers
# (`openai-codex` subscription, `openai-api` key). Every other Hermes provider is
# stored under its own Hermes slug.
AGOS_ID: dict[str, str] = {
    "anthropic": "claude",
    "openai-codex": "openai",
    "openai-api": "openai",
    "copilot": "copilot",
    "gemini": "gemini",
    "openrouter": "openrouter",
}
# Names only for the ids that are not one Hermes provider under its own slug (the
# owner's words for AGOS's merged rows); the rest show Hermes's own provider name
# (its picker's `name`, H: hermes_cli/inventory.py build_model_options_payload).
LABEL: dict[str, str] = {
    "claude": "Claude",
    "openai": "OpenAI",
}
# Shown in Settings even when not connected (so the owner sees where to connect):
# AGOS's stored ids above, in that order; Hermes's other providers come from its list.
ALWAYS_LISTED = tuple(dict.fromkeys(AGOS_ID.values()))
# A subscription Hermes signs in to with a token (its registry says api_key: a GitHub
# token, H: hermes_cli/auth.py PROVIDER_REGISTRY["copilot"]) and has no subscription
# mark for (H: agent/usage_pricing.py resolve_billing_route): AGOS's word for it.
# Every other provider's subscription-or-key comes from Hermes (mode_of).
SUBSCRIPTION_ONLY = {"copilot"}


def provider_name(agos: str, payload: dict[str, Any] | None = None) -> str:
    """The provider's name: AGOS's word for a merged row, else Hermes's own name."""
    if agos in LABEL:
        return LABEL[agos]
    for p in (payload or {}).get("providers", []):
        if str(p.get("slug") or "") == agos and p.get("name"):
            return str(p["name"])
    return agos


def is_sign_in(auth: str) -> bool:
    """A Hermes sign-in AGOS starts with `hermes auth add <slug>`: Hermes's own
    OAuth auth types (H: hermes_cli/auth.py ProviderConfig.auth_type oauth_device_code,
    oauth_external, oauth_minimax). Its other kinds (aws_sdk, vertex,
    external_process) need a cloud account file or an outside program."""
    return auth.startswith("oauth_")


# Subscriptions each workspace signs in to in its own Hermes root (ADR 0020): their
# refresh token is single-use, so Hermes keeps one login per home and never shares
# it between homes. These two stay General Settings' one login, as Hermes keeps
# them: Copilot is a GitHub token (Hermes's auth type api_key, H: hermes_cli/auth.py
# PROVIDER_REGISTRY["copilot"]), Nous lives in Hermes's own cross-profile store
# (H: hermes_cli/auth_nous.py:363 _nous_shared_store_path).
GENERAL_LOGINS = {"copilot", "nous"}
# Logins Hermes borrows from another program (Claude Code's file): not the root's own.
_BORROWED = {"claude_code"}


def per_workspace(slug: str, auth: str = "") -> bool:
    """A subscription each workspace signs in to on its own."""
    if slug in GENERAL_LOGINS:
        return False
    return slug in ("anthropic", "openai-codex") or is_sign_in(auth)


def own_logins(credentials: "list[Credential]") -> set[str]:
    """Slugs a home holds its own subscription login for (Hermes's pool)."""
    return {
        c.slug
        for c in credentials
        if c.kind == "oauth"
        and c.label not in _BORROWED
        and per_workspace(c.slug, "oauth_external")
    }


def extra_providers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Hermes's providers beyond the five AGOS always lists (one row per provider)."""
    seen: set[str] = set()
    out = []
    for p in payload.get("providers", []):
        slug = str(p.get("slug") or "")
        if not slug or slug in AGOS_ID or slug in seen:
            continue
        auth = str(p.get("auth") or "")
        key_env = str(p.get("keyEnv") or "")
        # Hermes's own auth type decides: a sign-in, or a key under its variable.
        # Anything else (a cloud account, an outside program, a hand-made endpoint
        # with no key variable) can't be connected from here.
        if not is_sign_in(auth) and not (auth == "api_key" and key_env):
            continue
        seen.add(slug)
        out.append({**p, "slug": slug, "auth": auth, "keyEnv": key_env})
    return out


# Hermes's own ladder order, and its "Disable reasoning" row ("none").
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
NO_CONTROL = ["standard"]  # the route takes no reasoning setting


def efforts_for(levels: Any) -> list[str]:
    """Hermes's levels for one model, in its order, plus "none"; or NO_CONTROL."""
    if not isinstance(levels, list) or not levels:
        return list(NO_CONTROL)
    names = list(dict.fromkeys(str(x).strip().lower() for x in levels if str(x).strip()))
    ordered = [e for e in EFFORT_ORDER if e in names] + [e for e in names if e not in EFFORT_ORDER]
    return [*ordered, "none"]


def default_effort(efforts: list[str], current: str) -> str:
    """Hermes's own choice: the configured level if this model has it, else medium."""
    if current in efforts:
        return current
    if "medium" in efforts:
        return "medium"
    return efforts[0]


# How Hermes got the login, in the owner's words (never the account secret).
_SOURCE = {
    "claude_code": "your Claude Code login",
    "device_code": "your ChatGPT account",
    "gh auth token": "your GitHub account (gh)",
    "COPILOT_GITHUB_TOKEN": "your GitHub account",
}

# Logins added from Settings (`hermes auth add <slug>`) are labelled `<slug>-oauth-N`.
_OAUTH_N = re.compile(r"-oauth-\d+$")
_OAUTH_LABEL = {
    "anthropic": "your Claude account",
    "openai-codex": "your ChatGPT account",
    "copilot": "your GitHub account",
}


_SCRIPT = """
import json, sys
from hermes_cli.auth import PROVIDER_REGISTRY
from hermes_cli.inventory import build_model_options_payload, load_picker_context
from hermes_cli.main_provider_setup import _main_model_reasoning_efforts
from hermes_cli.config import load_config
from hermes_cli.setup import _current_reasoning_effort
# refresh=1 asks each provider live (e.g. account-gated models such as GPT-6 Astra
# only appear after a live, account-scoped discovery); 0 reads the engine's cache.
p = build_model_options_payload(load_picker_context(), include_unconfigured=True,
                                refresh=sys.argv[1:] == ["1"])
def efforts(slug, model):
    # The same levels `hermes model` offers for this model (None = no control).
    try:
        return _main_model_reasoning_efforts(model, slug)
    except Exception:
        return None
out = []
for x in p.get("providers", []):
    ids = [m if isinstance(m, str) else m.get("id") for m in x.get("models") or []]
    ok = bool(x.get("authenticated"))
    # the engine's auth type: the picker's (unconnected rows), else its provider registry's.
    reg = PROVIDER_REGISTRY.get(x.get("slug") or "")
    out.append({"slug": x.get("slug"), "name": x.get("name"), "authenticated": ok, "models": ids,
                "auth": x.get("auth_type") or getattr(reg, "auth_type", "") or "",
                "keyEnv": x.get("key_env") or "",
                "efforts": {m: efforts(x.get("slug"), m) for m in ids if m} if ok else {}})
try:
    current = _current_reasoning_effort(load_config())
except Exception:
    current = ""
# the engine's own key variables of each provider, in its order (its registry; a provider
# with no registry row, OpenRouter, by its name in the engine's list of known keys).
from hermes_cli.config import OPTIONAL_ENV_VARS
def key_envs(slug):
    cfg = PROVIDER_REGISTRY.get(slug)
    found = list(getattr(cfg, "api_key_env_vars", None) or ())
    guess = slug.upper().replace("-", "_") + "_API_KEY"
    return found or ([guess] if guess in OPTIONAL_ENV_VARS else [])
slugs = {"anthropic", "openai-api", "gemini", "openrouter"} | {str(x["slug"]) for x in out if x["slug"]}
json.dump({"providers": out, "currentEffort": current,
           "keyEnvs": {s: key_envs(s) for s in sorted(slugs)}}, sys.stdout)
"""


@dataclass(frozen=True)
class Credential:
    slug: str
    label: str  # e.g. "claude_code", "gh auth token" — never the secret
    kind: Literal["oauth", "api_key"]


def pool_credentials(found: dict[str, Any]) -> list[Credential]:
    """Hermes's credential pool (its dashboard's redacted list_credential_pool, the
    pool `hermes auth list` prints: engine/hermes.py _POOL) → which credentials exist
    (labels and kinds only)."""
    out: list[Credential] = []
    for p in (found.get("pool") or {}).get("providers") or []:
        slug = str(p.get("provider") or "")
        for e in p.get("entries") or []:
            kind = str(e.get("auth_type") or "")
            if slug and kind in ("oauth", "api_key"):
                out.append(Credential(slug, str(e.get("label") or ""), kind))  # type: ignore[arg-type]
    return out


def mode_of(slug: str, credentials: list[Credential], auth: str = "") -> Mode:
    """Subscription ("cli") or key ("api"), as Hermes has it: its registry's auth type
    (`auth`: a sign-in is a subscription), else the kind of the login its credential
    pool holds (oauth or api_key)."""
    if slug in SUBSCRIPTION_ONLY or is_sign_in(auth):
        return "cli"
    kinds = {c.kind for c in credentials if c.slug == slug}
    return "cli" if "oauth" in kinds else "api"


def slug_mode(slug: str, *, keyed: bool = False) -> Mode:
    """The mode of a Hermes provider named in a config (no login to look at). The
    reverse of hermes_slug.

    - `keyed`: the route carries its own API key (a fallback entry's api_key /
      key_env, H: hermes_cli/fallback_config.py:38-53): Hermes calls with that key,
      so it is an API key, also for `anthropic` (Hermes takes literal Anthropic
      keys, H: hermes_cli/auth.py:208-214).
    - A slug whose subscription and key are different Hermes providers says it
      itself (openai-codex vs openai-api); Copilot is AGOS's subscription word.
    - `anthropic` is one Hermes provider for both. With no key on the route Hermes
      picks the home's credential at run time (H: agent/anthropic_credentials.py:700-718:
      ANTHROPIC_TOKEN, then ANTHROPIC_API_KEY, then its Claude login); the route
      alone doesn't say which, so it is shown as the subscription each workspace
      signs in to."""
    if keyed:
        return "api"
    agos = AGOS_ID.get(slug, slug)
    if slug in SUBSCRIPTION_ONLY or hermes_slug(agos, "cli") == slug != hermes_slug(agos, "api"):
        return "cli"
    return "cli" if agos == "claude" else "api"


def hermes_slug(provider: str, mode: str) -> str:
    """The Hermes provider for a task's AGOS provider + mode."""
    if provider == "claude":
        return "anthropic"
    if provider == "openai":
        return "openai-codex" if mode == "cli" else "openai-api"
    return provider


def _label(model_id: str) -> str:
    """claude-opus-5-5 → Claude Opus 5.5; gpt-5.4-mini → GPT 5.4 Mini."""
    words: list[str] = []
    for word in re.sub(r"-(\d{8})$", "", model_id).split("-"):
        if word.isdigit() and words and re.fullmatch(r"[\d.]+", words[-1]):
            words[-1] += f".{word}"
        else:
            words.append(word)
    return " ".join(w.upper() if w == "gpt" else w[:1].upper() + w[1:] for w in words)


def to_catalog(payload: dict[str, Any], credentials: list[Credential]) -> list[dict[str, Any]]:
    """Hermes model options → AGOS CatalogProvider[] (only logged-in providers)."""
    by_id: dict[str, dict[str, Any]] = {}
    for p in payload.get("providers", []):
        slug = str(p.get("slug") or "")
        extra = slug in {str(x["slug"]) for x in extra_providers(payload)}
        agos = AGOS_ID.get(slug) or (slug if extra else None)
        if not agos or not p.get("authenticated") or not p.get("models"):
            continue
        mode: Mode = "api" if extra else mode_of(slug, credentials, str(p.get("auth") or ""))
        label = LABEL.get(agos) or str(p.get("name") or slug)  # else Hermes's own name
        entry = by_id.setdefault(agos, {"id": agos, "label": label, "models": []})
        known = {m["id"]: m for m in entry["models"]}
        levels = p.get("efforts") or {}
        current = str(payload.get("currentEffort") or "").strip().lower()
        for model in p["models"]:
            if not isinstance(model, str) or not model:
                continue
            if model in known:
                if mode not in known[model]["modes"]:
                    known[model]["modes"].append(mode)
                continue
            efforts = efforts_for(levels.get(model))
            item = {
                "id": model,
                "label": _label(model),
                "modes": [mode],
                "efforts": efforts,
                "defaultEffort": default_effort(efforts, current),
            }
            entry["models"].append(item)
            known[model] = item
    return list(by_id.values())


def to_connections(
    payload: dict[str, Any],
    credentials: list[Credential],
    workspaces: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """What Settings → Models shows: which providers are connected, and how.

    `workspaces`: each workspace root's own subscription logins
    ({"id", "name", "logins": [slug]}); a per-workspace subscription is shown as
    connected in N of them, never from the shared home."""
    authed = {str(p.get("slug")) for p in payload.get("providers", []) if p.get("authenticated")}
    key_envs = payload.get("keyEnvs") or {}
    rows: dict[str, dict[str, Any]] = {
        agos: {
            "id": agos,
            "name": provider_name(agos, payload),
            "cli": {
                "tool": "AGOS",
                "installed": agos not in ("gemini", "openrouter"),
                "account": None,
                "loginCommand": f"hermes auth add {hermes_slug(agos, 'cli')}",
            },
            "api": None,
            "apiKey": agos != "copilot",
            # Hermes's own key variables for this provider (its registry, in its order).
            "keyEnvs": list(key_envs.get(hermes_slug(agos, "api")) or []),
        }
        for agos in ALWAYS_LISTED
    }
    for c in credentials:
        agos = AGOS_ID.get(c.slug)
        if not agos or c.slug not in authed:
            continue
        # Per login, not per provider: Claude can have a subscription AND a key.
        if c.kind == "oauth" or c.slug in SUBSCRIPTION_ONLY:
            rows[agos]["cli"]["account"] = _SOURCE.get(c.label) or _OAUTH_LABEL.get(
                c.slug if _OAUTH_N.search(c.label) else "", c.label.replace("_", " ")
            )
        else:
            rows[agos]["api"] = {"last4": "", "status": "", "statusAt": "", "problem": ""}
    for p in extra_providers(payload):
        sign_in = is_sign_in(p["auth"])
        on = bool(p.get("authenticated"))
        rows[p["slug"]] = {
            "id": p["slug"],
            "name": str(p.get("name") or p["slug"]),
            "cli": {
                "tool": "AGOS",
                "installed": sign_in,
                "account": "your account" if sign_in and on else None,
                "loginCommand": f"hermes auth add {p['slug']}",
            },
            "api": {"last4": "", "status": "", "statusAt": "", "problem": ""}
            if on and not sign_in
            else None,
            "apiKey": not sign_in,
            "keyEnv": p["keyEnv"] or None,
            "keyEnvs": list(key_envs.get(p["slug"]) or ([p["keyEnv"]] if p["keyEnv"] else [])),
            "more": True,
        }
    if workspaces is not None:
        slug_of_row = {"claude": "anthropic", "openai": "openai-codex"}
        for row_id, row in rows.items():
            slug = slug_of_row.get(row_id, row_id)
            sign_in = row_id in slug_of_row or bool(row.get("more") and row["cli"]["installed"])
            if not sign_in or not per_workspace(slug, "oauth_external"):
                continue
            states = [
                {"id": w["id"], "name": w["name"], "connected": slug in w["logins"]}
                for w in workspaces
            ]
            done = sum(1 for w in states if w["connected"])
            row["workspaces"] = states
            row["perWorkspace"] = True
            row["cli"]["account"] = f"{done} of {len(states)} workspaces" if done else None
    return list(rows.values())


def hermes_python(engine: EngineConfig) -> str:
    """A Python that imports Hermes and its dependencies, for the small
    `python -c ...` / `python script.py` probes AGOS runs.

    It is Hermes's own runtime command (`hermes --print-runtime-command --module X`,
    H: hermes_cli/_launchers.py print_runtime_command / runtime_command: its store
    Python, `-I`, and its bootstrap: env scrub, its checkout on sys.path, the home
    pin, `import hermes_bootstrap`), used as it is; only its last step, running
    module X, becomes running AGOS's `-c` code or script. AGOS keeps no bootstrap of
    its own and reads nothing out of Hermes's text."""
    launcher = _runtime_launcher(engine.hermes_bin)
    if launcher is None:
        # No Hermes there, or one that can't say (callers treat it as "not available").
        raise FileNotFoundError(f"{engine.hermes_bin} gave no runtime command")
    return launcher


def hermes_runtime_argv(engine: EngineConfig) -> list[str]:
    """The same Python as hermes_python, as Hermes's own runtime command itself
    (its store Python, `-I`, its bootstrap) instead of AGOS's launcher file. For a
    run behind a root's Landlock wall (engine/wall.py): the wall opens Hermes's
    install and runtime, never AGOS's cache, so a launcher file there can't start
    walled (EACCES on exec); Hermes's own command can."""
    argv = _runtime_argv(engine.hermes_bin)
    if argv is None:
        raise FileNotFoundError(f"{engine.hermes_bin} gave no runtime command")
    return list(argv)


_LAUNCHERS: dict[str, str] = {}
_ARGVS: dict[str, list[str]] = {}
# What runs in place of Hermes's `runpy.run_module(X)`: the probe's own `-c` code or
# script, with the arguments after it.
_DISPATCH = (
    "import os, sys, runpy\n"
    "a = sys.argv[1:]\n"
    "if a[:1] == ['-c']:\n"
    "    sys.argv = ['-c', *a[2:]]\n"
    "    exec(compile(a[1], '<string>', 'exec'), {'__name__': '__main__'})\n"
    "else:\n"
    "    sys.argv = a\n"
    "    sys.path.insert(0, os.path.dirname(os.path.abspath(a[0])))\n"
    "    runpy.run_path(a[0], run_name='__main__')\n"
)


def _runtime_argv(hermes_bin: str) -> list[str] | None:
    """Hermes's runtime command, with AGOS's `-c`/script dispatch as its last step."""
    from agos_core.engine.hermes import JUDGE_MODULE, JUDGE_RUN

    if hermes_bin in _ARGVS:
        return _ARGVS[hermes_bin]
    try:
        off_loop("hermes --print-runtime-command")
        done = subprocess.run(  # noqa: S603 - the configured hermes binary
            [hermes_bin, "--print-runtime-command", "--module", JUDGE_MODULE],
            capture_output=True,
            text=True,
            timeout=hermes_wait(30),
            check=False,
        )
        argv = json.loads(done.stdout.strip().splitlines()[-1]) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        argv = None
    if (
        not isinstance(argv, list)
        or len(argv) < 3
        or not all(isinstance(a, str) for a in argv)
        or JUDGE_RUN not in argv[-1]
        or not Path(argv[0]).exists()
    ):
        return None
    argv = [*argv[:-1], argv[-1].replace(JUDGE_RUN, f"exec({_DISPATCH!r})")]
    _ARGVS[hermes_bin] = argv
    return argv


def _runtime_launcher(hermes_bin: str) -> str | None:
    if hermes_bin in _LAUNCHERS:
        return _LAUNCHERS[hermes_bin]
    argv = _runtime_argv(hermes_bin)
    if argv is None:
        return None
    # One launcher per install: two Hermes installs on one machine (an upgrade
    # tried next to the running one) never rewrite each other's.
    install = hashlib.sha256("\0".join(argv).encode()).hexdigest()[:12]
    home = Path.home() / ".cache" / "agos" / "hermes-python" / install / "bin"
    home.mkdir(parents=True, exist_ok=True)
    path = home / "python"
    body = "#!/bin/sh\nexec " + " ".join(shlex.quote(a) for a in argv) + ' "$@"\n'
    if not path.exists() or path.read_text() != body:
        path.write_text(body)
        path.chmod(0o755)
    _LAUNCHERS[hermes_bin] = str(path)
    return str(path)


_REPOS: dict[str, Path | None] = {}


def hermes_repo(engine: EngineConfig) -> Path | None:
    """The Hermes checkout (catalogs like optional-mcps live there), as Hermes's own
    runtime has it on its path (where its `hermes_constants` module is)."""
    if engine.hermes_bin in _REPOS:
        return _REPOS[engine.hermes_bin]
    code = "import os, hermes_constants; print(os.path.dirname(os.path.abspath(hermes_constants.__file__)))"
    try:
        off_loop("hermes repo")
        done = subprocess.run(  # noqa: S603 - Hermes's own runtime
            [hermes_python(engine), "-c", code],
            capture_output=True,
            text=True,
            timeout=hermes_wait(60),
            env=_hermes_engine.with_runtime(
                {"HOME": str(engine.host_home), "PATH": "/usr/bin:/bin:/usr/local/bin"}
            ),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = done.stdout.strip().splitlines() if done.returncode == 0 else []
    found = Path(lines[-1]) if lines and Path(lines[-1]).is_dir() else None
    _REPOS[engine.hermes_bin] = found
    return found


log = logging.getLogger(__name__)

# The shared home's files Hermes's model picker reads (load_picker_context and
# build_model_options_payload: its config, keys, logins and its providers' model
# lists it keeps); a change there is asked again behind the next page.
_CATALOG_FILES = (
    "config.yaml",
    ".env",
    "auth.json",
    "models_dev_cache.json",
    "provider_models_cache.json",
)


@dataclass
class ModelCatalog:
    """Cached view of Hermes's providers and models.

    The shared home (General Settings) answers for keys and its own logins. A
    subscription each workspace signs in to on its own (`per_workspace`) is read
    from the workspaces' roots: Hermes's credential pool in each, and the model list from
    one root that is signed in."""

    engine: EngineConfig
    ttl_s: float = 300
    # (workspace id, name, root) of every workspace on a Hermes root of its own.
    roots: Callable[[], list[tuple[str, str, Path]]] | None = None
    _at: float = 0
    _value: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # What Hermes's answer was read from (`_stamp`, taken before the read), and the
    # one ask behind the pages (`_behind`): never two, and none for 20 s after one
    # failed (a broken Hermes is not started again on every page).
    _seen: tuple[Any, ...] = ()
    _asking: bool = False
    _retry_at: float = 0
    _ask_lock: threading.Lock = field(default_factory=threading.Lock)

    def _python(self) -> str:
        return hermes_python(self.engine)

    def _run(self, args: list[str], timeout: float, home: Path | None = None) -> str:
        env = {"HOME": str(self.engine.host_home), "PATH": "/usr/bin:/bin:/usr/local/bin"}
        if home is not None:
            env["HERMES_HOME"] = str(home)
        off_loop("hermes models")
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            args,
            capture_output=True,
            text=True,
            timeout=hermes_wait(timeout),
            env=_hermes_engine.with_runtime(env),
            check=False,
        )
        hermes_contract.ran(result)
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-1:] or [""]
            raise RuntimeError(f"{Path(args[0]).name} exited {result.returncode}: {tail[0][:200]}")
        return result.stdout

    def pool(self, home: Path | None = None) -> list[Credential]:
        """The credentials Hermes's pool holds in this home (the shared one when
        None): its own redacted list (engine/hermes.py _POOL), not a parse of
        `hermes auth list`'s printed table."""
        from agos_core.engine.hermes import _POOL

        script = _POOL.replace("@JOB@", repr(json.dumps({"do": "list"})))
        out = self._run([self._python(), "-c", script], 60, home)
        lines = [ln for ln in out.splitlines() if ln.startswith("AGOS-POOL ")]
        if not lines:
            raise RuntimeError("The engine didn't list its credential pool")
        found = json.loads(lines[-1][len("AGOS-POOL ") :])
        if found.get("error"):
            raise RuntimeError(str(found["error"])[:200])
        return pool_credentials(found)

    def root_logins(self, root: Path) -> set[str]:
        """The subscriptions one root holds its own login for (Hermes's pool there)."""
        return own_logins(self.pool(root))

    def _workspaces(self) -> list[dict[str, Any]]:
        listed = self.roots() if self.roots is not None else []

        def one(item: tuple[str, str, Path]) -> dict[str, Any]:
            ws, name, root = item
            try:
                logins = sorted(self.root_logins(root))
            except (OSError, RuntimeError, subprocess.SubprocessError):
                logins = []
            return {"id": ws, "name": name, "root": root, "logins": logins}

        if not listed:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(listed))) as pool:
            return list(pool.map(one, listed))

    def _with_workspace_logins(
        self, payload: dict[str, Any], pool: list[Credential], workspaces: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[Credential]]:
        """A per-workspace subscription counts as connected (and lists its models)
        when at least one workspace root is signed in to it; never through the
        shared home's own or borrowed login."""
        providers = list(payload.get("providers", []))
        creds = [
            c for c in pool if not (c.kind == "oauth" and per_workspace(c.slug, "oauth_external"))
        ]
        for i, p in enumerate(providers):
            slug = str(p.get("slug") or "")
            if not per_workspace(slug, str(p.get("auth") or "")) or slug == "openai-api":
                continue
            signed = next((w for w in workspaces if slug in w["logins"]), None)
            keyed = any(c.slug == slug and c.kind == "api_key" for c in pool)
            if signed is None:
                if not keyed:
                    providers[i] = {**p, "authenticated": False, "models": [], "efforts": {}}
                continue
            creds.append(Credential(slug, "workspace", "oauth"))
            if p.get("authenticated") and p.get("models"):
                continue
            try:
                theirs = json.loads(
                    self._run([self._python(), "-c", _SCRIPT, "0"], 120, signed["root"])
                )
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
                continue
            found = next((x for x in theirs.get("providers", []) if x.get("slug") == slug), None)
            if found:
                providers[i] = found
        return {**payload, "providers": providers}, creds

    def _stamp(self) -> tuple[Any, ...]:
        """What Hermes reads for the catalog, as it is now: the shared home's config,
        keys, logins and model lists, and each workspace root's logins (its own
        pool) and name (shown with them)."""
        home = self.engine.hermes_home
        listed = self.roots() if self.roots is not None else []
        return (
            read_cache.file_stamp(*(home / name for name in _CATALOG_FILES)),
            tuple(
                (ws, name, str(root), read_cache.file_stamp(root / "auth.json"))
                for ws, name, root in listed
            ),
        )

    def load(self, *, refresh: bool = False) -> dict[str, Any]:
        """Hermes's providers and models. `refresh` (the owner's action: a key
        saved, a login, a logout): Hermes is asked now, live. Otherwise the kept
        answer at once; once it is `ttl_s` old or a file Hermes reads for it
        changed (`_stamp`), Hermes is asked again behind the page (stale_ok: a
        model picker never waits ~1-3 s for Hermes's start once it answered)."""
        if not refresh and self._value:
            if time.monotonic() - self._at >= self.ttl_s or self._stamp() != self._seen:
                self._behind()
            return self._value
        with self._lock:
            if self._value and not refresh:
                return self._value  # read by the ask this one waited for
            return self._read(live=True)

    def kept(self) -> dict[str, Any] | None:
        """The answer already read, never a wait (a page view: None before the core's
        read-ahead or a picker read it once)."""
        return self.load() if self._value else None

    def _behind(self) -> None:
        with self._ask_lock:
            if self._asking or time.monotonic() < self._retry_at:
                return
            self._asking = True

        def run() -> None:
            try:
                with self._lock:
                    self._read(live=False)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                log.info("model catalog not read again from Hermes: %s", error)
                self._retry_at = time.monotonic() + 20
            finally:
                with self._ask_lock:
                    self._asking = False

        read_cache.submit(run)

    def _read(self, *, live: bool) -> dict[str, Any]:
        """Asks Hermes (called with `_lock` held). `live` asks each provider (its
        account-gated models); otherwise Hermes's own cache of their lists."""
        stamp = self._stamp()  # before the read: a change meanwhile is asked again
        payload = json.loads(
            self._run([self._python(), "-c", _SCRIPT, "1" if live else "0"], timeout=120)
        )
        pool = self.pool()
        workspaces = self._workspaces() if self.roots is not None else None
        if workspaces is not None:
            payload, pool = self._with_workspace_logins(payload, pool, workspaces)
        shown = (
            [{k: w[k] for k in ("id", "name", "logins")} for w in workspaces]
            if workspaces is not None
            else None
        )
        self._value = {
            "catalog": to_catalog(payload, pool),
            "providers": to_connections(payload, pool, shown),
        }
        self._at = time.monotonic()
        self._seen = stamp
        return self._value


def selection_from_hermes(slug: str, model: str, effort: str | None) -> "ModelSelection | None":
    """Hermes's provider slug, model and reasoning effort as AGOS's ModelSelection
    (the reverse of hermes_slug / hermes_model). None when Hermes has no model."""
    from agos_core.domain.models import ModelSelection

    if not slug or not model:
        return None
    provider = AGOS_ID.get(slug, slug)
    mode = slug_mode(slug)
    try:
        return ModelSelection.model_validate(
            {"provider": provider, "mode": mode, "model": model, "effort": effort or "medium"}
        )
    except ValueError:
        return None


def hermes_model(selection: "ModelSelection") -> dict[str, Any]:
    """`provider`, `model` and `model_options` for a Hermes run. The owner's choice is
    sent as is: Hermes never falls back to another model silently."""
    provider = hermes_slug(selection.provider, selection.mode)
    body: dict[str, Any] = {"provider": provider, "model": selection.model}
    if selection.effort not in ("standard", "default"):  # "none" = reasoning off
        body["model_options"] = {"reasoning_effort": selection.effort}
    return body
