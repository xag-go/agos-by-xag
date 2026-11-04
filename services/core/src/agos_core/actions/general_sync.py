"""General Settings → every workspace's own Hermes root (ADR 0020).

Before 0020 every workspace was a profile of one Hermes home, and part of what the
owner sets once in General Settings reached them all by inheritance: the provider
API keys (OpenRouter, Gemini, …) in that home's `.env`, read by every profile, and
the login in its `auth.json`. A workspace on its own root inherits nothing from
that home, so AGOS writes the general values into each root and each member
profile under it, and again whenever one is created or migrated.

- API keys: the shared home stays the one place General Settings writes (the page
  reads it back from there), then `sync` copies each key into every root's and
  every member's Hermes with Hermes's own credential save
  (`save_provider_env_credential`: `.env`, the credential pool in `auth.json`,
  config.yaml copies of the old value). A key a workspace has of its own (a line AGOS never
  wrote there) is kept: per-workspace values win. A ledger in each home
  (`.agos-general.json`) remembers which lines are AGOS's copies, so a key the
  owner removes in General Settings is removed from every root too, and only
  AGOS's copies are ever touched.
- Why copies and not one Hermes secret source: Hermes can feed every profile from
  one store (`secrets.command`, Bitwarden, 1Password, with per-profile aliasing),
  but a running gateway pulls a source ONCE per home (hermes_cli/env_loader.py
  `_APPLIED_HOMES`, only cron fires re-pull), while it reads each profile's `.env`
  again for every turn (agent/secret_scope.py `build_profile_secret_scope`). With
  a source, every key the owner changes or removes would wait for a restart of
  every workspace's gateway, which AGOS never does under running work. Hermes's
  Managed Scope's `.env` doesn't fit keys either: its values beat a profile's own
  and can't be set per profile (H: agent/secret_scope.py managed `.env` applied
  last, hermes_cli/config.py `env_write_refusal`), while a workspace keeps a key
  of its own here (a line AGOS never wrote wins). So the key copies stay
  (proven against the installed Hermes: tests/test_secrets_command_once.py).
- Logins (OAuth subscriptions: Claude, ChatGPT, …): a refresh token is single-use
  and rotates, so Hermes keeps one login per home and never shares it between
  homes. Each root signs in on its own (the same account, Hermes's own
  `hermes auth add` run in that root by `engine/provider_login.py`); its members
  read the root's login (Hermes's profile fallback). General Settings → Models
  lists every workspace and walks through the ones not signed in yet. Once a root
  has its own login, Hermes stops borrowing Claude Code's file there
  (`auth.adopt_external_logins: false`, `own_logins_only`). AGOS never reads,
  moves or writes a token.
- The owner's timezone, fallback models, limits and time limits are ONE value
  for every workspace: Hermes's managed scope, one config.yaml every Hermes
  process AGOS runs reads (actions/hermes_managed.py). Only each profile's
  sandbox `TZ` is written here (owner_time.write_home).
- Everything else General Settings sets is written into every profile by its own
  code (owner rules, tool services, the Brain, the guard plugin), through
  `engine.profile_home`, which follows each workspace's layout.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agos_core.context import Core
from agos_core.engine.hermes import EngineError
from agos_core.engine.login_borrow import borrowing_needed as borrowing_needed
from agos_core.engine.login_borrow import hermes_logins as hermes_logins
from agos_core.engine.login_borrow import own_login as own_login

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger("agos.general_sync")

LEDGER = ".agos-general.json"
NAMES_SETTING = "general.env_names"  # extra key names saved from General Settings
# What a provider key looks like in Hermes's .env; never the channel, API-server,
# AGOS or webhook lines (those are each profile's own).
_KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,63}_(API_KEY|API_TOKEN|ACCESS_TOKEN|KEY|TOKEN)$")
# GITHUB_*: the Skills Hub token (Settings → Tools) is for the library's own Hermes
# homes only (engine/github_token.py); no workspace gets it.
_NOT_GENERAL = ("TELEGRAM_", "API_SERVER_", "AGOS_", "WEBHOOK_", "HERMES_", "MCP_", "GITHUB_")


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for line in path.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.lstrip().startswith("#"):
                out[name.strip()] = value.strip()
    return out


def managed_names(core: Core) -> list[str]:
    """The key names General Settings owns: the five providers', the ones saved for
    Hermes's other providers, and every provider key in the shared home's .env."""
    from agos_core.db.app_settings import get_setting

    # The five providers' keys are named by Hermes (its registry): every one General
    # Settings saved or removed is remembered (remember_name), the rest are in .env.
    names = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"}
    names |= {"OPENROUTER_API_KEY"}
    saved = get_setting(core.db, NAMES_SETTING, [])
    if isinstance(saved, list):
        names |= {str(n) for n in saved if _KEY_NAME.match(str(n))}
    if core.engine is not None:
        names |= {
            n
            for n in _read_env(core.engine.settings.hermes_home / ".env")
            if _KEY_NAME.match(n) and not n.startswith(_NOT_GENERAL)
        }
    return sorted(n for n in names if not n.startswith(_NOT_GENERAL))


def remember_name(core: Core, name: str) -> None:
    """A key saved in General Settings for one of Hermes's other providers."""
    from agos_core.db.app_settings import get_setting, set_setting

    if not _KEY_NAME.match(name):
        return
    saved = get_setting(core.db, NAMES_SETTING, [])
    names = {str(n) for n in saved} if isinstance(saved, list) else set()
    if name not in names:
        set_setting(core.db, NAMES_SETTING, sorted(names | {name}))


def general_values(core: Core) -> dict[str, str]:
    """The general keys as General Settings saved them (the shared home's .env)."""
    if core.engine is None:
        return {}
    env = _read_env(core.engine.settings.hermes_home / ".env")
    return {n: env[n] for n in managed_names(core) if env.get(n)}


def _ledger(home: Path) -> set[str]:
    try:
        data = json.loads((home / LEDGER).read_text())
    except (OSError, ValueError):
        return set()
    return {str(n) for n in data.get("env", [])} if isinstance(data, dict) else set()


def push_home(
    home: Path,
    values: dict[str, str],
    names: list[str],
    save: Callable[[Path, dict[str, str], list[str]], None],
) -> list[str]:
    """Writes the general keys into one home with Hermes's own credential save
    (`save`: engine.save_credentials, Hermes's credential_lifecycle: .env, the
    credential pool, config.yaml copies). A line the home has of its own (not in
    its ledger) wins and is left alone. Returns the names changed."""
    if not (home / "config.yaml").is_file():
        return []
    have = _read_env(home / ".env")
    mine = _ledger(home)
    changed: list[str] = []
    drop: list[str] = []
    put: dict[str, str] = {}
    for name in names:
        own = name in have and name not in mine  # the workspace's own value
        if own:
            continue
        value = values.get(name)
        if value is None:
            if name in mine:  # removed in General Settings: AGOS's copy goes
                if name in have:
                    drop.append(name)
                mine.discard(name)
                changed.append(name)
            continue
        if "\n" in value or "\r" in value:
            continue
        if have.get(name) != value:
            put[name] = value
            changed.append(name)
        mine.add(name)
    if drop or put:
        # The ledger only after Hermes took them: a failed save is tried again.
        save(home, put, drop)
    (home / LEDGER).write_text(json.dumps({"env": sorted(mine)}, sort_keys=True))
    with contextlib.suppress(OSError):
        (home / LEDGER).chmod(0o600)
    return changed


def homes(core: Core, workspace_id: str | None = None) -> list[tuple[str, Path]]:
    """(workspace, home) of every profile on a workspace's own root: the root (its
    Co-Founder) and each profile under it (members, team agents)."""
    engine = core.engine
    if engine is None:
        return []
    if workspace_id is not None:
        ids = [workspace_id]
    else:
        ids = [str(r["id"]) for r in core.db.execute("SELECT id FROM workspaces")]
    out: list[tuple[str, Path]] = []
    for ws in ids:
        for name in engine.own_profiles(ws):
            home = engine.home_of(name)
            if home is not None and (home / "config.yaml").is_file():
                out.append((ws, home))
    return out


def sync(core: Core, workspace_id: str | None = None) -> dict[str, Any]:
    """Every root (or one workspace's) gets General Settings' keys. Safe to repeat."""
    values = general_values(core)
    names = managed_names(core)
    zone = _zone(core)
    report: dict[str, Any] = {"homes": 0, "changed": {}}
    save = _saver(core)

    def one(target: tuple[str, Path]) -> list[str] | None:
        ws, home = target
        try:
            changed = push_home(home, values, names, save)
            if _push_zone(core, home, zone):
                changed.append("timezone")
        except (OSError, EngineError) as error:
            log.warning("general settings not written into %s: %s", home, error)
            return None
        if changed:
            log.info("general settings → %s (%s): %s", ws, home.name, ", ".join(changed))
        return changed

    # Every home side by side, up to 4 at once (each its own write lock; one after
    # another was a Hermes start per home, 16 live, on every key save).
    targets = list(homes(core, workspace_id))
    if targets:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
            results = list(pool.map(one, targets))
        for (_ws, home), changed in zip(targets, results, strict=True):
            if changed is None:
                continue
            report["homes"] += 1
            if changed:
                report["changed"][str(home)] = changed
    return report


def sync_home(core: Core, home: Path) -> list[str]:
    """One new (or migrated) home gets them at once."""
    try:
        changed = push_home(home, general_values(core), managed_names(core), _saver(core))
    except EngineError as error:
        log.warning("general keys not written into %s: %s", home, error)
        changed = []
    if _push_zone(core, home, _zone(core)):
        changed.append("timezone")
    return changed


def _saver(core: Core) -> Callable[[Path, dict[str, str], list[str]], None]:
    """Hermes's own credential save in a home (engine.save_credentials)."""
    engine = core.engine

    def save(home: Path, values: dict[str, str], drop: list[str]) -> None:
        if engine is None:
            raise EngineError("the agent engine is off")
        engine.save_credentials(home, values, drop)

    return save


def _zone(core: Core) -> str:
    """The owner's timezone as General Settings saved it (Hermes's managed scope)."""
    from agos_core.actions import owner_time

    return owner_time.owner_zone(core)


def _push_zone(core: Core, home: Path, zone: str) -> bool:
    """The owner's timezone into one workspace profile's sandbox (`TZ`); Hermes's
    own `timezone` is the managed scope's, read by every home."""
    from agos_core.actions import owner_time
    from agos_core.engine.hermes import EngineError

    if not zone:
        return False
    try:
        return owner_time.write_home(core, home, zone)
    except EngineError as error:
        log.warning("sandbox timezone not written into %s: %s", home, error)
        return False


# ---- logins: each root signs in on its own ----------------------------------------


def pools(core: Core, homes: list[Path]) -> list[list[dict[str, Any]]]:
    """Each home's credential pool entries as Hermes read them (in parallel; a home
    Hermes couldn't read gives none)."""
    from concurrent.futures import ThreadPoolExecutor

    engine = core.engine
    if engine is None or not homes:
        return []

    def one(home: Path) -> list[dict[str, Any]]:
        found = hermes_logins(engine, home)
        return list((found or {}).get("pool") or [])

    with ThreadPoolExecutor(max_workers=min(4, len(homes))) as pool:
        return list(pool.map(one, homes))


def own_logins_only(core: Core, workspace_id: str) -> None:
    """The root (and every member under it) uses only its own logins from now on:
    Hermes's `auth.adopt_external_logins: false`, set with `hermes config set`."""
    engine = core.engine
    if engine is None:
        return
    prefix = engine.settings.profile_prefix
    for name in engine.own_profiles(workspace_id):
        engine.set_setting(name[len(prefix) :], "auth.adopt_external_logins", "false")


def login_state(core: Core, workspace_id: str) -> dict[str, Any]:
    """Whether the workspace's root can reach its model, as Hermes says it
    (`hermes auth status <its provider>`: a login, a key, or a provider that needs
    neither), and a subscription it only borrows counts as none. "needsLogin" is
    shown in AGOS."""
    engine = core.engine
    if engine is None:
        return {"root": False, "needsLogin": False, "provider": "", "signedIn": []}
    root = engine.root(workspace_id)
    found = hermes_logins(engine, root, status=True)
    if found is None:
        return {"root": True, "needsLogin": True, "provider": "", "signedIn": []}
    provider = str(found.get("provider") or "")
    signed = sorted(
        {
            str(e.get("provider"))
            for e in found.get("pool") or []
            if own_login(found, str(e.get("provider")))
        }
        | set(found.get("signed_in_state") or [])
    )
    needs = bool(provider) and (not found.get("logged_in") or borrowing_needed(engine, root))
    return {"root": True, "needsLogin": needs, "provider": provider, "signedIn": signed}
