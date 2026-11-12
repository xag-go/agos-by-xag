"""Which of the Co-Founder's tools Hermes's Tool Search keeps out of the model's tool
list (deferred behind tool_search / tool_describe / tool_call) and which it shows on
every turn (eager): ONE AGOS setting, written into each workspace root's Hermes
config, so the token cost of AGOS's own tools can be measured both ways.

What Hermes offers (v0.22.2, H: tools/tool_search.py): `tools.tool_search.enabled`
(auto | on | off) and `tools.tool_search.defer` (a list of tool names that ARE
deferred, replacing Hermes's curated list). A plugin tool (AGOS's agos_* tools, toolset
"agos") is always deferrable (`is_deferrable_tool_name`: not core, not a client
surface), whatever `defer` says; Hermes has no per-tool "never defer". So:

- `defer` (names): written as Hermes's own curated list plus these names, so more of
  Hermes's core tools can be deferred one by one;
- `eager` (names): Hermes can keep a plugin tool eager only with the whole bridge off,
  so a non-empty list writes `tools.tool_search.enabled: off` in the Co-Founder's
  profile (every tool of THAT profile eager; members keep Hermes's behaviour);
- nothing set (the default) = Hermes's own behaviour: nothing written, and what AGOS
  wrote before is unset.

Only the root profile (the Co-Founder, the one profile with AGOS's tools) is written.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agos_core.actions.errors import ActionError
from agos_core.context import Core
from agos_core.db.app_settings import get_setting, set_setting
from agos_core.hermes_gateway import cli as hermes_cli

log = logging.getLogger("agos.tool_search")

KEY = "hermes.tool_search"
ENABLED = "tools.tool_search.enabled"
DEFER = "tools.tool_search.defer"


def read(core: Core) -> dict[str, list[str]]:
    raw = get_setting(core.db, KEY, {})
    raw = raw if isinstance(raw, dict) else {}
    return {
        k: sorted({str(n).strip() for n in raw.get(k) or [] if str(n).strip()})
        for k in ("eager", "defer")
    }


def _hermes_defer(core: Core) -> list[str]:
    """Hermes's own curated `defer` list (its DEFAULT_CONFIG, read from Hermes)."""
    from agos_core.actions import cofounder_hermes

    found = cofounder_hermes._row(core, DEFER).get("default")
    if not isinstance(found, list):
        raise ActionError("The engine's own list of deferred tools can't be read.", 503)
    return [str(n) for n in found]


def commands(core: Core, wanted: dict[str, list[str]], have: dict[str, Any]) -> list[list[str]]:
    """The root profile's `hermes config set/unset` commands for this choice (`have`:
    its config.yaml now; an unset only for a key it holds)."""
    from agos_core.engine import config_file

    out: list[list[str]] = []
    if wanted["eager"]:
        out.append(["config", "set", ENABLED, "off"])
    elif config_file.get(have, ENABLED) is not None:
        out.append(["config", "unset", ENABLED])
    if wanted["defer"]:
        names = list(dict.fromkeys([*_hermes_defer(core), *wanted["defer"]]))
        out.append(["config", "set", DEFER, json.dumps(names)])
    elif config_file.get(have, DEFER) is not None:
        out.append(["config", "unset", DEFER])
    return out


def _ours(core: Core) -> bool:
    """AGOS wrote these keys (the setting was set since): only then does going back to
    the default unset them; a value the owner set himself on the Hermes settings page
    stays his."""
    raw = get_setting(core.db, KEY, {})
    return bool(isinstance(raw, dict) and raw.get("written"))


def apply(core: Core, workspace_id: str, wanted: dict[str, list[str]] | None = None) -> None:
    """Into this workspace's root profile (the Co-Founder's)."""
    from agos_core.engine import config_file

    if core.engine is None:
        return
    wanted = read(core) if wanted is None else wanted
    if not wanted["eager"] and not wanted["defer"] and not _ours(core):
        return  # Hermes's own behaviour: nothing written
    root = core.engine.split(workspace_id)[0]
    todo = commands(core, wanted, config_file.read(core.engine.profile_home(root)))
    if todo:
        hermes_cli.config_writes(core.engine, root, todo)


def keep_all(core: Core) -> int:
    """Every workspace's root as the setting says (AGOS's start, a change)."""
    from agos_core.db.workspaces import list_workspaces

    wanted = read(core)
    done = 0
    for ws in list_workspaces(core.db):
        try:
            apply(core, ws.id, wanted)
            done += 1
        except Exception:
            log.exception("tool search setting not written in %s", ws.id)
    return done


def save(core: Core, eager: list[str], defer: list[str]) -> dict[str, list[str]]:
    clean = {
        "eager": sorted({n.strip() for n in eager if n.strip()}),
        "defer": sorted({n.strip() for n in defer if n.strip()}),
    }
    written = _ours(core) or bool(clean["eager"] or clean["defer"])
    set_setting(core.db, KEY, {**clean, "written": written})
    keep_all(core)
    if not clean["eager"] and not clean["defer"]:
        set_setting(core.db, KEY, {**clean, "written": False})  # back to Hermes's own
    return clean
