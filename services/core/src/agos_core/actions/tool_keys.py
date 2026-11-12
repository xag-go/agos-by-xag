"""Workspace → Settings → Keys: keys for the workspace's own tools and scripts.

The owner types an app's name and pastes its key; The engine keeps it (engine/tool_keys.py
says where and how). AGOS keeps only what Hermes has no place for: the app's name as
he typed it and when the key was saved and last tested (`tool_keys.<ws>`), never the
key or any part of it. The list itself is Hermes's: the names in the root's
`terminal.env_passthrough`, each with whether its `.env` line is there.

Each workspace's keys live in its own Hermes root only: every call works on the
root of the workspace in the URL, and a name not in that root's list is unknown.
The Co-Founder learns the names only (actions/engine.py cofounder_view).

Every agent of the workspace gets them too (`share`). Hermes scopes a sandbox's
passthrough by profile: a member's commands get the names in ITS config's
`terminal.env_passthrough`, valued from ITS `.env` (H: tools/env_passthrough.py
`_load_config_passthrough` keyed by `hermes_home_key`, agent/secret_scope.py), and
a profile under a root reads neither of the root's. So each member profile holds a
copy, written by Hermes's own writers (`save_env_value`, `hermes config set`), with
a ledger (`.agos-tool-keys.json`) of the names that are AGOS's copies: a key the
owner removes goes from every member, and only AGOS's copies are ever touched.
The root stays the one place the Keys page reads and writes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from agos_core.actions.errors import ActionError, NotFoundError
from agos_core.context import Core
from agos_core.db.app_settings import delete_setting, get_setting, set_setting
from agos_core.db.rows import now
from agos_core.engine import tool_keys as tk
from agos_core.engine.hermes import EngineError
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.tool_keys")

META = "tool_keys."  # + workspace id: {name: {app, saved_at, tested_at, test_ok}}
SHARED = ".agos-tool-keys.json"  # in each member home: {"names": [AGOS's copies]}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(workspace_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(workspace_id, threading.Lock())


def _root(core: Core, workspace_id: str) -> Any:
    from agos_core.actions.workspaces import require_workspace

    engine = core.engine
    if engine is None:
        raise ActionError("The engine isn't available.", status=503)
    if engine.split(workspace_id)[1]:
        raise NotFoundError("This workspace")
    require_workspace(core, workspace_id)
    home = engine.profile_home(workspace_id)
    if not (home / "config.yaml").is_file():
        raise ActionError("This workspace isn't set up yet. Try again in a minute.")
    return home


def _meta(core: Core, workspace_id: str) -> dict[str, dict[str, Any]]:
    found = get_setting(core.db, META + workspace_id, {})
    return (
        {str(k): dict(v) for k, v in found.items() if isinstance(v, dict)}
        if isinstance(found, dict)
        else {}
    )


def _set_meta(core: Core, workspace_id: str, meta: dict[str, dict[str, Any]]) -> None:
    if meta:
        set_setting(core.db, META + workspace_id, meta)
    else:
        delete_setting(core.db, META + workspace_id)


def names(core: Core, workspace_id: str) -> list[str]:
    """The names Hermes passes into this workspace's tools (its root's list)."""
    from agos_core.engine import config_file

    if core.engine is None:
        return []
    return tk.passthrough(config_file.read(core.engine.profile_home(workspace_id)))


def read(core: Core, workspace_id: str) -> dict[str, Any]:
    from agos_core.engine import config_file

    home = _root(core, workspace_id)
    env = config_file.read_env(home)
    meta = _meta(core, workspace_id)
    keys = []
    for name in tk.passthrough(config_file.read(home)):
        info = meta.get(name, {})
        value = env.get(name, "")
        keys.append(
            {
                "app": str(info.get("app") or name),
                "name": name,
                "saved": bool(value.strip()),
                "ends_with": tk.shown_end(value),
                "saved_at": info.get("saved_at"),
                "tested_at": info.get("tested_at"),
                "test_ok": info.get("test_ok"),
                "testable": tk.probe_for(name) is not None,
            }
        )
    return {"keys": keys}


def _managed_elsewhere(name: str) -> str | None:
    """Why AGOS keeps this name for another of its cards (None: it doesn't)."""
    from agos_core.actions import hermes_all_settings as hall

    if name.startswith(tk.RESERVED_PREFIXES):
        return "This name is kept for the engine and AGOS themselves."
    card = hall.card_keys().get(name)
    if card is not None:
        return f"This key is changed on {hall.CARD_LABELS[card]}, not here."
    if hall.forced_env(name) or hall.locked_env(name):
        return "AGOS sets this one itself for the workspace: it can't be changed here."
    return None


def _facts(core: Core, home: Any, app: str, extra: list[str] | None = None) -> dict[str, Any]:
    assert core.engine is not None
    try:
        return core.engine.tool_keys(
            home,
            {"do": "facts", "slug": tk.slug(app), "names": tk.candidates(app) + (extra or [])},
        )
    except EngineError as error:
        raise ActionError("The engine didn't answer. Try again in a minute.", status=503) from error


def _choose(
    core: Core, workspace_id: str, home: Any, app: str, name: str | None
) -> tuple[str, str]:
    """(variable name, where to get a key) for this app, or a refusal."""
    from agos_core.engine import config_file

    try:
        app = tk.clean_app(app)
        if name:
            wanted = name.strip()
            if not tk.NAME.match(wanted):
                raise tk.NameProblem("A key name is A-Z, 0-9 and _, starting with a letter.")
            facts = _facts(core, home, app, [wanted])
            if (facts.get("own") or {}).get(wanted, True):
                raise tk.NameProblem(
                    f"{wanted} is a key the engine keeps for itself: it can't be added here."
                )
            picked = tk.Picked(wanted, "", False)
        else:
            picked = tk.pick(app, _facts(core, home, app))
    except tk.NameProblem as problem:
        raise ActionError(str(problem)) from problem
    why = _managed_elsewhere(picked.name)
    if why:
        raise ActionError(why)
    ours = tk.passthrough(config_file.read(home))
    if picked.name not in ours and picked.name in config_file.read_env(home):
        raise ActionError(
            f"This workspace already uses a key named {picked.name} for something "
            "else, so it isn't replaced from here."
        )
    return picked.name, picked.url


def preview(core: Core, workspace_id: str, app: str) -> dict[str, Any]:
    """The name a key for this app would be saved under (nothing is written)."""
    home = _root(core, workspace_id)
    name, url = _choose(core, workspace_id, home, app, None)
    return {"name": name, "url": url, "exists": name in names(core, workspace_id)}


def _clean_key(key: str) -> str:
    key = key.strip()
    if not key or len(key) > tk.KEY_MAX or any(c.isspace() for c in key):
        raise ActionError("Paste the key exactly as the app shows it, with no spaces.")
    return key


def _write_list(core: Core, workspace_id: str, wanted: list[str]) -> None:
    assert core.engine is not None
    hermes_cli.cli(core.engine, workspace_id, "config", "set", tk.PASSTHROUGH, json.dumps(wanted))


def _after_change(core: Core, workspace_id: str) -> None:
    """Every member gets the change (`share`). The root's gateway reads the
    passthrough lists only when it starts: a running one goes once more (Hermes's
    own stop drains running answers), so the next command sees the change. Then
    the Co-Founder's view (names only)."""
    from agos_core.actions import engine as engine_actions
    from agos_core.actions import hermes_channel

    share(core, workspace_id)
    hermes_channel.restart_gateway(core, workspace_id, wait=True)
    engine_actions.refresh_cofounder_view(core, workspace_id)
    from agos_core.actions import hermes_all_settings

    hermes_all_settings.warm_after_write(core)  # the root's .env rows and passthrough


def _hermes_save(core: Core, home: Any, name: str, key: str) -> None:
    assert core.engine is not None
    try:
        done = core.engine.tool_keys(home, {"do": "save", "name": name}, secret=key)
    except EngineError as error:
        raise ActionError("The engine didn't save the key. Try again.", status=503) from error
    if done.get("refused") == "own":
        raise ActionError(f"{name} is a key the engine keeps for itself: it can't be added here.")
    if done.get("refused") == "managed":
        raise ActionError(f"{name} is set for every workspace by the managed settings.")
    if not done.get("saved"):
        raise ActionError("The engine didn't save the key. Try again.", status=503)


def save(
    core: Core, workspace_id: str, app: str, key: str, name: str | None = None
) -> dict[str, Any]:
    """A key for an app: its value into the root's .env (Hermes's writer), its
    name into the root's passthrough list. The same app again replaces it."""
    from agos_core.engine import config_file

    home = _root(core, workspace_id)
    key = _clean_key(key)
    with _lock(workspace_id):
        chosen, _url = _choose(core, workspace_id, home, app, name)
        _hermes_save(core, home, chosen, key)
        listed = tk.passthrough(config_file.read(home))
        if chosen not in listed:
            _write_list(core, workspace_id, [*listed, chosen])
        meta = _meta(core, workspace_id)
        meta[chosen] = {"app": tk.clean_app(app), "saved_at": now()}
        _set_meta(core, workspace_id, meta)
    log.info("workspace %s: tool key %s saved", workspace_id, chosen)
    _after_change(core, workspace_id)
    return {**read(core, workspace_id), "saved_name": chosen}


def _known(core: Core, workspace_id: str, home: Any, name: str) -> str:
    from agos_core.engine import config_file

    if name not in tk.passthrough(config_file.read(home)):
        raise NotFoundError("This key")
    return name


def replace(core: Core, workspace_id: str, name: str, key: str) -> dict[str, Any]:
    home = _root(core, workspace_id)
    key = _clean_key(key)
    with _lock(workspace_id):
        _known(core, workspace_id, home, name)
        why = _managed_elsewhere(name)
        if why:
            raise ActionError(why)
        _hermes_save(core, home, name, key)
        meta = _meta(core, workspace_id)
        info = meta.get(name, {})
        meta[name] = {"app": info.get("app") or name, "saved_at": now()}
        _set_meta(core, workspace_id, meta)
    log.info("workspace %s: tool key %s replaced", workspace_id, name)
    _after_change(core, workspace_id)
    return {**read(core, workspace_id), "saved_name": name}


def remove(core: Core, workspace_id: str, name: str) -> dict[str, Any]:
    """The key out of the root's .env and its name out of the list."""
    from agos_core.engine import config_file

    home = _root(core, workspace_id)
    with _lock(workspace_id):
        _known(core, workspace_id, home, name)
        why = _managed_elsewhere(name)
        if why:
            raise ActionError(why)
        assert core.engine is not None
        try:
            done = core.engine.tool_keys(home, {"do": "remove", "name": name})
        except EngineError as error:
            raise ActionError("The engine didn't remove the key. Try again.", status=503) from error
        if done.get("refused"):
            raise ActionError(f"The engine keeps {name} for itself: it isn't removed from here.")
        _write_list(
            core, workspace_id, [n for n in tk.passthrough(config_file.read(home)) if n != name]
        )
        meta = _meta(core, workspace_id)
        meta.pop(name, None)
        _set_meta(core, workspace_id, meta)
    log.info("workspace %s: tool key %s removed", workspace_id, name)
    _after_change(core, workspace_id)
    return read(core, workspace_id)


def test(core: Core, workspace_id: str, name: str) -> dict[str, Any]:
    """Is the key there and handed to the tools, as Hermes's own sandbox code
    resolves it; and, for an app with a cheap check, does the app take it."""
    home = _root(core, workspace_id)
    _known(core, workspace_id, home, name)
    meta = _meta(core, workspace_id)
    app = str(meta.get(name, {}).get("app") or name)
    probe = tk.probe_for(name)
    assert core.engine is not None
    try:
        found = core.engine.tool_keys(home, {"do": "test", "name": name, "probe": probe})
    except EngineError as error:
        raise ActionError("The engine didn't answer. Try again in a minute.", status=503) from error
    ok = False
    if not found.get("present"):
        message = "This key isn't saved any more. Add it again."
    elif found.get("own"):
        message = "The engine keeps this name for itself and doesn't give it to tools."
    elif not found.get("passed"):
        message = "Saved, but the engine doesn't hand it to the tools. Save it again."
    elif missing := _members_missing(core, name, workspace_id):
        agents = (
            "agent of this workspace doesn't" if missing == 1 else "agents of this workspace don't"
        )
        message = f"Saved, but {missing} {agents} get it yet. Save it again."
    elif probe is None:
        ok, message = True, f"Ready: tools and scripts can read it as ${name}."
    elif found.get("status") in probe["ok"]:
        ok, message = True, f"Works: {app} accepted the key."
    elif found.get("status") in probe["refused"]:
        message = f"{app} refused this key. Check it and replace it."
    else:
        message = f"Saved, but {app} couldn't be reached to try it. Test again later."
    with _lock(workspace_id):
        meta = _meta(core, workspace_id)
        if name in meta:
            meta[name] = {**meta[name], "tested_at": now(), "test_ok": ok}
            _set_meta(core, workspace_id, meta)
    return {"ok": ok, "message": message}


# ---- every agent of the workspace gets the root's keys --------------------------------


def _ledger(home: Path) -> set[str]:
    try:
        found = json.loads((home / SHARED).read_text())
    except (OSError, ValueError):
        return set()
    names = found.get("names") if isinstance(found, dict) else None
    return {str(n) for n in names} if isinstance(names, list) else set()


def members(core: Core, workspace_id: str) -> list[tuple[str, Path]]:
    """(engine key, home) of each profile under the workspace's root (members,
    team agents), set up far enough to take keys."""
    engine = core.engine
    if engine is None:
        return []
    prefix = engine.settings.profile_prefix
    out: list[tuple[str, Path]] = []
    for name in engine.own_profiles(workspace_id)[1:]:
        key = name[len(prefix) :]
        home = engine.profile_home(key)
        if (home / "config.yaml").is_file():
            out.append((key, home))
    return out


def root_values(core: Core, workspace_id: str) -> dict[str, str]:
    """The root's tool keys that hold a value: what every member gets."""
    from agos_core.engine import config_file

    assert core.engine is not None
    root = core.engine.profile_home(workspace_id)
    env = config_file.read_env(root)
    return {
        n: env[n]
        for n in tk.passthrough(config_file.read(root))
        if env.get(n, "").strip() and not _managed_elsewhere(n)
    }


def share_home(core: Core, key: str, home: Path, values: dict[str, str]) -> bool:
    """One member gets exactly the root's keys (`values`); AGOS's copies of keys
    gone from the root go. Nothing runs when the member already matches. True when
    something changed (names only are logged)."""
    from agos_core.engine import config_file

    assert core.engine is not None
    mine = _ledger(home)
    env = config_file.read_env(home)
    drop = sorted(n for n in mine if n not in values)
    listed = tk.passthrough(config_file.read(home))
    stale = {n for n, v in values.items() if env.get(n, "") != v.strip()}
    if stale or any(n in env for n in drop):
        done = core.engine.tool_keys(home, {"do": "share", "drop": drop}, secret=json.dumps(values))
        put = [str(n) for n in done.get("put") or []]
    else:
        put = [n for n in values if env.get(n, "").strip()]
    wanted = [n for n in listed if n not in drop] + [n for n in put if n not in listed]
    if wanted != listed:
        hermes_cli.config_writes(
            core.engine, key, [("config", "set", tk.PASSTHROUGH, json.dumps(wanted))]
        )
    changed = bool(stale) or wanted != listed or set(put) != mine
    if set(put) != mine or not (home / SHARED).exists():
        (home / SHARED).write_text(json.dumps({"names": sorted(put)}))
        with contextlib.suppress(OSError):
            (home / SHARED).chmod(0o600)
    if changed:
        log.info("tool keys → %s: %s", key, ", ".join(sorted(put)) or "none")
    return changed


def share(core: Core, workspace_id: str, only: str | None = None) -> int:
    """Every member of the workspace (or the one engine key `only`) gets the
    root's keys. Safe to repeat; up to 4 members at once. Returns how many
    members changed; one that fails is logged and tried again next time."""
    if core.engine is None:
        return 0
    targets = [(k, h) for k, h in members(core, workspace_id) if only in (None, k)]
    if not targets:
        return 0
    values = root_values(core, workspace_id)

    def one(target: tuple[str, Path]) -> bool:
        try:
            return share_home(core, target[0], target[1], values)
        except (OSError, EngineError, ValueError) as error:
            log.warning("tool keys not given to %s: %s", target[0], type(error).__name__)
            return False

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        return sum(pool.map(one, targets))


def _members_missing(core: Core, name: str, workspace_id: str) -> int:
    """How many members' sandboxes don't get this key, as Hermes resolves it."""
    assert core.engine is not None
    engine = core.engine

    def one(target: tuple[str, Path]) -> bool:
        try:
            found = engine.tool_keys(target[1], {"do": "test", "name": name})
        except EngineError:
            return True
        return not found.get("passed")

    targets = members(core, workspace_id)
    if not targets:
        return 0
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
        return sum(pool.map(one, targets))


def cofounder_note(core: Core, workspace_id: str) -> str:
    """For the Co-Founder's view: which key NAMES its tools get (never a value)."""
    try:
        listed = names(core, workspace_id)
    except OSError:
        return ""
    if not listed:
        return ""
    meta = _meta(core, workspace_id)
    lines = [
        f"- ${n}" + (f" ({meta[n]['app']})" if meta.get(n, {}).get("app") else "") for n in listed
    ]
    return (
        "## Keys for your tools\n"
        "The owner saved these keys for this workspace (Settings → Keys). Every command and "
        "script you or any agent of this workspace runs gets each one as an environment "
        "variable: read it by its name "
        '(e.g. os.environ["NAME"]). Never print, log, save or send a key\'s value, and never '
        "ask the owner to paste one in the chat: he adds or replaces keys in Settings → Keys.\n"
        + "\n".join(lines)
    )
