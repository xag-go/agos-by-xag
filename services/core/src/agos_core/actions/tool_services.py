"""The services Hermes's tools use (pictures, video, voice, web search, X search…),
set up once in AGOS (Settings → Tools) and written into Hermes.

The list of services is Hermes's own (engine/hermes_tools.py). Choosing one runs
Hermes's own selection (as its dashboard does) and its keys go into Hermes's .env:
first in AGOS's connectors home (a Hermes home, the one place every workspace's
copy comes from, like the Google login), then in every workspace's profile and its
members'. AGOS keeps nothing of it: the service shown is the one each profile's
Hermes uses (read from its own config with Hermes's picker, engine
tool_services_in), its keys are Hermes's list for that service, and their last 4
characters are read from Hermes's .env each time. The keys
never reach a sandbox (Hermes runs these tools itself). Each copy is written by
Hermes's own code (save_env_value), and copies rather than one Hermes secret source
for the same reason as General Settings' keys (actions/general_sync.py): a running
gateway reads `.env` for each turn but a secret source only once. The selection
isn't Hermes's managed scope either (actions/hermes_managed.py): it is Hermes's
`apply_provider_selection` run in each home, which picks among the rows THAT home
can use (hermes_cli/tools_config_providers.py:809 `_visible_providers(cat,
config)`, :814 the Nous gate by that root's own login) and edits whatever keys the
provider needs (:815 `_write_provider_config`, :820-826): no fixed key list to pin.
"""

from __future__ import annotations

import contextlib
import logging
import re
import threading
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.engine import hermes_tools

log = logging.getLogger("agos.tool_services")

# AGOS's old copy ({toolset: {"provider", "keys"}}): moved into Hermes once at
# core start (move_old_setting) and deleted. The choice lives only in Hermes.
OLD_SETTING = "tools.services"
_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_LOCK = threading.Lock()  # one change at a time (Hermes rewrites its config whole)


def _active(core: Core, home: Any) -> dict[str, str | None]:
    """The service each toolset of one Hermes home uses (Hermes's own picker)."""
    assert core.engine is not None
    try:
        return core.engine.tool_services_in(home)
    except Exception as error:  # noqa: BLE001 - not known: shown as not set up
        log.info("tool services of %s not read: %s", home, error)
        return {}


def _key_names(toolset: str, provider: str) -> list[str]:
    """The keys a service takes: Hermes's own list (its catalog's env vars)."""
    found = next((p for p in hermes_tools.providers(toolset) if p.get("name") == provider), None)
    env = (found or {}).get("env") or []
    return [str(e["key"]) for e in env if _ENV_KEY.match(str(e.get("key")))]


def homes(core: Core) -> list[tuple[str, Any]]:
    """(label, home) of every profile whose picker `chosen` reads (the shared home
    when there is none yet)."""
    from agos_core.actions.hermes_time_limits import profiles

    return [(p.label, p.home) for p in profiles(core)] or [("", _home(core))]


def chosen(core: Core) -> dict[str, Any]:
    """Per toolset, the service the workspaces' Hermes use (read from each
    profile's own config, as Hermes's picker finds it), with its keys' last 4
    read from the .env of a profile that uses it. When profiles differ: the most
    common one, and `spread` (service → profiles)."""
    if core.engine is None:
        return {}
    from concurrent.futures import ThreadPoolExecutor

    found = homes(core)
    with ThreadPoolExecutor(max_workers=8) as pool:
        actives = list(pool.map(lambda h: _active(core, h[1]), found))
    groups: dict[str, dict[str | None, list[tuple[str, Any]]]] = {}
    for (label, home), active in zip(found, actives, strict=True):
        for toolset, provider in active.items():
            groups.setdefault(toolset, {}).setdefault(provider, []).append((label, home))
    out: dict[str, Any] = {}
    for toolset, by in groups.items():
        ordered = sorted(by.items(), key=lambda item: -len(item[1]))
        provider, where = ordered[0]
        if provider is None and len(ordered) > 1:  # one set up somewhere: show it
            provider, where = ordered[1]
        if provider is None:
            continue
        names = _key_names(toolset, provider)
        values = _values_in(where[0][1], names)
        entry: dict[str, Any] = {
            "provider": provider,
            "keys": {k: values.get(k, "")[-4:] for k in names},
        }
        if len(ordered) > 1:
            entry["spread"] = [
                {"provider": p, "profiles": [label for label, _ in w]} for p, w in ordered
            ]
        out[toolset] = entry
    return out


def _home(core: Core) -> Any:
    return core.settings.data_dir / "system" / "connectors"


def _values(core: Core, keys: list[str]) -> dict[str, str]:
    """The keys' values from the connectors home (Hermes wrote them there)."""
    return _values_in(_home(core), keys)


def _values_in(home: Any, keys: list[str]) -> dict[str, str]:
    """The keys' values from a Hermes home's .env."""
    out: dict[str, str] = {}
    with contextlib.suppress(OSError):
        for line in (home / ".env").read_text().splitlines():
            k, _, v = line.partition("=")
            if k in keys:
                out[k] = v.strip().strip('"').strip("'")
    return out


def _profiles(core: Core) -> list[tuple[str, Any]]:
    from agos_core.db.workspaces import list_workspaces

    assert core.engine is not None
    out = []
    for workspace in list_workspaces(core.db):
        for name in core.engine.own_profiles(workspace.id):
            home = core.engine.home_of(name)
            if home is not None and (home / "config.yaml").is_file():
                out.append((workspace.id, home))
    return out


def set_service(core: Core, toolset: str, provider: str, keys: dict[str, str]) -> dict[str, Any]:
    """The owner picked a service for a tool (and gave its keys, when it needs some)."""
    with _LOCK:
        return _set_service(core, toolset, provider, keys)


def _set_service(core: Core, toolset: str, provider: str, keys: dict[str, str]) -> dict[str, Any]:
    if core.engine is None:
        raise ActionError("The engine is off.", 409)
    found = next((p for p in hermes_tools.providers(toolset) if p.get("name") == provider), None)
    if found is None:
        raise NotFoundError("This service")
    if found.get("nous"):
        from agos_core.actions import apps

        if not apps.nous_signed_in(core):
            raise ActionError("Sign in to Nous Portal first (the button above).", 409)
    wanted = [str(e["key"]) for e in found.get("env") or [] if _ENV_KEY.match(str(e.get("key")))]
    clean = {k: str(keys.get(k) or "").strip() for k in wanted}
    have = _values(core, wanted)
    missing = [k for k in wanted if not clean[k] and not have.get(k)]
    if missing:
        raise ActionError(f"Fill in: {', '.join(missing)}")
    env = {k: v for k, v in clean.items() if v}
    if any(len(v) < 8 or "\n" in v or " " in v for v in env.values()):
        raise ActionError("That doesn't look like a key.")
    from agos_core.engine.provider_login import NOT_INSTALLS

    job = {
        "toolset": toolset,
        "provider": provider,
        "env": env,
        "install": True,
        "not_installs": sorted(NOT_INSTALLS),
    }
    # First the one place every workspace's copy comes from, then every profile.
    step = core.engine.set_tool_service(_home(core), job)
    if step:  # Hermes's install for it, once (the install is shared by every profile)
        core.engine.tools_install(
            _home(core), step, core.settings.data_dir / "system" / "logs" / "tools-install.log"
        )
    values = {**have, **env}
    problems = _spread(core, toolset, provider, values)
    return {"ok": not problems, "problems": problems, "installing": step}


def _spread(core: Core, toolset: str, provider: str, values: dict[str, str]) -> list[str]:
    """Each profile's own .env, through Hermes's save_env_value. Not one Hermes
    secret source: a running gateway pulls a source once per home, but reads
    each profile's .env on every turn (see actions/general_sync.py)."""
    assert core.engine is not None
    problems = []
    for workspace_id, home in _profiles(core):
        try:
            core.engine.set_tool_service(
                home, {"toolset": toolset, "provider": provider, "env": values}
            )
        except Exception as error:  # noqa: BLE001 - the others still get it
            problems.append(f"{workspace_id}: {error}")
    return problems


def apply_home(core: Core, home: Any) -> None:
    """A new profile (a workspace's, or a member's) uses the services set up in
    Settings → Tools: those the connectors home's Hermes uses (the one place every
    workspace's copy comes from), where the new home's Hermes uses another."""
    if core.engine is None or not (_home(core) / "config.yaml").is_file():
        return
    source = {k: v for k, v in _active(core, _home(core)).items() if v}
    if not source:
        return
    here = _active(core, home)
    for toolset, provider in source.items():
        names = _key_names(toolset, provider)
        values = _values(core, names)
        if here.get(toolset) == provider and set(_values_in(home, names)) >= set(values):
            continue
        with contextlib.suppress(Exception):
            core.engine.set_tool_service(
                home, {"toolset": toolset, "provider": provider, "env": values}
            )


def apply_to(core: Core, workspace_id: str) -> None:
    if core.engine is None:
        return
    for name in core.engine.own_profiles(workspace_id):
        home = core.engine.home_of(name)
        if home is not None and (home / "config.yaml").is_file():
            apply_home(core, home)


def move_old_setting(core: Core) -> bool:
    """AGOS's old copy (app_settings `tools.services`) → Hermes, once. Every
    profile already got the service from it (each save wrote every profile), so
    Hermes holds it; only the connectors home (where new profiles take it from)
    is set where its Hermes uses another service. Then the copy is deleted; kept
    for the next start when the connectors home didn't take it."""
    from agos_core.db.app_settings import delete_setting, get_setting

    old = get_setting(core.db, OLD_SETTING, None)
    if old is None:
        return False
    if core.engine is None:
        return False
    if isinstance(old, dict) and old:
        here = _active(core, _home(core)) if (_home(core) / "config.yaml").is_file() else {}
        for toolset, choice in old.items():
            provider = choice.get("provider") if isinstance(choice, dict) else None
            if not provider or here.get(str(toolset)) == provider:
                continue
            if not any(p.get("name") == provider for p in hermes_tools.providers(str(toolset))):
                continue  # no longer in Hermes's list
            values = _values(core, _key_names(str(toolset), str(provider)))
            try:
                core.engine.set_tool_service(
                    _home(core), {"toolset": toolset, "provider": provider, "env": values}
                )
            except Exception as error:  # noqa: BLE001 - kept for the next start
                log.warning("old tool service %s not moved: %s", toolset, error)
                return False
    delete_setting(core.db, OLD_SETTING)
    log.info("tool services moved from AGOS's settings into Hermes")
    return True
